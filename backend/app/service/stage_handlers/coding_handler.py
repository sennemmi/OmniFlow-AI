"""
代码生成阶段处理器（使用 CodeGenerationService 统一服务）

与 E2E 测试脚本保持一致，使用统一的 CodeGenerationService 进行代码生成和修复
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService
from app.service.code_generation_service import code_generation_service
from app.service.sandbox_file_service import get_sandbox_file_service
from app.utils.agent_debug_utils import get_agent_debugger


class CodingHandler(StageHandler):
    """代码生成阶段处理器（使用统一服务）"""

    @property
    def stage_name(self) -> StageName:
        return StageName.CODING

    async def prepare(self, context: StageContext) -> StageContext:
        """准备阶段：获取 DESIGN 阶段输出，创建 CODING 阶段记录"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 获取 DESIGN 阶段输出
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.DESIGN
        )
        result = await context.session.execute(statement)
        design_stage = result.scalar_one_or_none()

        if not design_stage or not design_stage.output_data:
            raise ValueError("No design output found for CODING stage")

        context.previous_output = design_stage.output_data

        # 创建 CODING 阶段
        coding_stage = await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=self.stage_name,
            input_data=design_stage.output_data,
            session=context.session
        )
        context.stage_id = coding_stage.id

        # 提交事务释放连接
        await context.session.commit()

        return context

    async def execute(self, context: StageContext) -> StageResult:
        """执行代码生成（使用 CodeGenerationService）"""
        pipeline_id = context.pipeline_id
        design_output = context.previous_output

        await push_log(pipeline_id, "info", "开始代码生成...", stage="CODING")

        # 获取 REQUIREMENT 阶段的 injected_files
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == StageName.REQUIREMENT
        )
        result = await context.session.execute(statement)
        requirement_stage = result.scalar_one_or_none()

        injected_files = {}
        if requirement_stage and requirement_stage.output_data:
            injected_files = requirement_stage.output_data.get("injected_files", {})

        try:
            await push_log(
                pipeline_id,
                "info",
                "📦 使用 CodeGenerationService 生成代码",
                stage="CODING"
            )

            # 获取文件服务和调试器
            file_service = get_sandbox_file_service(pipeline_id)
            debugger = get_agent_debugger()

            # 【统一】使用 CodeGenerationService 进行代码生成和修复
            result = await code_generation_service.generate_and_fix(
                design_output=design_output,
                injected_files=injected_files,
                pipeline_id=pipeline_id,
                workspace_path=settings.TARGET_PROJECT_PATH,
                file_service=file_service,
                debugger=debugger,
                enable_linting=True,
                enable_contract_check=True,
            )

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"代码生成失败: {error_msg}", stage="CODING")
                return StageResult.failure_result(
                    message=f"Code generation failed: {error_msg}",
                    output_data={"error": error_msg}
                )

            # 获取生成的文件
            code_files = result.get("files", [])
            fix_history = result.get("fix_history", [])
            linting_passed = not any(
                fix.get("type") == "lint_fix" and not fix.get("success")
                for fix in fix_history
            )

            await push_log(
                pipeline_id,
                "info",
                f"代码生成完成，共 {len(code_files)} 个文件"
                + (f"（经历 {len(fix_history)} 轮修复）" if fix_history else ""),
                stage="CODING"
            )

            if linting_passed:
                await push_log(pipeline_id, "info", "✅ Linting 检查通过", stage="CODING")
            else:
                await push_log(pipeline_id, "warning", "⚠️ Linting 检查有警告", stage="CODING")

            # 【架构优化】记录修改的文件列表，供 DELIVERY 阶段使用
            modified_files = [f.get("file_path", "") for f in code_files if f.get("file_path")]

            # 返回成功
            return StageResult.success_result(
                message="Code generated successfully",
                output_data={
                    "coder_output": result.get("output", {}),
                    "files": code_files,
                    "modified_files": modified_files,  # 【新增】记录修改的文件列表
                    "fix_history": fix_history,
                    "linting_passed": linting_passed,
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                },
                status=PipelineStatus.PAUSED  # 等待审批
            )

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码生成执行失败: {str(e)}", stage="CODING")
            return StageResult.failure_result(
                message=f"Code generation failed: {str(e)}",
                output_data={"error": str(e), "error_type": type(e).__name__}
            )

    async def complete(self, context: StageContext, result: StageResult) -> None:
        """完成阶段：保存结果"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        # 重新获取 stage
        statement = select(PipelineStage).where(PipelineStage.id == context.stage_id)
        query_result = await context.session.execute(statement)
        coding_stage = query_result.scalar_one_or_none()

        if coding_stage:
            await WorkflowService.complete_stage(
                stage=coding_stage,
                output_data=result.output_data,
                success=result.success,
                session=context.session
            )

        if result.success:
            # 更新 Pipeline 状态为 PAUSED（等待审批）
            pipeline = await WorkflowService.get_pipeline_with_stages(
                context.pipeline_id, context.session
            )
            if pipeline:
                await WorkflowService.set_pipeline_paused(pipeline, context.session)

            fix_history = result.output_data.get("fix_history", [])
            fix_summary = f"（经历 {len(fix_history)} 轮自动修复）" if fix_history else ""

            await push_log(
                context.pipeline_id,
                "info",
                f"代码生成完成{fix_summary}，等待审批",
                stage="CODING"
            )
        else:
            # 失败处理
            pipeline = await WorkflowService.get_pipeline_with_stages(
                context.pipeline_id, context.session
            )
            if pipeline:
                await WorkflowService.set_pipeline_failed(pipeline, context.session)

            from app.core.sse_log_buffer import remove_buffer
            remove_buffer(context.pipeline_id)

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
            f"代码生成阶段异常: {str(error)}",
            stage="CODING"
        )
        return StageResult.failure_result(
            message=f"Code generation failed: {str(error)}",
            output_data={"error": str(error), "error_type": type(error).__name__}
        )

    async def on_approved(
        self,
        context: StageContext,
        notes: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> StageResult:
        """CODING 阶段被批准后：进入测试阶段"""
        from sqlmodel import select
        from app.models.pipeline import PipelineStage

        await push_log(
            context.pipeline_id,
            "info",
            "代码已批准，进入测试阶段...",
            stage="CODING"
        )

        # 从数据库获取 CODING stage 的 output_data
        statement = select(PipelineStage).where(
            PipelineStage.pipeline_id == context.pipeline_id,
            PipelineStage.name == StageName.CODING
        )
        result = await context.session.execute(statement)
        coding_stage = result.scalar_one_or_none()

        # 获取 coding_output 和 files
        if coding_stage and coding_stage.output_data:
            coding_output = coding_stage.output_data.get("coder_output", {})
            files = coding_stage.output_data.get("files", [])
        else:
            coding_output = {}
            files = []
            await push_log(
                context.pipeline_id,
                "warning",
                "未找到 CODING 阶段的输出数据",
                stage="CODING"
            )

        await WorkflowService.create_stage(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.UNIT_TESTING,
            input_data={
                "coding_output": coding_output,
                "files": files
            },
            session=context.session
        )

        # 更新 Pipeline 当前阶段
        pipeline = await WorkflowService.get_pipeline_with_stages(
            context.pipeline_id, context.session
        )
        if pipeline:
            pipeline.current_stage = StageName.UNIT_TESTING
            await WorkflowService.set_pipeline_running(pipeline, context.session)

        return StageResult.success_result(
            message="进入测试阶段",
            output_data={
                "previous_stage": StageName.CODING.value,
                "next_stage": StageName.UNIT_TESTING.value
            },
            status=PipelineStatus.RUNNING
        )

    async def on_rejected(
        self,
        context: StageContext,
        reason: str,
        suggested_changes: Optional[str] = None
    ) -> StageResult:
        """CODING 阶段被驳回后：重新执行 CODING 阶段"""
        await push_log(
            context.pipeline_id,
            "info",
            f"代码被驳回，原因: {reason}，重新生成...",
            stage="CODING"
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
                "previous_stage": StageName.CODING.value,
                "current_stage": StageName.CODING.value,
                "feedback": rejection_feedback
            }
        )
