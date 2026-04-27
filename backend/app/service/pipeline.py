"""
Pipeline 业务服务
业务逻辑层 - 协调 Pipeline 创建、Agent 调用和人工审批
"""

from typing import Optional, Dict, Any
from pathlib import Path

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

import logging

from app.core.config import settings
from app.core.logging import info, op_logger
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)
from app.models.pipeline import (
    Pipeline, PipelineRead, PipelineStatus,
    PipelineStage, StageName, StageStatus, PipelineStageRead
)
from app.service.code_executor import CodeExecutorService
from app.service.git_provider import GitProviderService, GitProviderError
from app.service.platform_provider import GitHubProviderService
from app.service.workspace import workspace_context
from app.service.workflow import WorkflowService
from app.service.agent_coordinator import AgentCoordinatorService
from app.service.pr_generator import PRGeneratorService


class PipelineService:
    """
    Pipeline 业务服务
    
    负责：
    1. Pipeline 的创建和管理
    2. 协调 Agent 执行 - 委托给 AgentCoordinatorService
    3. 管理 Pipeline 状态流转 - 委托给 WorkflowService
    4. 代码交付 - 委托给 WorkspaceService 管理工作区
    5. PR 生成 - 委托给 PRGeneratorService
    """
    
    @classmethod
    async def create_pipeline_record(
        cls,
        requirement: str,
        element_context: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> PipelineRead:
        """创建 Pipeline 记录（仅创建，不触发分析）"""
        # 1. 创建 Pipeline
        pipeline = Pipeline(
            description=requirement,
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        session.add(pipeline)
        await session.flush()

        info("Pipeline 记录创建成功", pipeline_id=pipeline.id, status="RUNNING")

        # 2. 创建 REQUIREMENT 阶段
        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.REQUIREMENT,
            status=StageStatus.RUNNING,
            input_data={"requirement": requirement, "element_context": element_context}
        )
        session.add(stage)
        await session.flush()

        info("Pipeline 阶段创建成功", pipeline_id=pipeline.id, stage="REQUIREMENT")
        op_logger.log_pipeline_create(
            pipeline_id=pipeline.id,
            description=requirement,
            has_context=element_context is not None
        )

        # 3. 重新查询以获取完整数据
        statement = select(Pipeline).where(Pipeline.id == pipeline.id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline_with_stages = result.scalar_one()

        return cls._build_pipeline_read(pipeline_with_stages)
    
    @classmethod
    async def run_architect_task(
        cls,
        pipeline_id: int,
        requirement: str,
        element_context: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> None:
        """后台任务：运行 ArchitectAgent 分析"""
        await cls._trigger_architect_analysis(pipeline_id, requirement, element_context, session)
    
    @classmethod
    async def create_pipeline(cls, requirement: str, session: AsyncSession) -> PipelineRead:
        """创建新的 Pipeline（旧版同步方法，保留兼容性）"""
        # 1. 创建 Pipeline
        pipeline = Pipeline(
            description=requirement,
            status=PipelineStatus.RUNNING,
            current_stage=StageName.REQUIREMENT
        )
        session.add(pipeline)
        await session.flush()
        
        # 2. 创建 REQUIREMENT 阶段
        stage = PipelineStage(
            pipeline_id=pipeline.id,
            name=StageName.REQUIREMENT,
            status=StageStatus.RUNNING,
            input_data={"requirement": requirement}
        )
        session.add(stage)
        await session.commit()
        
        # 3. 触发 ArchitectAgent
        await cls._trigger_architect_analysis(pipeline.id, requirement, None, session)
        
        # 4. 返回结果
        statement = select(Pipeline).where(Pipeline.id == pipeline.id).options(
            selectinload(Pipeline.stages)
        )
        result = await session.execute(statement)
        pipeline_with_stages = result.scalar_one()
        return cls._build_pipeline_read(pipeline_with_stages)
    
    @classmethod
    def _build_pipeline_read(cls, pipeline: Pipeline) -> PipelineRead:
        """将 Pipeline ORM 对象转换为 PipelineRead"""
        stages_read = [
            PipelineStageRead(
                id=stage.id,
                name=stage.name,
                status=stage.status,
                input_data=stage.input_data,
                output_data=stage.output_data,
                created_at=stage.created_at,
                completed_at=stage.completed_at
            )
            for stage in (pipeline.stages or [])
        ]
        
        return PipelineRead(
            id=pipeline.id,
            description=pipeline.description,
            status=pipeline.status,
            current_stage=pipeline.current_stage,
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,
            stages=stages_read if stages_read else None
        )
    
    # ==================== Agent 触发方法（委托给 AgentCoordinatorService） ====================
    
    @classmethod
    async def _trigger_architect_analysis(
        cls,
        pipeline_id: int,
        requirement: str,
        element_context: Optional[Dict[str, Any]],
        session: AsyncSession
    ) -> None:
        """触发 ArchitectAgent 分析"""
        try:
            result = await AgentCoordinatorService.run_architect_analysis(
                pipeline_id, requirement, element_context, session
            )
            
            # 更新 Pipeline 状态
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                if result["success"]:
                    await WorkflowService.set_pipeline_paused(pipeline, session)
                else:
                    await WorkflowService.set_pipeline_failed(pipeline, session)
                    from app.core.sse_log_buffer import remove_buffer
                    remove_buffer(pipeline_id)

        except Exception:
            await session.rollback()
            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(pipeline_id)
            raise
    
    @classmethod
    async def _trigger_designer_analysis(cls, pipeline_id: int, session: AsyncSession) -> None:
        """触发 DesignerAgent 进行技术设计"""
        try:
            result = await AgentCoordinatorService.run_designer_analysis(pipeline_id, session)
            
            # 更新 Pipeline 状态
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                if result["success"]:
                    await WorkflowService.set_pipeline_paused(pipeline, session)
                else:
                    await WorkflowService.set_pipeline_failed(pipeline, session)

        except Exception:
            await session.rollback()
            raise
    
    @classmethod
    async def _trigger_architect_analysis_with_feedback(
        cls, pipeline_id: int, requirement: str, reason: str,
        suggested_changes: Optional[str], session: AsyncSession
    ) -> None:
        """携带驳回反馈重新触发 ArchitectAgent"""
        try:
            result = await AgentCoordinatorService.run_architect_with_feedback(
                pipeline_id, requirement, reason, suggested_changes, session
            )
            
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                if result["success"]:
                    await WorkflowService.set_pipeline_paused(pipeline, session)
                else:
                    await WorkflowService.set_pipeline_failed(pipeline, session)
                
        except Exception:
            await session.rollback()
    
    @classmethod
    async def _trigger_designer_analysis_with_feedback(
        cls, pipeline_id: int, reason: str,
        suggested_changes: Optional[str], session: AsyncSession
    ) -> None:
        """携带驳回反馈重新触发 DesignerAgent"""
        try:
            result = await AgentCoordinatorService.run_designer_with_feedback(
                pipeline_id, reason, suggested_changes, session
            )
            
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                if result["success"]:
                    await WorkflowService.set_pipeline_paused(pipeline, session)
                else:
                    await WorkflowService.set_pipeline_failed(pipeline, session)
                
        except Exception:
            await session.rollback()
    
    # ==================== 阶段触发方法 ====================
    
    @classmethod
    async def _trigger_coding_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 CODING 阶段 - 优化版：使用临时工作区和自动修复循环
        
        【增强】使用 AgentCoordinatorService.get_target_files_for_coding 获取目标文件
        这样可以利用新的 affected_files 字段，获取更完整的代码上下文
        """
        design_output = None
        coding_stage_id = None
        target_files = {}

        try:
            # 1. 获取 DESIGN 阶段输出（短暂持有连接）
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result = await session.execute(statement)
            design_stage = result.scalar_one_or_none()

            if not design_stage or not design_stage.output_data:
                return {"success": False, "status": PipelineStatus.FAILED.value, "message": "No design output found"}

            design_output = design_stage.output_data

            # 2. 创建 CODING 阶段（短暂持有连接）
            coding_stage = await WorkflowService.create_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.CODING,
                input_data=design_output,
                session=session
            )
            coding_stage_id = coding_stage.id

            # 3. 【增强】使用 AgentCoordinatorService 获取目标文件
            # 这样可以利用新的 affected_files 字段，获取更完整的代码上下文
            target_files = await AgentCoordinatorService.get_target_files_for_coding(
                pipeline_id=pipeline_id,
                design_output=design_output,
                session=session
            )

            # 4. 提交当前事务并关闭连接（关键：释放数据库连接）
            await session.commit()

        except Exception as e:
            await session.rollback()
            await push_log(pipeline_id, "error", f"准备代码生成阶段失败: {str(e)}", stage="CODING")
            return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Coding preparation failed: {str(e)}"}

        # 5. 使用临时工作区和自动修复循环执行代码生成
        from app.agents.multi_agent_coordinator import multi_agent_coordinator
        from app.service.workspace import async_workspace_context

        multi_agent_result = None

        try:
            async with async_workspace_context(pipeline_id) as ws:
                workspace_dir = ws.get_workspace_path()
                await push_log(pipeline_id, "info", f"创建临时工作区: {workspace_dir.name}", stage="CODING")

                # 调用带自动修复的协调器
                multi_agent_result = await multi_agent_coordinator.execute_with_auto_fix(
                    design_output=design_output,
                    target_files=target_files,
                    pipeline_id=pipeline_id,
                    workspace_path=str(workspace_dir)
                )

                # 如果成功，记录测试日志
                if multi_agent_result["success"] and "test_logs" in multi_agent_result:
                    await push_log(pipeline_id, "info", "测试日志已保存", stage="CODING")

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码生成执行失败: {str(e)}", stage="CODING")
            multi_agent_result = {
                "success": False,
                "error": str(e),
                "output": None
            }

        # 6. 重新获取连接，保存结果
        try:
            if not multi_agent_result or not multi_agent_result["success"]:
                error_msg = multi_agent_result.get("error", "Unknown error") if multi_agent_result else "Unknown error"

                # 修复：无论成功失败，都要把代码落库传给前端
                output_data_to_save = {
                    "error": error_msg,
                    "last_error_logs": multi_agent_result.get("last_error_logs") if multi_agent_result else None
                }
                # 如果有代码产出，挂载上去
                if multi_agent_result and multi_agent_result.get("output"):
                    output_data_to_save["multi_agent_output"] = multi_agent_result["output"]
                    output_data_to_save["target_files"] = target_files

                # 重新获取 stage 并更新为失败
                statement = select(PipelineStage).where(PipelineStage.id == coding_stage_id)
                result = await session.execute(statement)
                coding_stage = result.scalar_one_or_none()

                if coding_stage:
                    # 提取可观测性指标（如果有）
                    metrics = {
                        'input_tokens': multi_agent_result.get('input_tokens', 0) if multi_agent_result else 0,
                        'output_tokens': multi_agent_result.get('output_tokens', 0) if multi_agent_result else 0,
                        'duration_ms': multi_agent_result.get('duration_ms', 0) if multi_agent_result else 0,
                        'retry_count': multi_agent_result.get('attempt', 0) if multi_agent_result else 0,
                        'reasoning': multi_agent_result.get('reasoning') if multi_agent_result else None
                    }
                    await WorkflowService.complete_stage(
                        stage=coding_stage,
                        output_data=output_data_to_save,  # 使用组装好的 output_data
                        success=False,
                        session=session,
                        metrics=metrics
                    )

                pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
                if pipeline:
                    await WorkflowService.set_pipeline_failed(pipeline, session)

                from app.core.sse_log_buffer import remove_buffer
                remove_buffer(pipeline_id)

                await session.commit()
                return {
                    "success": False,
                    "status": PipelineStatus.FAILED.value,
                    "message": f"Multi-agent execution failed: {error_msg}"
                }

            # 7. 成功处理
            combined_output = multi_agent_result["output"]
            file_count = len(combined_output.get('files', []))
            attempt_count = multi_agent_result.get("attempt", 0)

            # Debug: 检查 CODING output 中 files 的 content 字段
            sample_files = combined_output.get('files', [])[:2]
            logger.info(f"[Debug] CODING output files sample: "
                        f"{[{'path': f.get('file_path'), 'has_content': bool(f.get('content')), 'has_original': 'original_content' in f} for f in sample_files]}")

            if attempt_count > 0:
                await push_log(pipeline_id, "info", f"代码生成完成（经过 {attempt_count + 1} 次尝试），共 {file_count} 个文件", stage="CODING")
            else:
                await push_log(pipeline_id, "info", f"代码生成完成，共 {file_count} 个文件", stage="CODING")

            # 重新获取 stage 并更新为成功
            statement = select(PipelineStage).where(PipelineStage.id == coding_stage_id)
            result = await session.execute(statement)
            coding_stage = result.scalar_one_or_none()

            if coding_stage:
                # 提取可观测性指标
                metrics = {
                    'input_tokens': multi_agent_result.get('input_tokens', 0),
                    'output_tokens': multi_agent_result.get('output_tokens', 0),
                    'duration_ms': multi_agent_result.get('duration_ms', 0),
                    'retry_count': attempt_count,
                    'reasoning': multi_agent_result.get('reasoning')
                }
                await WorkflowService.complete_stage(
                    stage=coding_stage,
                    output_data={
                        "multi_agent_output": combined_output,
                        "tests_included": combined_output.get("tests_included", False),
                        "target_files": target_files,
                        "auto_fix_attempts": attempt_count,
                        "test_logs": multi_agent_result.get("test_logs")
                    },
                    success=True,
                    session=session,
                    metrics=metrics
                )

            # 8. 创建 UNIT_TESTING 阶段（新增：在 CODING 之后进行单元测试）
            await WorkflowService.create_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.UNIT_TESTING,
                input_data={"coding_output": combined_output, "target_files": target_files, "design_output": design_output},
                session=session
            )

            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                pipeline.current_stage = StageName.UNIT_TESTING
                await WorkflowService.set_pipeline_running(pipeline, session)

            await push_log(pipeline_id, "info", "代码生成完成，进入单元测试阶段", stage="UNIT_TESTING")

            await session.commit()

            return {
                "success": True,
                "status": PipelineStatus.RUNNING.value,  # 改为 RUNNING，因为要继续执行 UNIT_TESTING
                "message": "Code generated successfully, entering unit testing",
                "files_count": file_count,
                "auto_fix_attempts": attempt_count
            }

        except Exception as e:
            await push_log(pipeline_id, "error", f"保存代码生成结果失败: {str(e)}", stage="CODING")
            await session.rollback()
            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(pipeline_id)
            return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Coding save failed: {str(e)}"}

    @classmethod
    async def _trigger_testing_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 UNIT_TESTING 阶段 - 生成测试并执行

        使用 TestAgent 生成测试代码，并在临时工作区执行验证。
        如果测试失败，可以启动自动修复循环（允许修改测试文件）。
        """
        coding_output = None
        design_output = None
        target_files = {}
        testing_stage_id = None

        try:
            # 1. 获取 CODING 阶段输出
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.CODING
            )
            result = await session.execute(statement)
            coding_stage = result.scalar_one_or_none()

            if not coding_stage or not coding_stage.output_data:
                return {"success": False, "status": PipelineStatus.FAILED.value, "message": "No coding output found"}

            coding_output = coding_stage.output_data.get("multi_agent_output", {})
            target_files = coding_stage.output_data.get("target_files", {})

            # 2. 获取 DESIGN 阶段输出（用于 TestAgent）
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.DESIGN
            )
            result = await session.execute(statement)
            design_stage = result.scalar_one_or_none()

            if design_stage and design_stage.output_data:
                design_output = design_stage.output_data

            # 3. 创建 UNIT_TESTING 阶段（如果还没有创建）
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.UNIT_TESTING
            )
            result = await session.execute(statement)
            testing_stage = result.scalar_one_or_none()

            if not testing_stage:
                testing_stage = await WorkflowService.create_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.UNIT_TESTING,
                    input_data={"coding_output": coding_output, "target_files": target_files, "design_output": design_output},
                    session=session
                )
            testing_stage_id = testing_stage.id

            # 4. 提交当前事务并关闭连接
            await session.commit()

        except Exception as e:
            await session.rollback()
            await push_log(pipeline_id, "error", f"准备单元测试阶段失败: {str(e)}", stage="UNIT_TESTING")
            return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Testing preparation failed: {str(e)}"}

        # 5. 使用临时工作区执行测试生成和验证
        from app.agents.multi_agent_coordinator import multi_agent_coordinator
        from app.service.workspace import async_workspace_context
        from app.agents import test_agent

        testing_result = None

        try:
            async with async_workspace_context(pipeline_id) as ws:
                workspace_dir = ws.get_workspace_path()
                await push_log(pipeline_id, "info", f"创建临时工作区用于测试: {workspace_dir.name}", stage="UNIT_TESTING")

                # 先写入代码文件到工作区
                from app.service.code_executor import CodeExecutorService
                from app.service.import_sanitizer import ImportSanitizer

                executor = CodeExecutorService(workspace_dir)
                all_files = coding_output.get("files", [])

                # 修正 import 路径
                all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

                # 强制添加 backend/ 前缀
                for f in all_files:
                    p = f.get("file_path", "")
                    p = p.lstrip("/")
                    if p and not p.startswith("backend/"):
                        f["file_path"] = f"backend/{p}"

                executor.apply_changes(
                    {f["file_path"]: f["content"] for f in all_files},
                    create_if_missing=True
                )

                # 6. 调用 TestAgent 生成测试
                await push_log(pipeline_id, "info", "TestAgent 开始生成测试代码...", stage="UNIT_TESTING")

                test_result = await test_agent.generate_tests(
                    design_output=design_output,
                    code_output=coding_output,
                    target_files=target_files,
                    pipeline_id=pipeline_id
                )

                if not test_result["success"]:
                    error_msg = test_result.get("error", "Unknown error")
                    await push_log(pipeline_id, "warning", f"TestAgent 生成测试失败: {error_msg}", stage="UNIT_TESTING")

                    # 测试生成失败，但代码是成功的，继续到 CODE_REVIEW
                    testing_result = {
                        "success": True,  # 标记为成功，因为代码本身没问题
                        "test_generated": False,
                        "test_error": error_msg
                    }
                else:
                    # 7. 写入测试文件到工作区
                    test_output = test_result["output"]
                    test_files = test_output.get("files", [])

                    if test_files:
                        await push_log(pipeline_id, "info", f"TestAgent 生成 {len(test_files)} 个测试文件", stage="UNIT_TESTING")

                        # 写入测试文件
                        for test_file in test_files:
                            file_path = test_file.get("file_path", "")
                            content = test_file.get("content", "")
                            if file_path and content:
                                # 确保测试文件路径正确
                                if not file_path.startswith("tests/") and not file_path.startswith("backend/tests/"):
                                    file_path = f"tests/{file_path}"
                                executor.apply_changes({file_path: content}, create_if_missing=True)

                        # 8. 运行测试验证
                        await push_log(pipeline_id, "info", "运行测试验证...", stage="UNIT_TESTING")

                        from app.service.test_runner import TestRunnerService
                        test_run_result = await TestRunnerService.run_tests(str(workspace_dir))

                        if test_run_result["success"]:
                            await push_log(pipeline_id, "success", "✅ 所有测试通过！", stage="UNIT_TESTING")
                            testing_result = {
                                "success": True,
                                "test_generated": True,
                                "test_files": test_files,
                                "test_run_success": True,
                                "test_logs": test_run_result.get("logs", "")
                            }
                        else:
                            # 测试失败，记录错误
                            error_summary = test_run_result.get("summary", "Unknown error")
                            await push_log(pipeline_id, "warning", f"⚠️ 测试未通过: {error_summary}", stage="UNIT_TESTING")

                            testing_result = {
                                "success": True,  # 代码本身没问题，只是测试失败
                                "test_generated": True,
                                "test_files": test_files,
                                "test_run_success": False,
                                "test_error": error_summary,
                                "test_logs": test_run_result.get("logs", "")
                            }
                    else:
                        await push_log(pipeline_id, "info", "TestAgent 未生成测试文件", stage="UNIT_TESTING")
                        testing_result = {
                            "success": True,
                            "test_generated": False,
                            "test_error": "No test files generated"
                        }

        except Exception as e:
            await push_log(pipeline_id, "error", f"单元测试执行失败: {str(e)}", stage="UNIT_TESTING")
            testing_result = {
                "success": True,  # 代码本身没问题
                "test_generated": False,
                "test_error": str(e)
            }

        # 9. 重新获取连接，保存结果
        try:
            statement = select(PipelineStage).where(PipelineStage.id == testing_stage_id)
            result = await session.execute(statement)
            testing_stage = result.scalar_one_or_none()

            if testing_stage:
                await WorkflowService.complete_stage(
                    stage=testing_stage,
                    output_data={
                        "testing_result": testing_result,
                        "coding_output": coding_output,
                        "target_files": target_files
                    },
                    success=testing_result["success"],
                    session=session
                )

            # 10. 创建 CODE_REVIEW 阶段
            await WorkflowService.create_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.CODE_REVIEW,
                input_data={
                    "coding_output": coding_output,
                    "testing_result": testing_result,
                    "target_files": target_files
                },
                session=session
            )

            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                pipeline.current_stage = StageName.CODE_REVIEW
                await WorkflowService.set_pipeline_paused(pipeline, session)

            await push_log(pipeline_id, "info", "单元测试完成，进入代码审查阶段", stage="CODE_REVIEW")

            await session.commit()

            return {
                "success": True,
                "status": PipelineStatus.PAUSED.value,
                "message": "Unit testing completed",
                "test_generated": testing_result.get("test_generated", False),
                "test_run_success": testing_result.get("test_run_success", False)
            }

        except Exception as e:
            await push_log(pipeline_id, "error", f"保存单元测试结果失败: {str(e)}", stage="UNIT_TESTING")
            await session.rollback()
            return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Testing save failed: {str(e)}"}

    @classmethod
    async def _trigger_delivery_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 DELIVERY 阶段（代码交付）"""
        git_branch = None
        commit_hash = None
        pr_url = None
        
        try:
            # 1. 获取 Pipeline 和 CODING 阶段信息
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if not pipeline:
                return {"success": False, "status": PipelineStatus.FAILED.value, "message": "Pipeline not found"}
            
            requirement_summary = pipeline.description[:80] if pipeline.description else f"Pipeline #{pipeline_id}"
            
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.CODING
            )
            result = await session.execute(statement)
            coding_stage = result.scalar_one_or_none()
            
            if not coding_stage or not coding_stage.output_data:
                return {"success": False, "status": PipelineStatus.FAILED.value, "message": "No coding output found"}
            
            coding_output = coding_stage.output_data
            multi_agent_output = coding_output.get("multi_agent_output", {})
            generated_files = multi_agent_output.get("files", [])
            
            # 2. 使用 WorkspaceService 管理临时工作区
            with workspace_context(pipeline_id) as ws:
                workspace_dir = ws.get_workspace_path()
                await push_log(pipeline_id, "info", f"创建临时工作区: {workspace_dir.name}", stage="DELIVERY")
                
                # 3. Git 操作
                git_service = GitProviderService(str(workspace_dir))
                from app.core.timezone import now
                timestamp = now().strftime("%Y%m%d_%H%M%S")
                git_branch = f"devflow/pipeline-{pipeline_id}-{timestamp}"
                
                try:
                    git_service.create_branch(git_branch)
                except GitProviderError as e:
                    if "分支已存在" in str(e):
                        git_service.checkout_branch(git_branch)
                    else:
                        raise
                
                # 4. 应用代码变更
                code_executor = CodeExecutorService(str(workspace_dir))
                changes_dict = {f["file_path"]: f["content"] for f in generated_files}
                
                await push_log(pipeline_id, "info", "应用代码变更...", stage="DELIVERY")
                execution_result = code_executor.apply_changes(changes=changes_dict, create_if_missing=True)
                
                if not execution_result.success:
                    code_executor.rollback_changes(execution_result.changes)
                    await WorkflowService.create_stage(
                        pipeline_id=pipeline_id, stage_name=StageName.DELIVERY,
                        input_data=None, session=session
                    )
                    pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
                    if pipeline:
                        await WorkflowService.set_pipeline_failed(pipeline, session)
                    from app.core.sse_log_buffer import remove_buffer
                    remove_buffer(pipeline_id)
                    return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Code execution failed"}
                
                # 5. Git 提交
                if execution_result.summary["success"] > 0:
                    git_service.add_files()
                    if git_service.has_changes():
                        commit_message = f"feat(pipeline-{pipeline_id}): {multi_agent_output.get('summary', '代码生成')[:100]}"
                        git_service.commit_changes(commit_message)
                        commit_hash = git_service.get_last_commit_hash()
                
                # 6. 推送分支
                await push_log(pipeline_id, "info", f"推送代码到远程分支 {git_branch}...", stage="DELIVERY")
                push_result = git_service.push_branch(git_branch)
                
                # 7. 生成 PR 描述（委托给 PRGeneratorService）
                pr_description = await PRGeneratorService.generate_pr_description(
                    pipeline_id=pipeline_id,
                    multi_agent_output=multi_agent_output,
                    execution_summary=execution_result.summary,
                    git_service=git_service
                )
                
                # 8. 创建 PR
                pr_title = f"OmniFlowAI: {requirement_summary}"
                async with GitHubProviderService() as github_service:
                    pr_result = await github_service.create_pull_request(
                        head_branch=git_branch, title=pr_title,
                        body=pr_description, base_branch="main"
                    )
                
                if pr_result.success:
                    pr_url = pr_result.pr_url
                    await push_log(pipeline_id, "info", f"PR 创建成功: {pr_url}", stage="DELIVERY")
            
            # 9. 创建 DELIVERY 阶段
            delivery_stage = PipelineStage(
                pipeline_id=pipeline_id,
                name=StageName.DELIVERY,
                status=StageStatus.SUCCESS,
                output_data={
                    "git_branch": git_branch, "commit_hash": commit_hash,
                    "pr_url": pr_url, "pr_created": pr_result.success,
                    "execution_summary": execution_result.summary
                }
            )
            session.add(delivery_stage)
            
            # 10. 更新 Pipeline 状态
            pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
            if pipeline:
                pipeline.current_stage = StageName.DELIVERY
                await WorkflowService.set_pipeline_paused(pipeline, session)
            
            await push_log(pipeline_id, "info", "Pipeline 执行完成！", stage="DELIVERY")
            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(pipeline_id)
            
            return {
                "success": True, "status": PipelineStatus.SUCCESS.value,
                "message": "Delivery completed", "git_branch": git_branch,
                "commit_hash": commit_hash, "pr_url": pr_url
            }
            
        except Exception as e:
            await push_log(pipeline_id, "error", f"代码交付失败: {str(e)}", stage="DELIVERY")
            await session.rollback()
            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(pipeline_id)
            return {"success": False, "status": PipelineStatus.FAILED.value, "message": f"Delivery failed: {str(e)}"}
    
    # ==================== 审批方法 ====================

    @classmethod
    async def approve_pipeline(
        cls, pipeline_id: int, notes: Optional[str],
        feedback: Optional[str], session: AsyncSession,
        background_tasks=None
    ) -> Dict[str, Any]:
        """审批 Pipeline，允许进入下一阶段

        Args:
            pipeline_id: Pipeline ID
            notes: 审批备注
            feedback: 反馈建议
            session: 数据库 session
            background_tasks: FastAPI BackgroundTasks，用于异步执行耗时任务
        """
        from fastapi import BackgroundTasks

        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)

        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        can_approve, error_msg = await WorkflowService.validate_can_approve(pipeline)
        if not can_approve:
            return {"success": False, "error": error_msg}

        current_stage = pipeline.current_stage

        if current_stage == StageName.REQUIREMENT:
            success, _, error = await WorkflowService.transition_to_next_stage(pipeline, session)
            if not success:
                return {"success": False, "error": error}

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
            success, _, error = await WorkflowService.transition_to_next_stage(pipeline, session)
            if not success:
                return {"success": False, "error": error}

            # 提交事务，确保阶段状态已更新
            await session.commit()

            # 使用后台任务异步执行代码生成，避免 HTTP 超时
            if background_tasks:
                from app.api.v1.pipeline import run_coding_task
                background_tasks.add_task(run_coding_task, pipeline_id)

                return {
                    "success": True,
                    "data": {
                        "pipeline_id": pipeline_id,
                        "previous_stage": StageName.DESIGN.value,
                        "next_stage": StageName.CODING.value,
                        "status": PipelineStatus.RUNNING.value,
                        "message": "代码生成任务已在后台启动，请通过日志监控进度",
                        "async": True
                    }
                }
            else:
                # 如果没有 background_tasks，同步执行（兼容旧调用）
                coding_result = await cls._trigger_coding_phase(pipeline_id, session)

                # 统一响应格式
                if coding_result["success"]:
                    testing_result = await cls._trigger_testing_phase(pipeline_id, session)
                    return {
                        "success": testing_result["success"],
                        "data": {
                            "pipeline_id": pipeline_id,
                            "previous_stage": StageName.DESIGN.value,
                            "next_stage": StageName.CODE_REVIEW.value,
                            "status": testing_result.get("status", PipelineStatus.PAUSED.value),
                            "message": testing_result.get("message", "Coding and unit testing completed"),
                            "delivery": {
                                "test_generated": testing_result.get("test_generated", False),
                                "test_run_success": testing_result.get("test_run_success", False)
                            }
                        }
                    }
                else:
                    return {
                        "success": False,
                        "data": {
                            "pipeline_id": pipeline_id,
                            "previous_stage": StageName.DESIGN.value,
                            "next_stage": StageName.CODING.value,
                            "status": PipelineStatus.FAILED.value,
                            "message": coding_result.get("message", "Code generation failed"),
                            "delivery": None
                        }
                    }

        elif current_stage == StageName.UNIT_TESTING:
            # 单元测试阶段审批，进入 CODE_REVIEW
            success, _, error = await WorkflowService.transition_to_next_stage(pipeline, session)
            if not success:
                return {"success": False, "error": error}

            # 获取测试阶段的结果
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.UNIT_TESTING
            )
            result = await session.execute(statement)
            testing_stage = result.scalar_one_or_none()

            testing_result = {}
            if testing_stage and testing_stage.output_data:
                testing_result = testing_stage.output_data.get("testing_result", {})

            await session.commit()

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": StageName.UNIT_TESTING.value,
                    "next_stage": StageName.CODE_REVIEW.value,
                    "status": PipelineStatus.PAUSED.value,
                    "message": "Unit testing approved, proceeding to code review",
                    "test_generated": testing_result.get("test_generated", False),
                    "test_run_success": testing_result.get("test_run_success", False)
                }
            }

        elif current_stage == StageName.CODE_REVIEW:
            success, _, error = await WorkflowService.transition_to_next_stage(pipeline, session)
            if not success:
                return {"success": False, "error": error}

            delivery_result = await cls._trigger_delivery_phase(pipeline_id, session)

            return {
                "success": delivery_result["success"],
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": StageName.CODE_REVIEW.value,
                    "next_stage": StageName.DELIVERY.value,
                    "status": delivery_result.get("status", PipelineStatus.SUCCESS.value),
                    "message": delivery_result.get("message", "Code delivered"),
                    "git_branch": delivery_result.get("git_branch"),
                    "commit_hash": delivery_result.get("commit_hash"),
                    "pr_url": delivery_result.get("pr_url")
                }
            }

        else:
            return {"success": False, "error": f"Unknown current stage: {current_stage}"}
    
    @classmethod
    async def reject_pipeline(
        cls, pipeline_id: int, reason: str,
        suggested_changes: Optional[str], session: AsyncSession
    ) -> Dict[str, Any]:
        """驳回 Pipeline，退回当前阶段重新执行"""
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}
        
        can_reject, error_msg = await WorkflowService.validate_can_reject(pipeline)
        if not can_reject:
            return {"success": False, "error": error_msg}
        
        current_stage = pipeline.current_stage
        
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}
        
        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=pipeline_id, stage_name=current_stage,
            rejection_feedback=rejection_feedback, session=session
        )
        
        await WorkflowService.set_pipeline_running(pipeline, session)
        
        if current_stage == StageName.REQUIREMENT:
            await cls._trigger_architect_analysis_with_feedback(
                pipeline_id, pipeline.description, reason, suggested_changes, session
            )
        elif current_stage == StageName.DESIGN:
            await cls._trigger_designer_analysis_with_feedback(
                pipeline_id, reason, suggested_changes, session
            )
        elif current_stage == StageName.UNIT_TESTING:
            # 单元测试阶段被驳回，回退到 CODING 重新生成代码和测试
            # 标记 CODING 阶段需要重新运行
            await WorkflowService.mark_stage_for_rerun(
                pipeline_id=pipeline_id, stage_name=StageName.CODING,
                rejection_feedback=rejection_feedback, session=session
            )
            # 重新触发 CODING 阶段（会自动进入 UNIT_TESTING）
            coding_result = await cls._trigger_coding_phase(pipeline_id, session)
            if coding_result["success"]:
                # CODING 成功后自动进入 UNIT_TESTING
                testing_result = await cls._trigger_testing_phase(pipeline_id, session)
                return {
                    "success": testing_result["success"],
                    "data": {
                        "pipeline_id": pipeline_id,
                        "current_stage": StageName.UNIT_TESTING.value,
                        "status": testing_result.get("status", PipelineStatus.PAUSED.value),
                        "message": "Coding and unit testing re-executed",
                        "test_generated": testing_result.get("test_generated", False),
                        "test_run_success": testing_result.get("test_run_success", False)
                    }
                }
            else:
                return {
                    "success": False,
                    "data": {
                        "pipeline_id": pipeline_id,
                        "status": PipelineStatus.FAILED.value,
                        "message": coding_result.get("message", "Code generation failed")
                    }
                }
        elif current_stage == StageName.CODE_REVIEW:
            # 代码审查阶段被驳回，回退到 CODING 重新生成
            await WorkflowService.mark_stage_for_rerun(
                pipeline_id=pipeline_id, stage_name=StageName.CODING,
                rejection_feedback=rejection_feedback, session=session
            )
            # 重新触发 CODING 阶段
            coding_result = await cls._trigger_coding_phase(pipeline_id, session)
            if coding_result["success"]:
                testing_result = await cls._trigger_testing_phase(pipeline_id, session)
                return {
                    "success": testing_result["success"],
                    "data": {
                        "pipeline_id": pipeline_id,
                        "current_stage": StageName.UNIT_TESTING.value,
                        "status": testing_result.get("status", PipelineStatus.PAUSED.value),
                        "message": "Coding and unit testing re-executed after rejection",
                        "test_generated": testing_result.get("test_generated", False),
                        "test_run_success": testing_result.get("test_run_success", False)
                    }
                }
            else:
                return {
                    "success": False,
                    "data": {
                        "pipeline_id": pipeline_id,
                        "status": PipelineStatus.FAILED.value,
                        "message": coding_result.get("message", "Code generation failed")
                    }
                }

        return {
            "success": True,
            "data": {
                "pipeline_id": pipeline_id,
                "current_stage": current_stage.value if current_stage else None,
                "status": PipelineStatus.RUNNING.value,
                "message": f"Pipeline rejected, re-running {current_stage.value if current_stage else 'current'} stage",
                "feedback": rejection_feedback
            }
        }
    
    # ==================== 后台任务方法 ====================

    @classmethod
    async def trigger_coding_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """公开方法：触发 CODING 阶段（供后台任务调用）"""
        return await cls._trigger_coding_phase(pipeline_id, session)

    @classmethod
    async def mark_pipeline_failed(cls, pipeline_id: int, error: str, session: AsyncSession) -> None:
        """标记 Pipeline 为失败状态"""
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        if pipeline:
            await WorkflowService.set_pipeline_failed(pipeline, session)
            # 记录错误信息到当前阶段
            if pipeline.current_stage:
                from app.models.pipeline import PipelineStage, StageName
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == pipeline.current_stage
                )
                result = await session.execute(statement)
                stage = result.scalar_one_or_none()
                if stage:
                    # 救命补丁：绝对不要覆盖原来的代码数据！把之前的代码原封不动继承过来
                    current_data = dict(stage.output_data) if stage.output_data else {}
                    current_data["error"] = error
                    stage.output_data = current_data

                    # 强制告诉 SQLAlchemy 字典被修改了，必须落库保存！
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(stage, "output_data")

    # ==================== 查询方法 ====================

    @classmethod
    async def get_pipeline_status(cls, pipeline_id: int, session: AsyncSession) -> Optional[PipelineRead]:
        """获取 Pipeline 状态"""
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        return cls._build_pipeline_read(pipeline) if pipeline else None
    
    @classmethod
    async def list_pipelines(cls, session: AsyncSession, skip: int = 0, limit: int = 100) -> list[PipelineRead]:
        """列出所有 Pipeline"""
        statement = select(Pipeline).offset(skip).limit(limit)
        result = await session.execute(statement)
        pipelines = result.scalars().all()
        
        return [
            PipelineRead(
                id=p.id, description=p.description, status=p.status,
                current_stage=p.current_stage, created_at=p.created_at,
                updated_at=p.updated_at, stages=None
            )
            for p in pipelines
        ]
