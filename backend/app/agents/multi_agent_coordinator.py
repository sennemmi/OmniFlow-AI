"""
多 Agent 协作协调器
实现 CoderAgent 和 TestAgent 的协作执行

重构说明：
- 移除 ThreadPoolExecutor，使用纯异步执行
- CoderAgent 和 TestAgent 顺序执行（TestAgent 依赖 CoderAgent 输出）
- 保留结果合并逻辑
- 新增 Auto-Fix Loop：生成 -> 运行 -> 报错 -> 修复 的闭环迭代
"""

import asyncio
import logging
from typing import Dict, List, Optional, TypedDict, Any

from pydantic import BaseModel, Field

from app.agents.coder import coder_agent
from app.agents.tester import test_agent
from app.service.test_runner import TestRunnerService
from app.service.code_executor import CodeExecutorService
from app.core.event_bus import emit_log
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class MultiAgentState(TypedDict):
    """多 Agent 协作状态"""
    design_output: Dict[str, Any]
    target_files: Dict[str, str]
    
    # CoderAgent 输出
    code_output: Optional[Dict[str, Any]]
    code_error: Optional[str]
    
    # TestAgent 输出
    test_output: Optional[Dict[str, Any]]
    test_error: Optional[str]
    
    # 最终结果
    final_output: Optional[Dict[str, Any]]
    error: Optional[str]


class CodeAndTestOutput(BaseModel):
    """代码和测试输出组合"""
    code_files: List[Dict[str, Any]] = Field(description="代码文件列表")
    test_files: List[Dict[str, Any]] = Field(description="测试文件列表")
    code_summary: str = Field(description="代码生成摘要")
    test_summary: str = Field(description="测试生成摘要")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖")
    tests_included: bool = Field(default=True, description="是否包含测试")


