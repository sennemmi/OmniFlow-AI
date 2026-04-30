"""
代码工具化搜索服务

提供类似 LSP/Grep/Glob 的工具化代码搜索能力，作为 RAG 的轻量级替代方案。

核心工具：
1. Glob 搜索 - 基于文件路径模式匹配
2. Grep 搜索 - 基于内容正则匹配
3. LSP 风格符号搜索 - 基于 AST 的符号定义/引用查找
4. 文件树浏览 - 目录结构导航

特点：
- 无需向量数据库，零依赖
- 实时搜索，无需预建索引
- 精确匹配，可解释性强
- 适合确定性代码导航场景
"""

import os
import re
import ast
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SymbolType(Enum):
    """符号类型"""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"


@dataclass
class Symbol:
    """代码符号"""
    name: str
    type: SymbolType
    file_path: str
    line: int
    column: int
    end_line: Optional[int] = None
    signature: Optional[str] = None
    docstring: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
        }


@dataclass
class GrepResult:
    """Grep 搜索结果"""
    file_path: str
    line: int
    content: str
    match_start: int
    match_end: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line": self.line,
            "content": self.content,
            "match_start": self.match_start,
            "match_end": self.match_end,
        }


@dataclass
class GlobResult:
    """Glob 搜索结果"""
    file_path: str
    file_type: str  # "file" or "directory"
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
        }


