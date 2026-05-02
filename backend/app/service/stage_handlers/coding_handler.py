"""
代码生成阶段处理器（带 Auto-Fix 增强版）

与 E2E 测试脚本保持一致：
- 代码生成后自动进行语法检查和修复
- 契约检查失败时自动补齐缺失符号
- 使用 Sandbox 进行文件操作
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.sse_log_buffer import push_log
from app.models.pipeline import StageName, PipelineStatus, StageStatus
from app.agents.coder import coder_agent
from app.service.sandbox_manager import sandbox_manager
from app.service.stage_handlers.base import StageContext, StageHandler, StageResult
from app.service.workflow import WorkflowService


class CodingHandler(StageHandler):
    """代码生成阶段处理器（带 Auto-Fix 增强版）"""

    MAX_FIX_RETRIES = 3  # 最大自动修复次数

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
        """执行代码生成（带 Auto-Fix 闭环）"""
        pipeline_id = context.pipeline_id
        design_output = context.previous_output

        await push_log(pipeline_id, "info", "开始代码生成...", stage="CODING")

        # 获取 REQUIREMENT 阶段的 injected_files
        from sqlmodel import select
        from app.models.pipeline import PipelineStage, StageName

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
            # 【增强】使用 Auto-Fix 循环生成代码
            final_result = await self._generate_code_with_auto_fix(
                design_output=design_output,
                pipeline_id=pipeline_id,
                injected_files=injected_files
            )

            if not final_result.get("success"):
                error_msg = final_result.get("error", "Unknown error")
                await push_log(pipeline_id, "error", f"代码生成失败: {error_msg}", stage="CODING")
                return StageResult.failure_result(
                    message=f"Code generation failed: {error_msg}",
                    output_data={"error": error_msg}
                )

            # 获取生成的文件
            code_files = final_result.get("code_files", [])
            fix_history = final_result.get("fix_history", [])

            await push_log(
                pipeline_id,
                "info",
                f"代码生成完成，共 {len(code_files)} 个文件"
                + (f"（经历 {len(fix_history)} 轮修复）" if fix_history else ""),
                stage="CODING"
            )

            # 返回成功
            return StageResult.success_result(
                message="Code generated successfully",
                output_data={
                    "coder_output": final_result.get("coder_output", {}),
                    "files": code_files,
                    "fix_history": fix_history
                },
                status=PipelineStatus.PAUSED  # 等待审批
            )

        except Exception as e:
            await push_log(pipeline_id, "error", f"代码生成执行失败: {str(e)}", stage="CODING")
            return StageResult.failure_result(
                message=f"Code generation failed: {str(e)}",
                output_data={"error": str(e), "error_type": type(e).__name__}
            )

    async def _generate_code_with_auto_fix(
        self,
        design_output: Dict,
        pipeline_id: int,
        injected_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        【增强】带 Auto-Fix 的代码生成

        流程：
        1. 调用 CoderAgent 生成代码
        2. 语法检查 → 自动修复
        3. 契约检查 → 自动补齐
        4. 返回最终结果
        """
        from app.service.sandbox_file_service import get_sandbox_file_service
        from app.service.e2e_test_service import E2ETestService
        from app.utils.repair_loop_utils import run_syntax_fix_loop, run_contract_fix_loop
        from app.utils.file_operation_utils import merge_and_write_files
        from app.utils.agent_output_utils import extract_code_files

        # 获取文件服务（直接使用，不通过 orchestrator）
        file_service = get_sandbox_file_service(pipeline_id)
        e2e_service = E2ETestService()

        fix_history = []
        attempt = 0

        while attempt <= self.MAX_FIX_RETRIES:
            attempt += 1

            if attempt > 1:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"第 {attempt - 1} 轮修复后重新生成代码...",
                    stage="CODING"
                )

            # 1. 调用 CoderAgent 生成代码
            coder_result = await coder_agent.generate_code(
                design_output=design_output,
                pipeline_id=pipeline_id,
                injected_files=injected_files
            )

            if not coder_result.get("success"):
                # 检查是否是致命错误（上下文超限）
                error_msg = coder_result.get("error", "")
                if self._is_fatal_error(error_msg):
                    return {
                        "success": False,
                        "error": f"Context limit exceeded: {error_msg}",
                        "fatal_error": True
                    }
                return {
                    "success": False,
                    "error": f"CoderAgent failed: {error_msg}"
                }

            coder_output = coder_result.get("output", {})
            code_files = extract_code_files(coder_output)

            if not code_files:
                return {
                    "success": False,
                    "error": "No files generated by CoderAgent"
                }

            await push_log(
                pipeline_id,
                "info",
                f"CoderAgent 生成 {len(code_files)} 个文件",
                stage="CODING"
            )

            # 2. 写入文件到沙箱
            async def retry_callback(fp, sb, rb, cc):
                # 简化处理：直接返回失败，让上层处理
                return False, cc

            written_count = await merge_and_write_files(
                code_files, file_service, retry_callback
            )

            await push_log(
                pipeline_id,
                "info",
                f"已写入 {written_count} 个文件到沙箱",
                stage="CODING"
            )

            # 3. 语法检查
            await push_log(pipeline_id, "info", "执行语法检查...", stage="CODING")
            syntax_errors = await e2e_service.validate_code_syntax(code_files, file_service)

            if syntax_errors:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"发现 {len(syntax_errors)} 个语法错误，启动自动修复...",
                    stage="CODING"
                )

                # 准备错误文件内容
                error_files_with_content = []
                for err in syntax_errors:
                    fp = err.file
                    read_res = await file_service.read_file(fp)
                    if read_res.exists:
                        error_files_with_content.append((fp, read_res.content))
                    else:
                        error_files_with_content.append((fp, ""))

                # 运行语法修复循环
                fixed_files = await run_syntax_fix_loop(
                    syntax_errors=[err.to_dict() for err in syntax_errors],
                    files_to_check=error_files_with_content,
                    file_service=file_service,
                    design_output={**design_output, "pipeline_id": pipeline_id},
                    max_retries=self.MAX_FIX_RETRIES
                )

                # 重新验证语法
                remaining_errors = await e2e_service.validate_code_syntax(
                    code_files, file_service
                )

                if remaining_errors:
                    await push_log(
                        pipeline_id,
                        "error",
                        f"语法错误自动修复失败，仍有 {len(remaining_errors)} 个错误",
                        stage="CODING"
                    )
                    # 继续下一轮重试
                    fix_history.append({
                        "type": "syntax_fix",
                        "success": False,
                        "attempt": attempt,
                        "remaining_errors": len(remaining_errors)
                    })
                    continue
                else:
                    await push_log(
                        pipeline_id,
                        "info",
                        "语法错误修复成功",
                        stage="CODING"
                    )
                    fix_history.append({
                        "type": "syntax_fix",
                        "success": True,
                        "attempt": attempt,
                        "fixed_count": len(fixed_files)
                    })

            # 4. 契约检查
            interface_specs = design_output.get("interface_specs", [])
            if interface_specs:
                await push_log(
                    pipeline_id,
                    "info",
                    f"执行契约检查（{len(interface_specs)} 个符号）...",
                    stage="CODING"
                )

                missing_symbols = await e2e_service.verify_contract(
                    file_service, code_files, interface_specs
                )

                if missing_symbols:
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"契约检查失败，缺失 {len(missing_symbols)} 个符号，启动自动补齐...",
                        stage="CODING"
                    )

                    # 运行契约修复循环
                    fixed, still_missing, fix_files = await run_contract_fix_loop(
                        missing_syms=missing_symbols,
                        interface_specs=interface_specs,
                        design_output={**design_output, "pipeline_id": pipeline_id},
                        file_service=file_service,
                        max_retries=self.MAX_FIX_RETRIES
                    )

                    if not fixed:
                        await push_log(
                            pipeline_id,
                            "error",
                            f"契约自动修复失败，仍有缺失: {still_missing}",
                            stage="CODING"
                        )
                        fix_history.append({
                            "type": "contract_fix",
                            "success": False,
                            "attempt": attempt,
                            "still_missing": still_missing
                        })
                        # 如果达到最大重试次数，返回失败
                        if attempt >= self.MAX_FIX_RETRIES:
                            return {
                                "success": False,
                                "error": f"Contract fix failed after {self.MAX_FIX_RETRIES} attempts",
                                "missing_symbols": still_missing,
                                "fix_history": fix_history
                            }
                        continue
                    else:
                        await push_log(
                            pipeline_id,
                            "info",
                            f"契约自动修复成功，补齐 {len(fix_files)} 个文件",
                            stage="CODING"
                        )
                        code_files.extend(fix_files)
                        fix_history.append({
                            "type": "contract_fix",
                            "success": True,
                            "attempt": attempt,
                            "fixed_count": len(fix_files)
                        })
                else:
                    await push_log(
                        pipeline_id,
                        "info",
                        "契约检查通过",
                        stage="CODING"
                    )

            # 所有检查通过
            return {
                "success": True,
                "coder_output": coder_output,
                "code_files": code_files,
                "fix_history": fix_history
            }

        # 达到最大重试次数
        return {
            "success": False,
            "error": f"Auto-fix failed after {self.MAX_FIX_RETRIES} attempts",
            "fix_history": fix_history
        }

    def _is_fatal_error(self, error_msg: str) -> bool:
        """判断是否是不可重试的致命错误"""
        if not error_msg:
            return False
        fatal_signatures = [
            "choices': None",
            "choices is None",
            "context length exceeded",
            "maximum context length",
            "token limit exceeded",
        ]
        return any(sig in error_msg for sig in fatal_signatures)

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
        """
        CODING 阶段被批准后：进入测试阶段
        """
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
        """
        CODING 阶段被驳回后：重新执行 CODING 阶段
        """
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
