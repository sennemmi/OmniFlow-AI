"""
Pipeline 业务服务
业务逻辑层 - 协调 Pipeline 创建、Agent 调用和人工审批
"""

from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.coder import coder_agent
from app.models.pipeline import (
    Pipeline, PipelineRead, PipelineStatus,
    PipelineStage, StageName, StageStatus, PipelineStageRead
)
from app.service.project import ProjectService
from app.service.git_provider import GitProviderService, GitProviderError
from app.service.code_executor import CodeExecutorService


class PipelineService:
    """
    Pipeline 业务服务
    
    负责：
    1. Pipeline 的创建和管理
    2. 协调 ArchitectAgent/DesignerAgent 分析需求
    3. 管理 Pipeline 状态流转（含人工审批）
    4. 实现"自动回归"思想（驳回后重新执行）
    """
    
    @classmethod
    async def create_pipeline(
        cls,
        requirement: str,
        session: AsyncSession
    ) -> PipelineRead:
        """
        创建新的 Pipeline
        
        流程：
        1. 保存 Pipeline 到数据库
        2. 创建初始阶段（REQUIREMENT）
        3. 异步触发 ArchitectAgent 分析
        
        Args:
            requirement: 用户需求描述
            session: 数据库会话
            
        Returns:
            PipelineRead: 创建的 Pipeline 信息
        """
        from sqlmodel import select
        
        # 1. 创建 Pipeline
        pipeline = Pipeline(
            description=requirement,
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        session.add(pipeline)
        await session.flush()  # 获取 ID
        
        # 2. 创建 REQUIREMENT 阶段
        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.REQUIREMENT,
            status=StageStatus.RUNNING,
            input_data={"requirement": requirement}
        )
        session.add(stage)
        await session.commit()
        
        # 3. 重新查询以获取完整数据（包括 stages）
        statement = select(Pipeline).where(Pipeline.id == pipeline.id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline_with_stages = result.scalar_one()
        
        # 4. 异步触发 ArchitectAgent（这里先同步执行）
        # TODO: 使用 Celery 或 BackgroundTasks 实现真正的异步
        await cls._trigger_architect_analysis(pipeline.id, requirement, session)
        
        # 构建 PipelineRead 对象
        return cls._build_pipeline_read(pipeline_with_stages)
    
    @classmethod
    def _build_pipeline_read(cls, pipeline: Pipeline) -> PipelineRead:
        """
        将 Pipeline ORM 对象转换为 PipelineRead
        
        Args:
            pipeline: Pipeline ORM 对象
            
        Returns:
            PipelineRead: 读取模型
        """
        stages_read = []
        if pipeline.stages:
            for stage in pipeline.stages:
                stages_read.append(PipelineStageRead(
                    id=stage.id,
                    name=stage.name,
                    status=stage.status,
                    input_data=stage.input_data,
                    output_data=stage.output_data,
                    created_at=stage.created_at,
                    completed_at=stage.completed_at
                ))
        
        return PipelineRead(
            id=pipeline.id,
            description=pipeline.description,
            status=pipeline.status,
            current_stage=pipeline.current_stage,
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,
            stages=stages_read if stages_read else None
        )
    
    @classmethod
    async def _trigger_architect_analysis(
        cls,
        pipeline_id: int,
        requirement: str,
        session: AsyncSession
    ) -> None:
        """
        触发 ArchitectAgent 分析
        
        分析完成后，Pipeline 状态设为 PAUSED，等待人工审批
        
        Args:
            pipeline_id: Pipeline ID
            requirement: 需求描述
            session: 数据库会话
        """
        from sqlmodel import select
        
        try:
            # 获取项目文件树
            from app.service.project import get_current_project_tree
            file_tree_node = get_current_project_tree(max_depth=4)
            file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
            
            # 调用 ArchitectAgent
            result = await architect_agent.analyze(requirement, file_tree)
            
            # 获取当前阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result_query = await session.execute(statement)
            stage = result_query.scalar_one_or_none()
            
            if stage:
                if result["success"]:
                    stage.status = StageStatus.SUCCESS
                    stage.output_data = result["output"]
                else:
                    stage.status = StageStatus.FAILED
                    stage.output_data = {"error": result["error"]}
                
                stage.completed_at = datetime.utcnow()
                session.add(stage)
            
            # 更新 Pipeline 状态为 PAUSED，等待人工审批
            statement = select(Pipeline).where(Pipeline.id == pipeline_id)
            result_query = await session.execute(statement)
            pipeline = result_query.scalar_one_or_none()
            
            if pipeline:
                if result["success"]:
                    # 分析成功，设为 PAUSED 等待审批
                    pipeline.status = PipelineStatus.PAUSED
                else:
                    # 分析失败
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
        except Exception as e:
            # 记录错误但不抛出，避免影响 API 响应
            print(f"Architect analysis failed for pipeline {pipeline_id}: {e}")
            await session.rollback()
    
    @classmethod
    async def approve_pipeline(
        cls,
        pipeline_id: int,
        notes: Optional[str],
        feedback: Optional[str],
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        审批 Pipeline，允许进入下一阶段
        
        如果当前是 REQUIREMENT 阶段，触发 DesignerAgent
        如果当前是 DESIGN 阶段，触发 CoderAgent
        
        Args:
            pipeline_id: Pipeline ID
            notes: 审批备注
            feedback: 反馈建议
            session: 数据库会话
            
        Returns:
            Dict: 审批结果
        """
        from sqlmodel import select
        
        # 获取 Pipeline
        statement = select(Pipeline).where(Pipeline.id == pipeline_id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}
        
        # 检查状态
        if pipeline.status != PipelineStatus.PAUSED:
            return {"success": False, "error": f"Pipeline is not in PAUSED state, cannot approve"}
        
        current_stage = pipeline.current_stage
        
        if current_stage == StageName.REQUIREMENT:
            # 进入 DESIGN 阶段
            pipeline.status = PipelineStatus.RUNNING
            pipeline.current_stage = StageName.DESIGN
            await session.commit()
            
            # 触发 DesignerAgent
            await cls._trigger_designer_analysis(pipeline_id, session)
            
            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": StageName.REQUIREMENT.value,
                    "next_stage": StageName.DESIGN.value,
                    "status": PipelineStatus.RUNNING.value,
                    "message": "Pipeline approved, proceeding to DESIGN stage"
                }
            }
        
        elif current_stage == StageName.DESIGN:
            # 进入 CODING 阶段
            pipeline.status = PipelineStatus.RUNNING
            pipeline.current_stage = StageName.CODING
            await session.commit()
            
            # 触发 CoderAgent 和代码执行流程
            coding_result = await cls._trigger_coding_phase(pipeline_id, session)
            
            return {
                "success": coding_result["success"],
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": StageName.DESIGN.value,
                    "next_stage": StageName.CODING.value,
                    "status": coding_result.get("status", PipelineStatus.RUNNING.value),
                    "message": coding_result.get("message", "Pipeline approved, proceeding to CODING stage"),
                    "git_branch": coding_result.get("git_branch"),
                    "commit_hash": coding_result.get("commit_hash")
                }
            }
        
        else:
            return {"success": False, "error": f"Unknown current stage: {current_stage}"}
    
    @classmethod
    async def reject_pipeline(
        cls,
        pipeline_id: int,
        reason: str,
        suggested_changes: Optional[str],
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        驳回 Pipeline，退回当前阶段重新执行
        
        实现"自动回归"思想：携带 Reject 理由重新运行 Agent
        
        Args:
            pipeline_id: Pipeline ID
            reason: 驳回原因
            suggested_changes: 建议修改
            session: 数据库会话
            
        Returns:
            Dict: 驳回结果
        """
        from sqlmodel import select
        
        # 获取 Pipeline
        statement = select(Pipeline).where(Pipeline.id == pipeline_id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}
        
        # 检查状态
        if pipeline.status != PipelineStatus.PAUSED:
            return {"success": False, "error": f"Pipeline is not in PAUSED state, cannot reject"}
        
        current_stage = pipeline.current_stage
        
        # 记录驳回信息到当前阶段的 output_data
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == current_stage
        )
        result = await session.execute(statement)
        stage = result.scalar_one_or_none()
        
        if stage:
            if stage.output_data is None:
                stage.output_data = {}
            stage.output_data["rejection_feedback"] = {
                "reason": reason,
                "suggested_changes": suggested_changes,
                "rejected_at": datetime.utcnow().isoformat()
            }
            stage.status = StageStatus.RUNNING  # 重新设为运行中
            session.add(stage)
        
        # 重新运行当前阶段
        pipeline.status = PipelineStatus.RUNNING
        await session.commit()
        
        # 根据当前阶段重新触发对应的 Agent
        if current_stage == StageName.REQUIREMENT:
            # 重新触发 ArchitectAgent，携带驳回反馈
            requirement = pipeline.description
            await cls._trigger_architect_analysis_with_feedback(
                pipeline_id, requirement, reason, suggested_changes, session
            )
        elif current_stage == StageName.DESIGN:
            # 重新触发 DesignerAgent，携带驳回反馈
            await cls._trigger_designer_analysis_with_feedback(
                pipeline_id, reason, suggested_changes, session
            )
        
        return {
            "success": True,
            "data": {
                "pipeline_id": pipeline_id,
                "current_stage": current_stage.value if current_stage else None,
                "status": PipelineStatus.RUNNING.value,
                "message": f"Pipeline rejected, re-running {current_stage.value if current_stage else 'current'} stage with feedback",
                "feedback": {
                    "reason": reason,
                    "suggested_changes": suggested_changes
                }
            }
        }
    
    @classmethod
    async def _trigger_designer_analysis(
        cls,
        pipeline_id: int,
        session: AsyncSession
    ) -> None:
        """
        触发 DesignerAgent 进行技术设计
        
        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
        """
        from sqlmodel import select
        
        design_stage = None
        error_message = None
        
        try:
            # 获取 REQUIREMENT 阶段的输出作为输入
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result = await session.execute(statement)
            requirement_stage = result.scalar_one_or_none()
            
            if not requirement_stage or not requirement_stage.output_data:
                error_message = "No requirement output found"
                print(f"{error_message} for pipeline {pipeline_id}")
                raise ValueError(error_message)
            
            architect_output = requirement_stage.output_data
            
            # 创建 DESIGN 阶段
            design_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name=StageName.DESIGN,
                status=StageStatus.RUNNING,
                input_data=architect_output
            )
            session.add(design_stage)
            await session.commit()
            
            # 调用 DesignerAgent
            agent_result = await designer_agent.design(architect_output)
            
            # 更新 DESIGN 阶段
            if agent_result["success"]:
                design_stage.status = StageStatus.SUCCESS
                design_stage.output_data = agent_result["output"]
            else:
                design_stage.status = StageStatus.FAILED
                design_stage.output_data = {"error": agent_result["error"]}
            
            design_stage.completed_at = datetime.utcnow()
            session.add(design_stage)
            
            # 更新 Pipeline 状态为 PAUSED，等待人工审批
            statement = select(Pipeline).where(Pipeline.id == pipeline_id)
            query_result = await session.execute(statement)
            pipeline = query_result.scalar_one_or_none()
            
            if pipeline:
                if agent_result["success"]:
                    pipeline.status = PipelineStatus.PAUSED
                else:
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
        except Exception as e:
            # 以吞掉异常为耻：必须记录错误并更新状态
            error_message = error_message or str(e)
            print(f"Designer analysis failed for pipeline {pipeline_id}: {error_message}")
            
            try:
                # 更新 DESIGN 阶段为 FAILED
                if design_stage:
                    design_stage.status = StageStatus.FAILED
                    design_stage.output_data = {"error": error_message}
                    design_stage.completed_at = datetime.utcnow()
                    session.add(design_stage)
                
                # 更新 Pipeline 状态为 FAILED
                statement = select(Pipeline).where(Pipeline.id == pipeline_id)
                result = await session.execute(statement)
                pipeline = result.scalar_one_or_none()
                
                if pipeline:
                    pipeline.status = PipelineStatus.FAILED
                    await session.commit()
                else:
                    await session.rollback()
            except Exception as update_error:
                # 如果连状态更新都失败，至少打印错误
                print(f"Failed to update pipeline status: {update_error}")
                await session.rollback()
                raise
    
    @classmethod
    async def _trigger_architect_analysis_with_feedback(
        cls,
        pipeline_id: int,
        requirement: str,
        reason: str,
        suggested_changes: Optional[str],
        session: AsyncSession
    ) -> None:
        """
        携带驳回反馈重新触发 ArchitectAgent
        
        Args:
            pipeline_id: Pipeline ID
            requirement: 原始需求
            reason: 驳回原因
            suggested_changes: 建议修改
            session: 数据库会话
        """
        from sqlmodel import select
        
        try:
            # 获取项目文件树
            from app.service.project import get_current_project_tree
            file_tree_node = get_current_project_tree(max_depth=4)
            file_tree = ProjectService.file_tree_to_dict(file_tree_node) if file_tree_node else {}
            
            # 构建带反馈的需求
            feedback_requirement = f"""原始需求: {requirement}

审批反馈:
- 驳回原因: {reason}
- 建议修改: {suggested_changes or '无'}

请根据以上反馈重新分析需求。"""
            
            # 调用 ArchitectAgent
            result = await architect_agent.analyze(feedback_requirement, file_tree)
            
            # 获取当前阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result_query = await session.execute(statement)
            stage = result_query.scalar_one_or_none()
            
            if stage:
                if result["success"]:
                    stage.status = StageStatus.SUCCESS
                    stage.output_data = result["output"]
                else:
                    stage.status = StageStatus.FAILED
                    stage.output_data = {"error": result["error"]}
                
                stage.completed_at = datetime.utcnow()
                session.add(stage)
            
            # 更新 Pipeline 状态
            statement = select(Pipeline).where(Pipeline.id == pipeline_id)
            result_query = await session.execute(statement)
            pipeline = result_query.scalar_one_or_none()
            
            if pipeline:
                if result["success"]:
                    pipeline.status = PipelineStatus.PAUSED
                else:
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
        except Exception as e:
            print(f"Architect re-analysis failed for pipeline {pipeline_id}: {e}")
            await session.rollback()
    
    @classmethod
    async def _trigger_designer_analysis_with_feedback(
        cls,
        pipeline_id: int,
        reason: str,
        suggested_changes: Optional[str],
        session: AsyncSession
    ) -> None:
        """
        携带驳回反馈重新触发 DesignerAgent
        
        Args:
            pipeline_id: Pipeline ID
            reason: 驳回原因
            suggested_changes: 建议修改
            session: 数据库会话
        """
        from sqlmodel import select
        
        try:
            # 获取 REQUIREMENT 阶段的输出
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.REQUIREMENT
            )
            result = await session.execute(statement)
            requirement_stage = result.scalar_one_or_none()
            
            if not requirement_stage or not requirement_stage.output_data:
                return
            
            architect_output = requirement_stage.output_data
            
            # 添加反馈到输入
            architect_output_with_feedback = {
                **architect_output,
                "rejection_feedback": {
                    "reason": reason,
                    "suggested_changes": suggested_changes
                }
            }
            
            # 调用 DesignerAgent
            result = await designer_agent.design(architect_output_with_feedback)
            
            # 获取 DESIGN 阶段
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result_query = await session.execute(statement)
            design_stage = result_query.scalar_one_or_none()
            
            if design_stage:
                if result["success"]:
                    design_stage.status = StageStatus.SUCCESS
                    design_stage.output_data = result["output"]
                else:
                    design_stage.status = StageStatus.FAILED
                    design_stage.output_data = {"error": result["error"]}
                
                design_stage.completed_at = datetime.utcnow()
                session.add(design_stage)
            
            # 更新 Pipeline 状态
            statement = select(Pipeline).where(Pipeline.id == pipeline_id)
            result_query = await session.execute(statement)
            pipeline = result_query.scalar_one_or_none()
            
            if pipeline:
                if result["success"]:
                    pipeline.status = PipelineStatus.PAUSED
                else:
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
        except Exception as e:
            print(f"Designer re-analysis failed for pipeline {pipeline_id}: {e}")
            await session.rollback()
    
    @classmethod
    async def _trigger_coding_phase(
        cls,
        pipeline_id: int,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        触发 CODING 阶段
        
        流程：
        1. 创建 Git 分支 devflow/pipeline-{id}
        2. 运行 CoderAgent 生成代码
        3. 调用 CodeExecutorService 写入文件
        4. 自动 git commit
        5. 将 Pipeline 状态设为 SUCCESS
        
        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            
        Returns:
            Dict: 执行结果
        """
        from sqlmodel import select
        
        git_branch = None
        commit_hash = None
        
        try:
            # 1. 创建 Git 分支
            git_service = GitProviderService()
            git_branch = f"devflow/pipeline-{pipeline_id}"
            
            try:
                git_service.create_branch(git_branch)
            except GitProviderError as e:
                # 分支可能已存在，尝试切换
                if "分支已存在" in str(e):
                    git_service.checkout_branch(git_branch)
                else:
                    raise
            
            # 2. 获取 DESIGN 阶段的输出
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result = await session.execute(statement)
            design_stage = result.scalar_one_or_none()
            
            if not design_stage or not design_stage.output_data:
                return {
                    "success": False,
                    "status": PipelineStatus.FAILED.value,
                    "message": "No design output found",
                    "git_branch": git_branch
                }
            
            design_output = design_stage.output_data
            
            # 3. 创建 CODING 阶段
            coding_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name=StageName.CODING,
                status=StageStatus.RUNNING,
                input_data=design_output
            )
            session.add(coding_stage)
            await session.commit()
            
            # 4. 读取目标文件当前内容
            code_executor = CodeExecutorService()
            target_files = {}
            
            # 从 design_output 中提取需要修改的文件
            if "function_changes" in design_output:
                for change in design_output["function_changes"]:
                    file_path = change.get("file", "")
                    if file_path:
                        content = code_executor.get_file_content(file_path)
                        if content:
                            target_files[file_path] = content
            
            # 5. 调用 CoderAgent 生成代码
            coder_result = await coder_agent.generate_code(design_output, target_files)
            
            if not coder_result["success"]:
                # 更新 CODING 阶段状态
                coding_stage.status = StageStatus.FAILED
                coding_stage.output_data = {"error": coder_result["error"]}
                coding_stage.completed_at = datetime.utcnow()
                session.add(coding_stage)
                
                # 更新 Pipeline 状态
                statement = select(Pipeline).where(Pipeline.id == pipeline_id)
                result = await session.execute(statement)
                pipeline = result.scalar_one_or_none()
                if pipeline:
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
                return {
                    "success": False,
                    "status": PipelineStatus.FAILED.value,
                    "message": f"CoderAgent failed: {coder_result['error']}",
                    "git_branch": git_branch
                }
            
            # 6. 应用代码变更
            generated_files = coder_result["output"]["files"]
            changes_dict = {}
            for file_change in generated_files:
                changes_dict[file_change["file_path"]] = file_change["content"]
            
            execution_result = code_executor.apply_changes(
                changes=changes_dict,
                create_if_missing=True
            )
            
            if not execution_result.success:
                # 回滚变更
                code_executor.rollback_changes(execution_result.changes)
                
                # 更新 CODING 阶段状态
                coding_stage.status = StageStatus.FAILED
                coding_stage.output_data = {
                    "error": "Code execution failed",
                    "execution_errors": execution_result.errors
                }
                coding_stage.completed_at = datetime.utcnow()
                session.add(coding_stage)
                
                # 更新 Pipeline 状态
                statement = select(Pipeline).where(Pipeline.id == pipeline_id)
                result = await session.execute(statement)
                pipeline = result.scalar_one_or_none()
                if pipeline:
                    pipeline.status = PipelineStatus.FAILED
                await session.commit()
                
                return {
                    "success": False,
                    "status": PipelineStatus.FAILED.value,
                    "message": f"Code execution failed: {execution_result.errors}",
                    "git_branch": git_branch
                }
            
            # 7. Git 提交
            if execution_result.summary["success"] > 0:
                git_service.add_files()
                
                if git_service.has_changes():
                    commit_message = f"feat(pipeline-{pipeline_id}): {coder_result['output']['summary'][:100]}"
                    git_service.commit_changes(commit_message)
                    commit_hash = git_service.get_last_commit_hash()
            
            # 8. 更新 CODING 阶段状态
            coding_stage.status = StageStatus.SUCCESS
            coding_stage.output_data = {
                "coder_output": coder_result["output"],
                "execution_summary": execution_result.summary,
                "git_branch": git_branch,
                "commit_hash": commit_hash
            }
            coding_stage.completed_at = datetime.utcnow()
            session.add(coding_stage)
            
            # 9. 更新 Pipeline 状态为 SUCCESS
            statement = select(Pipeline).where(Pipeline.id == pipeline_id)
            result = await session.execute(statement)
            pipeline = result.scalar_one_or_none()
            
            if pipeline:
                pipeline.status = PipelineStatus.SUCCESS
                await session.commit()
            
            return {
                "success": True,
                "status": PipelineStatus.SUCCESS.value,
                "message": "Coding phase completed successfully",
                "git_branch": git_branch,
                "commit_hash": commit_hash,
                "files_changed": execution_result.summary
            }
            
        except Exception as e:
            print(f"Coding phase failed for pipeline {pipeline_id}: {e}")
            await session.rollback()
            
            return {
                "success": False,
                "status": PipelineStatus.FAILED.value,
                "message": f"Coding phase failed: {str(e)}",
                "git_branch": git_branch
            }
    
    @classmethod
    async def get_pipeline_status(
        cls,
        pipeline_id: int,
        session: AsyncSession
    ) -> Optional[PipelineRead]:
        """
        获取 Pipeline 状态
        
        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            
        Returns:
            PipelineRead: Pipeline 状态信息，不存在返回 None
        """
        from sqlmodel import select
        
        statement = select(Pipeline).where(Pipeline.id == pipeline_id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline = result.scalar_one_or_none()
        
        if pipeline:
            return cls._build_pipeline_read(pipeline)
        return None
    
    @classmethod
    async def list_pipelines(
        cls,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> list[PipelineRead]:
        """
        列出所有 Pipeline
        
        Args:
            session: 数据库会话
            skip: 跳过数量
            limit: 返回数量限制
            
        Returns:
            list[PipelineRead]: Pipeline 列表
        """
        from sqlmodel import select
        
        statement = select(Pipeline).offset(skip).limit(limit)
        result = await session.execute(statement)
        pipelines = result.scalars().all()
        
        # 对于列表，不加载 stages
        return [
            PipelineRead(
                id=p.id,
                description=p.description,
                status=p.status,
                current_stage=p.current_stage,
                created_at=p.created_at,
                updated_at=p.updated_at,
                stages=None
            )
            for p in pipelines
        ]
