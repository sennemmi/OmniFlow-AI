"""
技术设计阶段处理器（使用 AgentCoordinatorService）

使用统一的 AgentCoordinatorService 构建 Agent 上下文
与 E2E 测试脚本保持一致
"""

import logging
from typing import Optional

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.core.contract_validator import ContractValidator
from app.core.contract_alignment import ensure_main_py_in_affected_files
from app.agents.designer import designer_agent
from app.models.pipeline import StageName, PipelineStatus, StageStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.agent_coordinator_service import agent_coordinator_service

logger = logging.getLogger(__name__)


class DesignHandler(StageHandler):
    """技术设计阶段处理器（使用统一服务）"""

    @property
    def stage_name(self) -> StageName:
        return StageName.DESIGN

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 REQUIREMENT 阶段输出"""
        from app.repositories import PipelineStageRepository
        from app.models.pipeline import StageStatus

        # 获取 REQUIREMENT 阶段输出作为输入
        requirement_stage = await PipelineStageRepository.get_by_pipeline_and_name(
            context.pipeline_id, StageName.REQUIREMENT, context.session
        )

        if not requirement_stage or not requirement_stage.output_data:
            raise ValueError("No requirement output found for DESIGN stage")

        context.previous_output = requirement_stage.output_data

        # 创建 DESIGN 阶段记录
        design_stage = await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=self.stage_name,
            input_data=context.previous_output,
            session=context.session
        )
        context.stage_id = design_stage.id

        # 【修复】确保 DESIGN stage 状态为 RUNNING，前端才能显示"执行中"
        # WorkflowService.create_stage 默认创建 RUNNING 状态，但这里再次确认
        if design_stage.status != StageStatus.RUNNING:
            design_stage.status = StageStatus.RUNNING
            await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行技术设计（使用 AgentCoordinatorService）"""
        pipeline_id = context.pipeline_id

        await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")

        # 获取 REQUIREMENT 阶段的输出
        arch_output = context.previous_output

        # 【新增】强制将 main.py 加入 affected_files（当新增 API 路由时）
        arch_output = ensure_main_py_in_affected_files(arch_output)

        # 【新增】重试机制，最大3次
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # 【统一】使用 AgentCoordinatorService 构建上下文
                # 获取需求描述
                requirement = arch_output.get("requirement", "")

                # 构建 DesignerAgent 上下文
                designer_context = await agent_coordinator_service.build_designer_context(
                    requirement=requirement,
                    arch_output=arch_output,
                    pipeline_id=pipeline_id
                )

                await push_log(
                    pipeline_id,
                    "info",
                    f"调用 DesignerAgent (尝试 {attempt + 1}/{max_retries}, injected_files: {len(designer_context.get('injected_files', {}))} files)",
                    stage="DESIGN"
                )

                # 调用 DesignerAgent
                design_result = await designer_agent.design(
                    architect_output=designer_context["arch_output"],
                    related_code_context="",  # 空字符串，与测试脚本一致
                    full_files_context=designer_context["injected_files"],
                    pipeline_id=pipeline_id
                )

                # 保存 Agent 调试信息
                self._save_agent_log(
                    agent_name="DesignerAgent",
                    stage=f"design_attempt_{attempt + 1}",
                    input_data=designer_context,
                    output_data=design_result,
                    system_prompt=designer_agent.system_prompt
                )

                if not design_result.get("success"):
                    error_msg = design_result.get("error", "Unknown error")
                    await push_log(pipeline_id, "warning", f"技术设计失败（尝试 {attempt + 1}/{max_retries}）: {error_msg}", stage="DESIGN")
                    last_error = error_msg
                    if attempt < max_retries - 1:
                        await push_log(pipeline_id, "info", f"等待重试...", stage="DESIGN")
                        import asyncio
                        await asyncio.sleep(1)  # 短暂等待后重试
                        continue
                    else:
                        return StageResult.failure_result(
                            message=f"Technical design failed after {max_retries} attempts: {error_msg}",
                            output_data={"error": error_msg, "attempts": attempt + 1}
                        )

                design_output = design_result.get("output", {})
                interface_specs = design_output.get("interface_specs", [])

                # 【契约校验】校验 interface_specs 的完整性
                contract_errors = ContractValidator.validate_interface_specs(design_output)
                if contract_errors:
                    error_detail = "; ".join(contract_errors)
                    await push_log(pipeline_id, "warning", f"契约校验失败（尝试 {attempt + 1}/{max_retries}）: {error_detail}", stage="DESIGN")
                    last_error = f"Contract validation failed: {error_detail}"
                    if attempt < max_retries - 1:
                        await push_log(pipeline_id, "info", f"契约对齐校验失败，重新生成设计...", stage="DESIGN")
                        import asyncio
                        await asyncio.sleep(1)  # 短暂等待后重试
                        continue
                    else:
                        return StageResult.failure_result(
                            message=f"Contract validation failed after {max_retries} attempts: {error_detail}",
                            output_data={"error": error_detail, "design_output": design_output, "attempts": attempt + 1}
                        )

                await push_log(
                    pipeline_id,
                    "info",
                    f"技术设计完成（尝试 {attempt + 1}/{max_retries}），接口契约 ({len(interface_specs)} 项)",
                    stage="DESIGN"
                )
                await push_log(pipeline_id, "info", "契约校验通过，等待审批", stage="DESIGN")

                # 返回成功，状态为 PAUSED（等待审批）
                return StageResult.success_result(
                    message="Technical design completed",
                    output_data=design_output,
                    status=PipelineStatus.PAUSED,
                    metrics=self._build_metrics(design_result, designer_context, design_output)
                )

            except Exception as e:
                error_msg = str(e)
                error("Designer analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True, attempt=attempt + 1)
                await push_log(pipeline_id, "error", f"技术设计异常（尝试 {attempt + 1}/{max_retries}）: {error_msg[:500]}", stage="DESIGN")
                last_error = error_msg
                if attempt < max_retries - 1:
                    await push_log(pipeline_id, "info", f"等待重试...", stage="DESIGN")
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                else:
                    raise

        # 所有重试都失败
        return StageResult.failure_result(
            message=f"Technical design failed after {max_retries} attempts: {last_error}",
            output_data={"error": last_error, "attempts": max_retries}
        )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存 Stage 输出并更新 Pipeline 状态"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage, PipelineStatus

        # 【关键修复】保存 Stage 的 output_data
        if context.stage_id:
            statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
            query_result = await context.session.execute(statement)
            stage = query_result.scalar_one_or_none()
            if stage:
                stage.output_data = result.output_data
                from app.core.timezone import now
                # 【修复】正确映射 PipelineStatus 到 StageStatus
                # StageStatus 没有 paused，当 Pipeline 是 paused 时，Stage 应该是 SUCCESS（等待审批）
                if result.success:
                    if result.status == PipelineStatus.PAUSED:
                        stage.status = StageStatus.SUCCESS  # 阶段执行成功，等待审批
                    elif result.status == PipelineStatus.SUCCESS:
                        stage.status = StageStatus.SUCCESS
                    elif result.status == PipelineStatus.RUNNING:
                        stage.status = StageStatus.RUNNING
                    else:
                        stage.status = StageStatus.SUCCESS
                else:
                    stage.status = StageStatus.FAILED
                stage.completed_at = now()
                stage.input_tokens = result.metrics.get("input_tokens", 0)
                stage.output_tokens = result.metrics.get("output_tokens", 0)
                stage.duration_ms = result.metrics.get("duration_ms", 0)
                stage.retry_count = result.metrics.get("retry_count", 0)
                stage.reasoning = result.metrics.get("reasoning")
                await context.session.commit()

        # 更新 Pipeline 状态
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )

        if pipeline:
            if result.success:
                await WorkflowService.set_pipeline_paused(pipeline, context.session)
            else:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)

    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """错误处理"""
        await push_log(
            context.pipeline_id,
            "error",
            f"技术设计阶段异常: {str(error)}",
            stage="DESIGN"
        )
        return StageResult.failure_result(
            message=f"Technical design failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        DESIGN 阶段被批准后：触发后台 CODING 任务
        """
        await push_log(
            context.pipeline_id,
            "info",
            "技术设计已批准，代码生成任务将在后台启动...",
            stage="DESIGN"
        )

        # 返回 async=True 信息，由 PipelineService 处理后台任务
        return StageResult.success_result(
            message="代码生成任务已在后台启动，请通过日志监控进度",
            output_data={
                "previous_stage": StageName.DESIGN.value,
                "next_stage": StageName.CODING.value,
                "async": True,
                "requires_background_task": True
            },
            status=PipelineStatus.RUNNING
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        DESIGN 阶段被驳回后：重新执行 DESIGN 阶段
        """
        await push_log(
            context.pipeline_id,
            "info",
            f"技术设计被驳回，原因: {reason}，重新设计...",
            stage="DESIGN"
        )

        # 重新执行当前阶段
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        result = await self.run(StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        ))

        return StageResult(
            success=result.success,
            status=result.status,
            message=result.message,
            output_data={
                "previous_stage": StageName.DESIGN.value,
                "current_stage": StageName.DESIGN.value,
                "feedback": rejection_feedback
            }
        )
