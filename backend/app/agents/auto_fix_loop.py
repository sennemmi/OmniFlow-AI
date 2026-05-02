"""
Auto-Fix 循环模块

负责代码生成、测试、修复的完整闭环编排
"""

import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional, Any, Set
from pathlib import Path

from app.agents.coder import coder_agent
from app.agents.tester import test_agent
from app.agents.repairer_with_tools import RepairerAgentWithTools
from app.service.sandbox_manager import sandbox_manager
from app.service.code_executor import CodeExecutorService
from app.service.file_write_handler import file_write_handler
from app.service.file_writer import FileWriterService
from app.service.import_sanitizer import ImportSanitizer
from app.service.error_context_parser import parse_error_context
from app.core.code_validator import code_validator
from app.core.event_bus import emit_log
from app.core.sse_log_buffer import push_log
from app.core.config import settings
from app.core.resilience import ResilienceManager, RetryConfig, CircuitBreakerOpenError
from app.core.contract_checker import check_contract_before_test, ContractViolationError


def extract_missing_symbols(logs: str) -> List[str]:
    """
    从测试日志中提取缺失的符号名

    解析 ImportError 和 ModuleNotFoundError，提取无法导入的符号名称
    """
    missing = []

    # 匹配 ImportError: cannot import name 'xxx'
    import_errors = re.findall(r"ImportError: cannot import name ['\"](\w+)['\"]", logs)
    missing.extend(import_errors)

    # 匹配 ModuleNotFoundError: No module named 'xxx'
    module_errors = re.findall(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]", logs)
    missing.extend(module_errors)

    # 匹配 AttributeError: module 'xxx' has no attribute 'yyy'
    attr_errors = re.findall(r"AttributeError: module ['\"][\w.]+['\"] has no attribute ['\"](\w+)['\"]", logs)
    missing.extend(attr_errors)

    # 匹配 NameError: name 'xxx' is not defined
    name_errors = re.findall(r"NameError: name ['\"](\w+)['\"] is not defined", logs)
    missing.extend(name_errors)

    return list(set(missing))

logger = logging.getLogger(__name__)

# 【致命错误】上下文超限等不可重试的错误签名
FATAL_ERRORS = [
    "choices': None",       # 上下文超限，重试无效
    "choices is None",
    "completion_tokens': 0, 'prompt_tokens': 0",
    "context length exceeded",
    "maximum context length",
    "token limit exceeded",
]


def _is_fatal_error(error_msg: str) -> bool:
    """判断是否是不可重试的致命错误（如上下文超限）"""
    if not error_msg:
        return False
    return any(sig in error_msg for sig in FATAL_ERRORS)


