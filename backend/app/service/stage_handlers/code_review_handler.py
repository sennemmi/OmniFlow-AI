"""
代码审查阶段处理器

处理 CODE_REVIEW 阶段：
- 纯人工审批阶段，无自动执行逻辑
- 批准后触发 DELIVERY 阶段
- 驳回后回退到 CODING 阶段
"""

from typing import Optional

from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class CodeReviewHandler(StageHandler):
    """代码审查阶段处理器"""

    @property
    def stage_name(self) -> StageName:
        return StageName.CODE_REVIEW

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 UNIT_TESTING 阶段输出"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 获取 UNIT_TESTING 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(statement)
        testing_stage = result.scalar_one_or_none()

        if testing_stage and testing_stage.output_data:
            context.input_data["testing_result"] = testing_stage.output_data.get("testing_result", {})
            context.input_data["coding_output"] = testing_stage.output_data.get("coding_output", {})
            context.input_data["target_files"] = testing_stage.output_data.get("target_files", {})

        # 获取或创建 CODE_REVIEW 阶段
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODE_REVIEW
        )
        result = await context.session.execute(statement)
        review_stage = result.scalar_one_or_none()

        if not review_stage:
            review_stage = await WorkflowService.create_stage(
                pipeline_id=context.pipeline_id,
                stage_name=self.stage_name,
                input_data=context.input_data,
                session=context.session
            )

        context.stage_id = review_stage.id
        await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行代码审查阶段（纯人工审批，无需自动执行）"""
        await push_log(
            context.pipeline_id,
            "info",
            "代码审查阶段已准备就绪，等待人工审批...",
            stage="CODE_REVIEW"
        )

        # 此阶段为纯人工审批，无需自动执行
        return StageResult.success_result(
            message="Code review stage ready for approval",
            output_data={
                "testing_result": context.input_data.get("testing_result", {}),
                "coding_output": context.input_data.get("coding_output", {}),
                "target_files": context.input_data.get("target_files", {})
            },
            status=PipelineStatus.PAUSED
        )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：更新阶段状态"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        review_stage = query_result.scalar_one_or_none()

        if review_stage:
            await WorkflowService.complete_stage(
                stage=review_stage,
                output_data=result.output_data,
                success=result.success,
                session=context.session
            )

        await context.session.commit()

    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """错误处理"""
        await push_log(
            context.pipeline_id,
            "error",
            f"代码审查阶段异常: {str(error)}",
            stage="CODE_REVIEW"
        )
        return StageResult.failure_result(
            message=f"Code review failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """
        CODE_REVIEW 阶段被批准后：触发 DELIVERY 阶段
        """
        from app.service.stage_handlers import DeliveryHandler

        await push_log(
            context.pipeline_id,
            "info",
            "代码审查已批准，开始代码交付...",
            stage="CODE_REVIEW"
        )

        # 执行 DELIVERY 阶段
        delivery_handler = DeliveryHandler()
        delivery_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={}
        )

        delivery_result = await delivery_handler.run(delivery_context)

        return StageResult(
            success=delivery_result.success,
            status=delivery_result.status,
            message=delivery_result.message,
            output_data={
                "previous_stage": StageName.CODE_REVIEW.value,
                "next_stage": StageName.DELIVERY.value,
                "delivery_result": delivery_result.output_data
            },
            git_branch=delivery_result.git_branch,
            commit_hash=delivery_result.commit_hash,
            pr_url=delivery_result.pr_url
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """
        CODE_REVIEW 阶段被驳回后：回退到 CODING 重新生成
        """
        from app.service.stage_handlers import CodingHandler, TestingHandler

        await push_log(
            context.pipeline_id,
            "info",
            f"代码审查被驳回，原因: {reason}，回退到代码生成阶段...",
            stage="CODE_REVIEW"
        )

        # 标记 CODING 阶段需要重新执行
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODING,
            rejection_feedback=rejection_feedback,
            session=context.session
        )

        # 重新触发 CODING 阶段
        coding_handler = CodingHandler()
        coding_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        )

        coding_result = await coding_handler.run(coding_context)

        if coding_result.success:
            # CODING 成功后，执行 TESTING
            testing_handler = TestingHandler()
            testing_result = await testing_handler.run(StageContext(
                pipeline_id=context.pipeline_id,
                session=context.session,
                input_data={}
            ))

            return StageResult(
                success=testing_result.success,
                status=testing_result.status,
                message="Coding and unit testing re-executed after rejection",
                output_data={
                    "previous_stage": StageName.CODE_REVIEW.value,
                    "current_stage": StageName.UNIT_TESTING.value,
                    "test_generated": testing_result.output_data.get("testing_result", {}).get("test_generated", False),
                    "test_run_success": testing_result.output_data.get("testing_result", {}).get("test_run_success", False)
                }
            )
        else:
            return StageResult.failure_result(
                message="Code generation failed after rejection",
                output_data={
                    "previous_stage": StageName.CODE_REVIEW.value,
                    "current_stage": StageName.CODING.value,
                    "error": coding_result.message
                }
            )
