"""
代码生成服务 (CodeGenerationService)

统一 E2E 测试和 Pipeline 中的代码生成与修复流程。
消除重复实现，确保行为一致。
"""

import logging
import time
from typing import Dict, List, Optional, Any, Callable

from app.agents.coder import coder_agent
from app.agents.repairer_with_tools import RepairerAgentWithTools
from app.service.import_sanitizer import ImportSanitizer
from app.service.sandbox_file_service import SandboxFileService
from app.service.code_validation_service import CodeValidationService
from app.core.contract_checker import check_contract_before_test
from app.core.config import settings
from app.core.sse_log_buffer import push_log
from app.utils.linting_utils import run_linting_check
from app.utils.agent_instruction_utils import (
    build_key_mismatch_fix_instruction,
    build_contract_fix_instruction,
    build_retry_fix_instruction,
)
from app.utils.agent_output_utils import extract_key_mismatches
from app.utils.repair_loop_utils import run_syntax_fix_loop

logger = logging.getLogger(__name__)


class CodeGenerationService:
    """
    统一的代码生成与修复服务

    职责：
    1. 调用 CoderAgent 生成代码（含键名重试、符号缺失重试）
    2. 执行 Linting 检查与自动修复
    3. 执行语法验证、契约检查
    4. 文件写入（含 search_block 回退策略）
    5. 返回统一的生成结果

    使用场景：
    - E2E 测试脚本
    - CodingHandler (Pipeline)
    - 任何需要代码生成的地方
    """

    MAX_FIX_RETRIES = 3
    MAX_KEY_MISMATCH_RETRIES = 3
    MAX_MISSING_SYMBOLS_RETRIES = 3

    # 致命错误签名（不可重试）
    FATAL_ERRORS = [
        "choices': None",
        "choices is None",
        "completion_tokens': 0, 'prompt_tokens': 0",
        "context length exceeded",
        "maximum context length",
        "token limit exceeded",
    ]

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _is_fatal_error(self, error_msg: str) -> bool:
        """判断是否是不可重试的致命错误"""
        if not error_msg:
            return False
        return any(sig in error_msg for sig in self.FATAL_ERRORS)

    async def generate_and_fix(
        self,
        design_output: Dict[str, Any],
        injected_files: Optional[Dict[str, str]] = None,
        pipeline_id: Optional[int] = None,
        workspace_path: Optional[str] = None,
        file_service: Optional[SandboxFileService] = None,
        log_callback: Optional[Callable[[str, str], Any]] = None,
        debugger: Optional[Any] = None,
        enable_linting: bool = True,
        enable_contract_check: bool = True,
    ) -> Dict[str, Any]:
        """
        统一的代码生成与修复入口

        Args:
            design_output: 设计输出（包含 interface_specs, affected_files 等）
            injected_files: 预注入的文件内容（由 ArchitectAgent 提供）
            pipeline_id: Pipeline ID（用于日志和调试）
            workspace_path: 工作区路径（用于文件写入）
            file_service: 沙箱文件服务（可选）
            log_callback: 日志回调函数 (level, message) -> None
            debugger: AgentDebugger 实例
            enable_linting: 是否启用 Linting 检查
            enable_contract_check: 是否启用契约检查

        Returns:
            Dict: {
                "success": bool,
                "output": Dict,  # 生成的代码文件列表
                "files": List[Dict],  # 文件变更列表
                "attempt": int,  # 尝试次数
                "input_tokens": int,
                "output_tokens": int,
                "duration_ms": int,
                "error": Optional[str],
                "fix_history": List[Dict],  # 修复历史
            }
        """
        start_time = time.time()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        attempt = 0
        fix_history = []
        last_code_output = None
        current_error_context = None

        async def log(level: str, message: str):
            if log_callback:
                await log_callback(level, message)
            else:
                getattr(logger, level.lower(), logger.info)(message)
            if pipeline_id:
                await push_log(pipeline_id, level.lower(), message, stage="CODING")

        await log("info", "🚀 启动代码生成与修复流程...")

        # 获取 affected_files
        affected_files = design_output.get("affected_files", [])

        while attempt <= self.MAX_FIX_RETRIES:
            if attempt > 0:
                await log("warning", f"🔄 第 {attempt}/{self.MAX_FIX_RETRIES} 次修复尝试...")

            # 1. 调用 CoderAgent 生成代码
            code_result = await self._call_coder_agent(
                design_output=design_output,
                affected_files=affected_files,
                injected_files=injected_files,
                pipeline_id=pipeline_id,
                error_context=current_error_context,
                debugger=debugger,
            )

            self.total_input_tokens += code_result.get("input_tokens", 0) or 0
            self.total_output_tokens += code_result.get("output_tokens", 0) or 0

            # 处理生成失败
            if not code_result.get("success"):
                error_msg = code_result.get("error", "")

                # 致命错误，直接返回
                if self._is_fatal_error(error_msg):
                    await log("error", f"❌ 致命错误，中止重试: {error_msg}")
                    return self._build_result(
                        success=False,
                        error=f"Context limit exceeded: {error_msg}",
                        attempt=attempt,
                        start_time=start_time,
                        fatal_error=True,
                    )

                # 键名不匹配重试
                if "返回键名与契约不一致" in error_msg:
                    retry_result = await self._handle_key_mismatch_retry(
                        pipeline_id=pipeline_id,
                        design_output=design_output,
                        injected_files=injected_files,
                        code_result=code_result,
                        debugger=debugger,
                        log_callback=log_callback,
                    )
                    if retry_result:
                        code_result = retry_result
                        self.total_input_tokens += retry_result.get("input_tokens", 0) or 0
                        self.total_output_tokens += retry_result.get("output_tokens", 0) or 0
                        fix_history.append({"type": "key_mismatch_retry", "success": True})
                    else:
                        return self._build_result(
                            success=False,
                            error="Key mismatch retry failed",
                            attempt=attempt,
                            start_time=start_time,
                        )

                # 符号缺失重试
                elif "缺少契约要求的符号" in error_msg:
                    retry_result = await self._handle_missing_symbols_retry(
                        pipeline_id=pipeline_id,
                        design_output=design_output,
                        injected_files=injected_files,
                        error_message=error_msg,
                        debugger=debugger,
                        log_callback=log_callback,
                    )
                    if retry_result:
                        code_result = retry_result
                        self.total_input_tokens += retry_result.get("input_tokens", 0) or 0
                        self.total_output_tokens += retry_result.get("output_tokens", 0) or 0
                        fix_history.append({"type": "missing_symbols_retry", "success": True})
                    else:
                        return self._build_result(
                            success=False,
                            error="Missing symbols retry failed",
                            attempt=attempt,
                            start_time=start_time,
                        )

                else:
                    # 其他错误
                    return self._build_result(
                        success=False,
                        error=f"Code generation failed: {error_msg}",
                        attempt=attempt,
                        start_time=start_time,
                    )

            # 2. 处理生成的文件
            code_output = code_result.get("code_output", {})
            all_files = code_output.get("files", [])

            if not all_files:
                return self._build_result(
                    success=False,
                    error="No files generated by CoderAgent",
                    attempt=attempt,
                    start_time=start_time,
                )

            # 3. Import 路径清理
            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)
            if fix_report:
                await log("warning", f"📝 自动修正了 {len(fix_report)} 个文件的 import 路径")

            # 路径防御
            for f in all_files:
                p = f.get("file_path", "")
                p = p.lstrip("/")
                if p and not p.startswith("backend/"):
                    f["file_path"] = f"backend/{p}"

            # 4. 文件写入
            write_success, write_errors = await self._write_files(
                files=all_files,
                workspace_path=workspace_path,
                pipeline_id=pipeline_id,
                file_service=file_service,
                design_output=design_output,
            )

            if not write_success:
                await log("error", f"❌ 文件写入失败: {write_errors}")
                current_error_context = f"文件写入失败:\n{write_errors}"
                attempt += 1
                fix_history.append({"type": "write_retry", "success": False, "error": write_errors})
                continue

            await log("info", f"✅ 文件写入成功 ({len(all_files)} 个文件)")

            # 5. Linting 检查
            if enable_linting:
                lint_passed, lint_errors = await self._run_linting_check(
                    files=all_files,
                    pipeline_id=pipeline_id,
                    file_service=file_service,
                )
                if not lint_passed:
                    await log("warning", f"⚠️ 发现 {len(lint_errors)} 个 Lint 问题，启动修复...")
                    current_error_context = self._format_lint_errors_for_agent(lint_errors)
                    attempt += 1
                    fix_history.append({"type": "lint_fix", "success": False, "errors": lint_errors})
                    continue

                await log("success", "✅ Lint 检查通过")

            # 6. 语法验证（优先在沙箱内检查）
            syntax_errors = await self._validate_code_syntax(all_files, pipeline_id, file_service)
            if syntax_errors:
                await log("warning", f"⚠️ 发现 {len(syntax_errors)} 个语法错误，启动修复...")

                # 【与原始 E2E 完全一致】从沙箱读取错误文件的内容
                error_files_with_content = []
                for err in syntax_errors:
                    fp = err.get("file", "")
                    if fp and file_service:
                        read_res = await file_service.read_file(fp)
                        if read_res.exists:
                            error_files_with_content.append((fp, read_res.content))
                        else:
                            error_files_with_content.append((fp, ""))
                    elif fp:
                        # 如果没有 file_service，从 all_files 中获取内容
                        for f in all_files:
                            if f.get("file_path") == fp:
                                error_files_with_content.append((fp, f.get("content", "")))
                                break

                # 【与原始 E2E 完全一致】调用 run_syntax_fix_loop 修复语法错误
                fixed_files = await run_syntax_fix_loop(
                    syntax_errors=syntax_errors,
                    files_to_check=error_files_with_content,
                    file_service=file_service or SandboxFileService(
                        workspace_dir=workspace_path or settings.TARGET_PROJECT_PATH,
                        pipeline_id=pipeline_id or 0
                    ),
                    design_output={**design_output, "pipeline_id": pipeline_id},
                    max_retries=self.MAX_FIX_RETRIES,
                    debugger=debugger,
                    coder_system_prompt=coder_agent.system_prompt,
                    pipeline_id=pipeline_id,
                )

                # 【与原始 E2E 完全一致】重新验证语法错误是否已修复
                # 从沙箱读取修复后的文件内容进行验证
                fixed_files_with_content = []
                for err in syntax_errors:
                    fp = err.get("file", "")
                    if fp and file_service:
                        read_res = await file_service.read_file(fp)
                        if read_res.exists:
                            fixed_files_with_content.append({
                                "file_path": fp,
                                "content": read_res.content
                            })
                remaining_syntax_errors = await self._validate_code_syntax(fixed_files_with_content, pipeline_id, file_service)
                if remaining_syntax_errors:
                    await log("error", f"❌ 修复后仍有 {len(remaining_syntax_errors)} 个语法错误")
                    for err in remaining_syntax_errors:
                        await log("error", f"   - {err.get('file', 'unknown')}: {err.get('error', 'unknown error')}")
                    return self._build_result(
                        success=False,
                        error="语法错误自动修复失败",
                        attempt=attempt,
                        start_time=start_time,
                        fix_history=fix_history + [{"type": "syntax_fix", "success": False, "errors": remaining_syntax_errors}],
                    )

                await log("success", "✅ 语法错误修复成功")

            await log("success", "✅ 语法验证通过")

            # 7. 契约检查
            if enable_contract_check:
                code_files_dict = {f["file_path"]: f["content"] for f in all_files if f.get("content")}
                contract_check = check_contract_before_test(
                    design_output=design_output,
                    code_files=code_files_dict
                )

                if not contract_check.get("success", True):
                    violations = contract_check.get("violations", [])
                    await log("error", f"❌ 契约检查失败: 发现 {len(violations)} 个问题")
                    current_error_context = (
                        f"【契约检查失败】代码未满足接口契约要求:\n"
                        f"{chr(10).join(violations[:10])}\n\n"
                        f"请确保实现了所有 interface_specs 中声明的函数/类。"
                    )
                    attempt += 1
                    fix_history.append({"type": "contract_fix", "success": False, "violations": violations})
                    continue

                await log("success", "✅ 契约检查通过")

            # 8. 同步到沙箱（如果提供了 file_service）
            if file_service:
                await self._sync_files_to_sandbox(all_files, pipeline_id, file_service)

            # 所有检查通过
            await log("success", "🎉 代码生成与验证全部通过！")

            return self._build_result(
                success=True,
                output=code_output,
                files=all_files,
                attempt=attempt,
                start_time=start_time,
                fix_history=fix_history,
            )

        # 达到最大重试次数
        await log("error", f"🚨 达到最大重试次数 ({self.MAX_FIX_RETRIES})")

        return self._build_result(
            success=False,
            error=f"Auto-fix reached max retries ({self.MAX_FIX_RETRIES})",
            output=last_code_output,
            attempt=attempt,
            start_time=start_time,
            fix_history=fix_history,
        )

    async def _call_coder_agent(
        self,
        design_output: Dict[str, Any],
        affected_files: List[str],
        injected_files: Optional[Dict[str, str]],
        pipeline_id: Optional[int],
        error_context: Optional[str],
        debugger: Optional[Any],
    ) -> Dict[str, Any]:
        """调用 CoderAgent 生成代码"""
        coder_input = {
            "design_output": design_output,
            "pipeline_id": pipeline_id,
            "error_context": error_context,
            "injected_files": injected_files,
        }

        try:
            result = await coder_agent.generate_code(**coder_input)

            # 保存调试信息
            if debugger:
                debugger.save_agent_io(
                    agent_name="CoderAgent",
                    stage="generate_code",
                    input_data=coder_input,
                    output_data=result,
                    metadata={
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "duration_ms": result.get("duration_ms", 0),
                    },
                    success=result.get("success", False),
                    error=result.get("error"),
                    tool_calls=result.get("tool_results", []),
                    system_prompt=coder_agent.system_prompt,
                )

            if result.get("success"):
                return {
                    "success": True,
                    "code_output": result.get("output", {}),
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                }

        except Exception as e:
            logger.error(f"CoderAgent execution failed: {e}")
            return {
                "success": False,
                "error": f"CoderAgent execution failed: {str(e)}",
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }

    async def _handle_key_mismatch_retry(
        self,
        pipeline_id: Optional[int],
        design_output: Dict[str, Any],
        injected_files: Optional[Dict[str, str]],
        code_result: Dict[str, Any],
        debugger: Optional[Any],
        log_callback: Optional[Callable],
    ) -> Optional[Dict[str, Any]]:
        """处理键名不匹配重试"""
        key_mismatches = extract_key_mismatches(code_result.get("output", {}))

        if log_callback:
            log_callback("warning", "检测到返回键名不匹配，启动重试...")

        key_mismatch_instruction = build_key_mismatch_fix_instruction(
            key_mismatches, injected_files or {}
        )

        for retry_attempt in range(self.MAX_KEY_MISMATCH_RETRIES):
            if log_callback:
                log_callback("warning", f"键名不匹配重试 {retry_attempt + 1}/{self.MAX_KEY_MISMATCH_RETRIES}...")

            instruction, force_full_file = build_retry_fix_instruction(
                retry_attempt, self.MAX_KEY_MISMATCH_RETRIES, key_mismatch_instruction
            )

            retry_design_output = {
                **design_output,
                "fix_mode": True,
                "force_full_file": force_full_file,
                "fix_instruction": instruction,
                "affected_files": list(injected_files.keys()) if injected_files else [],
            }

            retry_input = {
                "design_output": retry_design_output,
                "pipeline_id": pipeline_id,
                "injected_files": injected_files,
            }

            retry_result = await coder_agent.generate_code(**retry_input)

            # 保存调试信息
            if debugger:
                debugger.save_agent_io(
                    agent_name="CoderAgent",
                    stage=f"key_mismatch_retry_{retry_attempt + 1}",
                    input_data=retry_input,
                    output_data=retry_result,
                    metadata={"attempt": retry_attempt + 1, "key_mismatches": key_mismatches},
                    success=retry_result.get("success", False),
                    error=retry_result.get("error"),
                    tool_calls=retry_result.get("tool_results", []),
                    system_prompt=coder_agent.system_prompt,
                )

            if retry_result.get("success"):
                if log_callback:
                    log_callback("success", f"键名不匹配重试成功")
                return {
                    "success": True,
                    "code_output": retry_result.get("output", {}),
                    "input_tokens": retry_result.get("input_tokens", 0),
                    "output_tokens": retry_result.get("output_tokens", 0),
                    "duration_ms": retry_result.get("duration_ms", 0),
                }

        return None

    async def _handle_missing_symbols_retry(
        self,
        pipeline_id: Optional[int],
        design_output: Dict[str, Any],
        injected_files: Optional[Dict[str, str]],
        error_message: str,
        debugger: Optional[Any],
        log_callback: Optional[Callable],
    ) -> Optional[Dict[str, Any]]:
        """处理符号缺失重试"""
        import re

        if log_callback:
            log_callback("warning", "检测到符号缺失，启动重试...")

        # 从错误消息中提取缺失的符号
        missing_symbols = re.findall(r"'([^']+)'", error_message)
        interface_specs = design_output.get("interface_specs", [])

        missing_specs = [
            spec for spec in interface_specs
            if any(f"{spec.get('symbol_name', '')} in {spec.get('module', '')}" in m for m in missing_symbols)
        ]

        fix_instruction = build_contract_fix_instruction(missing_specs)

        for retry_attempt in range(self.MAX_MISSING_SYMBOLS_RETRIES):
            if log_callback:
                log_callback("warning", f"符号缺失重试 {retry_attempt + 1}/{self.MAX_MISSING_SYMBOLS_RETRIES}...")

            instruction, _ = build_retry_fix_instruction(
                retry_attempt, self.MAX_MISSING_SYMBOLS_RETRIES, fix_instruction
            )

            retry_design_output = {
                **design_output,
                "fix_mode": True,
                "force_full_file": True,
                "fix_instruction": instruction,
                "affected_files": list(set(
                    [s.get("module", "").replace(".", "/") + ".py" for s in missing_specs if s.get("module")]
                    + list(injected_files.keys())
                )),
            }

            retry_input = {
                "design_output": retry_design_output,
                "pipeline_id": pipeline_id,
                "injected_files": injected_files,
            }

            retry_result = await coder_agent.generate_code(**retry_input)

            # 保存调试信息
            if debugger:
                debugger.save_agent_io(
                    agent_name="CoderAgent",
                    stage=f"missing_symbols_retry_{retry_attempt + 1}",
                    input_data=retry_input,
                    output_data=retry_result,
                    metadata={"attempt": retry_attempt + 1, "missing_specs": missing_specs},
                    success=retry_result.get("success", False),
                    error=retry_result.get("error"),
                    tool_calls=retry_result.get("tool_results", []),
                    system_prompt=coder_agent.system_prompt,
                )

            if retry_result.get("success"):
                if log_callback:
                    log_callback("success", f"符号缺失重试成功")
                return {
                    "success": True,
                    "code_output": retry_result.get("output", {}),
                    "input_tokens": retry_result.get("input_tokens", 0),
                    "output_tokens": retry_result.get("output_tokens", 0),
                    "duration_ms": retry_result.get("duration_ms", 0),
                }

        return None

    async def _write_files(
        self,
        files: List[Dict[str, Any]],
        workspace_path: Optional[str],
        pipeline_id: Optional[int],
        file_service: Optional[SandboxFileService] = None,
        design_output: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """写入文件到工作区

        使用 merge_and_write_files 逻辑，支持 add/modify/重试机制
        与原有 E2E 脚本完全一致
        """
        from app.utils.file_operation_utils import merge_and_write_files, normalize_file_path
        from app.utils.agent_instruction_utils import build_search_block_retry_instruction
        from app.agents.coder import coder_agent

        try:
            # 如果没有 file_service，创建本地文件服务
            if not file_service:
                from app.service.sandbox_file_service import SandboxFileService
                target_path = workspace_path or settings.TARGET_PROJECT_PATH
                file_service = SandboxFileService(
                    workspace_dir=target_path,
                    pipeline_id=pipeline_id or 0
                )

            # 创建重试回调函数（与 E2E 脚本完全一致）
            async def retry_callback(file_path, search_block, replace_block, current_content):
                """处理 search_block 不匹配的重试（与 E2E 脚本完全一致）"""
                logger.warning(f"[CodeGenerationService] search_block 不匹配，启动重试: {file_path}")

                max_retries = 3
                for retry_attempt in range(max_retries):
                    logger.info(f"  🔄 重新请求 CoderAgent 修复 {file_path} (第 {retry_attempt + 1}/{max_retries} 次)...")

                    retry_input = {
                        "design_output": {
                            "fix_mode": True,
                            "fix_instruction": build_search_block_retry_instruction(
                                file_path, current_content, replace_block
                            ),
                            "affected_files": [file_path]
                        },
                        "pipeline_id": pipeline_id,
                        "injected_files": {file_path: current_content}
                    }

                    retry_result = await coder_agent.generate_code(**retry_input)

                    # 保存调试信息
                    if self.debugger:
                        self.debugger.save_agent_io(
                            agent_name="CoderAgent",
                            stage="search_block_retry",
                            input_data=retry_input,
                            output_data=retry_result,
                            metadata={"attempt": retry_attempt + 1, "max_retries": max_retries, "file_path": file_path},
                            success=retry_result.get("success", False),
                            error=retry_result.get("error"),
                            tool_calls=retry_result.get("tool_results", []),
                            system_prompt=coder_agent.system_prompt
                        )

                    if retry_result.get("success"):
                        retry_output = retry_result.get("output", {})
                        retry_files = retry_output.get("files", [])

                        for rfc in retry_files:
                            rfp = normalize_file_path(rfc.get("file_path", ""))
                            if rfp == file_path:
                                r_search = rfc.get("search_block", "")
                                r_replace = rfc.get("replace_block", "")
                                r_content = rfc.get("content", "")

                                if r_search and r_search in current_content:
                                    new_content = current_content.replace(r_search, r_replace, 1)
                                    logger.info(f"  ✅ modify(重试成功): {file_path}")
                                    return True, new_content
                                elif r_content:
                                    logger.info(f"  ✅ modify(重试-完整覆盖): {file_path}")
                                    return True, r_content
                                else:
                                    logger.warning(f"  ⚠️ modify(重试 {retry_attempt + 1} 无法应用): {file_path}")

                # 所有重试都失败
                return False, current_content

            # 使用 merge_and_write_files 写入文件（与 E2E 脚本完全一致）
            written_count = await merge_and_write_files(files, file_service, retry_callback)

            if written_count == 0 and files:
                return False, "No files were written"

            return True, ""

        except Exception as e:
            logger.error(f"File write failed: {e}")
            return False, str(e)

    async def _run_linting_check(
        self,
        files: List[Dict[str, Any]],
        pipeline_id: Optional[int],
        file_service: Optional[SandboxFileService],
    ) -> tuple[bool, List[Dict]]:
        """运行 Linting 检查"""
        if not file_service:
            # 如果没有 file_service，跳过 linting
            return True, []

        async def log_callback(level: str, message: str):
            if pipeline_id:
                await push_log(pipeline_id, level.lower(), message, stage="CODING")

        passed, errors = await run_linting_check(
            code_files=files,
            pipeline_id=pipeline_id,
            max_retries=0,  # 不在此处重试，由上层处理
            log_callback=log_callback,
            enabled=True,
        )

        return passed, errors

    def _format_lint_errors_for_agent(self, lint_errors: List[Dict]) -> str:
        """将 Lint 错误格式化为 Agent 可理解的格式"""
        lines = []
        for err in lint_errors:
            file_path = err.get("filename", "").replace("/workspace/backend/", "")
            line_no = err.get("location", {}).get("row", "?")
            code = err.get("code", "?")
            message = err.get("message", "?")
            lines.append(f"  - {file_path}:{line_no} [{code}] {message}")
        return "【Lint 错误】代码存在以下格式/语法问题:\n" + "\n".join(lines)

    async def _validate_code_syntax(
        self,
        files: List[Dict[str, Any]],
        pipeline_id: Optional[int],
        file_service: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        验证代码语法（在 Docker 沙箱内执行）

        所有语法检查均在沙箱内执行，避免宿主机编码问题
        """
        if not pipeline_id:
            logger.warning("未提供 pipeline_id，无法执行语法检查")
            return []

        # 使用沙箱内批量语法检查
        from app.service.code_validation_service import code_validation_service
        errors = await code_validation_service.batch_check_syntax_in_sandbox(
            code_files=files,
            pipeline_id=pipeline_id
        )

        return [
            {
                "file": err.file,
                "error": err.error,
                "line": err.line,
            }
            for err in errors
        ]

    async def _sync_files_to_sandbox(
        self,
        files: List[Dict[str, Any]],
        pipeline_id: Optional[int],
        file_service: SandboxFileService,
    ) -> None:
        """同步文件到沙箱"""
        from app.service.sandbox_manager import sandbox_manager

        for file_change in files:
            file_path = file_change.get("file_path", "")
            content = file_change.get("content", "")

            if file_path and content:
                try:
                    await sandbox_manager.write_file(
                        pipeline_id=pipeline_id,
                        path=file_path,
                        content=content,
                    )
                except Exception as e:
                    logger.warning(f"Failed to sync file to sandbox: {file_path}: {e}")

    def _build_result(
        self,
        success: bool,
        attempt: int,
        start_time: float,
        output: Optional[Dict] = None,
        files: Optional[List[Dict]] = None,
        error: Optional[str] = None,
        fix_history: Optional[List[Dict]] = None,
        fatal_error: bool = False,
    ) -> Dict[str, Any]:
        """构建统一的结果格式"""
        return {
            "success": success,
            "output": output or {},
            "files": files or [],
            "attempt": attempt,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "duration_ms": int((time.time() - start_time) * 1000),
            "error": error,
            "fix_history": fix_history or [],
            "fatal_error": fatal_error,
        }


# 全局单例实例
code_generation_service = CodeGenerationService()