class AutoFixLoop:
    """
    Auto-Fix 循环编排器

    实现 生成 -> 运行 -> 报错 -> 修复 的闭环迭代
    """

    MAX_FIX_RETRIES = 3  # 最大自动修复次数

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # 【智能重试】初始化测试运行重试执行器
        self._test_retry_executor = ResilienceManager.get_executor(
            name="test_runner",
            **RetryConfig.TEST_RUN
        )

    async def execute(
        self,
        design_output: Dict,
        affected_files: List[str],
        pipeline_id: int,
        workspace_path: str,
        sandbox_port: Optional[int] = None,
        error_context: Optional[str] = None,
        injected_files: Optional[Dict[str, str]] = None,
        file_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        执行带自动修复的多 Agent 代码生成

        【改造】不再传入预加载的 target_files，改为传入 affected_files 列表
        【核心】支持 injected_files 参数，由上游 ArchitectAgent 预读取的文件内容
        【新架构】支持 file_service 参数，用于直接操作 Sandbox 中的文件
        """
        current_error_context = error_context
        attempt = 0
        last_code_output = None

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        start_time = time.time()

        # ★ 读取测试文件（供参考，不强制 AI 使用）
        test_files = await self._read_test_files(pipeline_id, affected_files)

        if test_files:
            await push_log(
                pipeline_id,
                "info",
                f"📄 找到 {len(test_files)} 个相关测试文件，将提供给 AI 参考",
                stage="CODING"
            )

        if injected_files:
            await push_log(
                pipeline_id,
                "info",
                f"📦 从 ArchitectAgent 获取到 {len(injected_files)} 个预读取文件",
                stage="CODING"
            )

        while attempt <= self.MAX_FIX_RETRIES:
            if attempt > 0:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"检测到测试失败，开始第 {attempt} 次自动修复...",
                    stage="CODING"
                )

            # 1. Coder 生成代码（透传 injected_files）
            code_result = await self._execute_code_agent(
                design_output,
                test_files,
                pipeline_id=pipeline_id,
                error_context=current_error_context,
                injected_files=injected_files  # 【核心】透传上游注入的文件内容
            )

            self.total_input_tokens += code_result.get("input_tokens", 0) or 0
            self.total_output_tokens += code_result.get("output_tokens", 0) or 0

            if code_result.get("success") and code_result.get("code_output"):
                last_code_output = code_result["code_output"]

            if not code_result["success"]:
                error_msg = code_result.get("error", "")

                # 【致命错误判断】如果是上下文超限等不可重试错误，直接返回
                if _is_fatal_error(error_msg):
                    logger.error(f"AutoFixLoop: 检测到不可重试的致命错误（上下文超限），中止重试", extra={
                        "pipeline_id": pipeline_id,
                        "attempt": attempt,
                        "error": error_msg,
                        "total_input_tokens": self.total_input_tokens,
                        "total_output_tokens": self.total_output_tokens
                    })
                    await push_log(
                        pipeline_id,
                        "error",
                        f"❌ 检测到上下文超限错误，无法继续。建议减少同时修改的文件数量。",
                        stage="CODING"
                    )
                    return {
                        "success": False,
                        "error": f"Context limit exceeded: {error_msg}",
                        "output": None,
                        "attempt": attempt,
                        "input_tokens": self.total_input_tokens,
                        "output_tokens": self.total_output_tokens,
                        "duration_ms": int((time.time() - start_time) * 1000),
                        "fatal_error": True
                    }

                logger.error(f"AutoFixLoop: CoderAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "attempt": attempt,
                    "error": error_msg,
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens
                })
                return {
                    "success": False,
                    "error": f"Code generation failed: {error_msg}",
                    "output": None,
                    "attempt": attempt,
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000)
                }

            # 2. 处理生成的文件
            code_output = code_result.get("code_output", {})
            all_files = code_output.get("files", [])

            # 【工具驱动写入】检查工具执行结果中的文件修改
            tool_results = code_result.get("tool_results", [])
            files_from_tools = []
            for tool_result in tool_results:
                if tool_result.get("tool") == "replace_lines" and tool_result.get("success"):
                    file_path = tool_result.get("arguments", {}).get("file_path", "")
                    if file_path:
                        files_from_tools.append({
                            "file_path": file_path,
                            "change_type": "modify",
                            "description": f"通过 replace_lines 工具修改"
                        })

            # 合并工具修改的文件和输出中声明的文件
            if files_from_tools:
                # 以工具实际修改的文件为准
                all_files = files_from_tools
                logger.info(f"[Pipeline {pipeline_id}] 从工具结果中提取 {len(files_from_tools)} 个修改文件")
                await push_log(
                    pipeline_id, "info",
                    f"📝 通过工具调用完成 {len(files_from_tools)} 个文件的修改",
                    stage="CODING"
                )

            if not all_files:
                return {
                    "success": False,
                    "error": "No files generated by CoderAgent",
                    "output": None,
                    "attempt": attempt,
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000)
                }

            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

            # 路径防御
            for f in all_files:
                p = f.get("file_path", "")
                p = p.lstrip("/")
                if p and not p.startswith("backend/"):
                    f["file_path"] = f"backend/{p}"

            if fix_report:
                await push_log(
                    pipeline_id, "warning",
                    f"自动修正了 {len(fix_report)} 个文件的 import 路径",
                    stage="CODING"
                )
                code_output["files"] = all_files
                code_output["import_fixes"] = fix_report

            # 【改造后】使用 FileWriterService 写入文件（CoderAgent 已不再使用工具）
            file_writer = FileWriterService(settings.TARGET_PROJECT_PATH)
            write_results = file_writer.apply_changes(all_files)

            # 检查写入结果
            failed_writes = [r for r in write_results if not r.get("success")]
            if failed_writes:
                failed_files = [r.get("file") for r in failed_writes]
                error_msgs = [f"{r.get('file')}: {r.get('error')}" for r in failed_writes]
                logger.error(f"[Pipeline {pipeline_id}] 文件写入失败: {failed_files}")
                await push_log(
                    pipeline_id, "error",
                    f"❌ 文件写入失败 ({len(failed_writes)} 个): {', '.join(failed_files[:3])}",
                    stage="CODING"
                )

                # 构建错误上下文，让 CoderAgent 在下次重试时修复
                current_error_context = (
                    f"文件写入失败，请检查 search_block 是否精确匹配文件内容。\n"
                    f"失败文件:\n" + "\n".join(error_msgs[:5])
                )
                attempt += 1
                continue

            # 写入成功，同步到 sandbox
            await self._sync_files_to_sandbox(all_files, pipeline_id)

            await push_log(
                pipeline_id, "info",
                f"✅ 文件写入成功 ({len(all_files)} 个文件)",
                stage="CODING"
            )

            # 【语法验证】在契约检查前验证代码语法（同步 E2E 测试脚本的 Step 5）
            await push_log(
                pipeline_id, "info",
                "🔍 执行代码语法验证...",
                stage="CODING"
            )

            syntax_errors = await self._validate_code_syntax(all_files, pipeline_id)
            if syntax_errors:
                await push_log(
                    pipeline_id, "warning",
                    f"⚠️ 发现 {len(syntax_errors)} 个语法错误，启动修复...",
                    stage="CODING"
                )

                # 构建语法错误修复上下文
                error_details = "\n".join([
                    f"- {err.get('file', 'unknown')}: {err.get('error', 'unknown error')}"
                    for err in syntax_errors[:5]
                ])
                current_error_context = (
                    f"【语法错误】代码存在以下语法错误，请修复:\n{error_details}\n\n"
                    f"请确保所有生成的代码都是合法的 Python 语法。"
                )
                attempt += 1
                continue

            await push_log(
                pipeline_id, "success",
                "✅ 语法验证通过",
                stage="CODING"
            )

            # 【前置契约检查】在运行测试前验证代码是否满足契约
            await push_log(
                pipeline_id, "info",
                "🔍 执行前置契约检查...",
                stage="CODING"
            )

            # 构建 code_files 字典（从 all_files 中提取内容）
            code_files_dict = {}
            for file_change in all_files:
                file_path = file_change.get("file_path", "")
                content = file_change.get("content", "")
                if file_path and content:
                    code_files_dict[file_path] = content

            contract_check = check_contract_before_test(
                design_output=design_output,
                code_files=code_files_dict
            )

            if not contract_check.get("success", True):
                violations = contract_check.get("violations", [])
                check_type = contract_check.get("type", "unknown")

                logger.error(f"[Pipeline {pipeline_id}] 契约检查失败: {check_type}")
                await push_log(
                    pipeline_id, "error",
                    f"❌ 契约检查失败: 发现 {len(violations)} 个问题",
                    stage="CODING"
                )

                for v in violations[:5]:
                    await push_log(
                        pipeline_id, "error",
                        f"  - {v}",
                        stage="CODING"
                    )

                # 构建错误上下文，让 CoderAgent 修复缺失的实现
                current_error_context = (
                    f"【契约检查失败】代码未满足接口契约要求:\n"
                    f"{chr(10).join(violations[:10])}\n\n"
                    f"请确保实现了所有 interface_specs 中声明的函数/类。"
                )
                attempt += 1
                continue

            await push_log(
                pipeline_id, "success",
                "✅ 契约检查通过",
                stage="CODING"
            )

            # 3. 【阶段二：独立验证步骤】使用 VerifyAgent 进行验证
            verify_result = await self._verify_fixes(pipeline_id, all_files)

            if verify_result["verdict"] == "PASS":
                # 验证通过，退出循环
                await push_log(
                    pipeline_id,
                    "success",
                    "✅ 独立验证通过！AI 自动验证成功。",
                    stage="CODING"
                )

                # 启动预览服务器
                await self._start_preview_server(pipeline_id, sandbox_port)

                return {
                    "success": True,
                    "output": code_result["code_output"],
                    "attempt": attempt,
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "preview_port": sandbox_port
                }

            elif verify_result["verdict"] == "FAIL":
                # 【利益隔离】RepairerAgent 修复阶段
                # 【简化】直接使用原始测试日志，不再进行复杂的结构化解析
                raw_logs = verify_result.get("raw_logs", "")
                failed_tests = verify_result.get("failed_tests", [])
                missing_symbols = verify_result.get("missing_symbols", [])

                await push_log(
                    pipeline_id, "warning",
                    f"📝 验证失败，生成修复工单并调用 RepairerAgent（第 {attempt + 1} 次修复）...",
                    stage="CODING"
                )

                # 【调试】打印详细错误信息
                logger.info(f"[Pipeline {pipeline_id}] 【调试】验证失败详情:")
                logger.info(f"[Pipeline {pipeline_id}] 【调试】 - failed_tests 数量: {len(failed_tests)}")
                logger.info(f"[Pipeline {pipeline_id}] 【调试】 - 原始日志长度: {len(raw_logs)} 字符")
                logger.info(f"[Pipeline {pipeline_id}] 【调试】 - all_files: {[f.get('file_path', '') for f in all_files]}")

                # 【简化】构建修复工单 - 直接发送原始报错信息
                fix_order = {
                    "type": "fix_order",
                    "category": "code_bug",
                    "source": "VerificationAgent",
                    "failed_tests": failed_tests,
                    "error_logs": raw_logs[:3000],  # 发送原始报错日志（限制长度避免超限）
                    "generated_files": [f.get("file_path", "") for f in all_files],
                    "missing_symbols": missing_symbols,
                    "fix_hint": "根据测试失败日志修复代码，务必使所有测试通过。"
                }

                # 如果有缺失符号，添加到提示中
                if missing_symbols:
                    fix_order["fix_hint"] += f"\n【关键】以下符号缺失，必须实现: {', '.join(missing_symbols)}"

                # 【调试】打印修复工单
                logger.info(f"[Pipeline {pipeline_id}] 【调试】修复工单已生成，包含 {len(failed_tests)} 个失败测试")

                await push_log(
                    pipeline_id, "info",
                    f"📋 修复工单已生成: {len(failed_tests)} 个失败测试",
                    stage="CODING"
                )

                # 【新架构】收集所有相关文件的完整内容
                # 从 all_files 中提取文件内容
                target_files = {}
                for file_info in all_files:
                    file_path = file_info.get("file_path", "")
                    content = file_info.get("content", "")
                    if file_path and content:
                        # 标准化路径
                        clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                        target_files[clean_path] = content
                        logger.info(f"[Pipeline {pipeline_id}] 【调试】准备传入 RepairerAgent: {clean_path} ({len(content)} 字符)")
                
                # 如果没有从 all_files 获取到内容，尝试从 file_service 读取
                if not target_files and file_service:
                    logger.info(f"[Pipeline {pipeline_id}] 从 Sandbox 读取文件内容用于修复")
                    for file_info in all_files:
                        file_path = file_info.get("file_path", "")
                        if file_path:
                            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                            read_res = await file_service.read_file(clean_path)
                            if read_res.exists and read_res.content:
                                target_files[clean_path] = read_res.content
                                logger.info(f"[Pipeline {pipeline_id}] 【调试】从 Sandbox 读取: {clean_path} ({len(read_res.content)} 字符)")
                
                if not target_files:
                    logger.error(f"[Pipeline {pipeline_id}] 无法获取任何文件内容用于修复")
                    await push_log(
                        pipeline_id, "error",
                        "❌ 无法获取文件内容，修复失败",
                        stage="CODING"
                    )
                    attempt += 1
                    continue
                
                logger.info(f"[Pipeline {pipeline_id}] 共传入 {len(target_files)} 个文件的完整内容给 RepairerAgentWithTools")

                # 【利益隔离核心】调用 RepairerAgentWithTools 进行修复（支持工具调用和多轮对话）
                repairer = RepairerAgentWithTools()
                repair_result = await repairer.execute_with_tools(
                    pipeline_id=pipeline_id,
                    stage_name="CODING_REPAIR",
                    fix_order=fix_order,
                    target_files=target_files,  # 【关键】直接传入完整文件内容
                    file_service=file_service,  # 【新架构】传入 SandboxFileService 用于写入修复
                    max_rounds=3  # 最多3轮修复
                )

                if not repair_result.get("success"):
                    logger.error(f"[Pipeline {pipeline_id}] RepairerAgent 修复失败")
                    logger.error(f"[Pipeline {pipeline_id}] 【调试】修复结果: {json.dumps(repair_result, indent=2, ensure_ascii=False)[:1000]}")
                    await push_log(
                        pipeline_id, "error",
                        f"❌ RepairerAgent 修复失败: {repair_result.get('error', '未知错误')}",
                        stage="CODING"
                    )
                    # 【调试】打印更多错误信息
                    if repair_result.get('tool_results'):
                        logger.info(f"[Pipeline {pipeline_id}] 【调试】工具调用结果: {repair_result.get('tool_results')}")
                    if repair_result.get('injected_files'):
                        logger.info(f"[Pipeline {pipeline_id}] 【调试】读取的文件: {list(repair_result.get('injected_files', {}).keys())}")
                    attempt += 1
                    continue

                # 修复成功，更新 code_output
                repair_output = repair_result.get("output", {})
                if repair_output and "files" in repair_output:
                    all_files = repair_output["files"]
                    code_result["code_output"] = repair_output
                    logger.info(f"[Pipeline {pipeline_id}] RepairerAgent 修复完成，生成 {len(all_files)} 个文件修复")
                    await push_log(
                        pipeline_id, "info",
                        f"✅ RepairerAgent 修复完成，应用 {len(all_files)} 个文件修复",
                        stage="CODING"
                    )
                    await push_log(
                        pipeline_id, "info",
                        "🔄 修复已应用，将重新进行独立验证...",
                        stage="CODING"
                    )

                attempt += 1
                continue

        # 达到最大重试次数
        logger.error(f"AutoFixLoop: 自动修复达到最大次数", extra={
            "pipeline_id": pipeline_id,
            "max_retries": self.MAX_FIX_RETRIES,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens
        })

        return {
            "success": False,
            "error": f"自动修复达到最大次数({self.MAX_FIX_RETRIES})，仍有测试未通过。",
            "last_error_logs": current_error_context,
            "attempt": attempt,
            "output": last_code_output,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    async def _execute_code_agent(
        self,
        design_output: Dict[str, Any],
        test_files: Dict[str, str],
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None,
        injected_files: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """执行 CoderAgent"""
        from app.agents.coder import coder_agent

        logger.info(f"AutoFixLoop: 开始执行 CoderAgent", extra={
            "pipeline_id": pipeline_id,
            "affected_files": design_output.get("affected_files", []),
            "test_files_count": len(test_files),
            "injected_files_count": len(injected_files) if injected_files else 0
        })

        # 构建增强的 design_output（包含测试文件参考）
        enhanced_design = self._build_coder_prompt_with_tests(design_output, {}, test_files)

        try:
            code_result = await coder_agent.generate_code(
                design_output=enhanced_design,
                pipeline_id=pipeline_id,
                error_context=error_context,
                injected_files=injected_files  # 【核心】透传上游注入的文件内容
            )

            if code_result["success"]:
                return {
                    "success": True,
                    "code_output": code_result["output"],
                    "code_error": None,
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0),
                }
            else:
                return {
                    "success": False,
                    "code_output": None,
                    "code_error": code_result["error"],
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0),
                }
        except Exception as e:
            logger.error(f"AutoFixLoop: CoderAgent 执行异常", extra={
                "pipeline_id": pipeline_id,
                "error": str(e)
            })
            return {
                "success": False,
                "code_output": None,
                "code_error": f"CoderAgent execution failed: {str(e)}",
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }

    async def _read_test_files(
        self,
        pipeline_id: int,
        affected_files: List[str]
    ) -> Dict[str, str]:
        """根据 affected_files 读取对应的测试文件"""
        test_files = {}

        for file_path in affected_files:
            path_parts = file_path.split('/')
            if len(path_parts) < 2:
                continue

            file_name = path_parts[-1]
            module_name = file_name.replace('.py', '')

            possible_test_paths = [
                f"backend/tests/unit/test_{module_name}_api.py",
                f"backend/tests/unit/test_{module_name}.py",
                f"backend/tests/test_{module_name}.py",
            ]

            for test_path in possible_test_paths:
                try:
                    content = await sandbox_manager.read_file(pipeline_id, test_path)
                    if content:
                        test_files[test_path] = content
                        logger.info(f"读取测试文件成功: {test_path}", extra={
                            "pipeline_id": pipeline_id,
                            "test_file": test_path
                        })
                        break
                except Exception:
                    continue

        return test_files

    def _build_coder_prompt_with_tests(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        test_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """构建包含测试文件的 CoderAgent 输入"""
        if not test_files:
            return design_output

        enhanced_design = dict(design_output)
        enhanced_design["test_files_reference"] = {
            "description": "以下是对应的测试文件内容，供参考（绝对不能修改测试文件）",
            "files": {
                path: content[:3000]
                for path, content in test_files.items()
            }
        }

        return enhanced_design

    async def _write_files_to_sandbox(
        self,
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """写入文件到容器（用于实时预览）"""
        for file_change in all_files:
            await sandbox_manager.write_file(
                pipeline_id=pipeline_id,
                path=file_change["file_path"],
                content=file_change["content"]
            )

    async def _sync_files_to_sandbox(
        self,
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """
        同步已修改的文件到 sandbox（工具驱动模式）

        在工具驱动模式下，文件已通过 replace_lines 工具写入项目目录，
        此方法将文件同步到 sandbox 容器用于预览。
        
        【P3】对于没有 content 的文件，从宿主机项目目录读取最新内容再同步。
        """
        from app.core.config import settings
        from pathlib import Path

        target_path = Path(settings.TARGET_PROJECT_PATH)
        if not target_path.is_absolute():
            backend_dir = Path(__file__).parent.parent
            target_path = backend_dir.parent / settings.TARGET_PROJECT_PATH

        logger.info(f"[Pipeline {pipeline_id}] 【P3】开始同步 {len(all_files)} 个文件到 sandbox")
        
        files_read_from_host = 0
        files_with_content = 0
        sync_success = 0
        sync_failed = 0

        for file_change in all_files:
            file_path = file_change.get("file_path", "")
            content = file_change.get("content", "")
            
            if not file_path:
                logger.warning(f"[Pipeline {pipeline_id}] 【P3】跳过没有 file_path 的文件变更")
                continue

            # 【P3】如果没有 content，从宿主机项目目录读取
            if not content:
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")
                full_path = target_path / relative_path
                
                try:
                    if full_path.exists():
                        content = full_path.read_text(encoding='utf-8')
                        files_read_from_host += 1
                        logger.info(f"[Pipeline {pipeline_id}] 【P3】从宿主机读取文件内容: {full_path} ({len(content)} 字符)")
                    else:
                        logger.warning(f"[Pipeline {pipeline_id}] 【P3】文件不存在，跳过同步: {full_path}")
                        continue
                except Exception as e:
                    logger.error(f"[Pipeline {pipeline_id}] 【P3】读取文件失败 {file_path}: {e}")
                    sync_failed += 1
                    continue
            else:
                files_with_content += 1
            
            # 同步到 sandbox
            try:
                await sandbox_manager.write_file(
                    pipeline_id=pipeline_id,
                    path=file_path,
                    content=content
                )
                sync_success += 1
                logger.debug(f"[Pipeline {pipeline_id}] 【P3】同步文件到 sandbox: {file_path}")
            except Exception as e:
                sync_failed += 1
                logger.error(f"[Pipeline {pipeline_id}] 【P3】同步文件失败 {file_path}: {e}")
        
        logger.info(f"[Pipeline {pipeline_id}] 【P3】同步完成: {sync_success} 成功, {sync_failed} 失败, "
                   f"{files_read_from_host} 从宿主机读取, {files_with_content} 已有 content")

    async def _validate_code_syntax(
        self,
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> List[Dict[str, Any]]:
        """
        验证代码语法（同步 E2E 测试脚本的语法验证逻辑）

        Args:
            all_files: 代码文件列表
            pipeline_id: Pipeline ID

        Returns:
            语法错误列表，如果没有错误返回空列表
        """
        import py_compile
        import tempfile
        import os

        syntax_errors = []

        for file_change in all_files:
            file_path = file_change.get("file_path", "")
            content = file_change.get("content", "")

            if not file_path or not content:
                continue

            # 只检查 Python 文件
            if not file_path.endswith(".py"):
                continue

            # 创建临时文件进行语法检查
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                py_compile.compile(tmp_path, doraise=True)
            except py_compile.PyCompileError as e:
                # 提取行号
                line_no = 0
                error_msg = str(e)
                if "line" in error_msg.lower():
                    import re
                    line_match = re.search(r'line\s+(\d+)', error_msg, re.IGNORECASE)
                    if line_match:
                        line_no = int(line_match.group(1))

                syntax_errors.append({
                    "file": file_path,
                    "error": error_msg,
                    "line": line_no
                })
                logger.warning(f"[Pipeline {pipeline_id}] 语法错误: {file_path} - {error_msg}")
            finally:
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return syntax_errors

    async def _verify_fixes(
        self,
        pipeline_id: int,
        all_files: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        【阶段二：独立验证步骤 - 利益隔离核心】

        独立的验证步骤，与修复者（RepairerAgent）完全分离。
        """
        logger.info(f"[Pipeline {pipeline_id}] 开始独立验证步骤（利益隔离）")
        await push_log(
            pipeline_id,
            "info",
            "🔍 独立验证步骤（VerifyAgent）- 只检测，不修复...",
            stage="CODING"
        )

        # 运行测试
        test_result = await self._run_tests_in_sandbox(pipeline_id)

        # 构建验证报告
        if test_result.get("success"):
            logger.info(f"[Pipeline {pipeline_id}] ✅ 验证通过")
            await push_log(
                pipeline_id,
                "success",
                "✅ Verification PASSED: 所有测试通过",
                stage="CODING"
            )
            return {
                "verdict": "PASS",
                "errors": [],
                "summary": "所有测试通过",
                "structured_errors": None,
                "message": "Verification PASSED: 所有测试通过。",
                "evidence": test_result.get("evidence", {})
            }

        # 测试失败，解析结构化错误
        logs = test_result.get("logs", "")
        error_type = test_result.get("error_type", "unknown")
        generated_files = [f.get("file_path", "") for f in all_files]

        structured_errors = parse_error_context(
            logs=logs,
            failure_cause=error_type,
            generated_files=generated_files
        )

        # 【新增】提取缺失符号信息
        missing_symbols = extract_missing_symbols(logs)
        if missing_symbols:
            logger.warning(f"[Pipeline {pipeline_id}] 检测到缺失符号: {missing_symbols}")
            await push_log(
                pipeline_id,
                "warning",
                f"⚠️ 检测到缺失符号: {', '.join(missing_symbols)}",
                stage="CODING"
            )
            # 将缺失符号信息添加到结构化错误中
            structured_errors["missing_symbols"] = missing_symbols

        error_list = []
        for error in structured_errors.get("errors", []):
            file_path = error.get("file_path", "unknown")
            line = error.get("line", "?")
            summary = error.get("summary", "")
            error_list.append(f"[{file_path}:{line}] {summary}")

        logger.warning(f"[Pipeline {pipeline_id}] ❌ 验证失败: {len(error_list)} 个错误")
        await push_log(
            pipeline_id,
            "warning",
            f"❌ Verification FAILED: 发现 {len(error_list)} 个错误",
            stage="CODING",
            errors=error_list[:5]
        )

        # 【简化】直接从 test_result 获取 failed_tests
        failed_tests = test_result.get("failed_tests", [])

        return {
            "verdict": "FAIL",
            "errors": error_list,
            "failed_tests": failed_tests,  # 【新增】返回失败的测试名称列表
            "summary": test_result.get("summary", "测试失败"),
            "structured_errors": structured_errors,
            "missing_symbols": missing_symbols,  # 【新增】返回缺失符号列表
            "raw_logs": logs[:3000],  # 【增加】原始日志长度
            "message": (
                "Verification FAILED: 代码未通过测试。以下是失败的测试清单和关键日志。"
                "请将本报告交还给修复系统，不要尝试修复。"
            ),
            "evidence": test_result.get("evidence", {})
        }

    async def _run_tests_in_sandbox(
        self,
        pipeline_id: int,
        test_files: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """在沙箱内运行测试（带智能重试）"""
        await push_log(
            pipeline_id,
            "info",
            "正在运行自动化测试验证（沙箱内）...",
            stage="CODING"
        )

        async def _do_run_tests():
            # 【优化】移除 -x 参数，让 pytest 跑完全部测试，一次性收集所有失败
            # 【重要】不再使用 tail 截断日志，确保获取所有错误信息
            test_result_cmd = await sandbox_manager.exec_command(
                pipeline_id=pipeline_id,
                cmd="cd /workspace/backend && python -m pytest tests/ -v --tb=short --color=no 2>&1",
                timeout=120
            )
            return test_result_cmd

        try:
            test_result_cmd = await self._test_retry_executor.execute(_do_run_tests)
        except CircuitBreakerOpenError:
            await push_log(
                pipeline_id,
                "error",
                "测试服务暂时不可用，系统正在冷却，请稍后再试...",
                stage="CODING"
            )
            return {
                "success": False,
                "exit_code": -1,
                "logs": "Circuit breaker open",
                "summary": "测试服务暂时不可用",
                "error": "测试服务暂时不可用，系统正在冷却",
                "error_type": "circuit_breaker_open",
                "failed_tests": [],
                "is_test_file_error": False
            }
        except Exception as e:
            logger.error(f"Test execution failed after retries: {e}")
            await push_log(
                pipeline_id,
                "error",
                f"测试执行失败: {str(e)}",
                stage="CODING"
            )
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": "测试执行失败",
                "error": str(e),
                "error_type": "execution_error",
                "failed_tests": [],
                "is_test_file_error": False
            }

        test_logs = test_result_cmd['stdout'] + test_result_cmd['stderr']
        test_success = test_result_cmd['exit_code'] == 0

        # 分析错误类型
        error_type = None
        failed_tests = []

        if not test_success:
            import re

            if "SyntaxError" in test_logs and "test_" in test_logs:
                error_type = "test_syntax_error"
            elif "ImportError" in test_logs or "ModuleNotFoundError" in test_logs:
                if "test_" in test_logs or "tests/" in test_logs:
                    error_type = "test_import_error"
                else:
                    error_type = "import_error"
            elif "collection error" in test_logs.lower() or "ImportError while loading" in test_logs:
                error_type = "test_collection_error"
            elif "FAILED" in test_logs or "failed" in test_logs.lower():
                error_type = "test_failure"
                # 【修复】修正正则表达式，匹配 pytest 的 FAILED 格式
                # pytest 格式: FAILED tests/test_file.py::test_func
                failed_matches = re.findall(r'FAILED\s+(\S+::\S+)', test_logs)
                failed_tests = failed_matches
            elif "timeout" in test_logs.lower():
                error_type = "timeout"
            else:
                error_type = "unknown_error"

        return {
            "success": test_success,
            "exit_code": test_result_cmd['exit_code'],
            "logs": test_logs,
            "summary": "测试通过" if test_success else "测试失败",
            "error": None if test_success else test_logs[:500],
            "error_type": error_type,
            "failed_tests": failed_tests,
            "is_test_file_error": error_type in ["test_syntax_error", "test_import_error", "test_collection_error"] if error_type else False
        }

    async def _start_preview_server(
        self,
        pipeline_id: int,
        sandbox_port: Optional[int]
    ) -> bool:
        """启动预览服务器"""
        await push_log(
            pipeline_id,
            "info",
            "🚀 检查后端服务状态...",
            stage="CODING"
        )

        # 首先检查 8000 端口
        health_check_8000 = await sandbox_manager.exec_command(
            pipeline_id=pipeline_id,
            cmd="curl -s http://localhost:8000/api/v1/health 2>&1",
            timeout=5
        )

        if health_check_8000['exit_code'] == 0 and 'healthy' in health_check_8000['stdout']:
            await push_log(
                pipeline_id,
                "success",
                f"✅ 后端服务已在 8000 端口运行，可通过端口 {sandbox_port} 访问预览",
                stage="CODING"
            )
            return True

        # 如果 8000 端口没有服务，尝试在 8001 端口启动
        await push_log(
            pipeline_id,
            "info",
            "在 8001 端口启动后端服务...",
            stage="CODING"
        )

        await sandbox_manager.exec_command(
            pipeline_id=pipeline_id,
            cmd="cd /workspace/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info > /tmp/preview_server.log 2>&1 &",
            timeout=3
        )

        await asyncio.sleep(5)

        health_check = await sandbox_manager.exec_command(
            pipeline_id=pipeline_id,
            cmd="curl -s http://localhost:8001/api/v1/health 2>&1",
            timeout=10
        )

        if health_check['exit_code'] == 0 and 'healthy' in health_check['stdout']:
            await push_log(
                pipeline_id,
                "success",
                f"✅ 后端服务已启动，可通过端口 {sandbox_port} 访问预览",
                stage="CODING"
            )
            return True
        else:
            await push_log(
                pipeline_id,
                "warning",
                "⚠️ 后端服务启动可能有问题，但代码已生成",
                stage="CODING"
            )
            return False


# 单例实例
auto_fix_loop = AutoFixLoop()
