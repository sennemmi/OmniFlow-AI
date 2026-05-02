"""
代码验证服务

提供代码语法检查、测试导入验证、测试语法修复等功能
"""

import ast
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple

from app.service.sandbox_file_service import SandboxFileService

logger = logging.getLogger(__name__)


class SyntaxErrorInfo:
    """语法错误信息"""
    def __init__(self, file: str, error: str, line: int = 0, context: str = ""):
        self.file = file
        self.error = error
        self.line = line
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "error": self.error,
            "line": self.line,
            "context": self.context
        }


class CodeValidationService:
    """
    代码验证服务

    职责：
    1. 使用 py_compile 检查代码语法
    2. 验证测试文件的导入有效性
    3. 修复测试文件语法错误
    """

    def __init__(self):
        pass

    async def check_syntax_with_py_compile(
        self,
        code_files: List[Dict],
        file_service: SandboxFileService
    ) -> List[SyntaxErrorInfo]:
        """
        使用 python -m py_compile 检查代码语法错误

        Args:
            code_files: 代码文件列表
            file_service: 文件服务

        Returns:
            语法错误列表
        """
        syntax_errors = []

        for fc in code_files:
            fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
            change_type = fc.get("change_type")

            content_to_check = None
            if change_type == "add":
                content_to_check = fc.get("content", "")
            elif change_type == "modify":
                search_block = fc.get("search_block", "")
                replace_block = fc.get("replace_block", "")
                if search_block:
                    read_r = await file_service.read_file(fp)
                    if read_r.exists:
                        content_to_check = read_r.content.replace(search_block, replace_block, 1)

            if not content_to_check:
                continue

            error_info = self._check_single_file_syntax(fp, content_to_check)
            if error_info:
                syntax_errors.append(error_info)

        return syntax_errors

    def _check_single_file_syntax(self, file_path: str, content: str) -> Optional[SyntaxErrorInfo]:
        """检查单个文件的语法"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            result = subprocess.run(
                ['python', '-m', 'py_compile', tmp_path],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Syntax error"
                line_no = 0
                line_match = re.search(r'line (\d+)', error_msg)
                if line_match:
                    line_no = int(line_match.group(1))

                lines = content.splitlines()
                context_start = max(0, line_no - 3)
                context_end = min(len(lines), line_no + 2)
                context = "\n".join(lines[context_start:context_end])

                return SyntaxErrorInfo(
                    file=file_path,
                    error=error_msg,
                    line=line_no,
                    context=context
                )
        except Exception as e:
            return SyntaxErrorInfo(
                file=file_path,
                error=f"语法检查失败: {e}",
                line=0,
                context=""
            )
        finally:
            try:
                if 'tmp_path' in locals():
                    import os
                    os.unlink(tmp_path)
            except:
                pass

        return None

    async def validate_test_imports(
        self,
        test_files: List[Dict],
        file_service: SandboxFileService
    ) -> List[str]:
        """
        验证测试文件中的所有 import 是否真实存在

        Args:
            test_files: 测试文件列表
            file_service: 文件服务

        Returns:
            List[str]: 导入错误列表
        """
        errors = []

        for test_file in test_files:
            file_path = test_file.get("file_path", "")
            content = test_file.get("content", "")

            if not content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    if not module or not module.startswith("app."):
                        continue

                    module_path = module.replace(".", "/") + ".py"

                    read_res = await file_service.read_file(module_path)
                    if not read_res.exists:
                        errors.append(f"{file_path}: 导入的模块不存在: {module}")
                        continue

                    try:
                        module_tree = ast.parse(read_res.content)
                        module_symbols = self._extract_module_symbols(module_tree)

                        for alias in node.names:
                            if alias.name != "*" and alias.name not in module_symbols:
                                errors.append(f"{file_path}: 导入的符号不存在: {module}.{alias.name}")

                    except SyntaxError:
                        pass

        return errors

    def _extract_module_symbols(self, tree: ast.AST) -> Set[str]:
        """从 AST 中提取模块级符号"""
        module_symbols = set()

        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                module_symbols.add(n.name)
            elif isinstance(n, ast.ClassDef):
                module_symbols.add(n.name)
            elif isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    if alias.name:
                        module_symbols.add(alias.name)
            elif isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name:
                        module_symbols.add(alias.name.split('.')[0])

        return module_symbols

    def is_async_function(self, tree: ast.AST, func_name: str) -> bool:
        """检测函数是否是 async def"""
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
                return True
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AsyncFunctionDef) and item.name == func_name:
                        return True
        return False

    def is_inside_function(self, target_node: ast.AST, tree: ast.AST) -> bool:
        """判断节点是否在函数体内"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if child is target_node:
                        return True
        return False


# 单例实例
code_validation_service = CodeValidationService()
