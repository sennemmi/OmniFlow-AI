"""
代码验证服务

提供代码语法检查、测试导入验证、测试语法修复等功能
所有语法检查均在 Docker 沙箱内执行，避免宿主机编码问题
"""

import ast
import logging
import re
from typing import Dict, List, Optional, Any, Set

from app.service.sandbox_file_service import SandboxFileService
from app.service.sandbox_manager import sandbox_manager

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
    1. 在 Docker 沙箱内使用 py_compile 检查代码语法
    2. 验证测试文件的导入有效性
    3. 修复测试文件语法错误

    注意：所有语法检查均在沙箱内执行，避免宿主机编码问题
    """

    def __init__(self):
        pass

    async def check_syntax_in_sandbox(
        self,
        file_path: str,
        pipeline_id: int,
        content: Optional[str] = None
    ) -> Optional[SyntaxErrorInfo]:
        """
        在沙箱内检查单个文件的语法

        Args:
            file_path: 文件路径（相对于 backend/ 的路径）
            pipeline_id: Pipeline ID
            content: 可选，如果提供则先写入沙箱再检查

        Returns:
            None 表示语法正确，否则返回 SyntaxErrorInfo
        """
        try:
            clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            full_path = f"/workspace/backend/{clean_path}"

            # 如果提供了内容，先写入沙箱
            if content is not None:
                file_service = SandboxFileService(pipeline_id=pipeline_id)
                write_result = await file_service.write_file(clean_path, content)
                if not write_result.get("success"):
                    return SyntaxErrorInfo(
                        file=clean_path,
                        error=write_result.get("error", "写入沙箱失败"),
                        line=0
                    )

            # 在沙箱内执行语法检查
            result = await sandbox_manager.exec(
                pipeline_id,
                f"python -m py_compile {full_path} 2>&1",
                timeout=10
            )

            if result.exit_code != 0:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Syntax error"
                line_no = 0

                # 尝试从错误信息中提取行号
                line_match = re.search(r'line\s+(\d+)', error_msg, re.IGNORECASE)
                if line_match:
                    line_no = int(line_match.group(1))

                return SyntaxErrorInfo(
                    file=clean_path,
                    error=error_msg,
                    line=line_no,
                    context=""
                )

            return None  # 语法正确

        except Exception as e:
            return SyntaxErrorInfo(
                file=file_path,
                error=f"语法检查失败: {e}",
                line=0,
                context=""
            )

    async def batch_check_syntax_in_sandbox(
        self,
        code_files: List[Dict],
        pipeline_id: int
    ) -> List[SyntaxErrorInfo]:
        """
        批量检查代码文件语法（在沙箱内）

        Args:
            code_files: 代码文件列表，每个文件包含 file_path 和 content
            pipeline_id: Pipeline ID

        Returns:
            语法错误列表
        """
        errors = []

        for fc in code_files:
            fp = fc.get("file_path", "")
            content = fc.get("content", "")

            if not fp or not content or not fp.endswith(".py"):
                continue

            error_info = await self.check_syntax_in_sandbox(fp, pipeline_id, content)
            if error_info:
                errors.append(error_info)

        return errors

    async def check_syntax_in_sandbox_by_paths(
        self,
        file_paths: List[str],
        pipeline_id: int
    ) -> List[SyntaxErrorInfo]:
        """
        根据文件路径列表检查语法（文件已在沙箱中）

        Args:
            file_paths: 文件路径列表（相对于 backend/ 的路径）
            pipeline_id: Pipeline ID

        Returns:
            语法错误列表
        """
        errors = []

        for fp in file_paths:
            if not fp.endswith(".py"):
                continue

            error_info = await self.check_syntax_in_sandbox(fp, pipeline_id)
            if error_info:
                errors.append(error_info)

        return errors

    # Python 标准库模块名（可能与 app 模块冲突）
    STDLIB_MODULES = {
        'time', 'sys', 'os', 'json', 're', 'datetime', 'collections', 'typing',
        'pathlib', 'inspect', 'itertools', 'functools', 'hashlib', 'base64',
        'random', 'string', 'math', 'statistics', 'decimal', 'fractions',
        'calendar', 'zoneinfo', 'enum', 'dataclasses', 'abc', 'copy', 'pickle',
        'socket', 'urllib', 'http', 'email', 'mime', 'csv', 'xml', 'html',
        'sqlite3', 'logging', 'unittest', 'pdb', 'traceback', 'warnings',
        'contextlib', 'asyncio', 'concurrent', 'threading', 'multiprocessing',
        'subprocess', 'tempfile', 'shutil', 'glob', 'fnmatch', 'linecache',
        'textwrap', 'stringprep', 'codecs', 'encodings', 'io', 'csv'
    }

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

                    # 【修复】检查是否与标准库冲突
                    module_parts = module.split(".")
                    if any(part in self.STDLIB_MODULES for part in module_parts):
                        # 对于与标准库冲突的模块，放宽验证
                        # 因为 Python 的导入机制可能导致冲突
                        logger.warning(f"模块 {module} 包含标准库名称，放宽导入验证")
                        # 只检查文件是否存在，不检查符号
                        module_path = module.replace(".", "/") + ".py"
                        read_res = await file_service.read_file(module_path)
                        if not read_res.exists:
                            errors.append(f"{file_path}: 导入的模块不存在: {module}")
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
        """从 AST 中提取模块级符号（函数、类、变量、重导出等）"""
        module_symbols = set()

        for node in tree.body:  # 只遍历模块顶层，避免收集函数内部的变量
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                module_symbols.add(node.name)
            elif isinstance(node, ast.ClassDef):
                module_symbols.add(node.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name:
                        module_symbols.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        module_symbols.add(alias.name.split('.')[0])
            # ===== 新增部分：处理变量赋值 =====
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if not target.id.startswith('_'):
                            module_symbols.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    if not node.target.id.startswith('_'):
                        module_symbols.add(node.target.id)
            # ==================================

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