class MultiAgentCoordinator:
    """
    多 Agent 协作协调器

    负责协调 CoderAgent 和 TestAgent 的执行：
    1. 调用 CoderAgent 生成代码
    2. 调用 TestAgent 生成测试（依赖 CoderAgent 输出）
    3. 合并输出结果
    4. 支持 Auto-Fix Loop：测试失败时自动修复

    注意：TestAgent 需要 CoderAgent 的输出作为输入，所以是顺序执行
    """

    MAX_FIX_RETRIES = 3  # 最大自动修复次数
    
    async def _execute_code_agent(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent

        Args:
            design_output: DesignerAgent 的输出
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含 code_output 或 code_error，以及指标字段
        """
        logger.info(f"MultiAgentCoordinator: 开始执行 CoderAgent", extra={
            "pipeline_id": pipeline_id,
            "files_count": len(target_files)
        })

        try:
            code_result = await coder_agent.generate_code(design_output, target_files, pipeline_id)

            if code_result["success"]:
                logger.info(f"MultiAgentCoordinator: CoderAgent 执行成功", extra={
                    "pipeline_id": pipeline_id,
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0)
                })
                return {
                    "code_output": code_result["output"],
                    "code_error": None,
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0),
                }
            else:
                logger.error(f"MultiAgentCoordinator: CoderAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "error": code_result["error"],
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0)
                })
                return {
                    "code_output": None,
                    "code_error": code_result["error"],
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0),
                }
        except Exception as e:
            logger.error(f"MultiAgentCoordinator: CoderAgent 执行异常", extra={
                "pipeline_id": pipeline_id,
                "error": str(e)
            })
            return {
                "code_output": None,
                "code_error": f"CoderAgent execution failed: {str(e)}",
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }
    
    async def _execute_test_agent(
        self,
        design_output: Dict[str, Any],
        code_output: Optional[Dict[str, Any]],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 TestAgent

        Args:
            design_output: DesignerAgent 的输出
            code_output: CoderAgent 的输出
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含 test_output 或 test_error，以及指标字段
        """
        # 如果代码生成失败，跳过测试生成
        if not code_output:
            logger.info(f"MultiAgentCoordinator: 跳过测试生成（代码生成失败）", extra={
                "pipeline_id": pipeline_id
            })
            return {
                "test_output": None,
                "test_error": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }

        logger.info(f"MultiAgentCoordinator: 开始执行 TestAgent", extra={
            "pipeline_id": pipeline_id
        })

        try:
            test_result = await test_agent.generate_tests(design_output, code_output, target_files, pipeline_id)

            if test_result["success"]:
                logger.info(f"MultiAgentCoordinator: TestAgent 执行成功", extra={
                    "pipeline_id": pipeline_id,
                    "input_tokens": test_result.get("input_tokens", 0),
                    "output_tokens": test_result.get("output_tokens", 0),
                    "duration_ms": test_result.get("duration_ms", 0)
                })
                return {
                    "test_output": test_result["output"],
                    "test_error": None,
                    "input_tokens": test_result.get("input_tokens", 0),
                    "output_tokens": test_result.get("output_tokens", 0),
                    "duration_ms": test_result.get("duration_ms", 0),
                }
            else:
                logger.warning(f"MultiAgentCoordinator: TestAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "error": test_result["error"],
                    "input_tokens": test_result.get("input_tokens", 0),
                    "output_tokens": test_result.get("output_tokens", 0),
                    "duration_ms": test_result.get("duration_ms", 0)
                })
                return {
                    "test_output": None,
                    "test_error": test_result["error"],
                    "input_tokens": test_result.get("input_tokens", 0),
                    "output_tokens": test_result.get("output_tokens", 0),
                    "duration_ms": test_result.get("duration_ms", 0),
                }
        except Exception:
            logger.error(
                f"MultiAgentCoordinator: TestAgent 执行异常",
                extra={"pipeline_id": pipeline_id},
                exc_info=True
            )
            return {
                "test_output": None,
                "test_error": "TestAgent execution failed (查看后端日志获取详情)",
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }
    
    def _merge_results(
        self,
        code_output: Optional[Dict[str, Any]],
        test_output: Optional[Dict[str, Any]],
        target_files: Dict[str, str],
        code_error: Optional[str] = None,
        test_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并结果：修复元数据丢失问题，注入 original_content
        
        Args:
            code_output: CoderAgent 输出
            test_output: TestAgent 输出
            target_files: 原始文件内容映射
            code_error: 代码生成错误
            test_error: 测试生成错误
            
        Returns:
            Dict: 合并后的 final_output
        """
        # 1. 致命错误检查（仅限代码生成）
        if code_error:
            return {
                "final_output": None,
                "error": f"Code generation failed: {code_error}"
            }

        # 防御性转换
        code_output = code_output if isinstance(code_output, dict) else {}
        test_output = test_output if isinstance(test_output, dict) else {}

        # 2. 合并文件并注入 original_content
        all_files = []
        if code_output.get("files"):
            for f in code_output["files"]:
                # 核心修复：把 target_files 里的原始内容注入每个文件对象
                enriched = dict(f)  # 浅拷贝，不改原对象
                file_path = enriched.get("file_path", "")
                if "original_content" not in enriched:
                    enriched["original_content"] = target_files.get(file_path)  # None 表示新建文件
                all_files.append(enriched)

        # 3. 处理测试输出与非致命错误
        test_files = test_output.get("test_files") or test_output.get("files") or []  # 兼容不同 key

        if test_error:
            # 记录警告但不中断
            current_error = f"Test generation warning: {test_error}"
        else:
            # 测试文件同样注入 original_content（通常是 None，代表新建）
            for f in test_files:
                enriched = dict(f)
                file_path = enriched.get("file_path", "")
                if "original_content" not in enriched:
                    enriched["original_content"] = target_files.get(file_path)
                all_files.append(enriched)
            current_error = None

        # 4. 构建最终输出（确保 coverage_targets 等字段被提取）
        final_output = {
            "files": all_files,
            "summary": self._build_summary(code_output, test_output),
            "dependencies_added": list(set(
                code_output.get("dependencies_added", []) +
                test_output.get("dependencies_added", [])
            )),
            "tests_included": len(test_files) > 0,
            "code_summary": code_output.get("summary", ""),
            "test_summary": test_output.get("summary", "Skipped or failed"),
            # 关键修复：从 test_output 中准确获取 coverage_targets
            "coverage_targets": test_output.get("coverage_targets", []),
            "agent_outputs": {
                "coder": code_output,
                "tester": test_output
            }
        }

        return {
            "final_output": final_output,
            "error": current_error  # 保留非致命错误信息
        }
    
    def _extract_error_summary(self, test_results: Dict[str, Any]) -> str:
        """
        从测试结果中提取关键错误摘要（用于前端展示）

        Args:
            test_results: 测试结果字典

        Returns:
            str: 错误摘要
        """
        error_type = test_results.get("error_type", "unknown_error")
        failed_tests = test_results.get("failed_tests", [])
        summary = test_results.get("summary", "")
        logs = test_results.get("logs", "")

        # 根据错误类型提取关键信息
        if error_type == "syntax_error":
            # 提取语法错误的具体行号和信息
            import re
            syntax_match = re.search(r'SyntaxError: (.+?)(?:\n|$)', logs)
            line_match = re.search(r'line (\d+)', logs)
            if syntax_match:
                error_detail = syntax_match.group(1)
                line_info = f" (第 {line_match.group(1)} 行)" if line_match else ""
                return f"语法错误{line_info}: {error_detail[:100]}"
            return "代码存在语法错误，请检查 Python 语法"

        elif error_type == "import_error":
            # 提取导入错误的模块名
            import re
            import_match = re.search(r"ModuleNotFoundError: No module named ['\"](.+?)['\"]", logs)
            if import_match:
                module_name = import_match.group(1)
                return f"导入错误: 找不到模块 '{module_name}'"
            import_match = re.search(r"ImportError: (.+?)(?:\n|$)", logs)
            if import_match:
                return f"导入错误: {import_match.group(1)[:100]}"
            return "模块导入失败，请检查 import 语句"

        elif error_type == "test_failure":
            # 提取失败的测试名和断言信息
            if failed_tests:
                failed_test = failed_tests[0]
                # 尝试提取断言错误详情
                import re
                assert_match = re.search(r'AssertionError: (.+?)(?:\n|$)', logs)
                if assert_match:
                    return f"测试 '{failed_test}' 断言失败: {assert_match.group(1)[:100]}"
                return f"测试 '{failed_test}' 未通过"
            return f"测试失败: {summary[:100]}"

        elif error_type == "collection_error":
            return f"测试收集错误: {summary[:100]}"

        elif error_type == "timeout":
            return "测试执行超时"

        elif error_type == "pytest_not_found":
            return "未找到 pytest，请检查测试环境"

        else:
            return f"测试失败: {summary[:100]}"

    async def _log_test_failure(
        self,
        pipeline_id: int,
        test_results: Dict[str, Any],
        attempt: int,
        error_summary: str
    ) -> None:
        """
        强化测试失败日志输出

        同时输出到：
        1. 前端 SSE（用户可见）
        2. 后端日志（详细调试信息）

        Args:
            pipeline_id: Pipeline ID
            test_results: 测试结果
            attempt: 当前尝试次数
            error_summary: 错误摘要
        """
        error_type = test_results.get("error_type", "unknown_error")
        failed_tests = test_results.get("failed_tests", [])
        summary = test_results.get("summary", "")
        exit_code = test_results.get("exit_code", -1)

        # 构建详细的错误信息
        details = {
            "attempt": attempt,
            "exit_code": exit_code,
            "failed_tests_count": len(failed_tests),
        }

        # 根据错误类型输出不同的日志
        if error_type == "syntax_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 检测到语法错误",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将检查代码语法并修复",
                **details
            )
            # 额外输出语法错误详情到后端
            logger.error(
                f"[Pipeline {pipeline_id}] 语法错误详情:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "syntax_error"}
            )

        elif error_type == "import_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 模块导入失败",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将检查并修正 import 语句",
                **details
            )
            # 输出导入错误详情
            logger.error(
                f"[Pipeline {pipeline_id}] 导入错误详情:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "import_error"}
            )

        elif error_type == "test_failure":
            # 测试断言失败 - 提供失败的测试列表
            failed_tests_str = ", ".join(failed_tests[:3])
            if len(failed_tests) > 3:
                failed_tests_str += f" 等共 {len(failed_tests)} 个测试"

            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试未通过",
                stage="CODING",
                error_summary=error_summary,
                failed_tests=failed_tests_str,
                suggestion="AI 将分析失败原因并修复代码",
                **details
            )
            # 输出详细的测试失败日志
            logger.error(
                f"[Pipeline {pipeline_id}] 测试失败详情:\n{test_results.get('logs', '')[:2000]}",
                extra={
                    "pipeline_id": pipeline_id,
                    "error_type": "test_failure",
                    "failed_tests": failed_tests,
                    "exit_code": exit_code
                }
            )

        elif error_type == "collection_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试收集错误",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将检查测试文件结构",
                **details
            )
            logger.error(
                f"[Pipeline {pipeline_id}] 测试收集错误:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "collection_error"}
            )

        elif error_type == "timeout":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试执行超时",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将优化测试代码或减少测试范围",
                **details
            )

        elif error_type == "pytest_not_found":
            await emit_log(
                pipeline_id, "error",
                f"❌ 测试环境错误: 未找到 pytest",
                stage="CODING",
                error_summary=error_summary,
                suggestion="请检查测试环境配置",
                **details
            )

        else:
            # 未知错误
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试执行失败",
                stage="CODING",
                error_summary=error_summary,
                summary=summary,
                **details
            )
            logger.error(
                f"[Pipeline {pipeline_id}] 未知测试错误:\n{test_results.get('logs', '')[:2000]}",
                extra={"pipeline_id": pipeline_id, "error_type": error_type}
            )

    def _build_summary(self, code_output: Optional[Dict], test_output: Optional[Dict]) -> str:
        """构建合并后的摘要"""

        parts = []

        if code_output and "summary" in code_output:
            parts.append(f"代码生成: {code_output['summary']}")

        if test_output and "summary" in test_output:
            parts.append(f"测试生成: {test_output['summary']}")

        if test_output and "coverage_targets" in test_output:
            coverage = test_output["coverage_targets"]
            if coverage:
                parts.append(f"测试覆盖: {len(coverage)} 个测试目标")

        return "\n".join(parts) if parts else "代码和测试生成完成"

    async def _ensure_conftest(self, workspace_path: str) -> None:
        """
        [已废弃] 之前这里会暴力覆盖 conftest.py，导致原本的 fixture 丢失。
        现在 import 路径问题已经由 test_runner.py 的 env['PYTHONPATH'] 解决。
        """
        pass
    
    async def execute_parallel(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent 和 TestAgent

        策略：
        1. 先执行 CoderAgent 生成代码
        2. 再执行 TestAgent 生成测试（依赖 CoderAgent 输出）
        3. 合并结果
        4. 汇总指标（input_tokens, output_tokens, duration_ms）

        只要有代码输出，就认为执行成功（部分成功）
        测试生成失败不会导致整体失败

        Args:
            design_output: DesignerAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含合并后的结果或错误信息，以及指标字段
        """
        await emit_log(
            pipeline_id, "info",
            f"🚀 开始执行多 Agent 协作",
            stage="CODING",
            target_files_count=len(target_files)
        )

        # 1. 执行 CoderAgent
        code_result = await self._execute_code_agent(design_output, target_files, pipeline_id)

        # 2. 执行 TestAgent（依赖 CoderAgent 输出）
        test_result = await self._execute_test_agent(
            design_output,
            code_result.get("code_output"),
            target_files,
            pipeline_id
        )

        # 3. 合并结果
        merge_result = self._merge_results(
            code_result.get("code_output"),
            test_result.get("test_output"),
            target_files,
            code_result.get("code_error"),
            test_result.get("test_error")
        )

        # ★ 汇总指标
        input_tokens = (code_result.get("input_tokens", 0) or 0) + \
                       (test_result.get("input_tokens", 0) or 0)
        output_tokens = (code_result.get("output_tokens", 0) or 0) + \
                        (test_result.get("output_tokens", 0) or 0)
        duration_ms = (code_result.get("duration_ms", 0) or 0) + \
                      (test_result.get("duration_ms", 0) or 0)

        final_output = merge_result.get("final_output")
        # 只有当完全没有生成文件，或者存在 code_error 时才判定为失败
        is_failed = code_result.get("code_error") is not None or not final_output or not final_output.get("files")

        if is_failed:
            await emit_log(
                pipeline_id, "error",
                f"❌ 多 Agent 执行失败: {merge_result.get('error') or 'No output generated'}",
                stage="CODING"
            )
            return {
                "success": False,
                "error": merge_result.get("error") or "No output generated",
                "output": final_output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms
            }

        await emit_log(
            pipeline_id, "info",
            f"✅ 多 Agent 执行成功，生成 {len(final_output.get('files', []))} 个文件",
            stage="CODING",
            files_count=len(final_output.get("files", [])),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms
        )

        # 成功时也返回 error，以便调用者看到测试生成的警告
        return {
            "success": True,
            "error": merge_result.get("error"),
            "output": final_output,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": duration_ms
        }

    async def execute_with_auto_fix(
        self,
        design_output: Dict,
        target_files: Dict,
        pipeline_id: int,
        workspace_path: str  # 需要在临时工作区运行
    ) -> Dict[str, Any]:
        """
        执行带自动修复的多 Agent 代码生成

        流程：
        1. CoderAgent 生成代码
        2. CodeExecutor 将代码写入 workspace（临时工作区）
        3. TestRunner 在工作区执行 pytest
        4. 分析结果：
           - Case A (通过): 进入人工 Review 阶段
           - Case B (失败): 将 pytest 报错日志回传给 CoderAgent，增加 retry_count，进入步骤 1
           - Case C (达到最大次数): 标记失败并报错

        Args:
            design_output: DesignerAgent 的输出
            target_files: 目标文件当前内容
            pipeline_id: Pipeline ID
            workspace_path: 临时工作区路径

        Returns:
            Dict: 执行结果，包含累计的指标字段
        """
        import time

        current_error_context = None
        attempt = 0
        last_code_output = None  # 新增：保存最后一次生成的代码

        # ★ 累计指标
        total_input_tokens = 0
        total_output_tokens = 0
        start_time = time.time()

        while attempt <= self.MAX_FIX_RETRIES:
            if attempt > 0:
                await push_log(
                    pipeline_id,
                    "warning",
                    f"检测到测试失败，开始第 {attempt} 次自动修复...",
                    stage="CODING"
                )

            # 1. Coder 生成代码 (传入上一次的报错信息)
            code_result = await coder_agent.generate_code(
                design_output,
                target_files,
                pipeline_id=pipeline_id,
                error_context=current_error_context
            )

            # ★ 累计本次调用的指标
            total_input_tokens += code_result.get("input_tokens", 0) or 0
            total_output_tokens += code_result.get("output_tokens", 0) or 0

            # 新增：只要生成了代码，就保存下来
            if code_result.get("success") and code_result.get("output"):
                last_code_output = code_result["output"]

            if not code_result["success"]:
                logger.error(f"MultiAgentCoordinator: CoderAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "attempt": attempt,
                    "error": code_result["error"],
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens
                })
                return {
                    "success": False,
                    "error": f"Code generation failed: {code_result['error']}",
                    "output": None,
                    "attempt": attempt,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000)
                }

            # 2. 写入文件到工作区（先做 import 修正）
            from app.service.import_sanitizer import ImportSanitizer

            executor = CodeExecutorService(workspace_path)
            all_files = code_result["output"]["files"]

            # ★ 关键：写入前自动修正 import
            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

            # === 终极路径防御：强制将 AI 的文件装进 backend/ 目录 ===
            for f in all_files:
                p = f.get("file_path", "")
                p = p.lstrip("/")  # 去除开头的斜杠
                # 如果 AI 忘记加 backend/ 前缀，我们强行给它加上！
                if p and not p.startswith("backend/"):
                    f["file_path"] = f"backend/{p}"
            # =========================================================

            if fix_report:
                await push_log(
                    pipeline_id, "warning",
                    f"自动修正了 {len(fix_report)} 个文件的 import 路径: {list(fix_report.keys())}",
                    stage="CODING"
                )
                # 把修正报告写回 code_result，让 error_context 能感知
                code_result["output"]["files"] = all_files
                code_result["output"]["import_fixes"] = fix_report

            executor.apply_changes(
                {f["file_path"]: f["content"] for f in all_files},
                create_if_missing=True
            )

            # 2.5 创建 conftest.py 确保测试能正确导入模块
            await self._ensure_conftest(workspace_path)

            # 3. 运行测试 (关键闭环)
            await push_log(
                pipeline_id,
                "info",
                "正在运行自动化测试验证...",
                stage="CODING"
            )

            test_results = await TestRunnerService.run_tests(workspace_path)

            if test_results["success"]:
                await push_log(
                    pipeline_id,
                    "success",
                    "✅ 测试通过！AI 自动验证成功。",
                    stage="CODING"
                )

                # 生成测试代码（基于成功的代码）
                test_result = await self._execute_test_agent(
                    design_output,
                    code_result["output"],
                    target_files,
                    pipeline_id
                )

                # ★ 累计 TestAgent 的指标
                total_input_tokens += test_result.get("input_tokens", 0) or 0
                total_output_tokens += test_result.get("output_tokens", 0) or 0

                # 合并代码和测试
                merge_result = self._merge_results(
                    code_result["output"],
                    test_result.get("test_output"),
                    target_files,
                    code_result.get("error"),
                    test_result.get("test_error")
                )

                return {
                    "success": True,
                    "output": merge_result["final_output"],
                    "test_logs": test_results["logs"],
                    "attempt": attempt,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000)
                }

            # 4. 如果失败，构建详细的错误上下文并重试
            error_type = test_results.get("error_type", "unknown_error")
            failed_tests = test_results.get("failed_tests", [])
            error_message = test_results.get("error", test_results["summary"])
            exit_code = test_results.get("exit_code", -1)
            logs = test_results.get("logs", "")

            # 提取关键错误信息（用于前端展示）
            error_summary = self._extract_error_summary(test_results)

            # 构建结构化的错误上下文，帮助 AI 更好地理解问题
            current_error_context = f"""【测试执行结果】
状态: 失败
错误类型: {error_type}
退出码: {exit_code}
总结: {test_results['summary']}

【详细错误信息】
{error_message}

【失败的测试】
{chr(10).join(failed_tests) if failed_tests else '无特定测试失败（可能是收集错误或语法错误）'}

【完整日志】
{logs[:3000] if len(logs) > 3000 else logs}
"""

            # 强化日志输出：根据错误类型提供更详细的日志信息
            await self._log_test_failure(pipeline_id, test_results, attempt, error_summary)

            # 同步详细错误到后端日志
            logger.error(f"MultiAgentCoordinator: 测试执行失败详情", extra={
                "pipeline_id": pipeline_id,
                "attempt": attempt,
                "error_type": error_type,
                "exit_code": exit_code,
                "summary": test_results["summary"],
                "failed_tests": failed_tests,
                "error_message": error_message,
                "logs_preview": logs[:2000] if logs else "",
                "workspace_path": workspace_path
            })

            attempt += 1

        # 达到最大重试次数
        logger.error(f"MultiAgentCoordinator: 自动修复达到最大次数", extra={
            "pipeline_id": pipeline_id,
            "max_retries": self.MAX_FIX_RETRIES,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens
        })

        return {
            "success": False,
            "error": f"自动修复达到最大次数({self.MAX_FIX_RETRIES})，仍有测试未通过。",
            "last_error_logs": current_error_context,
            "attempt": attempt,
            "output": last_code_output,  # 新增：把最后一次生成的代码传出去
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "duration_ms": int((time.time() - start_time) * 1000)
        }


# 单例实例
multi_agent_coordinator = MultiAgentCoordinator()
