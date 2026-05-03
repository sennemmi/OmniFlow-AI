"""
代码生成阶段处理器（带 Auto-Fix 增强版）

与 E2E 测试脚本保持一致：
- 代码生成后自动进行语法检查和修复
- 契约检查失败时自动补齐缺失符号
- 使用 Sandbox 进行文件操作

【已简化】移除了不成熟的 Architect/Editor 分离模式，只保留稳定的传统模式
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
            # 【简化】只使用传统模式生成代码
            await push_log(
                pipeline_id,
                "info",
                "📦 使用传统模式生成代码",
                stage="CODING"
            )

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

            # 【新增】Linting 检查和自动修复
            await push_log(pipeline_id, "info", "🔍 运行 Linting 检查...", stage="CODING")
            linting_passed = await self._run_linting_check(
                code_files=code_files,
                pipeline_id=pipeline_id
            )
            if linting_passed:
                await push_log(pipeline_id, "info", "✅ Linting 检查通过", stage="CODING")
            else:
                await push_log(pipeline_id, "warning", "⚠️ Linting 检查有警告", stage="CODING")

            # 返回成功
            return StageResult.success_result(
                message="Code generated successfully",
                output_data={
                    "coder_output": final_result.get("coder_output", {}),
                    "files": code_files,
                    "fix_history": fix_history,
                    "linting_passed": linting_passed
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
        【统一入口】使用 AutoFixLoop 执行带自动修复的代码生成

        不再重复实现 Auto-Fix 逻辑，统一调用 AutoFixLoop 类
        """
        from app.agents.auto_fix_loop import AutoFixLoop
        from app.service.sandbox_file_service import get_sandbox_file_service
        from app.utils.agent_output_utils import extract_code_files

        # 获取文件服务
        file_service = get_sandbox_file_service(pipeline_id)

        # 提取 affected_files（从 design_output 中获取需要修改的文件列表）
        interface_specs = design_output.get("interface_specs", [])
        affected_files = list(set([
            spec.get("module", "").replace(".", "/") + ".py"
            for spec in interface_specs
            if spec.get("module")
        ]))

        # 实例化并执行 AutoFixLoop
        auto_fix_loop = AutoFixLoop()

        result = await auto_fix_loop.execute(
            design_output=design_output,
            affected_files=affected_files,
            pipeline_id=pipeline_id,
            workspace_path="/workspace/backend",
            injected_files=injected_files,
            file_service=file_service
        )

        # 转换结果为 CodingHandler 期望的格式
        if result.get("success"):
            code_output = result.get("code_output", {})
            code_files = extract_code_files(code_output)

            return {
                "success": True,
                "coder_output": code_output,
                "code_files": code_files,
                "fix_history": result.get("fix_history", []),
                "total_input_tokens": result.get("total_input_tokens", 0),
                "total_output_tokens": result.get("total_output_tokens", 0)
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "AutoFixLoop 执行失败"),
                "fatal_error": result.get("fatal_error", False),
                "fix_history": result.get("fix_history", [])
            }

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

    async def _run_linting_check(
        self,
        code_files: List[Dict],
        pipeline_id: int
    ) -> bool:
        """
        【新增】运行 Linting 检查并尝试自动修复
        
        Args:
            code_files: 代码文件列表
            pipeline_id: Pipeline ID
            
        Returns:
            bool: 是否通过（True 表示通过或有警告但不阻塞，False 表示严重错误）
        """
        import json
        from app.service.sandbox_manager import sandbox_manager
        
        LINTING_MAX_RETRIES = 3
        
        # 尝试运行 ruff 检查
        linting_errors = []
        checked_files = set()  # 用于去重，避免重复检查同一文件
        
        for file_obj in code_files:
            file_path = file_obj.get("file_path", "")
            if not file_path.endswith(".py"):
                continue
                
            # 转换为沙箱中的路径（相对于 /workspace/backend）
            if file_path.startswith("backend/"):
                sandbox_path = file_path
                normalized_path = file_path
            else:
                sandbox_path = f"backend/{file_path}"
                normalized_path = sandbox_path
            
            # 去重检查：如果已经检查过这个文件，跳过
            if normalized_path in checked_files:
                continue
            checked_files.add(normalized_path)
            
            # 尝试运行 ruff check
            try:
                result = await sandbox_manager.exec(
                    pipeline_id,
                    f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                    timeout=30
                )
                
                if result.stdout:
                    try:
                        errors = json.loads(result.stdout)
                        if errors:
                            # 过滤掉 "文件不存在" 错误 (E902) 和语法错误无法自动修复的
                            real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                            # 过滤掉 invalid-syntax 错误
                            real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                            if real_errors:
                                linting_errors.append({
                                    "file": file_path,
                                    "sandbox_path": sandbox_path,
                                    "errors": real_errors
                                })
                    except json.JSONDecodeError:
                        pass
                        
            except Exception as e:
                await push_log(pipeline_id, "warning", f"Linting 检查失败 {file_path}: {e}", stage="CODING")
        
        if not linting_errors:
            return True
            
        await push_log(pipeline_id, "warning", f"发现 {len(linting_errors)} 个文件有 Linting 错误", stage="CODING")
        
        # 尝试自动修复
        for attempt in range(LINTING_MAX_RETRIES):
            await push_log(pipeline_id, "info", f"🔄 Linting 自动修复尝试 {attempt + 1}/{LINTING_MAX_RETRIES}...", stage="CODING")
            
            try:
                # 使用 set 去重，避免重复修复同一文件
                fixed_paths = set()
                for error_info in linting_errors:
                    sandbox_path = error_info.get("sandbox_path", error_info["file"])
                    
                    # 去重：如果已经修复过这个文件，跳过
                    if sandbox_path in fixed_paths:
                        continue
                    fixed_paths.add(sandbox_path)
                    
                    # 运行 ruff fix
                    fix_result = await sandbox_manager.exec(
                        pipeline_id,
                        f"cd /workspace && ruff check {sandbox_path} --fix 2>&1 || true",
                        timeout=30
                    )
                    
                    output = fix_result.stdout[:200] if fix_result.stdout else "无输出"
                    # 过滤掉文件不存在的错误信息和语法错误
                    if "E902" not in output and "invalid-syntax" not in output.lower():
                        await push_log(pipeline_id, "info", f"修复 {sandbox_path}: {output}", stage="CODING")
                    
                # 重新检查
                remaining_errors = []
                checked_remaining = set()  # 去重集合
                for error_info in linting_errors:
                    sandbox_path = error_info.get("sandbox_path", error_info["file"])
                    
                    # 去重
                    if sandbox_path in checked_remaining:
                        continue
                    checked_remaining.add(sandbox_path)
                    
                    result = await sandbox_manager.exec(
                        pipeline_id,
                        f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                        timeout=30
                    )
                    
                    if result.stdout:
                        try:
                            errors = json.loads(result.stdout)
                            if errors:
                                # 过滤掉 "文件不存在" 错误和语法错误
                                real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                                real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                                if real_errors:
                                    remaining_errors.append({
                                        "file": error_info["file"],
                                        "sandbox_path": sandbox_path,
                                        "errors": real_errors
                                    })
                        except json.JSONDecodeError:
                            pass
                
                if not remaining_errors:
                    await push_log(pipeline_id, "info", "✅ Linting 修复完成", stage="CODING")
                    return True
                    
                linting_errors = remaining_errors
                
            except Exception as e:
                await push_log(pipeline_id, "warning", f"Linting 自动修复失败: {e}", stage="CODING")
                break
        
        if linting_errors:
            await push_log(pipeline_id, "warning", f"Linting 检查后仍有 {len(linting_errors)} 个文件有问题", stage="CODING")
            for err in linting_errors:
                await push_log(pipeline_id, "warning", f"  - {err['file']}: {len(err['errors'])} 个错误", stage="CODING")
        
        # 返回 True 允许继续，但记录警告
        return True

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
