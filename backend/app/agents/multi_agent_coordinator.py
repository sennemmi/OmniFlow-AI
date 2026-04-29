"""
多 Agent 协作协调器
实现 CoderAgent 和 TestAgent 的协作执行

重构说明：
- 移除 ThreadPoolExecutor，使用纯异步执行
- CoderAgent 和 TestAgent 顺序执行（TestAgent 依赖 CoderAgent 输出）
- 保留结果合并逻辑
- 新增 Auto-Fix Loop：生成 -> 运行 -> 报错 -> 修复 的闭环迭代
- 新增测试文件自动读取功能
- 新增 Line-Number Based Patching Protocol 支持
- 新增 AST 语法预检和 Ruff 自动修复集成
"""

import asyncio
import ast
import difflib
import logging
import re
from typing import Dict, List, Optional, TypedDict, Any
from pathlib import Path

from pydantic import BaseModel, Field

from app.agents.coder import coder_agent
from app.agents.tester import test_agent
from app.service.sandbox_tools import write_file as sandbox_write_file, exec_command, read_file
from app.core.event_bus import emit_log
from app.core.sse_log_buffer import push_log
from app.core.config import settings

logger = logging.getLogger(__name__)


class MultiAgentState(TypedDict):
    """多 Agent 协作状态"""
    design_output: Dict[str, Any]
    target_files: Dict[str, str]
    test_files: Dict[str, str]  # 新增：测试文件内容
    
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

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # =========================================================================
    # Line-Number Based Patching Protocol - 核心函数
    # =========================================================================

    @staticmethod
    def apply_line_patch(original_content: str, start_line: int, end_line: int, replace_block: str) -> str:
        """
        原子化行替换逻辑 - Line-Number Based Patching Protocol 核心

        Args:
            original_content: 原始文件内容
            start_line: 起始行号 (1-based, 包含)
            end_line: 结束行号 (1-based, 包含)
            replace_block: 新代码块

        Returns:
            str: 替换后的完整内容
        """
        orig_lines = original_content.splitlines()
        # 行号转索引 (1-based -> 0-based)
        # lines[:start-1] 是起始行之前的内容
        # lines[end:] 是结束行之后的内容
        new_lines = orig_lines[:start_line - 1] + replace_block.splitlines() + orig_lines[end_line:]
        return "\n".join(new_lines)

    @staticmethod
    def apply_patches_safely(original_content: str, patches: List[Dict[str, Any]]) -> str:
        """
        安全地应用多个补丁 - 防止行号漂移

        核心策略：
        1. 按 start_line 从大到小排序（倒序）
        2. 先改行号大的，再改行号小的
        3. 这样前面的修改不会影响后面的行号

        Args:
            original_content: 原始文件内容
            patches: 补丁列表，每个补丁包含 start_line, end_line, replace_block

        Returns:
            str: 应用所有补丁后的完整内容
        """
        lines = original_content.splitlines()

        # 按照 start_line 从大到小排序 (关键！防止行号漂移)
        sorted_patches = sorted(patches, key=lambda x: x.get('start_line', 0), reverse=True)

        for p in sorted_patches:
            s = p['start_line']
            e = p['end_line']
            new_chunk = p['replace_block'].splitlines()

            # 验证行号范围
            if s < 1 or e > len(lines) or s > e:
                raise ValueError(f"无效的行号范围: start_line={s}, end_line={e}, 文件共 {len(lines)} 行")

            # 这里的切片操作是原子的，倒序操作保证了 s 和 e 在本次循环中依然有效
            lines[s-1:e] = new_chunk

        return "\n".join(lines)

    @staticmethod
    def pre_flight_check(code: str) -> Optional[str]:
        """
        语法预检闸门 - 在写入磁盘前检查 Python 语法

        Args:
            code: 要检查的代码字符串

        Returns:
            Optional[str]: 如果有语法错误，返回错误信息；否则返回 None
        """
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"
        except Exception as e:
            return f"Parse error: {str(e)}"

    @staticmethod
    def validate_code_structure(code: str, file_path: str) -> Optional[str]:
        """
        验证代码结构完整性 - 检查常见的 AI 生成错误

        Args:
            code: 代码内容
            file_path: 文件路径

        Returns:
            Optional[str]: 如果结构有问题，返回错误信息；否则返回 None
        """
        lines = code.splitlines()

        # 1. 检查 FastAPI 路由文件是否缺少 router 定义
        if file_path.endswith('.py') and 'router' in code:
            has_router_import = any('APIRouter' in line for line in lines)
            has_router_init = any('router = APIRouter' in line or '= APIRouter(' in line for line in lines)
            has_decorator = any('@router.' in line for line in lines)

            if has_decorator and not (has_router_import and has_router_init):
                missing = []
                if not has_router_import:
                    missing.append("from fastapi import APIRouter")
                if not has_router_init:
                    missing.append("router = APIRouter(...)")
                return f"结构错误: 使用了 @router. 装饰器但缺少: {', '.join(missing)}"

        # 2. 检查使用了未定义的变量（简单检查）
        import re
        undefined_patterns = [
            (r'@(\w+)\.', "装饰器"),
            (r'^(\w+)\s*=', "变量赋值"),
        ]

        defined_names = set()
        imported_names = set()

        for line in lines:
            # 收集导入的名称
            if 'import ' in line:
                # from x import y
                match = re.match(r'from\s+\S+\s+import\s+(.+)', line)
                if match:
                    imports = match.group(1).split(',')
                    for imp in imports:
                        name = imp.strip().split()[0]  # handle 'as' alias
                        imported_names.add(name)
                # import x
                match = re.match(r'import\s+(.+)', line)
                if match:
                    imports = match.group(1).split(',')
                    for imp in imports:
                        imported_names.add(imp.strip().split('.')[0])

            # 收集定义的变量
            match = re.match(r'^(\w+)\s*=', line)
            if match:
                defined_names.add(match.group(1))

        # 检查装饰器使用的名称是否已定义
        for line in lines:
            match = re.match(r'@(\w+)\.', line)
            if match:
                name = match.group(1)
                if name not in defined_names and name not in imported_names and name not in ['staticmethod', 'classmethod', 'property']:
                    return f"结构错误: 使用了未定义的 '{name}' 对象（在装饰器中）"

        return None

    @staticmethod
    def get_best_match_hint(original_lines: List[str], search_block: str, start_line: int) -> str:
        """
        最接近匹配算法 - 当行号不匹配时给出智能提示

        Args:
            original_lines: 原始文件的行列表
            search_block: AI 预期的代码块
            start_line: AI 提供的起始行号

        Returns:
            str: 给 AI 的提示信息
        """
        if not search_block.strip():
            return "提示：expected_original 为空，无法验证"

        search_lines = search_block.strip().splitlines()
        if not search_lines:
            return "提示：expected_original 为空，无法验证"

        # 在预期行号附近搜索最相似的代码段
        search_window = 10  # 前后搜索 10 行
        search_start = max(0, start_line - 1 - search_window)
        search_end = min(len(original_lines), start_line - 1 + search_window + len(search_lines))

        best_ratio = 0.0
        best_match_start = -1

        # 滑动窗口找最佳匹配
        for i in range(search_start, search_end - len(search_lines) + 1):
            window = original_lines[i:i + len(search_lines)]
            window_text = "\n".join(window)
            search_text = "\n".join(search_lines)

            ratio = difflib.SequenceMatcher(None, window_text, search_text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_start = i

        if best_ratio > 0.8:
            # 找到高度相似的代码
            actual_line = best_match_start + 1
            if actual_line != start_line:
                return f"提示：行号偏移。你指定的 start_line={start_line}，但实际匹配的代码在第 {actual_line} 行"
            else:
                return "提示：代码内容有细微差异，请检查缩进或空格"
        elif best_ratio > 0.5:
            return f"提示：在指定位置附近找到相似度 {best_ratio:.0%} 的代码，请检查行号"
        else:
            # 检查是否是缩进问题
            first_search_line = search_lines[0] if search_lines else ""
            for i, line in enumerate(original_lines[search_start:search_end], start=search_start + 1):
                stripped_search = first_search_line.strip()
                stripped_actual = line.strip()
                if stripped_search and stripped_actual and stripped_search == stripped_actual:
                    # 内容匹配但缩进可能不同
                    search_indent = len(first_search_line) - len(first_search_line.lstrip())
                    actual_indent = len(line) - len(line.lstrip())
                    if search_indent != actual_indent:
                        return f"提示：第 {i} 行内容匹配但缩进不同。原文件是 {actual_indent} 个空格，你提供了 {search_indent} 个"

            return "提示：无法找到匹配的代码块，请重新检查行号和代码内容"

    def _flexible_search_replace(self, original_text: str, search_block: str, replace_block: str) -> Optional[str]:
        """多级模糊匹配替换算法 (Aider 简化版)"""
        if not search_block:
            return original_text

        # 【第1层】精确匹配
        if search_block in original_text:
            return original_text.replace(search_block, replace_block)

        # 【第2层】换行符归一化 (解决 \r\n vs \n)
        orig_norm = original_text.replace('\r\n', '\n')
        search_norm = search_block.replace('\r\n', '\n')
        replace_norm = replace_block.replace('\r\n', '\n')
        if search_norm in orig_norm:
            return orig_norm.replace(search_norm, replace_norm)

        # 【第3层】行级别的宽松匹配 (忽略每行首尾多余空格，忽略完全空白的行)
        def clean_lines(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        orig_lines_clean = clean_lines(orig_norm)
        search_lines_clean = clean_lines(search_norm)

        # 在清洗后的原文件中滑动窗口找匹配
        search_len = len(search_lines_clean)
        if search_len > 0:
            for i in range(len(orig_lines_clean) - search_len + 1):
                window = orig_lines_clean[i : i + search_len]
                if window == search_lines_clean:
                    # 在这里，我们确认逻辑上是匹配的
                    # 为了安全替换，我们退回到使用正则进行忽略空白的替换
                    pattern = r'\s*'.join(re.escape(line) for line in search_lines_clean)
                    # 将正则匹配到的原代码块，替换为 AI 提供的新代码块
                    return re.sub(pattern, replace_norm, orig_norm, count=1, flags=re.DOTALL)

        return None  # 彻底找不到

    async def _read_test_files(
        self,
        pipeline_id: int,
        affected_files: List[str]
    ) -> Dict[str, str]:
        """
        根据 affected_files 读取对应的测试文件
        
        规则：
        - 如果 affected_files 包含 backend/app/api/v1/health.py
        - 则尝试读取 backend/tests/unit/test_health_api.py
        
        Args:
            pipeline_id: Pipeline ID
            affected_files: 受影响的文件列表
            
        Returns:
            Dict[str, str]: 测试文件路径到内容的映射
        """
        test_files = {}
        
        for file_path in affected_files:
            # 提取模块名
            # 例如：backend/app/api/v1/health.py -> health
            path_parts = file_path.split('/')
            if len(path_parts) < 2:
                continue
                
            file_name = path_parts[-1]  # health.py
            module_name = file_name.replace('.py', '')  # health
            
            # 构建可能的测试文件路径
            possible_test_paths = [
                f"backend/tests/unit/test_{module_name}_api.py",
                f"backend/tests/unit/test_{module_name}.py",
                f"backend/tests/test_{module_name}.py",
            ]
            
            for test_path in possible_test_paths:
                try:
                    content = await read_file(pipeline_id, test_path)
                    if content:
                        test_files[test_path] = content
                        logger.info(f"读取测试文件成功: {test_path}", extra={
                            "pipeline_id": pipeline_id,
                            "test_file": test_path
                        })
                        break
                except Exception:
                    # 文件不存在或读取失败，继续尝试下一个
                    continue
        
        return test_files
    
    def _build_coder_prompt_with_tests(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        test_files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        构建包含测试文件的 CoderAgent 输入
        
        将测试文件内容注入到 design_output 中，让 AI 了解测试期望
        """
        if not test_files:
            return design_output
        
        # 创建新的 design_output 副本
        enhanced_design = dict(design_output)
        
        # 添加测试文件信息
        enhanced_design["test_files_reference"] = {
            "description": "以下是对应的测试文件内容，供参考（绝对不能修改测试文件）",
            "files": {
                path: content[:3000]  # 限制长度，避免 token 过多
                for path, content in test_files.items()
            }
        }
        
        return enhanced_design
    
    async def _execute_code_agent(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        test_files: Dict[str, str],
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行 CoderAgent

        Args:
            design_output: DesignerAgent 的输出
            target_files: 目标文件路径到内容的映射
            test_files: 测试文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录
            error_context: 错误上下文（用于修复模式）

        Returns:
            Dict: 包含 code_output 或 code_error，以及指标字段
        """
        logger.info(f"MultiAgentCoordinator: 开始执行 CoderAgent", extra={
            "pipeline_id": pipeline_id,
            "files_count": len(target_files),
            "test_files_count": len(test_files)
        })
        
        # 构建增强的 design_output（包含测试文件）
        enhanced_design = self._build_coder_prompt_with_tests(
            design_output, target_files, test_files
        )

        try:
            code_result = await coder_agent.generate_code(
                enhanced_design, 
                target_files, 
                pipeline_id,
                error_context=error_context
            )

            if code_result["success"]:
                logger.info(f"MultiAgentCoordinator: CoderAgent 执行成功", extra={
                    "pipeline_id": pipeline_id,
                    "input_tokens": code_result.get("input_tokens", 0),
                    "output_tokens": code_result.get("output_tokens", 0),
                    "duration_ms": code_result.get("duration_ms", 0)
                })
                return {
                    "success": True,
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
        集成 Line-Number Based Patching Protocol 和 AST 语法预检
        支持同一文件多个补丁的合并应用（防止行号漂移）
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

        # 2. 按文件分组，收集所有修改
        from collections import defaultdict
        file_changes_map = defaultdict(list)  # file_path -> list of changes

        if code_output.get("files"):
            for f in code_output["files"]:
                file_path = f.get("file_path", "")
                change_type = f.get("change_type", "modify")

                # 只处理 modify 类型的变更，add/delete 单独处理
                if change_type in ["modify", "update"]:
                    file_changes_map[file_path].append(f)
                else:
                    # add/delete 类型直接处理
                    pass

        # 3. 合并文件并注入 original_content
        all_files = []
        processed_files = set()

        if code_output.get("files"):
            for f in code_output["files"]:
                enriched = dict(f)
                file_path = enriched.get("file_path", "")
                change_type = enriched.get("change_type", "modify")

                # 跳过已处理的文件（同一文件的多个修改已合并）
                if file_path in processed_files:
                    continue
                processed_files.add(file_path)

                original = target_files.get(file_path, "")
                enriched["original_content"] = original

                # 【Line-Number Based Patching Protocol - 升级版】
                if change_type in ["modify", "update"]:
                    # 检查同一文件是否有多个修改
                    patches = file_changes_map.get(file_path, [])

                    if len(patches) == 1:
                        # 单个补丁，直接应用
                        single_patch = patches[0]
                        start_line = single_patch.get("start_line")
                        end_line = single_patch.get("end_line")
                        replace_block = single_patch.get("replace_block", "")
                        expected_original = single_patch.get("expected_original")

                        if start_line and end_line:
                            result = self._apply_single_patch(
                                file_path=file_path,
                                original=original,
                                start_line=start_line,
                                end_line=end_line,
                                replace_block=replace_block,
                                expected_original=expected_original
                            )
                            if result["error"]:
                                return result
                            enriched["content"] = result["content"]
                        elif enriched.get("content"):
                            # 兜底：如果 AI 还是生成了 content，进行语法检查
                            syntax_error = self.pre_flight_check(enriched["content"])
                            if syntax_error:
                                return {
                                    "final_output": None,
                                    "error": f"[{file_path}] 语法错误: {syntax_error}"
                                }
                        else:
                            return {"final_output": None, "error": f"[{file_path}] 缺少 start_line 或 end_line"}
                    else:
                        # 多个补丁，使用安全合并算法（倒序应用）
                        result = self._apply_multiple_patches(
                            file_path=file_path,
                            original=original,
                            patches=patches
                        )
                        if result["error"]:
                            return result
                        enriched["content"] = result["content"]

                elif change_type == "add":
                    # 新建文件也需要语法检查
                    content = enriched.get("content", "")
                    if content and file_path.endswith(".py"):
                        syntax_error = self.pre_flight_check(content)
                        if syntax_error:
                            return {
                                "final_output": None,
                                "error": f"[{file_path}] 新文件语法错误: {syntax_error}"
                            }

                all_files.append(enriched)

        # 4. 处理测试输出与非致命错误
        test_files = test_output.get("test_files") or test_output.get("files") or []

        if test_error:
            current_error = f"Test generation warning: {test_error}"
        else:
            for f in test_files:
                enriched = dict(f)
                file_path = enriched.get("file_path", "")
                if "original_content" not in enriched:
                    enriched["original_content"] = target_files.get(file_path)

                # 测试文件也需要语法检查
                content = enriched.get("content", "")
                if content and file_path.endswith(".py"):
                    syntax_error = self.pre_flight_check(content)
                    if syntax_error:
                        return {
                            "final_output": None,
                            "error": f"[{file_path}] 测试文件语法错误: {syntax_error}"
                        }

                all_files.append(enriched)
            current_error = None

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
            "error": current_error
        }

    def _apply_single_patch(
        self,
        file_path: str,
        original: str,
        start_line: int,
        end_line: int,
        replace_block: str,
        expected_original: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        应用单个补丁，包含完整的验证流程

        Returns:
            Dict with "content" or "error" key
        """
        # 验证行号范围有效性
        orig_lines = original.splitlines()
        total_lines = len(orig_lines)

        if start_line < 1 or end_line > total_lines or start_line > end_line:
            return {
                "content": None,
                "error": f"[{file_path}] 无效的行号范围: start_line={start_line}, end_line={end_line}, 文件共 {total_lines} 行"
            }

        # 如果提供了 expected_original，验证行号是否匹配
        if expected_original:
            actual_block = "\n".join(orig_lines[start_line - 1:end_line])
            if actual_block.strip() != expected_original.strip():
                hint = self.get_best_match_hint(orig_lines, expected_original, start_line)
                return {
                    "content": None,
                    "error": f"[{file_path}] 行号验证失败。{hint}"
                }

        try:
            # 应用行号补丁
            new_content = self.apply_line_patch(
                original_content=original,
                start_line=start_line,
                end_line=end_line,
                replace_block=replace_block
            )

            # 【核心：AST 语法预检闸门 - 强化版错误信息】
            syntax_error = self.pre_flight_check(new_content)
            if syntax_error:
                return {
                    "content": None,
                    "error": f"[{file_path}] 行号替换失败！修改后出现语法错误: {syntax_error}。这通常是因为你给出的 start_line/end_line 范围不对，或者 replace_block 缩进有误。"
                }

            # 【结构完整性检查】
            structure_error = self.validate_code_structure(new_content, file_path)
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

    def _apply_multiple_patches(
        self,
        file_path: str,
        original: str,
        patches: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        应用多个补丁到同一个文件 - 使用倒序算法防止行号漂移

        Args:
            file_path: 文件路径
            original: 原始内容
            patches: 补丁列表

        Returns:
            Dict with "content" or "error" key
        """
        # 验证所有补丁的行号
        orig_lines = original.splitlines()
        total_lines = len(orig_lines)

        for p in patches:
            s = p.get("start_line", 0)
            e = p.get("end_line", 0)
            if s < 1 or e > total_lines or s > e:
                return {
                    "content": None,
                    "error": f"[{file_path}] 无效的行号范围: start_line={s}, end_line={e}, 文件共 {total_lines} 行"
                }

        try:
            # 使用安全合并算法（倒序应用）
            patch_list = [
                {
                    "start_line": p["start_line"],
                    "end_line": p["end_line"],
                    "replace_block": p.get("replace_block", "")
                }
                for p in patches
            ]

            new_content = self.apply_patches_safely(original, patch_list)

            # 【核心：AST 语法预检闸门 - 强化版错误信息】
            syntax_error = self.pre_flight_check(new_content)
            if syntax_error:
                return {
                    "content": None,
                    "error": f"[{file_path}] 多补丁合并后语法错误: {syntax_error}。这通常是因为补丁之间有重叠，或者 replace_block 缩进不一致。"
                }

            # 【结构完整性检查】
            structure_error = self.validate_code_structure(new_content, file_path)
            if structure_error:
                return {
                    "content": None,
                    "error": f"[{file_path}] {structure_error}"
                }

            return {"content": new_content, "error": None}

        except Exception as e:
            return {
                "content": None,
                "error": f"[{file_path}] 应用多补丁失败: {str(e)}"
            }
    
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

    def _extract_error_summary(self, test_results: Dict[str, Any]) -> str:
        """从测试结果中提取关键错误摘要"""
        error_type = test_results.get("error_type", "unknown_error")
        failed_tests = test_results.get("failed_tests", [])
        summary = test_results.get("summary", "")
        logs = test_results.get("logs", "")

        import re

        if error_type == "syntax_error":
            syntax_match = re.search(r'SyntaxError: (.+?)(?:\n|$)', logs)
            line_match = re.search(r'line (\d+)', logs)
            if syntax_match:
                error_detail = syntax_match.group(1)
                line_info = f" (第 {line_match.group(1)} 行)" if line_match else ""
                return f"语法错误{line_info}: {error_detail[:100]}"
            return "代码存在语法错误，请检查 Python 语法"

        elif error_type == "import_error":
            import_match = re.search(r"ModuleNotFoundError: No module named ['\"](.+?)['\"]", logs)
            if import_match:
                module_name = import_match.group(1)
                return f"导入错误: 找不到模块 '{module_name}'"
            import_match = re.search(r"ImportError: (.+?)(?:\n|$)", logs)
            if import_match:
                return f"导入错误: {import_match.group(1)[:100]}"
            return "模块导入失败，请检查 import 语句"

        elif error_type == "test_syntax_error":
            # 测试文件语法错误
            file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
            syntax_match = re.search(r'SyntaxError: (.+?)(?:\n|$)', logs)
            line_match = re.search(r'line (\d+)', logs)
            file_info = f" ({file_match.group(1)})" if file_match else ""
            if syntax_match:
                error_detail = syntax_match.group(1)
                line_info = f" 第 {line_match.group(1)} 行" if line_match else ""
                return f"测试文件语法错误{file_info}{line_info}: {error_detail[:100]}"
            return f"测试文件存在语法错误{file_info}，需要修复测试代码"

        elif error_type == "test_import_error":
            # 测试文件导入错误
            file_match = re.search(r'File "([^"]*test_[^"]+)"', logs)
            import_match = re.search(r"ModuleNotFoundError: No module named ['\"](.+?)['\"]", logs)
            file_info = f" ({file_match.group(1)})" if file_match else ""
            if import_match:
                return f"测试文件导入错误{file_info}: 找不到模块 '{import_match.group(1)}'"
            return f"测试文件导入失败{file_info}，请检查 import 语句"

        elif error_type == "test_collection_error":
            return f"测试收集错误: {summary[:100]}"

        elif error_type == "test_failure":
            if failed_tests:
                failed_test = failed_tests[0]
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
        """强化测试失败日志输出"""
        error_type = test_results.get("error_type", "unknown_error")
        failed_tests = test_results.get("failed_tests", [])
        summary = test_results.get("summary", "")
        exit_code = test_results.get("exit_code", -1)

        details = {
            "attempt": attempt,
            "exit_code": exit_code,
            "failed_tests_count": len(failed_tests),
        }

        if error_type == "syntax_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 检测到语法错误",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将检查代码语法并修复",
                **details
            )
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
            logger.error(
                f"[Pipeline {pipeline_id}] 导入错误详情:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "import_error"}
            )

        elif error_type == "test_failure":
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
            logger.error(
                f"[Pipeline {pipeline_id}] 测试失败详情:\n{test_results.get('logs', '')[:2000]}",
                extra={
                    "pipeline_id": pipeline_id,
                    "error_type": "test_failure",
                    "failed_tests": failed_tests,
                    "exit_code": exit_code
                }
            )

        elif error_type == "test_syntax_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试文件语法错误",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将修复测试文件语法",
                **details
            )
            logger.error(
                f"[Pipeline {pipeline_id}] 测试文件语法错误:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "test_syntax_error"}
            )

        elif error_type == "test_import_error":
            await emit_log(
                pipeline_id, "error",
                f"❌ 第 {attempt} 次尝试: 测试文件导入错误",
                stage="CODING",
                error_summary=error_summary,
                suggestion="AI 将修正测试文件的 import 语句",
                **details
            )
            logger.error(
                f"[Pipeline {pipeline_id}] 测试文件导入错误:\n{test_results.get('logs', '')[:1500]}",
                extra={"pipeline_id": pipeline_id, "error_type": "test_import_error"}
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

    async def _write_files_to_project(
        self,
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """写入文件到宿主机项目目录"""
        project_root = Path(settings.TARGET_PROJECT_PATH).resolve()
        for file_change in all_files:
            file_path = file_change["file_path"]
            content = file_change["content"]
            full_path = project_root / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            await push_log(
                pipeline_id, "info",
                f"文件已写入: {file_path}",
                stage="CODING"
            )

    async def _write_files_to_sandbox(
        self,
        all_files: List[Dict[str, Any]],
        pipeline_id: int
    ) -> None:
        """写入文件到容器（用于实时预览）"""
        for file_change in all_files:
            await sandbox_write_file(
                pipeline_id=pipeline_id,
                path=file_change["file_path"],
                content=file_change["content"]
            )

    async def _run_tests_in_sandbox(
        self,
        pipeline_id: int,
        test_files: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        在沙箱内运行测试
        
        Args:
            pipeline_id: Pipeline ID
            test_files: 可选的测试文件列表，用于检测测试文件错误
        """
        await push_log(
            pipeline_id,
            "info",
            "正在运行自动化测试验证（沙箱内）...",
            stage="CODING"
        )

        test_result_cmd = await exec_command(
            pipeline_id=pipeline_id,
            cmd="cd /workspace/backend && python -m pytest tests/ -v --tb=short --color=no -x 2>&1 | tail -100",
            timeout=120
        )

        test_logs = test_result_cmd['stdout'] + test_result_cmd['stderr']
        test_success = test_result_cmd['exit_code'] == 0

        # 分析错误类型
        error_type = None
        failed_tests = []
        
        if not test_success:
            import re
            
            # 检测测试文件语法错误（在测试收集阶段失败）
            if "SyntaxError" in test_logs and "test_" in test_logs:
                error_type = "test_syntax_error"
            # 检测测试文件导入错误
            elif "ImportError" in test_logs or "ModuleNotFoundError" in test_logs:
                if "test_" in test_logs or "tests/" in test_logs:
                    error_type = "test_import_error"
                else:
                    error_type = "import_error"
            # 检测测试收集错误
            elif "collection error" in test_logs.lower() or "ImportError while loading" in test_logs:
                error_type = "test_collection_error"
            # 检测普通测试失败
            elif "FAILED" in test_logs or "failed" in test_logs.lower():
                error_type = "test_failure"
                # 提取失败的测试名称
                failed_matches = re.findall(r'(\S+::\S+)\s+FAILED', test_logs)
                failed_tests = failed_matches
            # 检测超时
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
        """启动预览服务器
        
        注意：如果 Dockerfile 已经启动了服务（如 8000 端口），
        则不需要再次启动，只需检查服务是否健康即可。
        """
        await push_log(
            pipeline_id,
            "info",
            "🚀 检查后端服务状态...",
            stage="CODING"
        )
        
        # 首先检查 8000 端口（Dockerfile 默认端口）是否已有服务运行
        health_check_8000 = await exec_command(
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
        
        # 如果 8000 端口没有服务，尝试在 8001 端口启动（向后兼容）
        await push_log(
            pipeline_id,
            "info",
            "在 8001 端口启动后端服务...",
            stage="CODING"
        )
        
        await exec_command(
            pipeline_id=pipeline_id,
            cmd="cd /workspace/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info > /tmp/preview_server.log 2>&1 &",
            timeout=3
        )
        
        # 等待服务启动
        await asyncio.sleep(5)
        
        # 验证服务是否启动成功
        health_check = await exec_command(
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

    async def execute_with_auto_fix(
        self,
        design_output: Dict,
        target_files: Dict,
        pipeline_id: int,
        workspace_path: str,
        sandbox_port: Optional[int] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行带自动修复的多 Agent 代码生成
        """
        import time

        current_error_context = error_context  # 使用传入的 error_context 作为初始值
        attempt = 0
        last_code_output = None

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        start_time = time.time()
        
        # ★ 新增：读取测试文件
        affected_files = design_output.get("affected_files", [])
        test_files = await self._read_test_files(pipeline_id, affected_files)
        
        if test_files:
            await push_log(
                pipeline_id,
                "info",
                f"📄 找到 {len(test_files)} 个相关测试文件，将提供给 AI 参考",
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

            # 1. Coder 生成代码
            code_result = await self._execute_code_agent(
                design_output,
                target_files,
                test_files,  # 传入测试文件
                pipeline_id=pipeline_id,
                error_context=current_error_context
            )

            self.total_input_tokens += code_result.get("input_tokens", 0) or 0
            self.total_output_tokens += code_result.get("output_tokens", 0) or 0

            if code_result.get("success") and code_result.get("code_output"):
                last_code_output = code_result["code_output"]

            if not code_result["success"]:
                logger.error(f"MultiAgentCoordinator: CoderAgent 执行失败", extra={
                    "pipeline_id": pipeline_id,
                    "attempt": attempt,
                    "error": code_result["error"],
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens
                })
                return {
                    "success": False,
                    "error": f"Code generation failed: {code_result['error']}",
                    "output": None,
                    "attempt": attempt,
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000)
                }

            # 2. 处理生成的文件
            from app.service.import_sanitizer import ImportSanitizer

            code_output = code_result.get("code_output", {})
            all_files = code_output.get("files", [])
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

            # 写入文件
            await self._write_files_to_project(all_files, pipeline_id)
            await self._write_files_to_sandbox(all_files, pipeline_id)

            # 3. 分层测试 + ReviewAgent 决策（替换原来的 TestRunnerService.run_tests 调用）
            from app.service.layered_test_runner import LayeredTestRunner
            from app.agents.reviewer import review_agent

            layered_result = await LayeredTestRunner.run(
                workspace_path=workspace_path,
                new_files=all_files,             # code_result["output"]["files"]
                sandbox_port=sandbox_port,
                timeout=120,
            )

            decision = review_agent.decide(
                layered_result, attempt=attempt, max_retries=self.MAX_FIX_RETRIES
            )

            if decision.action == "proceed":
                # 全通过，退出循环
                await push_log(
                    pipeline_id,
                    "success",
                    "✅ 分层测试全部通过！AI 自动验证成功。",
                    stage="CODING"
                )

                # 启动预览服务器
                await self._start_preview_server(pipeline_id, sandbox_port)

                # 注意：测试代码生成移至 UNIT_TESTING 阶段，避免重复生成
                return {
                    "success": True,
                    "output": code_result["code_output"],
                    "test_layers": [lr.__dict__ for lr in layered_result.layers],
                    "attempt": attempt,
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "preview_port": sandbox_port
                }

            elif decision.action == "auto_fix":
                # 设置错误上下文，进入下一次 while 循环
                current_error_context = decision.error_context
                await push_log(
                    pipeline_id, "warning",
                    f"检测到代码问题，开始第 {attempt + 1} 次自动修复...",
                    stage="CODING"
                )
                attempt += 1
                continue

            elif decision.action == "request_user":
                # 新增：挂起流水线，等待用户决策
                await push_log(
                    pipeline_id, "warning",
                    decision.user_message,
                    stage="CODING",
                    approval_required=True,
                    options=decision.options,
                    regression_failed_tests=decision.regression_failed_tests or [],
                )
                # 返回特殊状态，让 CodingHandler 知道要挂起
                return {
                    "success": False,
                    "pending_user_decision": True,
                    "decision_options": decision.options,
                    "user_message": decision.user_message,
                    "regression_failed_tests": decision.regression_failed_tests or [],
                    "last_code_output": last_code_output,
                    "error": "等待用户决策",
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

        # 达到最大重试次数
        logger.error(f"MultiAgentCoordinator: 自动修复达到最大次数", extra={
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

    async def execute_parallel_v2(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        真正并发：CoderAgent 与 TestAgent(骨架模式) 同时运行。
        CoderAgent 完成后，TestAgent 进入填充模式补全断言。
        """
        import time
        start = time.time()

        await emit_log(pipeline_id, "info",
                       "🚀 并发启动 CoderAgent + TestAgent(骨架模式)",
                       stage="CODING")

        # ── 阶段一：真正并发 ─────────────────────────────────────────────
        code_task = asyncio.create_task(
            self._execute_code_agent(design_output, target_files, {}, pipeline_id)
        )
        skeleton_task = asyncio.create_task(
            test_agent.generate_skeleton(design_output, pipeline_id)
        )
        code_result, skeleton_result = await asyncio.gather(
            code_task, skeleton_task, return_exceptions=True
        )

        # 处理异常（gather 不抛出，异常作为返回值）
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

        # ── 阶段二：串行填充断言（依赖 code_result）────────────────────────
        await emit_log(pipeline_id, "info",
                       "✏️  CoderAgent 完成，TestAgent 开始填充断言", stage="CODING")

        fill_result = await test_agent.fill_assertions(
            skeleton_output=skeleton_output,
            code_output=code_result.get("code_output", {}),
            target_files=target_files,
            pipeline_id=pipeline_id,
        )

        # ── 合并结果 ────────────────────────────────────────────────────
        test_output = fill_result.get("output") if fill_result.get("success") else {}
        merge = self._merge_results(
            code_result.get("code_output"),
            test_output,
            target_files,
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
            "error": merge.get("error"),  # 非致命警告透传
            "output": final,
            "input_tokens": total_tokens_in,
            "output_tokens": total_tokens_out,
            "duration_ms": int((time.time() - start) * 1000),
        }

    async def execute_parallel(
        self,
        design_output: Dict,
        target_files: Dict,
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        并行执行 CoderAgent 和 TestAgent（非沙箱模式）

        注意：此方法用于非沙箱环境，直接生成代码和测试，不进行自动修复循环。
        生成的代码会经过 ImportSanitizer 修正导入路径。

        Args:
            design_output: DesignerAgent 的输出
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含生成结果和汇总指标
        """
        import time
        start_time = time.time()

        logger.info(f"MultiAgentCoordinator: 开始并行执行", extra={
            "pipeline_id": pipeline_id,
            "mode": "parallel"
        })

        # 1. 执行 CoderAgent
        code_result = await self._execute_code_agent(
            design_output,
            target_files,
            {},  # 无测试文件参考
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

        # 2. 应用 ImportSanitizer 修正导入路径
        from app.service.import_sanitizer import ImportSanitizer

        code_output = code_result.get("code_output", {})
        all_files = code_output.get("files", [])

        if all_files:
            all_files, fix_report = ImportSanitizer.sanitize_files(all_files)

            # 路径防御：确保文件路径以 backend/ 开头
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
            target_files,
            pipeline_id=pipeline_id
        )

        # 4. 合并结果
        merge_result = self._merge_results(
            code_output,
            test_result.get("test_output"),
            target_files,
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


# 单例实例
multi_agent_coordinator = MultiAgentCoordinator()
