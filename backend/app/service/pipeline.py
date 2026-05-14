"""
Pipeline 业务服务（重构版）
业务逻辑层 - 使用 StageHandler 策略模式协调 Pipeline 各阶段

【优化】引入阶段处理器（Stage Handler）策略：
- PipelineService 只负责调度
- 各阶段逻辑分散到独立的 Handler 类中
- 新增阶段只需添加 Handler，无需修改 PipelineService
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import BackgroundTasks
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.logging import info, warning, op_logger, error
from app.core.config import settings
from app.core.sse_log_buffer import push_log, remove_buffer
from app.core.database import async_session_factory
from app.models.pipeline import (
    Pipeline, PipelineRead, PipelineStatus,
    PipelineStage, StageName, StageStatus, PipelineStageRead
)
from app.repositories import PipelineRepository

logger = logging.getLogger(__name__)
from app.service.workflow import WorkflowService
from app.service.stage_handlers import (
    StageContext, StageHandlerRegistry,
    RequirementHandler, DesignHandler, CodingHandler,
    TestingHandler, CodeReviewHandler, DeliveryHandler
)
from app.service.sandbox_manager import sandbox_manager
from app.service.test_orchestrator import TestOrchestrator

class PipelineService:
    """
    Pipeline 业务服务（重构版）
    
    职责：
    1. Pipeline 的创建和管理
    2. 协调阶段执行 - 委托给 StageHandler
    3. 管理审批流程 - 使用 StageHandler 触发下一阶段
    
    【优化】阶段逻辑已拆分到独立的 Handler 类
    """

    # 【Task Registry】用于跟踪和管理正在运行的 Pipeline 后台任务
    _running_tasks: Dict[int, asyncio.Task] = {}

    @classmethod
    def _register_task(cls, pipeline_id: int, task: asyncio.Task) -> None:
        """注册正在运行的任务，任务完成时自动清理"""
        cls._running_tasks[pipeline_id] = task
        task.add_done_callback(lambda _: cls._running_tasks.pop(pipeline_id, None))

    @classmethod
    def _cancel_task(cls, pipeline_id: int) -> bool:
        """取消正在运行的任务，返回是否成功取消"""
        if pipeline_id in cls._running_tasks:
            task = cls._running_tasks[pipeline_id]
            if not task.done():
                task.cancel()
                info(f"Pipeline {pipeline_id} 的后台任务已取消", pipeline_id=pipeline_id)
                return True
            # 从注册表中移除
            del cls._running_tasks[pipeline_id]
        return False

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

        # 构建返回结果，确保失败时包含 error 字段
        response = {
            "success": result.success,
            "status": result.status.value,
            "message": result.message,
            "output_data": result.output_data,
            "git_branch": result.git_branch,
            "commit_hash": result.commit_hash,
            "pr_url": result.pr_url
        }

        # 如果执行失败，添加 error 字段（用于 API 返回）
        if not result.success:
            response["error"] = result.message or f"Stage {stage_name.value} execution failed"

        return response
    
    @classmethod
    async def _trigger_phase(
        cls,
        stage_name: StageName,
        pipeline_id: int,
        session: Optional[AsyncSession] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """触发指定阶段（供后台任务/并发调用）"""
        service = cls()
        if session is not None:
            return await service._trigger_stage(pipeline_id, stage_name, session, **kwargs)
        async with async_session_factory() as new_session:
            return await service._trigger_stage(pipeline_id, stage_name, new_session, **kwargs)

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
        success, next_stage, error_msg = await WorkflowService.transition_to_next_stage(pipeline, session)
        if not success:
            return {"success": False, "error": error_msg}

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

        # 通用后台任务机制：任何 handler 均可通过 requires_background_task 请求异步执行
        if result.output_data.get("requires_background_task"):
            task = asyncio.create_task(cls._run_coding_task_background(pipeline_id))
            cls._register_task(pipeline_id, task)

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "previous_stage": current_stage.value,
                    "next_stage": result.output_data.get("next_stage", next_stage.value if next_stage else None),
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

    @classmethod
    async def approve_code_review(
        cls,
        pipeline_id: int,
        approve_coding: bool,
        approve_testing: bool,
        feedback: str,
        session: AsyncSession,
        background_tasks: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        【新流程】审批 CODE_REVIEW 阶段，支持分别审批 CODER 和 TESTER

        Args:
            pipeline_id: Pipeline ID
            approve_coding: 是否接受 CODING 生成的代码
            approve_testing: 是否接受 TESTER 生成的测试
            feedback: 审批意见
            session: 数据库会话
            background_tasks: 后台任务

        Returns:
            Dict: 审批结果
        """
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        if pipeline.status != PipelineStatus.PAUSED:
            return {"success": False, "error": "Pipeline is not in paused state"}

        if pipeline.current_stage != StageName.CODE_REVIEW:
            return {"success": False, "error": f"Current stage is {pipeline.current_stage.value}, not CODE_REVIEW"}

        # 四种审批情况
        if approve_coding and approve_testing:
            # 两者都接受：进入 DELIVERY 阶段
            await push_log(pipeline_id, "info", "✅ 代码和测试都已接受，进入交付阶段", stage="DELIVERY")

            # 将 CODE_REVIEW 阶段标记为成功
            stmt = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.CODE_REVIEW
            )
            result = await session.execute(stmt)
            review_stage = result.scalars().first()
            if review_stage:
                review_stage.status = StageStatus.SUCCESS
                session.add(review_stage)
                await session.commit()

            # 调用 DELIVERY handler
            # 【修复】使用 handler.run(context) 而非直接调用 execute()，确保 prepare() 被调用
            service = cls()
            handler = service._registry.get(StageName.DELIVERY)
            if handler:
                context = StageContext(
                    pipeline_id=pipeline_id,
                    session=session,
                    input_data={}
                )
                result = await handler.run(context)

                return {
                    "success": result.success,
                    "data": {
                        "pipeline_id": pipeline_id,
                        "action": "proceed_to_delivery",
                        "status": result.status.value,
                        "message": result.message
                    }
                }
            else:
                return {"success": False, "error": "No handler for DELIVERY stage"}

        elif approve_coding and not approve_testing:
            # 只接受 CODING：重试 TESTING
            await push_log(pipeline_id, "info", "🔄 代码已接受，重新生成测试...", stage="UNIT_TESTING")

            task = asyncio.create_task(cls._retry_testing_only(pipeline_id, feedback))
            cls._register_task(pipeline_id, task)

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "action": "retry_testing",
                    "status": PipelineStatus.RUNNING.value,
                    "message": "重新生成测试中...",
                    "async": True
                }
            }

        elif not approve_coding and approve_testing:
            # 只接受 TESTING：重试 CODING
            await push_log(pipeline_id, "info", "🔄 测试已接受，重新生成代码...", stage="CODING")

            task = asyncio.create_task(cls._retry_coding_only(pipeline_id, feedback))
            cls._register_task(pipeline_id, task)

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "action": "retry_coding",
                    "status": PipelineStatus.RUNNING.value,
                    "message": "重新生成代码中...",
                    "async": True
                }
            }

        else:
            # 两者都拒绝：同时重试
            await push_log(pipeline_id, "info", "🔄 代码和测试都需要重新生成...", stage="CODING")

            # 先重试 CODING，完成后会自动重试 TESTING
            task = asyncio.create_task(cls._retry_coding_only(pipeline_id, feedback))
            cls._register_task(pipeline_id, task)

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "action": "retry_both",
                    "status": PipelineStatus.RUNNING.value,
                    "message": "重新生成代码和测试中...",
                    "async": True
                }
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
        return await cls._trigger_phase(StageName.CODING, pipeline_id, session, error_context=error_context)

    @classmethod
    async def mark_pipeline_failed(cls, pipeline_id: int, error: str, session: AsyncSession) -> None:
        """标记 Pipeline 为失败状态"""
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        if pipeline:
            await WorkflowService.set_pipeline_failed(pipeline, session)
            # 记录错误信息到当前阶段
            if pipeline.current_stage:
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == pipeline.current_stage
                )
                result = await session.execute(statement)
                stage = result.scalars().first()
                if stage:
                    # 救命补丁：绝对不要覆盖原来的代码数据！把之前的代码原封不动继承过来
                    current_data = dict(stage.output_data) if stage.output_data else {}
                    current_data["error"] = error
                    stage.output_data = current_data

                    # 强制告诉 SQLAlchemy 字典被修改了，必须落库保存！
                    flag_modified(stage, "output_data")
            
            # 【关键修复】Pipeline 失败时停止 Sandbox，避免资源泄漏
            # 使用 fast=True 立即终止容器，避免后台任务继续执行
            try:
                await sandbox_manager.stop(pipeline_id, fast=True)
                info("Pipeline 失败，Sandbox 已停止", pipeline_id=pipeline_id)
            except Exception as e:
                info(f"停止 Sandbox 时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

    @classmethod
    async def retry_pipeline(
        cls,
        pipeline_id: int,
        session: AsyncSession,
        background_tasks: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        重试失败的 Pipeline

        流程：
        1. 检查 Pipeline 状态是否为 failed
        2. 重置 Pipeline 状态为 running
        3. 重置当前失败阶段为 pending
        4. 重新启动 Sandbox（如果已停止）
        5. 后台异步重新执行当前阶段
        """
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)

        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        # 检查状态
        if pipeline.status.value != "failed":
            return {
                "success": False,
                "error": f"只能重试失败的 Pipeline，当前状态: {pipeline.status.value}"
            }

        current_stage = pipeline.current_stage
        if not current_stage:
            return {"success": False, "error": "Pipeline 没有当前阶段，无法重试"}

        await push_log(
            pipeline_id,
            "info",
            f"🔄 正在重试 Pipeline，从 {current_stage.value} 阶段重新开始...",
            stage=current_stage.value
        )

        # 1. 重置当前阶段状态为 pending
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == current_stage
        )
        result = await session.execute(statement)
        stage = result.scalars().first()

        if stage:
            stage.status = StageStatus.PENDING
            # 清除之前的错误信息，但保留其他数据
            if stage.output_data and isinstance(stage.output_data, dict):
                stage.output_data.pop("error", None)
            await push_log(
                pipeline_id,
                "info",
                f"阶段 {current_stage.value} 已重置为 pending 状态",
                stage=current_stage.value
            )

        # 2. 重置 Pipeline 状态为 running
        await WorkflowService.set_pipeline_running(pipeline, session)
        await push_log(
            pipeline_id,
            "info",
            "Pipeline 状态已重置为 running",
            stage=current_stage.value
        )

        await session.commit()

        # 3. 重新启动 Sandbox（如果已停止）
        try:
            project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
            sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
            info("Sandbox 重新启动成功",
                 pipeline_id=pipeline_id,
                 container_id=sandbox_info.container_id[:12],
                 port=sandbox_info.port)
            await push_log(
                pipeline_id,
                "info",
                f"🐳 Sandbox 重新启动成功 (端口: {sandbox_info.port})",
                stage=current_stage.value
            )
        except Exception as e:
            # Sandbox 可能已经在运行，这不是致命错误
            info(f"启动 Sandbox 时出错（可能已在运行）: {str(e)}", pipeline_id=pipeline_id)
            await push_log(
                pipeline_id,
                "warning",
                f"Sandbox 启动警告: {str(e)}",
                stage=current_stage.value
            )

        # 4. 根据当前阶段触发相应的后台任务
        if background_tasks and isinstance(background_tasks, BackgroundTasks):
            if current_stage == StageName.CODING:
                # 重试 CODING 阶段
                # 【Task Registry】注册后台任务以便后续取消
                task = asyncio.create_task(cls._run_coding_task_background(pipeline_id))
                cls._register_task(pipeline_id, task)
                await push_log(
                    pipeline_id,
                    "info",
                    "后台任务已启动：重新执行代码生成...",
                    stage="CODING"
                )
            elif current_stage == StageName.REQUIREMENT:
                # 重试 REQUIREMENT 阶段
                requirement_stage = None
                for s in pipeline.stages:
                    if s.name == StageName.REQUIREMENT:
                        requirement_stage = s
                        break

                if requirement_stage:
                    requirement = requirement_stage.input_data.get("requirement", "")
                    element_context = requirement_stage.input_data.get("element_context", {})
                    # 【Task Registry】注册后台任务以便后续取消
                    task = asyncio.create_task(
                        cls._run_architect_task_background(pipeline_id, requirement, element_context)
                    )
                    cls._register_task(pipeline_id, task)
                    await push_log(
                        pipeline_id,
                        "info",
                        "后台任务已启动：重新执行需求分析...",
                        stage="REQUIREMENT"
                    )
            else:
                # 其他阶段使用 StageHandler 重新执行
                handler = cls._get_handler_for_stage(current_stage)
                if handler:
                    # 【Task Registry】注册后台任务以便后续取消
                    task = asyncio.create_task(
                        cls._run_stage_background(pipeline_id, current_stage.value)
                    )
                    cls._register_task(pipeline_id, task)
                    await push_log(
                        pipeline_id,
                        "info",
                        f"后台任务已启动：重新执行 {current_stage.value} 阶段...",
                        stage=current_stage.value
                    )

        return {
            "success": True,
            "data": {
                "previous_stage": current_stage.value if current_stage else None,
                "current_stage": current_stage.value if current_stage else None,
                "message": f"Pipeline 重试已启动，正在重新执行 {current_stage.value} 阶段"
            }
        }

    @classmethod
    async def terminate_pipeline(
        cls,
        pipeline_id: int,
        reason: str,
        session: AsyncSession,
        background_tasks=None
    ) -> Dict[str, Any]:
        """
        终止 Pipeline

        Args:
            pipeline_id: Pipeline ID
            reason: 终止原因
            session: 数据库 session
            background_tasks: FastAPI BackgroundTasks，用于异步执行资源清理

        Returns:
            终止结果
        """
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)

        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        # 检查状态是否可以终止
        if pipeline.status.value not in ["running", "paused"]:
            return {
                "success": False,
                "error": f"无法终止状态为 {pipeline.status.value} 的 Pipeline"
            }

        await push_log(
            pipeline_id,
            "warning",
            f"🛑 Pipeline 被手动终止，原因: {reason}",
            stage=pipeline.current_stage.value if pipeline.current_stage else "UNKNOWN"
        )

        # 【关键】立即取消正在运行的 asyncio Task
        cls._cancel_task(pipeline_id)

        # 更新 Pipeline 状态为 failed
        await WorkflowService.set_pipeline_failed(pipeline, session)

        # 使用后台任务异步清理资源，避免阻塞 API 响应
        if background_tasks:
            background_tasks.add_task(
                cls._cleanup_pipeline_resources,
                pipeline_id,
                reason
            )
        else:
            # 如果没有提供 background_tasks，同步执行（兼容旧代码）
            await cls._cleanup_pipeline_resources(pipeline_id, reason)

        return {
            "success": True,
            "data": {
                "pipeline_id": pipeline_id,
                "status": "failed",
                "message": f"Pipeline 已终止: {reason}",
                "terminated_at": datetime.now().isoformat()
            }
        }

    @classmethod
    async def _cleanup_pipeline_resources(cls, pipeline_id: int, reason: str) -> None:
        """后台任务：清理 Pipeline 资源（Sandbox、临时文件夹、日志缓冲区等）"""
        # 0. 【新增】取消正在运行的 asyncio Task
        cls._cancel_task(pipeline_id)

        # 1. 获取临时文件夹路径（在停止 Sandbox 前获取）
        temp_dir = None
        try:
            sandbox_info = sandbox_manager.get_info(pipeline_id)
            if sandbox_info:
                temp_dir = sandbox_info.project_path
        except Exception as e:
            info(f"获取 Sandbox 信息时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

        # 2. 停止 Sandbox（使用快速停止）
        try:
            await sandbox_manager.stop(pipeline_id, fast=True)
            info("Sandbox 已停止", pipeline_id=pipeline_id)
        except Exception as e:
            info(f"停止 Sandbox 时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

        # 3. 【新增】清理临时文件夹
        if temp_dir:
            try:
                import shutil
                from pathlib import Path
                temp_path = Path(temp_dir)
                if temp_path.exists() and temp_path.is_dir():
                    # 确保只删除临时文件夹（安全检查）
                    if "omniflow" in temp_path.name or "temp" in temp_path.name.lower():
                        shutil.rmtree(temp_path, ignore_errors=True)
                        info(f"临时文件夹已清理: {temp_dir}", pipeline_id=pipeline_id)
                    else:
                        warning(f"跳过清理非临时文件夹: {temp_dir}", pipeline_id=pipeline_id)
            except Exception as e:
                info(f"清理临时文件夹时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

        # 4. 【新增】从 sandbox_manager 中移除记录
        try:
            if pipeline_id in sandbox_manager._sandboxes:
                del sandbox_manager._sandboxes[pipeline_id]
                info(f"Sandbox 记录已移除", pipeline_id=pipeline_id)
        except Exception as e:
            info(f"移除 Sandbox 记录时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

        # 5. 清理 SSE 日志缓冲区
        remove_buffer(pipeline_id)

        # 6. 【新增】清理文件锁，防止内存泄漏
        try:
            from app.service.sandbox_file_service import cleanup_pipeline_file_locks
            cleanup_pipeline_file_locks(pipeline_id)
        except Exception as e:
            info(f"清理文件锁时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

    @classmethod
    def _get_handler_for_stage(cls, stage_name: StageName) -> Optional[Any]:
        """获取阶段对应的 Handler（从注册表单例获取，保证全局唯一实例）"""
        from app.service.stage_handlers.registry import get_registry
        return get_registry().get(stage_name)

    @classmethod
    async def _run_stage_background(cls, pipeline_id: int, stage_name: str):
        """后台运行指定阶段"""
        # 【新增】启动时检查 Pipeline 是否已终止
        if await cls._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", f"Pipeline 已终止，后台任务({stage_name})退出", stage=stage_name)
            return

        async with async_session_factory() as session:
            try:
                stage_enum = StageName(stage_name)
                handler = cls._get_handler_for_stage(stage_enum)

                if handler:
                    context = StageContext(
                        pipeline_id=pipeline_id,
                        session=session,
                        input_data={}
                    )
                    await handler.run(context)
                    await session.commit()
            except Exception as e:
                await session.rollback()
                error(f"后台运行阶段 {stage_name} 失败", pipeline_id=pipeline_id, exc_info=True)

    @staticmethod
    async def _check_pipeline_terminated(pipeline_id: int) -> bool:
        """检查 Pipeline 是否已被终止（支持 failed 和 cancelled 状态）"""
        async with async_session_factory() as session:
            pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
            if pipeline and pipeline.status.value in ("failed", "cancelled"):
                return True
            return False



    @staticmethod
    async def _create_testing_stage_record(pipeline_id: int) -> None:
        """提前创建 UNIT_TESTING 阶段记录，让前端轮询时看到 TESTER 节点为"执行中" """
        async with async_session_factory() as pre_session:
            from app.repositories.pipeline_stage_repository import PipelineStageRepository
            existing = await PipelineStageRepository.get_by_pipeline_and_name(
                pipeline_id, StageName.UNIT_TESTING, pre_session
            )
            if not existing:
                pre_session.add(PipelineStage(
                    pipeline_id=pipeline_id,
                    name=StageName.UNIT_TESTING,
                    status=StageStatus.RUNNING,
                    input_data={}
                ))
                await pre_session.commit()
                await push_log(pipeline_id, "info", "UNIT_TESTING 阶段已就绪", stage="UNIT_TESTING")

    @staticmethod
    async def _execute_coding_and_testing_concurrent(pipeline_id: int) -> tuple:
        """并发执行 CODING 和 TESTING，返回 (coding_result, testing_result)"""
        coding_task = PipelineService._trigger_phase(StageName.CODING, pipeline_id=pipeline_id, session=None)
        testing_task = PipelineService._trigger_phase(StageName.UNIT_TESTING, pipeline_id=pipeline_id, session=None)
        return await asyncio.gather(coding_task, testing_task, return_exceptions=True)

    @staticmethod
    async def _handle_coding_testing_results(
        pipeline_id: int, coding_result, testing_result
    ) -> bool:
        """检查并发结果，失败时标记 Pipeline 失败。返回 True 表示应该继续。"""
        if isinstance(coding_result, Exception) or isinstance(testing_result, Exception):
            error_msg = ""
            if isinstance(coding_result, Exception):
                error_msg += f"CODING 异常: {coding_result} "
            if isinstance(testing_result, Exception):
                error_msg += f"TESTING 异常: {testing_result}"
            raise Exception(error_msg)

        if not coding_result.get("success"):
            async with async_session_factory() as err_session:
                await PipelineService.mark_pipeline_failed(
                    pipeline_id, coding_result.get("message", "Coding phase failed"), session=err_session
                )
                await err_session.commit()
            return False

        if not testing_result.get("success"):
            async with async_session_factory() as err_session:
                await PipelineService.mark_pipeline_failed(
                    pipeline_id, testing_result.get("message", "Testing phase failed"), session=err_session
                )
                await err_session.commit()
            return False

        return True

    @staticmethod
    async def _run_tests_and_update_stage(pipeline_id: int) -> dict:
        """gather 完成后运行分层测试并更新 UNIT_TESTING 阶段"""
        test_run_result = await TestOrchestrator._run_tests_after_gather(pipeline_id)

        async with async_session_factory() as session:
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.UNIT_TESTING
            )
            result = await session.execute(statement)
            testing_stage = result.scalars().first()

            if testing_stage:
                if not testing_stage.output_data:
                    testing_stage.output_data = {}
                tr = testing_stage.output_data.setdefault("testing_result", {})
                tr["test_run_success"] = test_run_result.get("test_run_success", False)
                tr["overall_success"] = test_run_result.get("success", False)
                tr["test_run_logs"] = test_run_result.get("logs", "")
                tr["test_run_layers"] = test_run_result.get("layers", [])
                tr["contract_check"] = test_run_result.get("contract_check")
                tr["failed_tests"] = test_run_result.get("failed_tests", [])
                tr["failure_cause"] = test_run_result.get("failure_cause")
                tr["test_details"] = test_run_result.get("test_details", {})
                tr["defense_violations"] = test_run_result.get("defense_violations", [])
                flag_modified(testing_stage, "output_data")

                # 兜底：如果阶段状态仍然是运行中，标记为成功
                if testing_stage.status == StageStatus.RUNNING:
                    testing_stage.status = StageStatus.SUCCESS

                await session.commit()

        if test_run_result.get("test_run_success") and not test_run_result.get("requires_user_decision"):
            asyncio.create_task(TestOrchestrator._start_fastapi_in_sandbox(pipeline_id))

        if test_run_result.get("requires_user_decision"):
            await push_log(
                pipeline_id, "warning",
                "⚠️ 自动修复失败，Pipeline 暂停等待人工决策",
                stage="UNIT_TESTING"
            )
        return test_run_result

    @staticmethod
    async def _store_review_report(pipeline_id: int, pipeline_stages: dict) -> dict:
        """生成并存储 AI 审查报告到 CODE_REVIEW 阶段"""
        await push_log(pipeline_id, "info", "🤖 生成 AI 代码审查报告...", stage="UNIT_TESTING")
        review_report = await PipelineService._generate_ai_review_report(pipeline_id)

        async with async_session_factory() as session:
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.CODE_REVIEW
            )
            result = await session.execute(statement)
            review_stage = result.scalars().first()

            if not review_stage:
                coding_stage = pipeline_stages.get(StageName.CODING)
                testing_stage_inner = pipeline_stages.get(StageName.UNIT_TESTING)
                review_stage = await WorkflowService.create_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.CODE_REVIEW,
                    input_data={
                        "coding_output": coding_stage.output_data if coding_stage else {},
                        "testing_result": testing_stage_inner.output_data.get("testing_result", {}) if testing_stage_inner else {},
                    },
                    session=session
                )

            if review_stage:
                if not review_stage.output_data:
                    review_stage.output_data = {}
                review_stage.output_data["review_report"] = review_report
                flag_modified(review_stage, "output_data")
                await session.commit()

        await push_log(pipeline_id, "info", f"✅ AI 审查报告已生成，发现 {len(review_report.get('issues', []))} 个问题", stage="CODE_REVIEW")
        return review_report

    @staticmethod
    async def _set_pipeline_paused_at_review(pipeline_id: int) -> None:
        """设置 Pipeline 为 PAUSED 状态，当前阶段为 CODE_REVIEW"""
        async with async_session_factory() as session:
            pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
            if not pipeline:
                return
            pipeline.status = PipelineStatus.PAUSED
            pipeline.current_stage = StageName.CODE_REVIEW

            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.CODE_REVIEW
            )
            result = await session.execute(statement)
            if not result.scalars().first():
                coding_stage = testing_stage = None
                for s in pipeline.stages:
                    if s.name == StageName.CODING:
                        coding_stage = s
                    elif s.name == StageName.UNIT_TESTING:
                        testing_stage = s
                await WorkflowService.create_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.CODE_REVIEW,
                    input_data={
                        "coding_output": coding_stage.output_data.get("coder_output", {}) if coding_stage else {},
                        "testing_result": testing_stage.output_data.get("testing_result", {}) if testing_stage else {},
                        "target_files": coding_stage.output_data.get("target_files", {}) if coding_stage else {},
                    },
                    session=session
                )
                await push_log(pipeline_id, "info", "创建 CODE_REVIEW 阶段，等待统一审批", stage="CODE_REVIEW")
            await session.commit()

    @staticmethod
    async def _run_coding_task_background(pipeline_id: int) -> None:
        """
        后台任务：并发执行 CODING 和 TESTING 阶段，gather 完成后统一运行测试
        【流程】CODING + TESTING 并发 → 统一运行测试 → 进入 CODE_REVIEW 审批
        """
        async def _check_terminated() -> bool:
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return True
            return False

        try:
            if await _check_terminated():
                return

            await push_log(pipeline_id, "info", "后台任务启动：并发执行代码生成和分层测试...", stage="CODING")
            await PipelineService._create_testing_stage_record(pipeline_id)

            coding_result, testing_result = await PipelineService._execute_coding_and_testing_concurrent(pipeline_id)

            if await _check_terminated():
                return

            if not await PipelineService._handle_coding_testing_results(pipeline_id, coding_result, testing_result):
                return

            if await _check_terminated():
                return

            # 预加载 pipeline stages
            from sqlalchemy.orm import selectinload
            async with async_session_factory() as session:
                statement = select(Pipeline).where(Pipeline.id == pipeline_id).options(selectinload(Pipeline.stages))
                result = await session.execute(statement)
                pipeline = result.scalars().first()
                if not pipeline:
                    await push_log(pipeline_id, "error", f"Pipeline {pipeline_id} 不存在", stage="CODING")
                    return
                pipeline_stages = {s.name: s for s in pipeline.stages}

            test_run_result = await PipelineService._run_tests_and_update_stage(pipeline_id)

            if await _check_terminated():
                return

            await PipelineService._store_review_report(pipeline_id, pipeline_stages)

            if await _check_terminated():
                return

            await PipelineService._set_pipeline_paused_at_review(pipeline_id)

            # 推送状态日志
            test_generated = testing_result.get("output_data", {}).get("testing_result", {}).get("test_generated", False)
            test_run_success = test_run_result.get("success", False)
            if test_generated and test_run_success:
                await push_log(pipeline_id, "success", "✅ 代码生成和测试运行完成，等待代码审查", stage="CODE_REVIEW")
            elif test_generated:
                await push_log(pipeline_id, "warning", "⚠️ 代码生成完成，测试部分未通过，等待代码审查", stage="CODE_REVIEW")
            else:
                await push_log(pipeline_id, "info", "代码生成和分层测试完成，等待代码审查", stage="CODE_REVIEW")

        except Exception as e:
            error("Pipeline CODING/UNIT_TESTING 阶段失败", pipeline_id=pipeline_id, exc_info=True)
            op_logger.log_pipeline_status_change(
                pipeline_id=pipeline_id, old_status='running', new_status='failed',
                stage='CODING', error=str(e)
            )
            try:
                async with async_session_factory() as err_session:
                    await PipelineService.mark_pipeline_failed(pipeline_id, error=str(e), session=err_session)
                    await err_session.commit()
            except Exception:
                pass

    @staticmethod
    async def _retry_coding_only(pipeline_id: int, feedback: str) -> None:
        """
        仅重试 CODING 阶段（TESTING 保持不变）

        当用户拒绝 CODING 但接受 TESTING 时调用
        【修复】使用 async with 上下文管理器确保 session 正确关闭
        """
        # 【新增】启动时检查 Pipeline 是否已终止
        if await PipelineService._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", "Pipeline 已终止，重试任务退出", stage="CODING")
            return

        async with async_session_factory() as session:
            try:
                await push_log(pipeline_id, "info", "重新生成代码（保留测试）...", stage="CODING")

                # 重置 CODING 阶段状态
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == StageName.CODING
                )
                result = await session.execute(statement)
                coding_stage = result.scalars().first()

                if coding_stage:
                    coding_stage.status = StageStatus.PENDING
                    # 保留原始 output_data，只追加 retry_feedback 标记
                    existing_data = dict(coding_stage.output_data) if coding_stage.output_data else {}
                    existing_data["retry_feedback"] = feedback
                    coding_stage.output_data = existing_data
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(coding_stage, "output_data")
                    await session.commit()
                    session.expire(coding_stage)

                # 重新执行 CODING
                coding_result = await PipelineService.trigger_coding_phase(
                    pipeline_id=pipeline_id,
                    session=session,
                    error_context=feedback
                )

                if coding_result.get("success"):
                    await session.commit()
                    await push_log(pipeline_id, "info", "代码重新生成完成", stage="CODING")

                    # 回到 CODE_REVIEW 等待审批
                    pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                    if pipeline:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.current_stage = StageName.CODE_REVIEW
                        await session.commit()
                else:
                    await session.rollback()
                    await push_log(pipeline_id, "error", "代码重新生成失败", stage="CODING")

            except Exception as e:
                await session.rollback()
                error(f"[Pipeline {pipeline_id}] 重试 CODING 失败: {e}")

    @staticmethod
    async def _retry_testing_only(pipeline_id: int, feedback: str) -> None:
        """
        仅重试 TESTING 阶段（CODING 保持不变）

        当用户拒绝 TESTING 但接受 CODING 时调用
        【修复】使用 async with 上下文管理器确保 session 正确关闭
        """
        # 【新增】启动时检查 Pipeline 是否已终止
        if await PipelineService._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", "Pipeline 已终止，重试任务退出", stage="UNIT_TESTING")
            return

        async with async_session_factory() as session:
            try:
                await push_log(pipeline_id, "info", "重新生成测试（保留代码）...", stage="UNIT_TESTING")

                # 重置 TESTING 阶段状态
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == StageName.UNIT_TESTING
                )
                result = await session.execute(statement)
                testing_stage = result.scalars().first()

                if testing_stage:
                    testing_stage.status = StageStatus.PENDING
                    existing_data = dict(testing_stage.output_data) if testing_stage.output_data else {}
                    existing_data["retry_feedback"] = feedback
                    testing_stage.output_data = existing_data
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(testing_stage, "output_data")
                    await session.commit()

                # 重新执行 TESTING
                testing_result = await PipelineService._trigger_phase(
                    StageName.UNIT_TESTING,
                    pipeline_id=pipeline_id,
                    session=session
                )

                if testing_result.get("success"):
                    await session.commit()
                    await push_log(pipeline_id, "info", "测试重新生成完成", stage="UNIT_TESTING")

                    # 回到 CODE_REVIEW 等待审批
                    pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                    if pipeline:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.current_stage = StageName.CODE_REVIEW
                        await session.commit()
                else:
                    await session.rollback()
                    await push_log(pipeline_id, "error", "测试重新生成失败", stage="UNIT_TESTING")

            except Exception as e:
                await session.rollback()
                error(f"[Pipeline {pipeline_id}] 重试 TESTING 失败: {e}")

    @staticmethod
    async def _run_architect_task_background(
        pipeline_id: int,
        requirement: str,
        element_context: Optional[Dict[str, Any]]
    ) -> None:
        """
        后台任务：运行 ArchitectAgent 分析

        【优化】优先从预热池获取 Sandbox，无可用容器时回退到正常启动。
        """
        # 【新增】启动时检查 Pipeline 是否已终止
        if await PipelineService._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务(Architect)退出", stage="REQUIREMENT")
            return

        import time as time_mod
        from pathlib import Path
        from app.core.config import settings

        t_total = time_mod.perf_counter()

        # 1. 获取 Sandbox（优先预热池）
        t1 = time_mod.perf_counter()
        sandbox_info = await sandbox_manager.acquire_from_pool(pipeline_id)
        if sandbox_info is None:
            # 回退：正常启动 Sandbox
            project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
            sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
            sandbox_ms = int((time_mod.perf_counter() - t1) * 1000)
            info("Sandbox 启动耗时 (回退)", pipeline_id=pipeline_id, duration_ms=sandbox_ms)
        else:
            sandbox_ms = int((time_mod.perf_counter() - t1) * 1000)
            info("Sandbox 预热池获取耗时", pipeline_id=pipeline_id, duration_ms=sandbox_ms)

        # 2. 【关键修复】为 ArchitectAgent 注入 SandboxFileService，确保在沙箱模式下执行
        from app.service.sandbox_file_service import SandboxFileService
        from app.agents import architect_agent
        file_service = SandboxFileService(pipeline_id)
        architect_agent.set_file_service(file_service)

        # 3. 执行需求分析
        t2 = time_mod.perf_counter()
        async with async_session_factory() as session:
            try:
                await PipelineService.run_architect_task(
                    pipeline_id=pipeline_id,
                    requirement=requirement,
                    element_context=element_context,
                    session=session
                )
                await session.commit()
                arch_ms = int((time_mod.perf_counter() - t2) * 1000)
                total_ms = int((time_mod.perf_counter() - t_total) * 1000)
                info(
                    "Pipeline REQUIREMENT 阶段完成 (计时)",
                    pipeline_id=pipeline_id,
                    sandbox_acquisition_ms=sandbox_ms,
                    architect_total_ms=arch_ms,
                    overall_ms=total_ms,
                )
            except Exception as e:
                await session.rollback()
                error(
                    "Pipeline REQUIREMENT 阶段失败",
                    pipeline_id=pipeline_id,
                    exc_info=True
                )
                op_logger.log_pipeline_status_change(
                    pipeline_id=pipeline_id,
                    old_status='running',
                    new_status='failed',
                    stage='REQUIREMENT',
                    error=str(e)
                )
                try:
                    async with async_session_factory() as err_session:
                        await PipelineService.mark_pipeline_failed(
                            pipeline_id=pipeline_id,
                            error=str(e),
                            session=err_session
                        )
                        await err_session.commit()
                except Exception:
                    pass

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

    # ==================== 测试用例编辑器方法 ====================

    @classmethod
    async def override_test_and_rerun(
        cls,
        pipeline_id: int,
        file_path: str,
        content: str,
        session: AsyncSession,
        background_tasks: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        【测试用例编辑器】人工覆盖测试代码并重跑测试

        Args:
            pipeline_id: Pipeline ID
            file_path: 测试文件路径
            content: 新的测试代码内容
            session: 数据库会话
            background_tasks: 后台任务

        Returns:
            Dict: 覆盖和重跑结果
        """
        from app.service.sandbox_file_service import get_sandbox_file_service
        from app.service.layered_test_runner import LayeredTestRunner

        # 1. 检查 Pipeline 状态
        pipeline = await WorkflowService.get_pipeline_with_stages(pipeline_id, session)
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        if pipeline.status not in [PipelineStatus.PAUSED, PipelineStatus.RUNNING]:
            return {"success": False, "error": f"Pipeline 状态为 {pipeline.status.value}，不可修改测试"}

        # 2. 获取沙箱文件服务
        file_service = get_sandbox_file_service(pipeline_id)

        await push_log(
            pipeline_id,
            "info",
            f"📝 用户正在修改测试文件: {file_path}",
            stage="UNIT_TESTING"
        )

        try:
            # 3. 【新增】语法检查
            await push_log(
                pipeline_id,
                "info",
                "🔍 检查测试代码语法...",
                stage="UNIT_TESTING"
            )

            import ast
            try:
                ast.parse(content)
                await push_log(
                    pipeline_id,
                    "info",
                    "✅ 语法检查通过",
                    stage="UNIT_TESTING"
                )
            except SyntaxError as e:
                error_msg = f"语法错误 at line {e.lineno}: {e.msg}"
                await push_log(
                    pipeline_id,
                    "error",
                    f"❌ 语法检查失败: {error_msg}",
                    stage="UNIT_TESTING"
                )
                return {
                    "success": False,
                    "error": f"语法检查失败: {error_msg}",
                    "test_run_success": False,
                    "syntax_error": True,
                    "line": e.lineno,
                    "message": e.msg
                }

            # 4. 写入用户修改的测试代码
            await file_service.write_file(file_path, content)
            await push_log(
                pipeline_id,
                "info",
                f"✅ 测试文件已更新: {file_path}",
                stage="UNIT_TESTING"
            )

            # 5. 【修改】只运行用户修改过的单个测试文件
            await push_log(
                pipeline_id,
                "info",
                f"🔄 正在运行用户修改的测试: {file_path}...",
                stage="UNIT_TESTING"
            )

            # 只运行用户修改的测试文件
            single_test_result = await TestOrchestrator._run_single_test_file(
                pipeline_id=pipeline_id,
                file_path=file_path,
                content=content,
                file_service=file_service
            )

            # 6. 更新 UNIT_TESTING 阶段的输出数据
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.UNIT_TESTING
            )
            result = await session.execute(statement)
            testing_stage = result.scalars().first()

            test_run_success = single_test_result.get("success", False)

            if testing_stage and testing_stage.output_data:
                # 更新测试文件内容
                current_test_files = testing_stage.output_data.get("test_files", [])
                updated_test_files = []
                for tf in current_test_files:
                    if tf.get("file_path") == file_path:
                        updated_test_files.append({"file_path": file_path, "content": content})
                    else:
                        updated_test_files.append(tf)

                # 更新测试结果
                testing_stage.output_data["test_files"] = updated_test_files
                testing_stage.output_data["testing_result"] = {
                    **testing_stage.output_data.get("testing_result", {}),
                    "test_run_success": test_run_success,
                    "test_generated": True,
                    "user_overridden": True,
                    "override_file": file_path,
                    "user_test_result": single_test_result  # 存储单个测试结果
                }

                # 标记修改
                flag_modified(testing_stage, "output_data")
                await session.commit()

            # 7. 推送测试结果日志
            if test_run_success:
                await push_log(
                    pipeline_id,
                    "success",
                    "✅ 用户修改后的测试通过！",
                    stage="UNIT_TESTING"
                )
            else:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"⚠️ 测试未通过: {single_test_result.get('error', 'Unknown error')}",
                    stage="UNIT_TESTING"
                )
                for failed_test in single_test_result.get("failed_tests", []):
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"   - {failed_test}",
                        stage="UNIT_TESTING"
                    )

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "file_path": file_path,
                    "test_run_success": test_run_success,
                    "message": "测试通过" if test_run_success else f"测试未通过: {single_test_result.get('error')}",
                    "failed_tests": single_test_result.get("failed_tests", []),
                    "logs": single_test_result.get("logs", ""),
                    "summary": single_test_result.get("summary", "")
                }
            }

        except Exception as e:
            error(f"[Pipeline {pipeline_id}] 覆盖测试代码失败: {e}")
            await push_log(
                pipeline_id,
                "error",
                f"❌ 覆盖测试代码失败: {str(e)}",
                stage="UNIT_TESTING"
            )
            return {
                "success": False,
                "error": f"Failed to override test: {str(e)}"
            }


    @classmethod
    async def delete_pipeline(
        cls,
        pipeline_id: int,
        session: AsyncSession,
        background_tasks: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        删除 Pipeline 及其关联的所有数据

        Args:
            pipeline_id: Pipeline ID
            session: 数据库会话
            background_tasks: 后台任务（用于异步清理资源）

        Returns:
            Dict: 删除结果
        """
        from app.repositories import PipelineRepository

        # 1. 检查 Pipeline 是否存在
        pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
        if not pipeline:
            return {"success": False, "error": f"Pipeline {pipeline_id} not found"}

        try:
            # 2. 停止 Sandbox（如果正在运行）
            try:
                await sandbox_manager.stop(pipeline_id, fast=True)
                info("Sandbox 已停止", pipeline_id=pipeline_id)
            except Exception as e:
                info(f"停止 Sandbox 时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

            # 3. 清理日志缓冲区
            remove_buffer(pipeline_id)

            # 4. 删除 Pipeline（级联删除 Stages）
            await PipelineRepository.delete(pipeline_id, session)
            await session.commit()

            info("Pipeline 已删除", pipeline_id=pipeline_id)
            op_logger.log_pipeline_delete(pipeline_id=pipeline_id)

            return {
                "success": True,
                "data": {
                    "pipeline_id": pipeline_id,
                    "message": f"Pipeline {pipeline_id} 及其关联数据已删除"
                }
            }

        except Exception as e:
            await session.rollback()
            error(f"删除 Pipeline 失败", pipeline_id=pipeline_id, exc_info=True)
            return {
                "success": False,
                "error": f"Failed to delete pipeline: {str(e)}"
            }

    @classmethod
    async def _generate_ai_review_report(cls, pipeline_id: int) -> dict:
        """
        生成 AI 代码审查报告

        Args:
            pipeline_id: Pipeline ID

        Returns:
            dict: 审查报告
        """
        from app.agents import code_reviewer_agent
        from app.repositories import PipelineRepository

        try:
            async with async_session_factory() as session:
                pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                if not pipeline:
                    return cls._create_fallback_review_report("Pipeline not found")

                # 获取 CODING 阶段输出
                coding_output = {}
                testing_result = {}
                file_changes = []
                design_doc = ""
                interface_specs = []

                for stage in pipeline.stages:
                    if stage.name == StageName.CODING and stage.output_data:
                        coding_output = stage.output_data
                        coder_output = coding_output.get("coder_output", {})
                        # 【修复】files 在 coding_output 根级别，不在 coder_output 中
                        file_changes = coding_output.get("files", [])
                        # 【修复】interface_specs 在 coder_output 中
                        interface_specs = coder_output.get("interface_specs", [])
                    elif stage.name == StageName.UNIT_TESTING and stage.output_data:
                        testing_result = stage.output_data.get("testing_result", {})
                    elif stage.name == StageName.DESIGN and stage.output_data:
                        design_doc = stage.output_data.get("technical_design", "")
                        # 【修复】如果还没有获取到 interface_specs，从 DESIGN 阶段获取
                        # DESIGN 阶段直接返回 design_output 作为 output_data
                        if not interface_specs:
                            interface_specs = stage.output_data.get("interface_specs", [])

                # 构建 Agent 初始状态
                initial_state = {
                    "file_changes": file_changes,
                    "test_results": testing_result,
                    "design_doc": design_doc,
                    "interface_specs": interface_specs,
                }

                # 【新增】记录输入数据摘要，便于调试
                logger.info(
                    f"[AI Review] 生成审查报告，输入数据: "
                    f"files={len(file_changes)}, "
                    f"interface_specs={len(interface_specs)}, "
                    f"design_doc_length={len(design_doc)}, "
                    f"has_test_results={bool(testing_result)}"
                )

                # 执行 Agent
                result = await code_reviewer_agent.execute(
                    pipeline_id=pipeline_id,
                    stage_name="UNIT_TESTING",
                    initial_state=initial_state
                )

                if result.get("success") and result.get("output"):
                    review_output = result["output"]
                    report = review_output.get("review_report", {})
                    logger.info(f"[AI Review] 审查报告生成成功，发现问题: {len(report.get('issues', []))}")
                    return report
                else:
                    error_msg = result.get("error", "未知错误")
                    logger.error(f"[AI Review] 审查报告生成失败: {error_msg}")
                    return cls._create_fallback_review_report(error_msg)

        except Exception as e:
            logger.error(f"[Pipeline {pipeline_id}] 生成审查报告异常：{e}")
            return cls._create_fallback_review_report(str(e))

    @classmethod
    def _create_fallback_review_report(cls, error_msg: str) -> dict:
        """创建降级审查报告（当 Agent 执行失败时）"""
        return {
            "issues": [],
            "overall_assessment": f"AI 审查报告生成失败: {error_msg}。请人工仔细审查代码。",
            "summary": "审查报告生成异常",
            "improvement_suggestions": ["请人工仔细审查代码", "检查代码是否符合设计规范"],
            "risk_level": "medium",
            "approval_recommendation": "approve_with_caution"
        }
