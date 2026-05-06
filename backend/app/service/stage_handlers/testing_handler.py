"""
Layered Testing Stage Handler

Handles UNIT_TESTING stage:
- Generate test code via TestAgent (based on design contract)
- Test execution moved to _run_coding_task_background after gather
"""

from typing import Optional

from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, StageStatus, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService

import logging
logger = logging.getLogger(__name__)


class TestingHandler(StageHandler):
    """Layered Testing Stage Handler"""

    @property
    def stage_name(self) -> StageName:
        return StageName.UNIT_TESTING

    async def prepare(self, context: StageContext) -> StageContext:
        """Prepare stage: get DESIGN stage output only (no waiting for CODING)"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 仅查询 DESIGN 阶段
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DESIGN
        )
        result = await context.session.execute(stmt)
        design_stage = result.scalar_one_or_none()
        if not design_stage or not design_stage.output_data:
            raise ValueError("No design output found for UNIT_TESTING stage")
        design_output = design_stage.output_data

        # 创建或更新 UNIT_TESTING 阶段（不再从 CODING 传 input）
        stmt = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(stmt)
        testing_stage = result.scalar_one_or_none()

        if not testing_stage:
            testing_stage = await WorkflowService.create_stage(
                pipeline_id=context.pipeline_id,
                stage_name=self.stage_name,
                input_data={"design_output": design_output},
                session=context.session
            )
        else:
            testing_stage.input_data = {"design_output": design_output}
            testing_stage.status = StageStatus.RUNNING
            context.session.add(testing_stage)

        context.input_data["design_output"] = design_output
        context.stage_id = testing_stage.id
        await context.session.commit()
        return context

    async def execute(self, context: StageContext) -> StageResult:
        """Execute layered test generation only (no test running - moved to gather completion)"""
        pipeline_id = context.pipeline_id
        design_output = context.input_data.get("design_output", {})

        from app.agents import test_agent
        from app.service.sandbox_file_service import get_sandbox_file_service

        file_service = get_sandbox_file_service(pipeline_id)

        await push_log(pipeline_id, "info", "开始生成分层测试（基于设计契约）...", stage="UNIT_TESTING")
        test_result = await test_agent.generate_tests(
            design_output=design_output,
            code_output=None,          # 不传 Coder 数据，完全凭契约生成
            pipeline_id=pipeline_id,
        )

        if not test_result.get("success"):
            return StageResult.failure_result(
                message=f"测试生成失败: {test_result.get('error', '')}"
            )

        test_files = test_result["output"].get("test_files", [])
        # 写入沙箱
        for tf in test_files:
            file_path = tf.get("file_path", "")
            content = tf.get("content", "")
            if file_path and content:
                await file_service.write_file(file_path, content)

        # 【修复】传递执行指标到 StageResult
        metrics = {
            "input_tokens": test_result.get("input_tokens", 0),
            "output_tokens": test_result.get("output_tokens", 0),
            "duration_ms": test_result.get("duration_ms", 0),
        }

        return StageResult.success_result(
            message="测试文件生成成功（待代码生成后运行）",
            output_data={
                "testing_result": {
                    "test_generated": True,
                    "test_run_success": False,  # 稍后运行
                    "test_files": test_files,
                }
            },
            metrics=metrics,
        )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """Complete stage: save results only (PAUSED state set by _run_coding_task_background after gather)"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        testing_stage = query_result.scalar_one_or_none()

        if testing_stage:
            testing_data = result.output_data.get("testing_result", {})
            await WorkflowService.complete_stage(
                stage=testing_stage,
                output_data=result.output_data,
                success=testing_data.get("success", True),
                session=context.session,
                metrics=result.metrics
            )

        # 只保存阶段数据，不设置 PAUSED（由 _run_coding_task_background 统一处理）
        await push_log(
            context.pipeline_id,
            "info",
            "测试生成阶段完成",
            stage="UNIT_TESTING"
        )
        await context.session.commit()

    async def handle_error(
        self,
        context: StageContext,
        error: Exception
    ) -> StageResult:
        """Error handling"""
        await push_log(
            context.pipeline_id,
            "error",
            f"Layered testing stage error: {str(error)}",
            stage="UNIT_TESTING"
        )
        return StageResult.failure_result(
            message=f"Layered testing failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """UNIT_TESTING stage approved: enter CODE_REVIEW stage"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        await push_log(
            context.pipeline_id,
            "info",
            "Layered testing approved, entering code review...",
            stage="UNIT_TESTING"
        )

        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.UNIT_TESTING
        )
        result = await context.session.execute(statement)
        testing_stage = result.scalar_one_or_none()

        testing_result = {}
        if testing_stage and testing_stage.output_data:
            testing_result = testing_stage.output_data.get("testing_result", {})

        coding_output = testing_stage.output_data.get("coding_output", {}) if testing_stage else {}
        target_files = testing_stage.output_data.get("target_files", {}) if testing_stage else {}

        await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODE_REVIEW,
            input_data={
                "coding_output": coding_output,
                "testing_result": testing_result,
                "target_files": target_files
            },
            session=context.session
        )

        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.CODE_REVIEW
            await WorkflowService.set_pipeline_paused(pipeline, context.session)

        await context.session.commit()

        return StageResult.success_result(
            message="Layered testing approved, proceeding to code review",
            output_data={
                "previous_stage": StageName.UNIT_TESTING.value,
                "next_stage": StageName.CODE_REVIEW.value,
                "test_generated": testing_result.get("test_generated", False),
                "test_run_success": testing_result.get("test_run_success", False)
            },
            status=PipelineStatus.PAUSED
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """UNIT_TESTING stage rejected: rollback to CODING to regenerate code and tests"""
        from app.service.stage_handlers import CodingHandler

        await push_log(
            context.pipeline_id,
            "info",
            f"Layered testing rejected, reason: {reason}, rolling back to code generation...",
            stage="UNIT_TESTING"
        )

        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.CODING,
            rejection_feedback=rejection_feedback,
            session=context.session
        )

        coding_handler = CodingHandler()
        coding_context = StageContext(
            pipeline_id=context.pipeline_id,
            session=context.session,
            input_data={},
            rejection_feedback=rejection_feedback
        )

        coding_result = await coding_handler.run(coding_context)

        if coding_result.success:
            testing_result = await self.run(StageContext(
                pipeline_id=context.pipeline_id,
                session=context.session,
                input_data={}
            ))

            return StageResult(
                success=testing_result.success,
                status=testing_result.status,
                message="Coding and layered testing re-executed",
                output_data={
                    "previous_stage": StageName.UNIT_TESTING.value,
                    "current_stage": StageName.UNIT_TESTING.value,
                    "test_generated": testing_result.output_data.get("testing_result", {}).get("test_generated", False),
                    "test_run_success": testing_result.output_data.get("testing_result", {}).get("test_run_success", False)
                }
            )
        else:
            return StageResult.failure_result(
                message="Code generation failed after rejection",
                output_data={
                    "previous_stage": StageName.UNIT_TESTING.value,
                    "current_stage": StageName.CODING.value,
                    "error": coding_result.message
                }
            )
