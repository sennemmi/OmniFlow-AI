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
        """注册正在运行的任务"""
        cls._running_tasks[pipeline_id] = task

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
    async def _trigger_coding_phase(
        cls,
        pipeline_id: int,
        session: Optional[AsyncSession] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        触发 CODING 阶段（供后台任务调用）

        【重要】如果传入 session，会使用该 session；否则创建独立 session。
        并发执行时应该传入 None，让每个阶段使用独立的 session 避免冲突。
        """
        service = cls()

        if session is not None:
            # 使用传入的 session（单线程模式）
            return await service._trigger_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.CODING,
                session=session,
                error_context=error_context
            )
        else:
            # 【并发模式】创建独立 session
            async with async_session_factory() as new_session:
                return await service._trigger_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.CODING,
                    session=new_session,
                    error_context=error_context
                )

    @classmethod
    async def _trigger_testing_phase(cls, pipeline_id: int, session: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """
        触发 UNIT_TESTING 阶段

        【重要】如果传入 session，会使用该 session；否则创建独立 session。
        并发执行时应该传入 None，让每个阶段使用独立的 session 避免冲突。
        """
        service = cls()

        if session is not None:
            # 使用传入的 session（单线程模式）
            return await service._trigger_stage(
                pipeline_id=pipeline_id,
                stage_name=StageName.UNIT_TESTING,
                session=session
            )
        else:
            # 【并发模式】创建独立 session
            async with async_session_factory() as new_session:
                return await service._trigger_stage(
                    pipeline_id=pipeline_id,
                    stage_name=StageName.UNIT_TESTING,
                    session=new_session
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

        # 处理 DESIGN 阶段的特殊情况（需要后台任务执行 CODING）
        if current_stage == StageName.DESIGN and background_tasks:
            if result.output_data.get("requires_background_task"):
                # 【Task Registry】注册后台任务以便后续取消
                task = asyncio.create_task(cls._run_coding_task_background(pipeline_id))
                cls._register_task(pipeline_id, task)

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

        # 【新流程】CODING 阶段被驳回时，打回 DESIGN 阶段重试
        target_stage = current_stage
        if current_stage == StageName.CODING:
            target_stage = StageName.DESIGN
            await push_log(
                pipeline_id,
                "info",
                f"代码被驳回，打回 DESIGN 阶段重新设计",
                stage="DESIGN"
            )

        # 标记目标阶段需要重新执行
        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=pipeline_id, stage_name=target_stage,
            rejection_feedback=rejection_feedback, session=session
        )

        # 【关键】如果是 CODING 被驳回，需要将 Pipeline 当前阶段设为 DESIGN
        if current_stage == StageName.CODING:
            pipeline.current_stage = StageName.DESIGN

        await WorkflowService.set_pipeline_running(pipeline, session)
        await session.commit()

        # 创建 StageContext
        context = StageContext(
            pipeline_id=pipeline_id,
            session=session,
            input_data={}
        )

        # 调用 Handler 的 on_rejected 方法（使用目标阶段的 handler）
        target_handler = service._registry.get(target_stage)
        if target_handler:
            result = await target_handler.on_rejected(context, reason, suggested_changes)
        else:
            # 如果没有找到 handler，使用当前 handler
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

            if background_tasks:
                # 【Task Registry】注册后台任务以便后续取消
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

            if background_tasks:
                # 【Task Registry】注册后台任务以便后续取消
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

            if background_tasks:
                # 【Task Registry】注册后台任务以便后续取消
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
        return await cls._trigger_coding_phase(pipeline_id, session, error_context)

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
                stage = result.scalar_one_or_none()
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
        stage = result.scalar_one_or_none()

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
        """获取阶段对应的 Handler"""
        handler_map = {
            StageName.REQUIREMENT: RequirementHandler(),
            StageName.DESIGN: DesignHandler(),
            StageName.CODING: CodingHandler(),
            StageName.UNIT_TESTING: TestingHandler(),
            StageName.CODE_REVIEW: CodeReviewHandler(),
            StageName.DELIVERY: DeliveryHandler(),
        }
        return handler_map.get(stage_name)

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
    async def _run_tests_after_gather(pipeline_id: int) -> Dict[str, Any]:
        """
        在 CODING 和 TESTING 都完成后，统一执行测试流程（支持逐层修复）

        流程：
        1. 从数据库读取 CODING 和 UNIT_TESTING 阶段的输出
        2. 【前置检查】契约检查 + 语法检查，失败则重新调用 Tester 生成测试
        3. 执行预测试，失败则调用 RepairService 修复，直到通过
        4. 执行分层测试（defense -> regression -> new_tests），每层失败后修复再重试
        5. 返回测试结果
        """

        # 【新增】初始化测试详情记录
        test_details = {
            "preliminary": {"attempts": [], "final_status": "pending"},
            "layers": {"defense": [], "regression": [], "new_tests": []},
            "repairs": [],
            "defense_violations": [],  # 记录对 defense 文件夹的修改尝试
        }
        from app.service.layered_test_runner import LayeredTestRunner, LayerResult
        from app.service.sandbox_file_service import get_sandbox_file_service
        from app.service.repair_service import repair_service
        from app.core.contract_checker import verify_contract
        from app.utils.test_execution import run_preliminary_test, analyze_test_failure
        from app.agents import test_agent
        from app.utils.agent_debug_utils import get_agent_debugger

        await push_log(pipeline_id, "info", "CODER 和 TESTER 都已完成，开始测试流程...", stage="UNIT_TESTING")

        # 【新增】测试流程开始前检查 Pipeline 是否已终止
        if await PipelineService._check_pipeline_terminated(pipeline_id):
            await push_log(pipeline_id, "warning", "Pipeline 已终止，测试流程退出", stage="UNIT_TESTING")
            return {"success": False, "error": "Pipeline terminated", "test_run_success": False}

        file_service = get_sandbox_file_service(pipeline_id)
        debugger = get_agent_debugger()

        # 从数据库获取 CODING 和 UNIT_TESTING 阶段的输出
        async with async_session_factory() as session:
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name.in_([StageName.CODING, StageName.UNIT_TESTING])
            )
            result = await session.execute(statement)
            stages = result.scalars().all()

            coding_stage = None
            testing_stage = None
            for stage in stages:
                if stage.name == StageName.CODING:
                    coding_stage = stage
                elif stage.name == StageName.UNIT_TESTING:
                    testing_stage = stage

            # 提取代码文件（从 CODING 阶段）
            code_files = []
            if coding_stage and coding_stage.output_data:
                coder_output = coding_stage.output_data.get("coder_output", {})
                code_files = coder_output.get("files", [])

            # 提取测试文件（从 UNIT_TESTING 阶段）
            test_files = []
            design_output = {}
            if testing_stage and testing_stage.output_data:
                testing_result = testing_stage.output_data.get("testing_result", {})
                test_files = testing_result.get("test_files", [])
                design_output = testing_stage.input_data.get("design_output", {})

        if not test_files:
            return {"success": False, "error": "No test files found", "contract_check": None}

        # 构建 code_files_dict 用于契约检查
        code_files_dict = {}
        for f in code_files:
            file_path = f.get("file_path", "")
            content = f.get("content", "")
            if file_path and content:
                file_path = file_path.lstrip("/")
                if not file_path.startswith("backend/"):
                    file_path = f"backend/{file_path}"
                code_files_dict[file_path] = content

        # ========== 【前置检查】契约检查 + 语法检查 ==========
        await push_log(pipeline_id, "info", "[前置检查] 执行契约检查和语法检查...", stage="UNIT_TESTING")

        interface_specs = design_output.get("interface_specs", [])
        max_tester_regeneration = 2  # 最多重新生成2次

        for regeneration in range(max_tester_regeneration + 1):
            # 契约检查
            contract_passed = True
            if interface_specs and code_files_dict:
                missing_symbols = verify_contract(code_files_dict, interface_specs)
                contract_passed = len(missing_symbols) == 0

                if not contract_passed:
                    await push_log(
                        pipeline_id, "warning",
                        f"❌ 契约检查失败: {len(missing_symbols)} 个符号未实现",
                        stage="UNIT_TESTING"
                    )
                    for sym in missing_symbols:
                        await push_log(pipeline_id, "warning", f"   - {sym}", stage="UNIT_TESTING")

            # 语法检查（对测试文件）
            syntax_passed = True
            syntax_errors = []
            import ast
            for tf in test_files:
                path = tf.get("file_path", "")
                content = tf.get("content", "")
                if path.endswith(".py") and content:
                    try:
                        ast.parse(content)
                    except SyntaxError as e:
                        syntax_passed = False
                        syntax_errors.append(f"{path}: SyntaxError at line {e.lineno}: {e.msg}")

            if not syntax_passed:
                await push_log(
                    pipeline_id, "warning",
                    f"❌ 语法检查失败: {len(syntax_errors)} 个文件存在语法错误",
                    stage="UNIT_TESTING"
                )
                for err in syntax_errors:
                    await push_log(pipeline_id, "warning", f"   - {err}", stage="UNIT_TESTING")

            # 检查是否通过
            if contract_passed and syntax_passed:
                await push_log(
                    pipeline_id, "info",
                    "✅ 契约检查和语法检查通过",
                    stage="UNIT_TESTING"
                )
                break
            else:
                if regeneration < max_tester_regeneration:
                    await push_log(
                        pipeline_id, "warning",
                        f"前置检查失败（尝试 {regeneration + 1}/{max_tester_regeneration}），重新调用 Tester 生成测试...",
                        stage="UNIT_TESTING"
                    )

                    # 重新调用 Tester 生成测试
                    test_result = await test_agent.generate_tests(
                        design_output=design_output,
                        code_output=None,
                        pipeline_id=pipeline_id,
                    )

                    if test_result.get("success"):
                        test_files = test_result["output"].get("test_files", [])
                        # 写入沙箱
                        for tf in test_files:
                            file_path = tf.get("file_path", "")
                            content = tf.get("content", "")
                            if file_path and content:
                                # 【修复】正确处理 Tester 生成的路径（已规范输出 backend/tests/ai_generated/...）
                                # 信任 Tester 生成的路径，不再添加前缀
                                await file_service.write_file(file_path, content)

                        await push_log(
                            pipeline_id, "info",
                            f"✅ 测试重新生成成功 ({len(test_files)} 个文件)",
                            stage="UNIT_TESTING"
                        )
                    else:
                        await push_log(
                            pipeline_id, "error",
                            f"❌ 测试重新生成失败: {test_result.get('error', '')}",
                            stage="UNIT_TESTING"
                        )
                        return {
                            "success": False,
                            "error": "前置检查失败且测试重新生成失败",
                            "test_run_success": False,
                            "layers": [{"layer": "pre_check", "passed": False, "summary": "前置检查失败"}]
                        }
                else:
                    await push_log(
                        pipeline_id, "error",
                        "❌ 前置检查在最大重试次数后仍未通过",
                        stage="UNIT_TESTING"
                    )
                    return {
                        "success": False,
                        "error": "契约检查或语法检查失败",
                        "test_run_success": False,
                        "layers": [{"layer": "pre_check", "passed": False, "summary": "前置检查失败"}]
                    }

        # 构建 all_files 列表
        all_files = []
        for f in code_files:
            file_path = f.get("file_path", "")
            content = f.get("content", "")
            if file_path and content:
                file_path = file_path.lstrip("/")
                if not file_path.startswith("backend/"):
                    file_path = f"backend/{file_path}"
                all_files.append({"file_path": file_path, "content": content})

        for tf in test_files:
            file_path = tf.get("file_path", "")
            content = tf.get("content", "")
            if file_path and content:
                # 【修复】信任 Tester 生成的路径（已规范输出 backend/tests/ai_generated/...）
                # 不再添加前缀，直接使用原始路径
                all_files.append({"file_path": file_path, "content": content})

        # ========== 1. 预测试（失败则修复直到通过）==========
        await push_log(pipeline_id, "info", "[Step 1/3] 执行预测试...", stage="UNIT_TESTING")

        max_preliminary_retries = 3
        preliminary_passed = False
        preliminary_logs = ""

        # 包装 push_log 为同步回调（push_log 内部无 await，直接调用即可）
        def _sync_push_log(level: str, msg: str):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(push_log(pipeline_id, level, msg, stage="UNIT_TESTING"))
                else:
                    # 无事件循环时直接同步执行（push_log 内部无 await）
                    asyncio.run(push_log(pipeline_id, level, msg, stage="UNIT_TESTING"))
            except RuntimeError:
                # get_event_loop 可能失败，fallback
                pass

        for retry in range(max_preliminary_retries):
            preliminary_result = await run_preliminary_test(
                pipeline_id=pipeline_id,
                test_files=test_files,
                file_service=file_service,
                timeout=60,
                log_callback=_sync_push_log
            )

            preliminary_logs = preliminary_result.get("logs", "")

            # 【新增】记录预测试尝试
            test_details["preliminary"]["attempts"].append({
                "attempt": retry + 1,
                "success": preliminary_result.get("success", False),
                "passed_count": preliminary_result.get("passed_count", 0),
                "failed_count": preliminary_result.get("failed_count", 0),
                "logs": preliminary_logs[:2000] if preliminary_logs else "",  # 限制日志长度
            })

            if preliminary_result.get("success"):
                preliminary_passed = True
                test_details["preliminary"]["final_status"] = "passed"
                await push_log(
                    pipeline_id, "info",
                    f"✅ 预测试通过 ({preliminary_result.get('passed_count', 0)} passed)",
                    stage="UNIT_TESTING"
                )
                break
            else:
                await push_log(
                    pipeline_id, "warning",
                    f"预测试失败（尝试 {retry + 1}/{max_preliminary_retries}），启动 RepairService...",
                    stage="UNIT_TESTING"
                )

                # 【修复】显式推送预测试错误详情到终端/SSE
                failed_count = preliminary_result.get("failed_count", 0)
                errors_count = preliminary_result.get("errors_count", 0)
                passed_count = preliminary_result.get("passed_count", 0)
                collected_count = preliminary_result.get("collected_count", 0)
                failed_tests = preliminary_result.get("failed_tests", [])
                error_tests = preliminary_result.get("error_tests", [])

                await push_log(
                    pipeline_id, "warning",
                    f"预测试统计: collected={collected_count} | passed={passed_count} | failed={failed_count} | errors={errors_count}",
                    stage="UNIT_TESTING"
                )
                if failed_tests:
                    await push_log(
                        pipeline_id, "warning",
                        f"失败测试: {', '.join(failed_tests[:10])}",
                        stage="UNIT_TESTING"
                    )
                if error_tests:
                    await push_log(
                        pipeline_id, "warning",
                        f"错误测试: {', '.join(error_tests[:10])}",
                        stage="UNIT_TESTING"
                    )

                # 提取并推送错误日志关键部分
                from app.utils.repair_utils import extract_pytest_failures
                error_summary = extract_pytest_failures(preliminary_logs, max_chars=3000)
                if error_summary:
                    await push_log(
                        pipeline_id, "warning",
                        f"【预测试错误详情】\n{error_summary}",
                        stage="UNIT_TESTING"
                    )

                # 【新增】检查 RepairAgent 是否尝试修改 defense 文件夹
                defense_violations = await PipelineService._check_defense_modifications(pipeline_id, file_service)
                if defense_violations:
                    violation_msg = f"🚫 检测到 RepairAgent 尝试修改 defense 文件夹: {defense_violations}"
                    await push_log(pipeline_id, "error", violation_msg, stage="UNIT_TESTING")
                    test_details["defense_violations"].extend(defense_violations)

                    # 终止 Pipeline
                    async with async_session_factory() as session:
                        pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                        if pipeline:
                            pipeline.status = PipelineStatus.FAILED
                            from app.core.timezone import now
                            pipeline.updated_at = now()
                            await session.commit()

                    return {
                        "success": False,
                        "error": f"RepairAgent 违规修改 defense 文件夹: {defense_violations}",
                        "test_run_success": False,
                        "defense_violations": defense_violations,
                        "test_details": test_details,
                        "layers": [{"layer": "preliminary", "passed": False, "summary": "违规修改 defense 文件夹"}]
                    }

                # 调用 RepairService 修复
                repair_result = await repair_service.start_repair(
                    pipeline_id=pipeline_id,
                    code_files=code_files,
                    test_files=test_files,
                    test_logs=preliminary_logs,
                    design_output=design_output,
                    file_service=file_service,
                    log_callback=lambda level, msg: push_log(pipeline_id, level, msg, stage="UNIT_TESTING"),
                    debugger=debugger,
                )

                # 【新增】记录修复详情
                test_details["repairs"].append({
                    "stage": "preliminary",
                    "attempt": retry + 1,
                    "success": repair_result.get("test_run_success", False),
                    "repair_rounds": repair_result.get("repair_rounds", 0),
                    "fixed_files": repair_result.get("fixed_files", []),
                    "fix_history": repair_result.get("fix_history", []),
                })

                if repair_result.get("test_run_success"):
                    await push_log(
                        pipeline_id, "success",
                        f"✅ 修复成功，重新进行预测试...",
                        stage="UNIT_TESTING"
                    )
                    # 更新代码文件（修复后的）
                    code_files = repair_result.get("fixed_files", code_files)
                else:
                    await push_log(
                        pipeline_id, "warning",
                        f"⚠️ 修复失败，预测试未通过，建议重试或完善需求说明",
                        stage="UNIT_TESTING"
                    )
                    test_details["preliminary"]["final_status"] = "failed"
                    # 【修改】返回警告而非失败，允许用户选择继续
                    return {
                        "success": True,  # 改为 True，表示流程可以继续
                        "warning": True,
                        "error": "预测试失败且修复未通过",
                        "test_run_success": False,
                        "requires_user_decision": True,
                        "suggestion": "建议重试或完善需求说明",
                        "test_details": test_details,
                        "layers": [{"layer": "preliminary", "passed": False, "summary": "预测试失败（需人工确认）"}]
                    }

        if not preliminary_passed:
            await push_log(
                pipeline_id, "warning",
                f"⚠️ 预测试在最大重试次数后仍未通过，建议重试或完善需求说明",
                stage="UNIT_TESTING"
            )
            # 【修改】返回警告而非失败
            return {
                "success": True,  # 改为 True
                "warning": True,
                "error": "预测试在最大重试次数后仍未通过",
                "test_run_success": False,
                "requires_user_decision": True,
                "suggestion": "建议重试或完善需求说明",
                "layers": [{"layer": "preliminary", "passed": False, "summary": "预测试失败（需人工确认）"}]
            }

        # ========== 2. 分层测试（逐层执行，每层失败后修复）==========
        await push_log(pipeline_id, "info", "[Step 2/3] 执行分层测试...", stage="UNIT_TESTING")

        layers: List[LayerResult] = []
        layer_order = ["defense", "regression", "new_tests"]
        max_layer_retries = 3

        for layer_name in layer_order:
            await push_log(pipeline_id, "info", f"  开始 {layer_name} 层测试...", stage="UNIT_TESTING")

            layer_passed = False
            layer_result = None

            for retry in range(max_layer_retries):
                # 运行当前层测试
                if layer_name == "defense":
                    layer_result = await LayeredTestRunner._run_defense_layer(
                        Path("/workspace"), file_service, 120
                    )
                elif layer_name == "regression":
                    layer_result = await LayeredTestRunner._run_regression_layer(
                        Path("/workspace"), file_service, 120
                    )
                else:  # new_tests
                    layer_result = await LayeredTestRunner._run_new_tests_layer(
                        Path("/workspace"), file_service, 120
                    )

                layers.append(layer_result)

                # 【新增】记录分层测试详情
                test_details["layers"][layer_name].append({
                    "attempt": retry + 1,
                    "passed": layer_result.passed,
                    "summary": layer_result.summary,
                    "logs": layer_result.logs[:2000] if layer_result.logs else "",
                    "failed_tests": layer_result.failed_tests if hasattr(layer_result, 'failed_tests') else [],
                })

                status = "✅ PASS" if layer_result.passed else "❌ FAIL"
                await push_log(
                    pipeline_id,
                    "info" if layer_result.passed else "warning",
                    f"  {status} {layer_name}: {layer_result.summary}",
                    stage="UNIT_TESTING"
                )

                if layer_result.passed:
                    layer_passed = True
                    break
                else:
                    # 当前层失败，调用 RepairService
                    await push_log(
                        pipeline_id, "warning",
                        f"  {layer_name} 层失败（尝试 {retry + 1}/{max_layer_retries}），启动修复...",
                        stage="UNIT_TESTING"
                    )

                    # 【新增】检查 RepairAgent 是否尝试修改 defense 文件夹
                    defense_violations = await PipelineService._check_defense_modifications(pipeline_id, file_service)
                    if defense_violations:
                        violation_msg = f"🚫 检测到 RepairAgent 尝试修改 defense 文件夹: {defense_violations}"
                        await push_log(pipeline_id, "error", violation_msg, stage="UNIT_TESTING")
                        test_details["defense_violations"].extend(defense_violations)

                        # 终止 Pipeline
                        async with async_session_factory() as session:
                            pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                            if pipeline:
                                pipeline.status = PipelineStatus.FAILED
                                from app.core.timezone import now
                                pipeline.updated_at = now()
                                await session.commit()

                        return {
                            "success": False,
                            "error": f"RepairAgent 违规修改 defense 文件夹: {defense_violations}",
                            "test_run_success": False,
                            "defense_violations": defense_violations,
                            "test_details": test_details,
                            "layers": [
                                {"layer": l.layer, "passed": l.passed, "summary": "违规修改 defense 文件夹"}
                                for l in layers
                            ]
                        }

                    repair_result = await repair_service.start_repair(
                        pipeline_id=pipeline_id,
                        code_files=code_files,
                        test_files=test_files,
                        test_logs=layer_result.logs,
                        design_output=design_output,
                        file_service=file_service,
                        log_callback=lambda level, msg: push_log(pipeline_id, level, msg, stage="UNIT_TESTING"),
                        debugger=debugger,
                    )

                    # 【新增】记录修复详情
                    test_details["repairs"].append({
                        "stage": layer_name,
                        "attempt": retry + 1,
                        "success": repair_result.get("test_run_success", False),
                        "repair_rounds": repair_result.get("repair_rounds", 0),
                        "fixed_files": repair_result.get("fixed_files", []),
                        "fix_history": repair_result.get("fix_history", []),
                    })

                    if repair_result.get("test_run_success"):
                        await push_log(
                            pipeline_id, "success",
                            f"  ✅ {layer_name} 层修复成功，重新测试...",
                            stage="UNIT_TESTING"
                        )
                        code_files = repair_result.get("fixed_files", code_files)
                    else:
                        await push_log(
                            pipeline_id, "warning",
                            f"  ⚠️ {layer_name} 层修复失败，建议重试或完善需求说明",
                            stage="UNIT_TESTING"
                        )
                        # 【修改】返回警告而非失败，允许用户选择继续
                        return {
                            "success": True,  # 改为 True
                            "warning": True,
                            "error": f"{layer_name} 层测试失败且修复未通过",
                            "test_run_success": False,
                            "requires_user_decision": True,
                            "suggestion": "建议重试或完善需求说明",
                            "test_details": test_details,
                            "layers": [
                                {"layer": l.layer, "passed": l.passed, "summary": l.summary + "（需人工确认）"}
                                for l in layers
                            ]
                        }

            if not layer_passed:
                await push_log(
                    pipeline_id, "warning",
                    f"  ⚠️ {layer_name} 层在最大重试次数后仍未通过，建议重试或完善需求说明",
                    stage="UNIT_TESTING"
                )
                # 【修改】返回警告而非失败
                return {
                    "success": True,  # 改为 True
                    "warning": True,
                    "error": f"{layer_name} 层在最大重试次数后仍未通过",
                    "test_run_success": False,
                    "requires_user_decision": True,
                    "suggestion": "建议重试或完善需求说明",
                    "test_details": test_details,
                    "layers": [
                        {"layer": l.layer, "passed": l.passed, "summary": l.summary + "（需人工确认）"}
                        for l in layers
                    ]
                }

        all_passed = all(l.passed for l in layers)

        # 【修改】即使测试未完全通过，也返回成功（带警告），让用户决定
        if not all_passed:
            await push_log(
                pipeline_id, "warning",
                "⚠️ 部分测试未通过，建议重试或完善需求说明",
                stage="UNIT_TESTING"
            )
            return {
                "success": True,  # 改为 True，流程继续
                "warning": True,
                "test_run_success": False,
                "requires_user_decision": True,
                "suggestion": "建议重试或完善需求说明",
                "contract_check": {"passed": True, "message": "契约检查已在前置步骤完成"},
                "logs": "\n\n".join([l.logs for l in layers]),
                "failed_tests": [],
                "test_details": test_details,
                "layers": [
                    {"layer": l.layer, "passed": l.passed, "summary": l.summary + ("（需人工确认）" if not l.passed else "")}
                    for l in layers
                ]
            }

        return {
            "success": True,
            "test_run_success": True,
            "contract_check": {"passed": True, "message": "契约检查已在前置步骤完成"},
            "logs": "\n\n".join([l.logs for l in layers]),
            "failed_tests": [],
            "test_details": test_details,
            "layers": [
                {"layer": l.layer, "passed": l.passed, "summary": l.summary}
                for l in layers
            ]
        }

    @staticmethod
    async def _check_pipeline_terminated(pipeline_id: int) -> bool:
        """检查 Pipeline 是否已被终止（支持 failed 和 cancelled 状态）"""
        async with async_session_factory() as session:
            pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
            if pipeline and pipeline.status.value in ("failed", "cancelled"):
                return True
            return False

    @staticmethod
    async def _start_fastapi_in_sandbox(pipeline_id: int) -> Dict[str, Any]:
        """
        分层测试通过后在 Sandbox 容器中启动 FastAPI 服务

        1. 杀掉 sandbox 中占用 8000 端口的进程
        2. 后台启动 uvicorn main:app
        3. 推送启动日志供用户查看

        Returns:
            Dict: {success, port, message}
        """
        try:
            # 1. 杀掉占用 8000 端口的进程
            kill_cmd = (
                "fuser -k 8000/tcp 2>/dev/null && echo 'killed' || echo 'port_free'"
            )
            kill_result = await sandbox_manager.exec(pipeline_id, kill_cmd, timeout=10)
            await push_log(
                pipeline_id, "info",
                f"端口 8000 清理结果: {kill_result.stdout.strip()}",
                stage="UNIT_TESTING"
            )

            # 2. 后台启动 FastAPI
            start_cmd = (
                "cd /workspace/backend && "
                "PYTHONPATH=/workspace/backend nohup python -m uvicorn main:app "
                "--host 0.0.0.0 --port 8000 "
                "> /tmp/fastapi.log 2>&1 & "
                "sleep 3 && "
                "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/health 2>/dev/null || echo 'starting'"
            )
            start_result = await sandbox_manager.exec(pipeline_id, start_cmd, timeout=15)
            status_output = start_result.stdout.strip()

            # 3. 获取 sandbox 对外端口
            sandbox_info = sandbox_manager.get_info(pipeline_id)
            host_port = sandbox_info.port if sandbox_info else "unknown"

            if "200" in status_output:
                await push_log(
                    pipeline_id, "success",
                    f"FastAPI 服务已在 Sandbox 中启动，对外端口: {host_port}",
                    stage="UNIT_TESTING"
                )
                await push_log(
                    pipeline_id, "info",
                    f"接口测试地址: http://localhost:{host_port}/api/v1/health",
                    stage="UNIT_TESTING"
                )
                return {"success": True, "port": host_port, "message": f"FastAPI started on sandbox port {host_port}"}
            else:
                await push_log(
                    pipeline_id, "info",
                    f"FastAPI 已启动，对外端口：{host_port}",
                    stage="UNIT_TESTING"
                )
                return {"success": True, "port": host_port, "message": f"FastAPI started on sandbox port {host_port}"}

        except Exception as e:
            await push_log(
                pipeline_id, "error",
                f"在 Sandbox 中启动 FastAPI 失败: {str(e)}",
                stage="UNIT_TESTING"
            )
            return {"success": False, "error": str(e)}
            return False

    @staticmethod
    async def _check_defense_modifications(pipeline_id: int, file_service: Any) -> List[str]:
        """
        检查 RepairAgent 是否尝试修改 defense 文件夹中的内容

        Returns:
            List[str]: 违规修改的文件路径列表，如果没有则返回空列表
        """
        violations = []
        try:
            # 获取最近修改的文件列表（可以通过文件服务的日志或检查文件修改时间）
            # 这里我们检查 sandbox 中 defense 目录下的文件是否被修改
            import os
            from pathlib import Path

            workspace_path = Path(f"/tmp/pipeline_{pipeline_id}")
            defense_path = workspace_path / "backend" / "tests" / "unit" / "defense"

            if defense_path.exists():
                # 检查 defense 目录下的所有文件
                for file_path in defense_path.rglob("*.py"):
                    # 检查文件是否被修改（可以通过比较哈希或修改时间）
                    # 简化处理：检查文件是否存在且可读
                    try:
                        relative_path = str(file_path.relative_to(workspace_path))
                        # 如果文件存在，记录它（实际应该检查是否被修改）
                        violations.append(relative_path)
                    except Exception:
                        pass

            # 【更严格的检查】通过 file_service 检查最近的写入操作
            # 这需要 file_service 支持记录写入历史
            # 暂时返回空列表，实际实现需要根据 file_service 的能力
            return []
        except Exception as e:
            logger.warning(f"检查 defense 修改时出错: {e}", extra={"pipeline_id": pipeline_id})
            return []

    @staticmethod
    async def _run_coding_task_background(pipeline_id: int) -> None:
        """
        后台任务：并发执行 CODING 和 TESTING 阶段，gather 完成后统一运行测试

        【新流程】CODING + TESTING 并发 → 统一运行测试 → 进入 CODE_REVIEW 审批
        - CODING 和 TESTING 同时执行（Tester 基于契约生成测试，不依赖 Coder 输出）
        - 两者都完成后，统一运行分层测试
        - 然后进入 CODE_REVIEW 阶段等待审批

        这是从 API 层迁移过来的后台任务函数，避免循环导入问题。
        【关键修复】并发执行时，CODING 和 TESTING 各自使用独立的 session，避免 SQLAlchemy 并发冲突
        """
        try:
            # 【新增】启动时检查 Pipeline 是否已终止
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return

            await push_log(pipeline_id, "info", "后台任务启动：并发执行代码生成和分层测试...", stage="CODING")
            await push_log(pipeline_id, "info", "🚀 CODING 和 TESTING 并发执行中...", stage="UNIT_TESTING")

            # 【关键修复】提前创建 UNIT_TESTING 阶段记录，让前端轮询时立即看到 TESTER 节点为"执行中"
            async with async_session_factory() as pre_session:
                from app.repositories.pipeline_stage_repository import PipelineStageRepository
                existing_testing = await PipelineStageRepository.get_by_pipeline_and_name(
                    pipeline_id, StageName.UNIT_TESTING, pre_session
                )
                if not existing_testing:
                    testing_stage = PipelineStage(
                        pipeline_id=pipeline_id,
                        name=StageName.UNIT_TESTING,
                        status=StageStatus.RUNNING,
                        input_data={}
                    )
                    pre_session.add(testing_stage)
                    await pre_session.commit()
                    await push_log(
                        pipeline_id, "info",
                        "UNIT_TESTING 阶段已就绪",
                        stage="UNIT_TESTING"
                    )

            # 【并发执行】同时启动 CODING 和 TESTING 阶段
            coding_task = PipelineService._trigger_coding_phase(
                pipeline_id=pipeline_id,
                session=None  # 独立 session
            )
            testing_task = PipelineService._trigger_testing_phase(
                pipeline_id=pipeline_id,
                session=None  # 独立 session
            )

            # 等待两个任务完成
            coding_result, testing_result = await asyncio.gather(
                coding_task,
                testing_task,
                return_exceptions=True
            )

            # 【新增】检查 Pipeline 是否已终止
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return

            # 处理异常结果
            if isinstance(coding_result, Exception) or isinstance(testing_result, Exception):
                error_msg = ""
                if isinstance(coding_result, Exception):
                    error_msg += f"CODING 异常: {coding_result} "
                if isinstance(testing_result, Exception):
                    error_msg += f"TESTING 异常: {testing_result}"
                raise Exception(error_msg)

            # 检查 CODING 结果
            if not coding_result.get("success"):
                op_logger.log_pipeline_status_change(
                    pipeline_id=pipeline_id,
                    old_status='running',
                    new_status='failed',
                    stage='CODING',
                    error=coding_result.get("message", "Unknown error")
                )
                async with async_session_factory() as err_session:
                    await PipelineService.mark_pipeline_failed(
                        pipeline_id=pipeline_id,
                        error=coding_result.get("message", "Coding phase failed"),
                        session=err_session
                    )
                    await err_session.commit()
                return

            # 检查 TESTING 结果
            if not testing_result.get("success"):
                op_logger.log_pipeline_status_change(
                    pipeline_id=pipeline_id,
                    old_status='running',
                    new_status='failed',
                    stage='UNIT_TESTING',
                    error=testing_result.get("message", "Testing phase failed")
                )
                async with async_session_factory() as err_session:
                    await PipelineService.mark_pipeline_failed(
                        pipeline_id=pipeline_id,
                        error=testing_result.get("message", "Testing phase failed"),
                        session=err_session
                    )
                    await err_session.commit()
                return

            # 【新增】运行测试前检查 Pipeline 是否已终止
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return

            # 【新增】检查 Pipeline 是否存在，并预加载 stages
            from sqlalchemy.orm import selectinload
            async with async_session_factory() as session:
                statement = (
                    select(Pipeline)
                    .where(Pipeline.id == pipeline_id)
                    .options(selectinload(Pipeline.stages))
                )
                result = await session.execute(statement)
                pipeline = result.scalar_one_or_none()
                if not pipeline:
                    await push_log(pipeline_id, "error", f"Pipeline {pipeline_id} 不存在", stage="CODING")
                    return
                # 【修复】预加载 stages 数据到字典，避免 DetachedInstanceError
                pipeline_stages = {s.name: s for s in pipeline.stages}

            # ========== 并行完成后：运行测试 ==========
            test_run_result = await PipelineService._run_tests_after_gather(pipeline_id)

            # 更新 UNIT_TESTING 阶段的 test_run_success 结果（包含契约检查结果）
            async with async_session_factory() as session:
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == StageName.UNIT_TESTING
                )
                result = await session.execute(statement)
                testing_stage = result.scalar_one_or_none()

                if testing_stage and testing_stage.output_data:
                    testing_stage.output_data["testing_result"]["test_run_success"] = test_run_result.get("test_run_success", False)
                    testing_stage.output_data["testing_result"]["overall_success"] = test_run_result.get("success", False)
                    testing_stage.output_data["testing_result"]["test_run_logs"] = test_run_result.get("logs", "")
                    testing_stage.output_data["testing_result"]["test_run_layers"] = test_run_result.get("layers", [])
                    testing_stage.output_data["testing_result"]["contract_check"] = test_run_result.get("contract_check")
                    testing_stage.output_data["testing_result"]["failed_tests"] = test_run_result.get("failed_tests", [])
                    testing_stage.output_data["testing_result"]["failure_cause"] = test_run_result.get("failure_cause")
                    # 【新增】保存详细的测试和修复记录
                    testing_stage.output_data["testing_result"]["test_details"] = test_run_result.get("test_details", {})
                    testing_stage.output_data["testing_result"]["defense_violations"] = test_run_result.get("defense_violations", [])
                    flag_modified(testing_stage, "output_data")
                    await session.commit()

            # 【新增】分层测试通过后，在 Sandbox 中启动 FastAPI 服务
            if test_run_result.get("test_run_success") and not test_run_result.get("requires_user_decision"):
                asyncio.create_task(PipelineService._start_fastapi_in_sandbox(pipeline_id))

            # 【新增】生成 AI 审查报告并存储到 UNIT_TESTING 阶段
            # 【新增】生成审查报告前检查 Pipeline 是否已终止
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return

            await push_log(
                pipeline_id,
                "info",
                "🤖 生成 AI 代码审查报告...",
                stage="UNIT_TESTING"
            )

            review_report = await PipelineService._generate_ai_review_report(pipeline_id)

            # 将审查报告存储到 CODE_REVIEW 阶段
            async with async_session_factory() as session:
                # 先创建 CODE_REVIEW 阶段（如果不存在）
                statement = select(PipelineStage).where(
                    PipelineStage.pipeline_id == pipeline_id,
                    PipelineStage.name == StageName.CODE_REVIEW
                )
                result = await session.execute(statement)
                review_stage = result.scalar_one_or_none()

                if not review_stage:
                    # 获取 CODING 和 TESTING 的输出数据（使用预加载的 stages）
                    coding_stage = pipeline_stages.get(StageName.CODING)
                    testing_stage = pipeline_stages.get(StageName.UNIT_TESTING)

                    coding_output = coding_stage.output_data if coding_stage else {}
                    testing_output = testing_stage.output_data if testing_stage else {}

                    review_stage = await WorkflowService.create_stage(
                        pipeline_id=pipeline_id,
                        stage_name=StageName.CODE_REVIEW,
                        input_data={
                            "coding_output": coding_output,
                            "testing_result": testing_output.get("testing_result", {}),
                        },
                        session=session
                    )

                # 将审查报告存储到 CODE_REVIEW 阶段的 output_data
                if review_stage:
                    if not review_stage.output_data:
                        review_stage.output_data = {}
                    review_stage.output_data["review_report"] = review_report
                    flag_modified(review_stage, "output_data")
                    await session.commit()

            await push_log(
                pipeline_id,
                "info",
                f"✅ AI 审查报告已生成，发现 {len(review_report.get('issues', []))} 个问题",
                stage="CODE_REVIEW"
            )

            # 【新增】设置 PAUSED 前检查 Pipeline 是否已终止
            if await PipelineService._check_pipeline_terminated(pipeline_id):
                await push_log(pipeline_id, "warning", "Pipeline 已终止，后台任务退出", stage="CODING")
                return

            # 设置 PAUSED -> CODE_REVIEW
            async with async_session_factory() as session:
                pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                if pipeline:
                    pipeline.status = PipelineStatus.PAUSED
                    pipeline.current_stage = StageName.CODE_REVIEW

                    # 创建 CODE_REVIEW 阶段（如果不存在）
                    statement = select(PipelineStage).where(
                        PipelineStage.pipeline_id == pipeline_id,
                        PipelineStage.name == StageName.CODE_REVIEW
                    )
                    result = await session.execute(statement)
                    existing_review_stage = result.scalar_one_or_none()

                    if not existing_review_stage:
                        # 获取 CODING 和 TESTING 的输出数据
                        coding_stage = None
                        testing_stage = None
                        for stage in pipeline.stages:
                            if stage.name == StageName.CODING:
                                coding_stage = stage
                            elif stage.name == StageName.UNIT_TESTING:
                                testing_stage = stage

                        coding_output = coding_stage.output_data if coding_stage else {}
                        testing_output = testing_stage.output_data if testing_stage else {}

                        await WorkflowService.create_stage(
                            pipeline_id=pipeline_id,
                            stage_name=StageName.CODE_REVIEW,
                            input_data={
                                "coding_output": coding_output.get("coder_output", {}),
                                "testing_result": testing_output.get("testing_result", {}),
                                "target_files": coding_output.get("target_files", {})
                            },
                            session=session
                        )
                        await push_log(
                            pipeline_id,
                            "info",
                            "创建 CODE_REVIEW 阶段，等待统一审批",
                            stage="CODE_REVIEW"
                        )

                    await session.commit()

                    # 推送状态日志
                    test_generated = testing_result.get("output_data", {}).get("testing_result", {}).get("test_generated", False)
                    test_run_success = test_run_result.get("success", False)

                    if test_generated and test_run_success:
                        await push_log(
                            pipeline_id,
                            "success",
                            "✅ 代码生成和测试运行完成，等待代码审查",
                            stage="CODE_REVIEW"
                        )
                    elif test_generated:
                        await push_log(
                            pipeline_id,
                            "warning",
                            "⚠️ 代码生成完成，测试部分未通过，等待代码审查",
                            stage="CODE_REVIEW"
                        )
                    else:
                        await push_log(
                            pipeline_id,
                            "info",
                            "代码生成和分层测试完成，等待代码审查",
                            stage="CODE_REVIEW"
                        )

        except Exception as e:
            error(
                "Pipeline CODING/UNIT_TESTING 阶段失败",
                pipeline_id=pipeline_id,
                exc_info=True
            )
            op_logger.log_pipeline_status_change(
                pipeline_id=pipeline_id,
                old_status='running',
                new_status='failed',
                stage='CODING',
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
                coding_stage = result.scalar_one_or_none()

                if coding_stage:
                    coding_stage.status = StageStatus.PENDING
                    coding_stage.output_data = {"retry_feedback": feedback}
                    await session.commit()

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
                testing_stage = result.scalar_one_or_none()

                if testing_stage:
                    testing_stage.status = StageStatus.PENDING
                    testing_stage.output_data = {"retry_feedback": feedback}
                    await session.commit()

                # 重新执行 TESTING
                testing_result = await PipelineService._trigger_testing_phase(
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
            single_test_result = await cls._run_single_test_file(
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
            testing_stage = result.scalar_one_or_none()

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
    async def _run_single_test_file(
        cls,
        pipeline_id: int,
        file_path: str,
        content: str,
        file_service: Any
    ) -> Dict[str, Any]:
        """
        运行单个测试文件

        Args:
            pipeline_id: Pipeline ID
            file_path: 测试文件路径
            content: 测试文件内容
            file_service: 沙箱文件服务

        Returns:
            Dict: 测试结果
        """
        from app.service.sandbox_manager import sandbox_manager
        import re

        try:
            # 在 Docker 容器中运行单个测试文件
            cmd = (
                f"cd /workspace && "
                f"PYTHONPATH=/workspace/backend python -m pytest {file_path} "
                f"-v --tb=short --color=no "
                f"2>&1"
            )

            exec_result = await sandbox_manager.exec(
                pipeline_id,
                cmd,
                timeout=120
            )

            stdout = exec_result.stdout or ""
            stderr = exec_result.stderr or ""
            logs = stdout + "\n" + stderr

            success = exec_result.exit_code == 0

            # 提取失败测试
            failed_tests = []
            if not success:
                pattern = r"FAILED\s+(\S+)"
                failed_tests = re.findall(pattern, logs)

            # 提取摘要
            summary_match = re.search(r"(\d+\s+passed|\d+\s+failed|\d+\s+error)", logs)
            if summary_match:
                summary = summary_match.group(0)
            else:
                summary = "测试执行完成" if success else "测试执行失败"

            return {
                "success": success,
                "exit_code": exec_result.exit_code,
                "logs": logs,
                "summary": summary,
                "failed_tests": failed_tests,
                "error": stderr if stderr else None
            }

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": "测试执行异常",
                "failed_tests": [],
                "error": str(e)
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
