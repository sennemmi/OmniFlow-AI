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
    PipelineStage, StageName, PipelineStageRead
)
from app.service.workflow import WorkflowService
from app.service.stage_handlers import (
    StageContext, StageHandlerRegistry,
    RequirementHandler, DesignHandler, CodingHandler,
    TestingHandler, DeliveryHandler
)
from app.repositories import PipelineStageRepository


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
        from app.models.pipeline import StageStatus
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
        rejection_feedback: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        通用阶段触发方法
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            session: 数据库会话
            input_data: 输入数据（可选）
            rejection_feedback: 驳回反馈（可选）
            
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
            rejection_feedback=rejection_feedback
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
    async def _trigger_coding_phase(cls, pipeline_id: int, session: AsyncSession) -> Dict[str, Any]:
        """触发 CODING 阶段（供后台任务调用）"""
        service = cls()
        return await service._trigger_stage(
            pipeline_id=pipeline_id,
            stage_name=StageName.CODING,
            session=session
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

        if current_stage == StageName.REQUIREMENT:
            success, _, error = await WorkflowService.transition_to_next_stage(pipeline, session)
            if not success:
                return {"success": False, "error": error}

            # 使用 StageHandler 触发 DESIGN 阶段
            result = await service._trigger_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.DESIGN,
                session=session
            )

            return {
                "success": result["success"],
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": StageName.REQUIREMENT.value,
                    "next_stage": StageName.DESIGN.value,
                    "status": result["status"],
                    "message": result["message"]
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
                                "test_generated": testing_result.get("output_data", {}).get("testing_result", {}).get("test_generated", False),
                                "test_run_success": testing_result.get("output_data", {}).get("testing_result", {}).get("test_run_success", False)
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
            testing_result = await PipelineStageRepository.get_output_data_value(
                pipeline_id=pipeline_id,
                stage_name=StageName.UNIT_TESTING,
                key="testing_result",
                session=session,
                default={}
            )

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
        service = cls()
        
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}
        
        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=pipeline_id, stage_name=current_stage,
            rejection_feedback=rejection_feedback, session=session
        )
        
        await WorkflowService.set_pipeline_running(pipeline, session)
        
        if current_stage == StageName.REQUIREMENT:
            # 使用 StageHandler 重新触发 REQUIREMENT 阶段
            result = await service._trigger_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.REQUIREMENT,
                session=session,
                input_data={"requirement": pipeline.description},
                rejection_feedback=rejection_feedback
            )
            
        elif current_stage == StageName.DESIGN:
            # 使用 StageHandler 重新触发 DESIGN 阶段
            result = await service._trigger_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.DESIGN,
                session=session,
                rejection_feedback=rejection_feedback
            )
            
        elif current_stage == StageName.UNIT_TESTING:
            # 单元测试阶段被驳回，回退到 CODING 重新生成代码和测试
            await WorkflowService.mark_stage_for_rerun(
                pipeline_id=pipeline_id, stage_name=StageName.CODING,
                rejection_feedback=rejection_feedback, session=session
            )
            
            # 重新触发 CODING 阶段（会自动进入 UNIT_TESTING）
            coding_result = await cls._trigger_coding_phase(pipeline_id, session)
            if coding_result["success"]:
                testing_result = await cls._trigger_testing_phase(pipeline_id, session)
                return {
                    "success": testing_result["success"],
                    "data": {
                        "pipeline_id": pipeline_id,
                        "current_stage": StageName.UNIT_TESTING.value,
                        "status": testing_result.get("status", PipelineStatus.PAUSED.value),
                        "message": "Coding and unit testing re-executed",
                        "test_generated": testing_result.get("output_data", {}).get("testing_result", {}).get("test_generated", False),
                        "test_run_success": testing_result.get("output_data", {}).get("testing_result", {}).get("test_run_success", False)
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
                        "test_generated": testing_result.get("output_data", {}).get("testing_result", {}).get("test_generated", False),
                        "test_run_success": testing_result.get("output_data", {}).get("testing_result", {}).get("test_run_success", False)
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
                stage = await PipelineStageRepository.get_by_pipeline_and_name(
                    pipeline_id=pipeline_id,
                    stage_name=pipeline.current_stage,
                    session=session
                )
                if stage:
                    # 救命补丁：绝对不要覆盖原来的代码数据！把之前的代码原封不动继承过来
                    await PipelineStageRepository.append_to_output_data(
                        stage_id=stage.id,
                        key="error",
                        value=error,
                        session=session
                    )

    @classmethod
    async def terminate_pipeline(
        cls,
        pipeline_id: int,
        reason: str,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """
        终止 Pipeline（用户手动终止）
        
        Args:
            pipeline_id: Pipeline ID
            reason: 终止原因
            session: 数据库会话
            
        Returns:
            Dict: 终止结果
        """
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}
        
        # 只能终止运行中或暂停（审批中）的 Pipeline
        if pipeline.status not in (PipelineStatus.RUNNING, PipelineStatus.PAUSED):
            return {
                "success": False, 
                "error": f"Cannot terminate pipeline with status: {pipeline.status.value}"
            }
        
        # 执行终止
        await WorkflowService.terminate_pipeline(pipeline, reason, session)
        
        return {
            "success": True,
            "data": {
                "pipeline_id": pipeline_id,
                "status": PipelineStatus.FAILED.value,
                "message": f"Pipeline terminated: {reason}",
                "terminated_at": pipeline.updated_at.isoformat() if pipeline.updated_at else None
            }
        }

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
