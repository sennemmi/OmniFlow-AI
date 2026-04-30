"""
Pipeline 业务服务（重构版）
业务逻辑层 - 使用 StageHandler 策略模式协调 Pipeline 各阶段

【优化】引入阶段处理器（Stage Handler）策略：
- PipelineService 只负责调度
- 各阶段逻辑分散到独立的 Handler 类中
- 新增阶段只需添加 Handler，无需修改 PipelineService
"""

from typing import Optional, Dict, Any

from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.logging import info, op_logger
from app.models.pipeline import (
    Pipeline, PipelineRead, PipelineStatus,
    PipelineStage, StageName, StageStatus, PipelineStageRead
)
from app.service.workflow import WorkflowService
from app.service.stage_handlers import (
    StageContext, StageHandlerRegistry,
    RequirementHandler, DesignHandler, CodingHandler,
    TestingHandler, CodeReviewHandler, DeliveryHandler
)


class PipelineService:
    """
    Pipeline 业务服务（重构版）
    
    职责：
    1. Pipeline 的创建和管理
    2. 协调阶段执行 - 委托给 StageHandler
    3. 管理审批流程 - 使用 StageHandler 触发下一阶段
    
    【优化】阶段逻辑已拆分到独立的 Handler 类
    """
    
    def __init__(self):
        """初始化并注册所有阶段处理器"""
        self._registry = StageHandlerRegistry()
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """注册所有阶段处理器"""
        self._registry.register(RequirementHandler())
        self._registry.register(DesignHandler())
        self._registry.register(CodingHandler())
        self._registry.register(TestingHandler())
        self._registry.register(CodeReviewHandler())
        self._registry.register(DeliveryHandler())
    
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
            status=StageStatus.PENDING,
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
        service = cls()
        handler = service._registry.get(StageName.REQUIREMENT)
        
        if not handler:
            raise ValueError("RequirementHandler not registered")
        
        context = StageContext(
            pipeline_id=pipeline_id,
            session=session,
            input_data={"requirement": requirement, "element_context": element_context}
        )
        
        await handler.run(context)
    
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
            status=PipelineStatus.RUNNING,
            input_data={"requirement": requirement}
        )
        session.add(stage)
        await session.commit()
        
        # 3. 触发 ArchitectAgent
        await cls.run_architect_task(pipeline.id, requirement, None, session)
        
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
                completed_at=stage.completed_at,
                input_tokens=stage.input_tokens or 0,
                output_tokens=stage.output_tokens or 0,
                duration_ms=stage.duration_ms or 0,
                retry_count=stage.retry_count or 0,
                reasoning=stage.reasoning,
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
    
    # ==================== 阶段触发方法（使用 StageHandler） ====================
    
    async def _trigger_stage(
        self,
        pipeline_id: int,
        stage_name: StageName,
        session: AsyncSession,
        input_data: Optional[Dict[str, Any]] = None,
        rejection_feedback: Optional[Dict[str, Any]] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        通用阶段触发方法

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            session: 数据库会话
            input_data: 输入数据（可选）
            rejection_feedback: 驳回反馈（可选）
            error_context: 错误上下文（可选，用于传递允许修改测试的授权等）

        Returns:
            Dict: 执行结果
        """
        handler = self._registry.get(stage_name)

        if not handler:
            return {
                "success": False,
                "error": f"No handler registered for stage: {stage_name.value}"
            }

        context = StageContext(
            pipeline_id=pipeline_id,
            session=session,
            input_data=input_data or {},
            rejection_feedback=rejection_feedback,
            error_context=error_context
        )

        result = await handler.run(context)

        return {
            "success": result.success,
            "status": result.status.value,
            "message": result.message,
            "output_data": result.output_data,
            "git_branch": result.git_branch,
            "commit_hash": result.commit_hash,
            "pr_url": result.pr_url
        }
    
    @classmethod
    async def _trigger_coding_phase(
        cls,
        pipeline_id: int,
        session: AsyncSession,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """触发 CODING 阶段（供后台任务调用）"""
        service = cls()
        return await service._trigger_stage(
            pipeline_id=pipeline_id,
            stage_name=StageName.CODING,
            session=session,
            error_context=error_context
        )
    
    @classmethod
    async def _trigger_testing_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 UNIT_TESTING 阶段"""
        service = cls()
        return await service._trigger_stage(
            pipeline_id=pipeline_id,
            stage_name=StageName.UNIT_TESTING,
            session=session
        )
    
    @classmethod
    async def _trigger_delivery_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 DELIVERY 阶段"""
        service = cls()
        return await service._trigger_stage(
            pipeline_id=pipeline_id,
            stage_name=StageName.DELIVERY,
            session=session
        )
    
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
        service = cls()

        # 获取当前阶段的 Handler
        handler = service._registry.get(current_stage)
        if not handler:
            return {"success": False, "error": f"No handler registered for stage: {current_stage.value}"}

        # 执行阶段流转
        success, next_stage, error = await WorkflowService.transition_to_next_stage(pipeline, session)
        if not success:
            return {"success": False, "error": error}

        # 提交事务，确保阶段状态已更新
        await session.commit()

        # 创建 StageContext
        context = StageContext(
            pipeline_id=pipeline_id,
            session=session,
            input_data={}
        )

        # 调用 Handler 的 on_approved 方法
        result = await handler.on_approved(context, notes, feedback)

        # 处理 DESIGN 阶段的特殊情况（需要后台任务）
        if current_stage == StageName.DESIGN and background_tasks:
            if result.output_data.get("requires_background_task"):
                from app.api.v1.pipeline import run_coding_task
                background_tasks.add_task(run_coding_task, pipeline_id)

                return {
                    "success": True,
                    "data": {
                        "pipeline_id": pipeline_id,
                        "previous_stage": StageName.DESIGN.value,
                        "next_stage": StageName.CODING.value,
                        "status": PipelineStatus.RUNNING.value,
                        "message": result.message,
                        "async": True
                    }
                }

        # 统一组装响应
        return {
            "success": result.success,
            "data": {
                "pipeline_id": pipeline_id,
                "previous_stage": current_stage.value,
                "next_stage": result.output_data.get("next_stage", next_stage.value if next_stage else None),
                "status": result.status.value,
                "message": result.message,
                **({"git_branch": result.git_branch} if result.git_branch else {}),
                **({"commit_hash": result.commit_hash} if result.commit_hash else {}),
                **({"pr_url": result.pr_url} if result.pr_url else {}),
                **({"test_generated": result.output_data.get("test_generated")} if "test_generated" in result.output_data else {}),
                **({"test_run_success": result.output_data.get("test_run_success")} if "test_run_success" in result.output_data else {})
            }
        }
    
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
        service = cls()

        # 获取当前阶段的 Handler
        handler = service._registry.get(current_stage)
        if not handler:
            return {"success": False, "error": f"No handler registered for stage: {current_stage.value}"}

        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        # 标记当前阶段需要重新执行
        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=pipeline_id, stage_name=current_stage,
            rejection_feedback=rejection_feedback, session=session
        )

        await WorkflowService.set_pipeline_running(pipeline, session)
        await session.commit()

        # 创建 StageContext
        context = StageContext(
            pipeline_id=pipeline_id,
            session=session,
            input_data={}
        )

        # 调用 Handler 的 on_rejected 方法
        result = await handler.on_rejected(context, reason, suggested_changes)

        # 统一组装响应
        response_data = {
            "pipeline_id": pipeline_id,
            "status": result.status.value,
            "message": result.message,
            "feedback": rejection_feedback
        }

        # 添加可选字段
        if "current_stage" in result.output_data:
            response_data["current_stage"] = result.output_data["current_stage"]
        elif "previous_stage" in result.output_data:
            response_data["current_stage"] = result.output_data["previous_stage"]
        else:
            response_data["current_stage"] = current_stage.value if current_stage else None

        if "test_generated" in result.output_data:
            response_data["test_generated"] = result.output_data["test_generated"]
        if "test_run_success" in result.output_data:
            response_data["test_run_success"] = result.output_data["test_run_success"]

        return {
            "success": result.success,
            "data": response_data
        }
    
    # ==================== 后台任务方法 ====================

    @classmethod
    async def trigger_coding_phase(
        cls,
        pipeline_id: int,
        session: AsyncSession,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """公开方法：触发 CODING 阶段（供后台任务调用）"""
        return await cls._trigger_coding_phase(pipeline_id, session, error_context)

    @classmethod
    async def mark_pipeline_failed(cls, pipeline_id: int, error: str, session: AsyncSession) -> None:
        """标记 Pipeline 为失败状态"""
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        if pipeline:
            await WorkflowService.set_pipeline_failed(pipeline, session)
            # 记录错误信息到当前阶段
            if pipeline.current_stage:
                from sqlmodel import select
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