class CodeTools:
    """
    代码工具化搜索服务

    提供 Glob/Grep/LSP 风格的代码搜索能力
    """

    def __init__(self, project_path: str):
        """
        初始化代码工具

        Args:
            project_path: 项目根目录路径
        """
        self.project_path = Path(project_path).resolve()
        self._file_cache: Dict[str, str] = {}  # 简单的文件内容缓存

    # =========================================================================
    # Tool 1: Glob 搜索
    # =========================================================================

    def glob(
        self,
        pattern: str,
        include_dirs: bool = False,
        max_depth: Optional[int] = None
    ) -> List[GlobResult]:
        """
        Glob 文件搜索

        Args:
            pattern: Glob 模式，如 "**/*.py", "app/api/*.py"
            include_dirs: 是否包含目录
            max_depth: 最大搜索深度

        Returns:
            List[GlobResult]: 匹配的文件列表

        示例：
            >>> tools.glob("**/*.py")
            >>> tools.glob("app/api/v1/*.py", max_depth=3)
        """
        results = []

        # 构建搜索路径
        if max_depth:
            # 限制深度的 glob
            for depth in range(max_depth + 1):
                depth_pattern = "/".join(["*"] * depth) + "/" + pattern
                for path in self.project_path.glob(depth_pattern):
                    if path.is_file() or (include_dirs and path.is_dir()):
                        results.append(self._create_glob_result(path))
        else:
            # 无限制 glob
            for path in self.project_path.rglob(pattern):
                if path.is_file() or (include_dirs and path.is_dir()):
                    results.append(self._create_glob_result(path))

        # 去重并保持顺序
        seen = set()
        unique_results = []
        for r in results:
            if r.file_path not in seen:
                seen.add(r.file_path)
                unique_results.append(r)

        return unique_results

    def _create_glob_result(self, path: Path) -> GlobResult:
        """创建 GlobResult"""
        relative_path = str(path.relative_to(self.project_path))
        if path.is_file():
            return GlobResult(
                file_path=relative_path,
                file_type="file",
                size_bytes=path.stat().st_size
            )
        else:
            return GlobResult(
                file_path=relative_path,
                file_type="directory",
                size_bytes=None
            )

    # =========================================================================
    # Tool 2: Grep 搜索
    # =========================================================================

    def grep(
        self,
        pattern: str,
        path_pattern: str = "**/*",
        case_sensitive: bool = False,
        max_results: int = 100,
        context_lines: int = 0
    ) -> List[GrepResult]:
        """
        Grep 内容搜索

        Args:
            pattern: 正则表达式模式
            path_pattern: 文件路径过滤模式
            case_sensitive: 是否区分大小写
            max_results: 最大结果数
            context_lines: 上下文行数

        Returns:
            List[GrepResult]: 匹配结果列表

        示例：
            >>> tools.grep("def ", "**/*.py")
            >>> tools.grep("class.*API", "app/api/*.py")
        """
        results = []
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            compiled_pattern = re.compile(pattern, flags)
        except re.error as e:
            logger.error(f"Invalid regex pattern: {pattern}, error: {e}")
            return []

        # 获取目标文件列表
        target_files = self.glob(path_pattern)

        for file_result in target_files:
            if file_result.file_type != "file":
                continue

            file_path = self.project_path / file_result.file_path

            # 跳过二进制文件
            if self._is_binary(file_path):
                continue

            try:
                content = self._read_file(file_path)
                lines = content.splitlines()

                for line_num, line in enumerate(lines, 1):
                    for match in compiled_pattern.finditer(line):
                        if len(results) >= max_results:
                            return results

                        # 提取上下文
                        if context_lines > 0:
                            start_idx = max(0, line_num - context_lines - 1)
                            end_idx = min(len(lines), line_num + context_lines)
                            content_with_context = "\n".join(lines[start_idx:end_idx])
                        else:
                            content_with_context = line

                        results.append(GrepResult(
                            file_path=file_result.file_path,
                            line=line_num,
                            content=content_with_context,
                            match_start=match.start(),
                            match_end=match.end()
                        ))

            except Exception as e:
                logger.warning(f"Error reading file {file_path}: {e}")
                continue

        return results

    def grep_symbol(
        self,
        symbol_name: str,
        symbol_type: Optional[SymbolType] = None,
        path_pattern: str = "**/*.py"
    ) -> List[Symbol]:
        """
        搜索特定符号定义

        Args:
            symbol_name: 符号名称
            symbol_type: 符号类型过滤
            path_pattern: 文件路径过滤

        Returns:
            List[Symbol]: 符号定义列表
        """
        # 构建搜索模式
        if symbol_type == SymbolType.FUNCTION:
            pattern = rf"^\s*def\s+{re.escape(symbol_name)}\s*\("
        elif symbol_type == SymbolType.CLASS:
            pattern = rf"^\s*class\s+{re.escape(symbol_name)}\b"
        elif symbol_type == SymbolType.METHOD:
            pattern = rf"^\s*def\s+{re.escape(symbol_name)}\s*\("
        else:
            pattern = rf"\b{re.escape(symbol_name)}\b"

        grep_results = self.grep(pattern, path_pattern, case_sensitive=True)

        symbols = []
        for result in grep_results:
            # 解析符号类型
            detected_type = self._detect_symbol_type(result.content, symbol_name)
            if symbol_type and detected_type != symbol_type:
                continue

            symbols.append(Symbol(
                name=symbol_name,
                type=detected_type or SymbolType.VARIABLE,
                file_path=result.file_path,
                line=result.line,
                column=result.match_start,
                signature=result.content.strip()
            ))

        return symbols

    def _detect_symbol_type(self, line: str, name: str) -> Optional[SymbolType]:
        """检测符号类型"""
        stripped = line.strip()
        if stripped.startswith("def "):
            if stripped.startswith(f"def {name}("):
                return SymbolType.FUNCTION
        elif stripped.startswith("class "):
            if stripped.startswith(f"class {name}"):
                return SymbolType.CLASS
        elif stripped.startswith("import ") or stripped.startswith("from "):
            return SymbolType.IMPORT
        return SymbolType.VARIABLE

    # =========================================================================
    # Tool 3: LSP 风格符号搜索
    # =========================================================================

    def find_symbol_definitions(
        self,
        symbol_name: str,
        file_path: Optional[str] = None
    ) -> List[Symbol]:
        """
        查找符号定义（LSP: textDocument/definition）

        Args:
            symbol_name: 符号名称
            file_path: 限制搜索的文件路径

        Returns:
            List[Symbol]: 符号定义列表
        """
        symbols = []

        if file_path:
            # 在指定文件中搜索
            target_files = [file_path]
        else:
            # 全局搜索
            target_files = [r.file_path for r in self.glob("**/*.py")]

        for target_file in target_files:
            full_path = self.project_path / target_file
            try:
                content = self._read_file(full_path)
                file_symbols = self._parse_python_symbols(content, target_file)

                for symbol in file_symbols:
                    if symbol.name == symbol_name:
                        symbols.append(symbol)

            except Exception as e:
                logger.warning(f"Error parsing file {target_file}: {e}")
                continue

        return symbols

    def find_symbol_references(
        self,
        symbol_name: str,
        file_path: Optional[str] = None
    ) -> List[GrepResult]:
        """
        查找符号引用（LSP: textDocument/references）

        Args:
            symbol_name: 符号名称
            file_path: 限制搜索的文件路径

        Returns:
            List[GrepResult]: 引用位置列表
        """
        pattern = rf"\b{re.escape(symbol_name)}\b"
        path_pattern = file_path if file_path else "**/*.py"

        return self.grep(pattern, path_pattern, case_sensitive=True)

    def get_document_symbols(self, file_path: str) -> List[Symbol]:
        """
        获取文件中的所有符号（LSP: textDocument/documentSymbol）

        Args:
            file_path: 文件路径

        Returns:
            List[Symbol]: 符号列表
        """
        full_path = self.project_path / file_path
        try:
            content = self._read_file(full_path)
            return self._parse_python_symbols(content, file_path)
        except Exception as e:
            logger.warning(f"Error parsing file {file_path}: {e}")
            return []

    def _parse_python_symbols(self, content: str, file_path: str) -> List[Symbol]:
        """解析 Python 文件中的符号"""
        symbols = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return symbols

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                symbol_type = SymbolType.METHOD if self._is_method(node) else SymbolType.FUNCTION
                symbols.append(Symbol(
                    name=node.name,
                    type=symbol_type,
                    file_path=file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    end_line=node.end_lineno if hasattr(node, 'end_lineno') else None,
                    signature=self._get_function_signature(node),
                    docstring=ast.get_docstring(node)
                ))
            elif isinstance(node, ast.ClassDef):
                symbols.append(Symbol(
                    name=node.name,
                    type=SymbolType.CLASS,
                    file_path=file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    end_line=node.end_lineno if hasattr(node, 'end_lineno') else None,
                    signature=self._get_class_signature(node),
                    docstring=ast.get_docstring(node)
                ))

        return symbols

    def _is_method(self, node: ast.FunctionDef) -> bool:
        """检查是否为方法"""
        # 简单启发式：检查第一个参数是否为 self/cls
        if node.args.args:
            first_arg = node.args.args[0].arg
            return first_arg in ('self', 'cls')
        return False

    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """获取函数签名"""
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)

        # 处理默认参数
        defaults_start = len(node.args.args) - len(node.args.defaults)
        for i, default in enumerate(node.args.defaults):
            arg_idx = defaults_start + i
            args[arg_idx] += f" = {ast.unparse(default)}"

        signature = f"def {node.name}({', '.join(args)})"

        if node.returns:
            signature += f" -> {ast.unparse(node.returns)}"

        return signature

    def _get_class_signature(self, node: ast.ClassDef) -> str:
        """获取类签名"""
        bases = [ast.unparse(base) for base in node.bases]
        signature = f"class {node.name}"
        if bases:
            signature += f"({', '.join(bases)})"
        return signature

    # =========================================================================
    # Tool 4: 文件树浏览
    # =========================================================================

    def list_directory_tree(
        self,
        path: str = ".",
        max_depth: int = 3,
        include_hidden: bool = False
    ) -> Dict[str, Any]:
        """
        列出目录树结构

        Args:
            path: 起始路径
            max_depth: 最大深度
            include_hidden: 是否包含隐藏文件

        Returns:
            Dict: 树形结构
        """
        target_path = self.project_path / path

        if not target_path.exists():
            return {"error": f"Path not found: {path}"}

        def build_tree(current_path: Path, current_depth: int) -> Dict[str, Any]:
            name = current_path.name or str(self.project_path.name)
            result = {
                "name": name,
                "path": str(current_path.relative_to(self.project_path)),
                "type": "directory" if current_path.is_dir() else "file",
            }

            if current_path.is_file():
                result["size"] = current_path.stat().st_size
                return result

            if current_depth >= max_depth:
                result["truncated"] = True
                return result

            children = []
            try:
                for item in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    # 跳过隐藏文件
                    if not include_hidden and item.name.startswith("."):
                        continue

                    # 跳过常见忽略目录
                    if item.name in ('__pycache__', 'node_modules', '.git', '.venv', 'venv'):
                        continue

                    children.append(build_tree(item, current_depth + 1))

                result["children"] = children
            except PermissionError:
                result["error"] = "Permission denied"

            return result

        return build_tree(target_path, 0)

    def find_files_by_content_type(
        self,
        content_type: str,
        max_results: int = 50
    ) -> List[GlobResult]:
        """
        按内容类型查找文件

        Args:
            content_type: 内容类型，如 "python", "javascript", "markdown"
            max_results: 最大结果数

        Returns:
            List[GlobResult]: 文件列表
        """
        type_extensions = {
            "python": ["*.py", "*.pyw"],
            "javascript": ["*.js", "*.jsx", "*.mjs"],
            "typescript": ["*.ts", "*.tsx"],
            "markdown": ["*.md", "*.markdown"],
            "json": ["*.json"],
            "yaml": ["*.yaml", "*.yml"],
            "html": ["*.html", "*.htm"],
            "css": ["*.css", "*.scss", "*.sass", "*.less"],
        }

        extensions = type_extensions.get(content_type.lower(), [f"*.{content_type}"])

        results = []
        for ext in extensions:
            for result in self.glob(ext):
                results.append(result)
                if len(results) >= max_results:
                    return results

        return results

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _read_file(self, file_path: Path) -> str:
        """读取文件内容（带缓存）"""
        str_path = str(file_path)

        if str_path in self._file_cache:
            return self._file_cache[str_path]

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                self._file_cache[str_path] = content
                return content
        except Exception as e:
            logger.warning(f"Error reading file {file_path}: {e}")
            raise

    def _is_binary(self, file_path: Path) -> bool:
        """检查是否为二进制文件"""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                return b'\x00' in chunk
        except:
            return True

    def clear_cache(self):
        """清除文件缓存"""
        self._file_cache.clear()


# 便捷函数
def get_code_tools(project_path: str) -> CodeTools:
    """
    获取 CodeTools 实例

    Args:
        project_path: 项目路径

    Returns:
        CodeTools: 代码工具实例
    """
    return CodeTools(project_path)
