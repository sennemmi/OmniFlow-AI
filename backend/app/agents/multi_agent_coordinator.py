"""
多 Agent 协作协调器
实现 CoderAgent 和 TestAgent 的协作执行

【重构说明】
- 核心逻辑已拆分到独立模块：
  - app/core/code_validator.py - 代码验证
  - app/service/search_replace_engine.py - 搜索替换引擎
  - app/service/file_write_handler.py - 文件写入处理
  - app/agents/auto_fix_loop.py - Auto-Fix 循环
- 本模块保留门面方法，负责协调各模块
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, TypedDict, Any
from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.coder import coder_agent
from app.agents.tester import test_agent
from app.agents.auto_fix_loop import auto_fix_loop
from app.service.sandbox_tools import write_file as sandbox_write_file
from app.service.code_executor import CodeExecutorService
from app.service.search_replace_engine import search_replace_engine
from app.service.file_write_handler import file_write_handler
from app.core.code_validator import code_validator
from app.core.event_bus import emit_log
from app.core.sse_log_buffer import push_log
from app.core.resilience import ResilienceManager, RetryConfig

logger = logging.getLogger(__name__)


class MultiAgentState(TypedDict):
    """多 Agent 协作状态"""
    design_output: Dict[str, Any]
    code_output: Optional[Dict[str, Any]]
    code_error: Optional[str]
    test_output: Optional[Dict[str, Any]]
    test_error: Optional[str]
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
    2. 调用 TestAgent 生成测试
    3. 合并输出结果
    4. 支持 Auto-Fix Loop

    【重构】核心逻辑已拆分到独立模块
    """

    MAX_FIX_RETRIES = 3

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._test_retry_executor = ResilienceManager.get_executor(
            name="test_runner",
            **RetryConfig.TEST_RUN
        )

    # =========================================================================
    # 门面方法 - 供外部调用
    # =========================================================================

    async def execute_with_auto_fix(
        self,
        design_output: Dict,
        affected_files: List[str],
        pipeline_id: int,
        workspace_path: str,
        sandbox_port: Optional[int] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行带自动修复的多 Agent 代码生成

        【重构】委托给 AutoFixLoop 模块
        """
        return await auto_fix_loop.execute(
            design_output=design_output,
            affected_files=affected_files,
            pipeline_id=pipeline_id,
            workspace_path=workspace_path,
            sandbox_port=sandbox_port,
            error_context=error_context
        )

    async def execute_parallel_v2(
        self,
        design_output: Dict[str, Any],
        affected_files: List[str],
        pipeline_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        真正并发：CoderAgent 与 TestAgent(骨架模式) 同时运行

        CoderAgent 完成后，TestAgent 进入填充模式补全断言
        """
        import time
        start = time.time()

        await emit_log(pipeline_id, "info",
                       "🚀 并发启动 CoderAgent + TestAgent(骨架模式)",
                       stage="CODING")

        # ── 阶段一：真正并发 ─────────────────────────────────────────────
        code_task = asyncio.create_task(
            self._execute_code_agent(design_output, {}, pipeline_id)
        )
        skeleton_task = asyncio.create_task(
            test_agent.generate_skeleton(design_output, pipeline_id)
        )
        code_result, skeleton_result = await asyncio.gather(
            code_task, skeleton_task, return_exceptions=True
        )

        # 处理异常
        if isinstance(code_result, Exception):
            return {"success": False, "error": str(code_result),
                    "input_tokens": 0, "output_tokens": 0,
                    "duration_ms": int((time.time() - start) * 1000)}

        if not code_result.get("success"):
            return {"success": False, "error": code_result.get("code_error", "Unknown error"),
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": int((time.time() - start) * 1000)}

        skeleton_output = (
            skeleton_result.get("output", {})
            if isinstance(skeleton_result, dict) and skeleton_result.get("success")
            else {}
        )

        # ── 阶段二：串行填充断言 ─────────────────────────────────────────
        await emit_log(pipeline_id, "info",
                       "✏️  CoderAgent 完成，TestAgent 开始填充断言", stage="CODING")

        fill_result = await test_agent.fill_assertions(
            skeleton_output=skeleton_output,
            code_output=code_result.get("code_output", {}),
            pipeline_id=pipeline_id,
        )

        # ── 合并结果 ────────────────────────────────────────────────────
        test_output = fill_result.get("output") if fill_result.get("success") else {}
        merge = self._merge_results(
            code_result.get("code_output"),
            test_output,
            code_error=None if code_result.get("success") else code_result.get("code_error"),
            test_error=None if fill_result.get("success") else fill_result.get("error"),
        )

        total_tokens_in = (code_result.get("input_tokens", 0) or 0) + \
                          (skeleton_result.get("input_tokens", 0) if isinstance(skeleton_result, dict) else 0) + \
                          (fill_result.get("input_tokens", 0) or 0)
        total_tokens_out = (code_result.get("output_tokens", 0) or 0) + \
                           (skeleton_result.get("output_tokens", 0) if isinstance(skeleton_result, dict) else 0) + \
                           (fill_result.get("output_tokens", 0) or 0)

        final = merge.get("final_output")
        if not final or not final.get("files"):
            return {"success": False, "error": merge.get("error") or "No output",
                    "input_tokens": total_tokens_in, "output_tokens": total_tokens_out,
                    "duration_ms": int((time.time() - start) * 1000)}

        return {
            "success": True,
            "error": merge.get("error"),
            "output": final,
            "input_tokens": total_tokens_in,
            "output_tokens": total_tokens_out,
            "duration_ms": int((time.time() - start) * 1000),
        }

    async def execute_parallel(
        self,
        design_output: Dict,
        affected_files: List[str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        并行执行 CoderAgent 和 TestAgent（非沙箱模式）
        """
        start_time = time.time()

        logger.info(f"MultiAgentCoordinator: 开始并行执行", extra={
            "pipeline_id": pipeline_id,
            "mode": "parallel"
        })

        # 1. 执行 CoderAgent
        code_result = await self._execute_code_agent(
            design_output,
            {},
            pipeline_id=pipeline_id
        )

        if not code_result["success"]:
            logger.error(f"MultiAgentCoordinator: CoderAgent 执行失败", extra={
                "pipeline_id": pipeline_id,
                "error": code_result["code_error"]
            })
            return {
                "success": False,
                "error": f"Code generation failed: {code_result['code_error']}",
                "output": None,
                "input_tokens": code_result.get("input_tokens", 0),
                "output_tokens": code_result.get("output_tokens", 0),
                "duration_ms": code_result.get("duration_ms", 0)
            }

        # 2. 应用 ImportSanitizer
        from app.service.import_sanitizer import ImportSanitizer

        code_output = code_result.get("code_output", {})
        all_files = code_output.get("files", [])

        if all_files:
            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

            for f in all_files:
                p = f.get("file_path", "")
                p = p.lstrip("/")
                if p and not p.startswith("backend/"):
                    f["file_path"] = f"backend/{p}"

            if fix_report:
                logger.info(f"MultiAgentCoordinator: 自动修正了 {len(fix_report)} 个文件的 import 路径", extra={
                    "pipeline_id": pipeline_id,
                    "fixes": fix_report
                })
                code_output["files"] = all_files
                code_output["import_fixes"] = fix_report

        # 3. 执行 TestAgent
        test_result = await self._execute_test_agent(
            design_output,
            code_output,
            pipeline_id=pipeline_id
        )

        # 4. 合并结果
        merge_result = self._merge_results(
            code_output,
            test_result.get("test_output"),
            code_result.get("code_error"),
            test_result.get("test_error")
        )

        # 5. 汇总指标
        total_input_tokens = (
            code_result.get("input_tokens", 0) +
            test_result.get("input_tokens", 0)
        )
        total_output_tokens = (
            code_result.get("output_tokens", 0) +
            test_result.get("output_tokens", 0)
        )
        total_duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"MultiAgentCoordinator: 并行执行完成", extra={
            "pipeline_id": pipeline_id,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "duration_ms": total_duration_ms
        })

        if merge_result["final_output"] is None:
            return {
                "success": False,
                "error": merge_result["error"],
                "output": None,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "duration_ms": total_duration_ms
            }

        return {
            "success": True,
            "output": merge_result["final_output"],
            "error": merge_result.get("error"),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "duration_ms": total_duration_ms
        }

    # =========================================================================
    # 内部方法 - 供门面方法调用
    # =========================================================================

    async def _execute_code_agent(
        self,
        design_output: Dict[str, Any],
        test_files: Dict[str, str],
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行 CoderAgent"""
        logger.info(f"MultiAgentCoordinator: 开始执行 CoderAgent", extra={
            "pipeline_id": pipeline_id,
            "affected_files": design_output.get("affected_files", []),
            "test_files_count": len(test_files)
        })

        # 构建增强的 design_output
        enhanced_design = self._build_coder_prompt_with_tests(design_output, {}, test_files)

        try:
            code_result = await coder_agent.generate_code(
                enhanced_design,
                pipeline_id,
                error_context=error_context
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
            logger.error(f"MultiAgentCoordinator: CoderAgent 执行异常", extra={
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

    async def _execute_test_agent(
        self,
        design_output: Dict[str, Any],
        code_output: Optional[Dict[str, Any]],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """执行 TestAgent"""
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
            test_result = await test_agent.generate_tests(design_output, code_output, pipeline_id)

            if test_result["success"]:
                return {
                    "test_output": test_result["output"],
                    "test_error": None,
                    "input_tokens": test_result.get("input_tokens", 0),
                    "output_tokens": test_result.get("output_tokens", 0),
                    "duration_ms": test_result.get("duration_ms", 0),
                }
            else:
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
                "test_error": "TestAgent execution failed",
                "input_tokens": 0,
                "output_tokens": 0,
                "duration_ms": 0,
            }

    def _merge_results(
        self,
        code_output: Optional[Dict[str, Any]],
        test_output: Optional[Dict[str, Any]],
        code_error: Optional[str] = None,
        test_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并结果：修复元数据丢失问题，注入 original_content

        【重构】使用 CodeExecutorService 按需读取，不再依赖预加载的 target_files
        """
        logger.info(f"[_merge_results] 开始合并结果")

        # 1. 致命错误检查
        if code_error:
            logger.error(f"[_merge_results] 代码生成失败: {code_error}")
            return {
                "final_output": None,
                "error": f"Code generation failed: {code_error}"
            }

        # 防御性转换
        code_output = code_output if isinstance(code_output, dict) else {}
        test_output = test_output if isinstance(test_output, dict) else {}

        # 【Read Token 机制】初始化 CodeExecutorService
        code_executor = CodeExecutorService()

        code_files_count = len(code_output.get("files", []))
        test_files_count = len(test_output.get("files", []))
        logger.info(f"[_merge_results] 代码文件: {code_files_count} 个, 测试文件: {test_files_count} 个")

        # 2. 按文件分组，收集所有修改
        from collections import defaultdict
        file_changes_map = defaultdict(list)

        if code_output.get("files"):
            for f in code_output["files"]:
                file_path = f.get("file_path", "")
                change_type = f.get("change_type", "modify")
                if change_type in ["modify", "update"]:
                    file_changes_map[file_path].append(f)

        logger.info(f"[_merge_results] 需要合并修改的文件: {len(file_changes_map)} 个")

        # 3. 合并文件并注入 original_content
        all_files = []
        processed_files = set()

        if code_output.get("files"):
            for f in code_output["files"]:
                enriched = dict(f)
                file_path = enriched.get("file_path", "")
                change_type = enriched.get("change_type", "modify")

                if file_path in processed_files:
                    continue
                processed_files.add(file_path)

                logger.info(f"[_merge_results] 处理文件: {file_path} (change_type={change_type})")

                # 【重构】使用 CodeExecutorService 按需读取文件内容
                relative_path = file_path.replace("backend/", "").replace("backend\\", "")
                read_result = code_executor.read_file(relative_path)

                if change_type == "add":
                    original = ""
                else:
                    original = read_result.content if read_result.exists else ""

                enriched["original_content"] = original
                enriched["read_token"] = read_result.read_token

                # 【重构】使用 search_replace_engine 进行补丁应用
                if change_type in ["modify", "update"]:
                    patches = file_changes_map.get(file_path, [])
                    if len(patches) == 1:
                        single_patch = patches[0]
                        search_block = single_patch.get("search_block")
                        replace_block = single_patch.get("replace_block", "")
                        fallback_start = single_patch.get("fallback_start_line")
                        fallback_end = single_patch.get("fallback_end_line")

                        if search_block:
                            result = self._apply_search_replace_with_validation(
                                file_path=file_path,
                                original=original,
                                search_block=search_block,
                                replace_block=replace_block,
                                fallback_start=fallback_start,
                                fallback_end=fallback_end
                            )
                            if result["error"]:
                                return result
                            enriched["content"] = result["content"]
                        else:
                            # 回退到行号模式
                            start_line = single_patch.get("start_line")
                            end_line = single_patch.get("end_line")
                            if start_line and end_line:
                                result = self._apply_single_patch(
                                    file_path=file_path,
                                    original=original,
                                    start_line=start_line,
                                    end_line=end_line,
                                    replace_block=replace_block
                                )
                                if result["error"]:
                                    return result
                                enriched["content"] = result["content"]
                    else:
                        # 多个补丁
                        result = self._apply_multiple_search_replace_patches(
                            file_path=file_path,
                            original=original,
                            patches=patches
                        )
                        if result["error"]:
                            return result
                        enriched["content"] = result["content"]

                elif change_type == "add":
                    content = enriched.get("content", "")
                    if content and file_path.endswith(".py"):
                        syntax_error = code_validator.pre_flight_check(content)
                        if syntax_error:
                            return {
                                "final_output": None,
                                "error": f"[{file_path}] 新文件语法错误: {syntax_error}"
                            }

                all_files.append(enriched)

        # 4. 处理测试输出
        test_files = test_output.get("test_files") or test_output.get("files") or []
        logger.info(f"[_merge_results] 处理测试文件: {len(test_files)} 个")

        for f in test_files:
            enriched = dict(f)
            file_path = enriched.get("file_path", "")
            content = enriched.get("content", "")

            relative_path = file_path.replace("backend/", "").replace("backend\\", "")
            read_result = code_executor.read_file(relative_path)

            if "original_content" not in enriched:
                enriched["original_content"] = read_result.content if read_result.exists else None
            enriched["read_token"] = read_result.read_token

            if content and file_path.endswith(".py"):
                syntax_error = code_validator.pre_flight_check(content)
                if syntax_error:
                    return {
                        "final_output": None,
                        "error": f"[{file_path}] 测试文件语法错误: {syntax_error}"
                    }

            all_files.append(enriched)

        # 5. 构建最终输出
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
            "coverage_targets": test_output.get("coverage_targets", []),
            "agent_outputs": {
                "coder": code_output,
                "tester": test_output
            }
        }

        return {
            "final_output": final_output,
            "error": test_error if test_error else None
        }

    # =========================================================================
    # 补丁应用方法 - 使用 search_replace_engine
    # =========================================================================

    def _apply_single_patch(
        self,
        file_path: str,
        original: str,
        start_line: int,
        end_line: int,
        replace_block: str
    ) -> Dict[str, Any]:
        """应用单个补丁"""
        orig_lines = original.splitlines()
        total_lines = len(orig_lines)

        if start_line < 1 or end_line > total_lines or start_line > end_line:
            return {
                "content": None,
                "error": f"[{file_path}] 无效的行号范围"
            }

        try:
            new_content = search_replace_engine.apply_line_patch(
                original_content=original,
                start_line=start_line,
                end_line=end_line,
                replace_block=replace_block
            )

            syntax_error = code_validator.pre_flight_check(new_content)
            if syntax_error:
                return {
                    "content": None,
                    "error": f"[{file_path}] 语法错误: {syntax_error}"
                }

            structure_error = code_validator.validate_code_structure(new_content, file_path)
            if structure_error:
                return {
                    "content": None,
                    "error": f"[{file_path}] {structure_error}"
                }

            return {"content": new_content, "error": None}
        except Exception as e:
            return {
                "content": None,
                "error": f"[{file_path}] 应用修改失败: {str(e)}"
            }

    def _apply_search_replace_with_validation(
        self,
        file_path: str,
        original: str,
        search_block: str,
        replace_block: str,
        fallback_start: Optional[int] = None,
        fallback_end: Optional[int] = None
    ) -> Dict[str, Any]:
        """应用搜索替换补丁，包含验证"""
        new_content = search_replace_engine.apply_search_replace(
            original=original,
            search_block=search_block,
            replace_block=replace_block,
            fallback_start=fallback_start,
            fallback_end=fallback_end
        )

        if new_content is None:
            return {
                "content": None,
                "error": f"[{file_path}] 搜索替换失败"
            }

        # 修改范围限制
        original_lines = original.splitlines()
        new_lines = new_content.splitlines()
        change_ratio = abs(len(new_lines) - len(original_lines)) / max(len(original_lines), 1)

        if change_ratio > 0.5:
            return {
                "content": None,
                "error": f"[{file_path}] 修改范围过大"
            }

        syntax_error = code_validator.pre_flight_check(new_content)
        if syntax_error:
            return {
                "content": None,
                "error": f"[{file_path}] 语法错误: {syntax_error}"
            }

        structure_error = code_validator.validate_code_structure(new_content, file_path)
        if structure_error:
            return {
                "content": None,
                "error": f"[{file_path}] {structure_error}"
            }

        return {"content": new_content, "error": None}

    def _apply_multiple_search_replace_patches(
        self,
        file_path: str,
        original: str,
        patches: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """应用多个搜索替换补丁"""
        sorted_patches = sorted(
            patches,
            key=lambda x: x.get('fallback_start_line', 0) or 0,
            reverse=True
        )

        current_content = original

        for p in sorted_patches:
            search_block = p.get("search_block", "")
            replace_block = p.get("replace_block", "")
            fallback_start = p.get("fallback_start_line")
            fallback_end = p.get("fallback_end_line")

            new_content = search_replace_engine.apply_search_replace(
                original=current_content,
                search_block=search_block,
                replace_block=replace_block,
                fallback_start=fallback_start,
                fallback_end=fallback_end
            )

            if new_content is None:
                return {
                    "content": None,
                    "error": f"[{file_path}] 多补丁搜索替换失败"
                }

            current_content = new_content

        syntax_error = code_validator.pre_flight_check(current_content)
        if syntax_error:
            return {
                "content": None,
                "error": f"[{file_path}] 多补丁后语法错误: {syntax_error}"
            }

        structure_error = code_validator.validate_code_structure(current_content, file_path)
        if structure_error:
            return {
                "content": None,
                "error": f"[{file_path}] {structure_error}"
            }

        return {"content": current_content, "error": None}

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _build_summary(self, code_output: Optional[Dict], test_output: Optional[Dict]) -> str:
        """构建合并后的摘要"""
        parts = []

        if code_output and "summary" in code_output:
            parts.append(f"代码生成: {code_output['summary']}")

        if test_output and "summary" in test_output:
            parts.append(f"测试生成: {test_output['summary']}")

        return "\n".join(parts) if parts else "代码和测试生成完成"

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
            "description": "以下是对应的测试文件内容，供参考",
            "files": {
                path: content[:3000]
                for path, content in test_files.items()
            }
        }

        return enhanced_design


# 单例实例
multi_agent_coordinator = MultiAgentCoordinator()
