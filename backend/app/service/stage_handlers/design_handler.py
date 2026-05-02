"""
技术设计阶段处理器（简化版）

与测试脚本 test_e2e_with_contract_v2.py 保持一致：
- 直接调用 designer_agent.design()
- 只保留审批阶段的功能
"""

import logging
from typing import Optional

from app.core.logging import info, error
from app.core.sse_log_buffer import push_log
from app.agents.designer import designer_agent

logger = logging.getLogger(__name__)
from app.models.pipeline import StageName, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class DesignHandler(StageHandler):
    """技术设计阶段处理器（简化版）"""

    @property
    def stage_name(self) -> StageName:
        return StageName.DESIGN

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 REQUIREMENT 阶段输出"""
        from app.repositories import PipelineStageRepository

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

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行技术设计（简化版，与测试脚本一致）"""
        pipeline_id = context.pipeline_id

        await push_log(pipeline_id, "info", "开始技术设计...", stage="DESIGN")

        # 获取 REQUIREMENT 阶段的输出
        arch_output = context.previous_output

        try:
            # 【简化】直接调用 designer_agent.design()，与测试脚本一致
            # 不通过 AgentCoordinatorService，不获取代码上下文（RAG 已禁用）
            design_result = await designer_agent.design(
                architect_output=arch_output,
                file_tree={},  # 空字典，与测试脚本一致
                related_code_context="",  # 空字符串，与测试脚本一致
                full_files_context=arch_output.get("injected_files", {}),  # 与测试脚本一致
                pipeline_id=pipeline_id
            )

            if not design_result.get("success"):
                error_msg = design_result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"技术设计失败: {error_msg}", stage="DESIGN")
                return StageResult.failure_result(
                    message=f"Technical design failed: {error_msg}",
                    output_data={"error": error_msg}
                )

            design_output = design_result.get("output", {})
            interface_specs = design_output.get("interface_specs", [])

            await push_log(
                pipeline_id,
                "info",
                f"技术设计完成，接口契约 ({len(interface_specs)} 项)",
                stage="DESIGN"
            )
            await push_log(pipeline_id, "info", "技术设计完成，等待审批", stage="DESIGN")

            # 返回成功，状态为 PAUSED（等待审批）
            return StageResult.success_result(
                message="Technical design completed",
                output_data=design_output,
                status=PipelineStatus.PAUSED
            )

        except Exception as e:
            error_msg = str(e)
            error("Designer analysis failed", pipeline_id=pipeline_id, error=error_msg, exc_info=True)
            await push_log(pipeline_id, "error", f"技术设计失败: {error_msg[:500]}", stage="DESIGN")
            raise

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存 Stage 输出并更新 Pipeline 状态"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 【关键修复】保存 Stage 的 output_data
        if context.stage_id:
            statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
            query_result = await context.session.execute(statement)
            stage = query_result.scalar_one_or_none()
            if stage:
                stage.output_data = result.output_data
                stage.status = PipelineStatus.SUCCESS if result.success else PipelineStatus.FAILED
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
