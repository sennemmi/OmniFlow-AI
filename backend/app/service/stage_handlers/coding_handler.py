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
        design_stage = result.scalars().first()

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
        requirement_stage = result.scalars().first()

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

            # 【新增】契约对齐检查：验证代码是否符合 Designer 的契约
            from app.core.contract_validator import ContractValidator
            design_output = context.input_data.get("design_output", {})
            interface_specs = design_output.get("interface_specs", [])

            if interface_specs and code_files:
                contract_errors = ContractValidator.validate_code_against_contract(
                    code_files, interface_specs
                )
                if contract_errors:
                    # 过滤出警告和错误
                    warnings = [e for e in contract_errors if e.startswith("[警告]")]
                    errors = [e for e in contract_errors if not e.startswith("[警告]")]

                    if warnings:
                        for warning in warnings:
                            await push_log(pipeline_id, "warning", f"⚠️ {warning}", stage="CODING")

                    if errors:
                        for error in errors:
                            await push_log(pipeline_id, "error", f"❌ {error}", stage="CODING")
                        # 契约不一致，返回失败
                        return StageResult.failure_result(
                            message=f"代码与契约不一致: {'; '.join(errors)}",
                            output_data={
                                "error": "Contract mismatch",
                                "contract_errors": errors,
                                "code_files": code_files,
                            }
                        )

                await push_log(pipeline_id, "info", "✅ 契约对齐检查通过", stage="CODING")

                # 【新增】验证 router 是否在 main.py 中注册
                main_py = await file_service.read_file("main.py")
                if main_py.exists:
                    router_errors = ContractValidator.validate_router_registration(
                        main_py.content, interface_specs
                    )
                    if router_errors:
                        for err in router_errors:
                            await push_log(pipeline_id, "error", f"❌ {err}", stage="CODING")
                        return StageResult.failure_result(
                            message=f"路由未注册: {'; '.join(router_errors)}",
                            output_data={"error": "Router not registered", "router_errors": router_errors}
                        )

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
        coding_stage = query_result.scalars().first()

        if coding_stage:
            await WorkflowService.complete_stage(
                stage=coding_stage,
                output_data=result.output_data,
                success=result.success,
                session=context.session
            )

        if result.success:
            # 【不再在此设置 PAUSED】 Pipeline 状态由调用方管理
            # 后台任务 _run_coding_task_background 会在所有阶段完成后统一设置 PAUSED
            # 单阶段审批模式由 trigger_coding_phase 的调用者决定何时暂停

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
        coding_stage = result.scalars().first()

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
        """CODING 阶段被驳回后：打回 DESIGN 阶段重新设计"""
        rejection_feedback = {"reason": reason, "suggested_changes": suggested_changes}

        await push_log(
            context.pipeline_id,
            "info",
            f"代码被驳回，打回 DESIGN 阶段重新设计。原因: {reason}",
            stage="DESIGN"
        )

        await WorkflowService.mark_stage_for_rerun(
            pipeline_id=context.pipeline_id,
            stage_name=StageName.DESIGN,
            rejection_feedback=rejection_feedback,
            session=context.session
        )

        return StageResult(
            success=True,
            status=PipelineStatus.RUNNING,
            message="打回 DESIGN 阶段重新设计",
            output_data={
                "previous_stage": StageName.CODING.value,
                "current_stage": StageName.DESIGN.value,
                "feedback": rejection_feedback
            }
        )
