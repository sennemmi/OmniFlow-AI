# app/agents/tools_edit.py

"""
高级编辑工具实现
使用 tree-sitter 进行精确的代码编辑
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple

from app.service.tree_sitter_utils import get_parser, find_symbol_node

logger = logging.getLogger(__name__)


class EditTools:
    """
    高级代码编辑工具
    - func_replace: 替换整个函数
    - insert_after: 在指定行后插入代码
    - delete_lines: 删除指定行范围
    """

    @staticmethod
    def func_replace(
        file_content: str,
        file_path: str,
        func_name: str,
        new_func_body: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        替换指定函数的完整实现

        Args:
            file_content: 原始文件内容
            file_path: 文件路径（用于选择 parser）
            func_name: 函数名
            new_func_body: 新的函数实现（包括 def 行）

        Returns:
            (success, message, new_content)
        """
        try:
            # 使用 tree-sitter 解析文件
            parser = get_parser(file_path)
            tree = parser.parse(bytes(file_content, "utf-8"))
            root = tree.root_node

            # 查找函数节点
            func_node = find_symbol_node(root, func_name, file_path)

            if func_node is None:
                return False, f"找不到函数: {func_name}", None

            # 获取函数的字节范围
            start_byte = func_node.start_byte
            end_byte = func_node.end_byte

            # 执行替换
            before = file_content[:start_byte]
            after = file_content[end_byte:]
            new_content = before + new_func_body + after

            return True, f"函数 {func_name} 替换成功", new_content

        except Exception as e:
            logger.error(f"[func_replace] 错误: {e}")
            return False, f"替换失败: {str(e)}", None

    @staticmethod
    def insert_after(
        file_content: str,
        after_line: int,
        code_block: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        在指定行之后插入新代码

        Args:
            file_content: 原始文件内容
            after_line: 在此行之后插入（1-based）
            code_block: 要插入的代码块

        Returns:
            (success, message, new_content)
        """
        try:
            lines = file_content.splitlines(keepends=True)

            if after_line < 0 or after_line > len(lines):
                return False, f"行号 {after_line} 超出范围 (1-{len(lines)})", None

            # 在指定行后插入
            new_lines = lines[:after_line] + [code_block + "\n"] + lines[after_line:]
            new_content = "".join(new_lines)

            return True, f"在第 {after_line} 行后插入成功", new_content

        except Exception as e:
            logger.error(f"[insert_after] 错误: {e}")
            return False, f"插入失败: {str(e)}", None

    @staticmethod
    def delete_lines(
        file_content: str,
        start_line: int,
        end_line: int
    ) -> Tuple[bool, str, Optional[str]]:
        """
        删除指定行范围的代码

        Args:
            file_content: 原始文件内容
            start_line: 起始行号（1-based，包含）
            end_line: 结束行号（1-based，包含）

        Returns:
            (success, message, new_content)
        """
        try:
            lines = file_content.splitlines(keepends=True)
            total_lines = len(lines)

            if start_line < 1 or end_line > total_lines or start_line > end_line:
                return False, f"行号范围 {start_line}-{end_line} 无效 (文件共 {total_lines} 行)", None

            # 删除指定行范围
            new_lines = lines[:start_line - 1] + lines[end_line:]
            new_content = "".join(new_lines)

            return True, f"删除第 {start_line}-{end_line} 行成功", new_content

        except Exception as e:
            logger.error(f"[delete_lines] 错误: {e}")
            return False, f"删除失败: {str(e)}", None


class EditToolsExecutor:
    """
    编辑工具执行器
    封装工具调用和结果格式化
    """

    def __init__(self, file_service=None):
        self.file_service = file_service

    @staticmethod
    def _normalize_file_path(file_path: str) -> str:
        """
        标准化文件路径
        - 移除 backend/ 前缀
        - 统一使用正斜杠
        - 确保有文件扩展名（用于 tree-sitter 识别语言）
        """
        if not file_path:
            return file_path

        # 统一使用正斜杠
        path = file_path.replace("\\", "/")

        # 移除 backend/ 前缀
        if path.startswith("backend/"):
            path = path[8:]

        # 确保有 .py 扩展名（tree-sitter 需要）
        if "." not in path.split("/")[-1]:
            path = path + ".py"

        return path

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        file_content: str,
        file_path: str
    ) -> str:
        """
        执行编辑工具

        Returns:
            JSON 字符串格式的结果
        """
        # 标准化文件路径（用于 tree-sitter 识别语言）
        normalized_path = self._normalize_file_path(file_path)

        try:
            if tool_name == "func_replace":
                func_name = arguments.get("func_name")
                new_func_body = arguments.get("new_func_body")

                # 使用标准化后的路径调用 tree-sitter
                success, message, new_content = EditTools.func_replace(
                    file_content, normalized_path, func_name, new_func_body
                )

                return json.dumps({
                    "success": success,
                    "message": message,
                    "new_content": new_content,
                    "tool": tool_name
                })

            elif tool_name == "insert_after":
                after_line = arguments.get("after_line")
                code_block = arguments.get("code_block")

                success, message, new_content = EditTools.insert_after(
                    file_content, after_line, code_block
                )

                return json.dumps({
                    "success": success,
                    "message": message,
                    "new_content": new_content,
                    "tool": tool_name
                })

            elif tool_name == "delete_lines":
                start_line = arguments.get("start_line")
                end_line = arguments.get("end_line")

                success, message, new_content = EditTools.delete_lines(
                    file_content, start_line, end_line
                )

                return json.dumps({
                    "success": success,
                    "message": message,
                    "new_content": new_content,
                    "tool": tool_name
                })

            else:
                return json.dumps({
                    "success": False,
                    "error": f"未知的编辑工具: {tool_name}"
                })

        except Exception as e:
            logger.error(f"[EditToolsExecutor] 执行 {tool_name} 失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "tool": tool_name
            })
