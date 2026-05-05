"""
Pipeline 业务服务（重构版）
业务逻辑层 - 使用 StageHandler 策略模式协调 Pipeline 各阶段

【优化】引入阶段处理器（Stage Handler）策略：
- PipelineService 只负责调度
- 各阶段逻辑分散到独立的 Handler 类中
- 新增阶段只需添加 Handler，无需修改 PipelineService
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.logging import info, op_logger, error
from app.core.config import settings
from app.core.sse_log_buffer import push_log, remove_buffer
from app.core.database import async_session_factory
from app.models.pipeline import (
    Pipeline, PipelineRead, PipelineStatus,
    PipelineStage, StageName, StageStatus, PipelineStageRead
)
from app.repositories import PipelineRepository
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
    async def start_sandbox_for_pipeline(
        cls,
        pipeline_id: int
    ) -> None:
        """
        为 Pipeline 启动 Docker Sandbox（在事务提交后调用）
        
        注意：此方法应在事务提交后调用，避免长时间占用数据库连接
        """
        try:
            project_path = str(Path(settings.TARGET_PROJECT_PATH).resolve())
            sandbox_info = await sandbox_manager.start(pipeline_id, project_path)
            info("Docker Sandbox 启动成功", 
                 pipeline_id=pipeline_id, 
                 container_id=sandbox_info.container_id[:12],
                 port=sandbox_info.port)
        except Exception as e:
            error_msg = f"Docker Sandbox 启动失败: {str(e)}"
            info(error_msg, pipeline_id=pipeline_id)
            # 不阻断流程，后续阶段可以尝试重新启动 Sandbox
    
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

        # 处理 DESIGN 阶段的特殊情况（需要后台任务执行 CODING）
        if current_stage == StageName.DESIGN and background_tasks:
            if result.output_data.get("requires_background_task"):
                background_tasks.add_task(cls._run_coding_task_background, pipeline_id)

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
                background_tasks.add_task(cls._retry_testing_only, pipeline_id, feedback)

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
                background_tasks.add_task(cls._retry_coding_only, pipeline_id, feedback)

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
                # 先重试 CODING，完成后会自动重试 TESTING
                background_tasks.add_task(cls._retry_coding_only, pipeline_id, feedback)

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
            try:
                await sandbox_manager.stop(pipeline_id)
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
                background_tasks.add_task(cls._run_coding_task_background, pipeline_id)
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
                    background_tasks.add_task(
                        cls._run_architect_task_background,
                        pipeline_id,
                        requirement,
                        element_context
                    )
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
                    background_tasks.add_task(
                        cls._run_stage_background,
                        pipeline_id,
                        current_stage.value
                    )
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

    @staticmethod
    async def _cleanup_pipeline_resources(pipeline_id: int, reason: str) -> None:
        """后台任务：清理 Pipeline 资源（Sandbox、日志缓冲区等）"""
        # 停止 Sandbox（使用快速停止）
        try:
            await sandbox_manager.stop(pipeline_id, fast=True)
            info("Sandbox 已停止", pipeline_id=pipeline_id)
        except Exception as e:
            info(f"停止 Sandbox 时出错（非关键）: {str(e)}", pipeline_id=pipeline_id)

        # 清理 SSE 日志缓冲区
        remove_buffer(pipeline_id)

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
    async def _run_coding_task_background(pipeline_id: int) -> None:
        """
        后台任务：并发执行 CODING 和 TESTING 阶段，完成后统一等待审批

        【新流程】CODING + TESTING 并发 → 统一审批
        - CODING 和 TESTING 同时执行
        - 两者都完成后，统一进入 CODE_REVIEW 阶段等待审批
        - 可以分别拒绝 CODING 或 TESTING，各自重写

        这是从 API 层迁移过来的后台任务函数，避免循环导入问题。
        【修复】使用 async with 上下文管理器确保 session 正确关闭
        """
        async with async_session_factory() as session:
            try:
                await push_log(pipeline_id, "info", "后台任务启动：并发执行代码生成和单元测试...", stage="CODING")
                await push_log(pipeline_id, "info", "🚀 CODING 和 TESTING 并发执行中...", stage="UNIT_TESTING")

                # 【并发执行】同时启动 CODING 和 TESTING 阶段
                coding_task = PipelineService.trigger_coding_phase(
                    pipeline_id=pipeline_id,
                    session=session
                )
                testing_task = PipelineService._trigger_testing_phase(
                    pipeline_id=pipeline_id,
                    session=session
                )

                # 等待两个任务完成
                coding_result, testing_result = await asyncio.gather(
                    coding_task,
                    testing_task,
                    return_exceptions=True
                )

                # 处理异常结果
                if isinstance(coding_result, Exception):
                    raise coding_result
                if isinstance(testing_result, Exception):
                    raise testing_result

                # 检查 CODING 结果
                if not coding_result.get("success"):
                    await session.rollback()
                    op_logger.log_pipeline_status_change(
                        pipeline_id=pipeline_id,
                        old_status='running',
                        new_status='failed',
                        stage='CODING',
                        error=coding_result.get("message", "Unknown error")
                    )
                    # 更新 pipeline 状态为 failed
                    try:
                        async with async_session_factory() as err_session:
                            await PipelineService.mark_pipeline_failed(
                                pipeline_id=pipeline_id,
                                error=coding_result.get("message", "Coding phase failed"),
                                session=err_session
                            )
                            await err_session.commit()
                    except Exception:
                        pass
                    return

                # CODING 成功，提交事务
                await session.commit()

                # 检查 TESTING 结果
                test_generated = False
                test_run_success = False
                if testing_result.get("success"):
                    test_generated = testing_result.get("test_generated", False)
                    test_run_success = testing_result.get("test_run_success", False)

                # 【关键】将 Pipeline 状态设为 paused，当前阶段设为 CODE_REVIEW，等待统一审批
                try:
                    pipeline = await PipelineRepository.get_by_id(pipeline_id, session)
                    if pipeline:
                        pipeline.status = PipelineStatus.PAUSED
                        pipeline.current_stage = StageName.CODE_REVIEW

                        # 【新流程】检查并创建 CODE_REVIEW 阶段（如果不存在）
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

                        await push_log(
                            pipeline_id,
                            "info",
                            "⏸️ 代码生成和单元测试完成，等待统一审批",
                            stage="CODE_REVIEW"
                        )
                except Exception as e:
                    error(f"[Pipeline {pipeline_id}] 设置暂停状态失败: {e}")

                # 推送状态日志
                if test_generated and test_run_success:
                    await push_log(
                        pipeline_id,
                        "success",
                        "✅ 代码生成和单元测试完成，等待代码审查",
                        stage="CODE_REVIEW"
                    )
                elif test_generated:
                    await push_log(
                        pipeline_id,
                        "warning",
                        "⚠️ 代码生成完成，单元测试部分未通过，等待代码审查",
                        stage="CODE_REVIEW"
                    )
                else:
                    await push_log(
                        pipeline_id,
                        "info",
                        "代码生成和单元测试完成，等待代码审查",
                        stage="CODE_REVIEW"
                    )

            except Exception as e:
                await session.rollback()
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
                # 更新 pipeline 状态为 failed
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

        这是从 API 层迁移过来的后台任务函数，避免循环导入问题。
        【修复】使用 async with 上下文管理器确保 session 正确关闭
        """
        async with async_session_factory() as session:
            try:
                await PipelineService.run_architect_task(
                    pipeline_id=pipeline_id,
                    requirement=requirement,
                    element_context=element_context,
                    session=session
                )
                # 显式提交
                await session.commit()
            except Exception as e:
                await session.rollback()
                # 记录结构化日志，同时记录完整堆栈
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
                # 更新 pipeline 状态为 failed，让前端感知
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
            # 3. 写入用户修改的测试代码
            await file_service.write_file(file_path, content)
            await push_log(
                pipeline_id,
                "info",
                f"✅ 测试文件已更新: {file_path}",
                stage="UNIT_TESTING"
            )

            # 4. 获取测试文件列表（用于重跑测试）
            test_files = [{"file_path": file_path, "content": content}]

            # 5. 重新运行测试
            await push_log(
                pipeline_id,
                "info",
                "🔄 正在重新运行测试...",
                stage="UNIT_TESTING"
            )

            layered_result = await LayeredTestRunner.run(
                workspace_path="/workspace",
                new_files=test_files,
                sandbox_port=None,
                timeout=120,
                file_service=file_service
            )

            # 6. 更新 UNIT_TESTING 阶段的输出数据
            statement = select(PipelineStage).where(
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.name == StageName.UNIT_TESTING
            )
            result = await session.execute(statement)
            testing_stage = result.scalar_one_or_none()

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
                    "test_run_success": layered_result.all_passed,
                    "test_generated": True,
                    "user_overridden": True,
                    "override_file": file_path
                }

                # 标记修改
                flag_modified(testing_stage, "output_data")
                await session.commit()

            # 7. 推送测试结果日志
            if layered_result.all_passed:
                await push_log(
                    pipeline_id,
                    "success",
                    "✅ 用户修改后的测试全部通过！",
                    stage="UNIT_TESTING"
                )
            else:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"⚠️ 测试未通过: {layered_result.failure_cause or 'Unknown error'}",
                    stage="UNIT_TESTING"
                )
                for failed_test in layered_result.failed_tests:
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
                    "test_run_success": layered_result.all_passed,
                    "message": "测试全部通过" if layered_result.all_passed else f"测试未通过: {layered_result.failure_cause}",
                    "failed_tests": layered_result.failed_tests,
                    "layers": [
                        {
                            "layer": layer.layer,
                            "passed": layer.passed,
                            "summary": layer.summary
                        }
                        for layer in layered_result.layers
                    ]
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
