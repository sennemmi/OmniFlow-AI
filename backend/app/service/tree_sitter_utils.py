"""
Tree-sitter 语言感知解析工具

为 read_chunk / grep_ast 提供多语言 AST 支持，
替代 Python 原生 ast 模块，兼容 Python/TypeScript/JavaScript。
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

from tree_sitter import Language, Parser, Node
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
import tree_sitter_javascript as tsjavascript

logger = __import__("logging").getLogger(__name__)

# 语言映射，根据文件后缀选择
LANG_MAP: Dict[str, Language] = {
    ".py": Language(tspython.language()),
    ".ts": Language(tstypescript.language_typescript()),
    ".tsx": Language(tstypescript.language_tsx()),
    ".js": Language(tsjavascript.language()),
    ".jsx": Language(tsjavascript.language()),
}

# 不同语言中代表函数/类定义的节点类型
_SYMBOL_NODE_TYPES = {
    "python": (
        "function_definition",
        "async_function_definition",
        "class_definition",
    ),
    "typescript": (
        "function_declaration",
        "function_signature",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "interface_declaration",
    ),
    "javascript": (
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
    ),
}

# import 节点类型
_IMPORT_NODE_TYPES = {
    "python": ("import_statement", "import_from_statement"),
    "typescript": ("import_statement", "import_declaration"),
    "javascript": ("import_statement", "import_declaration"),
}


def _detect_language(file_path: str) -> str:
    """根据后缀检测语言类别（用于内部类型映射）"""
    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in (".ts", ".tsx"):
        return "typescript"
    if ext in (".js", ".jsx"):
        return "javascript"
    return "python"  # 默认回退


def get_parser(file_path: str) -> Parser:
    """根据文件路径获取对应语言的 Tree-sitter Parser"""
    ext = Path(file_path).suffix.lower()
    lang = LANG_MAP.get(ext)
    if not lang:
        raise ValueError(f"Unsupported language for {file_path} (ext={ext})")
    parser = Parser(lang)
    return parser


def find_symbol_node(root: Node, symbol_name: str, file_path: str = "") -> Optional[Node]:
    """
    在 AST 中查找函数定义或类定义节点，名称匹配。

    支持 Python / TypeScript / JavaScript。
    """
    lang = _detect_language(file_path)
    valid_types = _SYMBOL_NODE_TYPES.get(lang, _SYMBOL_NODE_TYPES["python"])

    def _walk(node: Node) -> Optional[Node]:
        if node.type in valid_types:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = name_node.text.decode("utf-8")
                if name == symbol_name:
                    return node
        for child in node.children:
            found = _walk(child)
            if found is not None:
                return found
        return None

    return _walk(root)


def find_enclosing_node(
    root: Node, start_byte: int, end_byte: int, file_path: str = ""
) -> Optional[Node]:
    """找到包含给定字节范围的最小语法节点（通常为函数/类）"""
    lang = _detect_language(file_path)
    valid_types = _SYMBOL_NODE_TYPES.get(lang, _SYMBOL_NODE_TYPES["python"])

    best: Optional[Node] = None

    def _walk(node: Node) -> None:
        nonlocal best
        if node.start_byte <= start_byte and node.end_byte >= end_byte:
            if node.type in valid_types:
                if best is None or (node.end_byte - node.start_byte) < (
                    best.end_byte - best.start_byte
                ):
                    best = node
        for child in node.children:
            _walk(child)

    _walk(root)
    return best


def extract_summary(code: str, parser: Parser, file_path: str = "") -> str:
    """提取 imports + 顶层符号签名（多语言兼容）"""
    tree = parser.parse(bytes(code, "utf-8"))
    root = tree.root_node
    lines = code.split("\n")

    lang = _detect_language(file_path)
    import_types = _IMPORT_NODE_TYPES.get(lang, _IMPORT_NODE_TYPES["python"])
    symbol_types = _SYMBOL_NODE_TYPES.get(lang, _SYMBOL_NODE_TYPES["python"])

    import_lines: List[str] = []
    sig_lines: List[str] = []

    for child in root.children:
        if child.type in import_types:
            import_lines.append(child.text.decode("utf-8"))
        elif child.type in symbol_types:
            # 取定义的第一行（到冒号或大括号）
            start_line = child.start_point[0]
            if start_line < len(lines):
                sig_lines.append(lines[start_line].rstrip())

    parts: List[str] = []
    if import_lines:
        parts.append("# === Imports ===")
        parts.extend(dict.fromkeys(import_lines))  # 去重保序
    if sig_lines:
        parts.append("\n# === Top-level symbols ===")
        parts.extend(sig_lines)

    return "\n".join(parts)


def list_top_symbols(code: str, parser: Parser, file_path: str = "") -> List[str]:
    """列出文件的顶层符号名"""
    try:
        tree = parser.parse(bytes(code, "utf-8"))
        root = tree.root_node
        lang = _detect_language(file_path)
        valid_types = _SYMBOL_NODE_TYPES.get(lang, _SYMBOL_NODE_TYPES["python"])

        symbols: List[str] = []
        for child in root.children:
            if child.type in valid_types:
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    symbols.append(name_node.text.decode("utf-8"))
        return symbols
    except Exception:
        return []


def grep_ast_file(
    code: str,
    rel_path: str,
    pattern: str,
    search_type: str,
    parser: Parser,
) -> List[Dict[str, Any]]:
    """
    在单个文件中执行 AST 搜索（替代原 _grep_ast_file 中的 ast 逻辑）

    search_type 支持：
      - "text"       普通文本搜索（正则）
      - "function"   搜索函数定义
      - "class"      搜索类定义
      - "callers"    搜索调用了某函数的位置
      - "import"     搜索 import 了某模块的文件
    """
    results: List[Dict[str, Any]] = []
    lines = code.splitlines()

    # --- 文本搜索（退化到 grep 行为）---
    if search_type == "text":
        try:
            rx = __import__("re").compile(pattern, __import__("re").IGNORECASE)
        except __import__("re").error:
            rx = __import__("re").compile(
                __import__("re").escape(pattern), __import__("re").IGNORECASE
            )
        for i, line in enumerate(lines):
            if rx.search(line):
                results.append({
                    "file": rel_path,
                    "line": i + 1,
                    "content": line.rstrip(),
                    "context": "\n".join(lines[max(0, i - 1) : i + 3]),
                })
        return results

    # --- AST 搜索 ---
    try:
        tree = parser.parse(bytes(code, "utf-8"))
        root = tree.root_node
    except Exception:
        return results

    lang = _detect_language(rel_path)
    valid_symbol_types = _SYMBOL_NODE_TYPES.get(lang, _SYMBOL_NODE_TYPES["python"])

    if search_type in ("function", "class"):
        if search_type == "function":
            target_types = tuple(
                t for t in valid_symbol_types if "function" in t or "method" in t or "arrow" in t
            )
        else:
            target_types = tuple(
                t for t in valid_symbol_types if "class" in t or "interface" in t
            )

        def _walk_symbols(node: Node) -> None:
            if node.type in target_types:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = name_node.text.decode("utf-8")
                    if pattern.lower() in name.lower():
                        results.append({
                            "file": rel_path,
                            "line": node.start_point[0] + 1,
                            "name": name,
                            "end_line": node.end_point[0] + 1,
                            "content": lines[node.start_point[0]].rstrip(),
                        })
            for child in node.children:
                _walk_symbols(child)

        _walk_symbols(root)

    elif search_type == "callers":
        def _walk_calls(node: Node) -> None:
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node is not None:
                    name = ""
                    if func_node.type == "identifier":
                        name = func_node.text.decode("utf-8")
                    elif func_node.type == "member_expression":
                        # 取属性名
                        attr = func_node.child_by_field_name("property")
                        if attr is not None:
                            name = attr.text.decode("utf-8")
                    if name == pattern:
                        ln = node.start_point[0]
                        results.append({
                            "file": rel_path,
                            "line": ln + 1,
                            "content": lines[ln].rstrip() if ln < len(lines) else "",
                            "context": "\n".join(lines[max(0, ln - 1) : ln + 3]),
                        })
            for child in node.children:
                _walk_calls(child)

        _walk_calls(root)

    elif search_type == "import":
        import_types = _IMPORT_NODE_TYPES.get(lang, _IMPORT_NODE_TYPES["python"])

        def _walk_imports(node: Node) -> None:
            if node.type in import_types:
                # 将整个 import 语句文本与 pattern 比较
                stmt = node.text.decode("utf-8")
                if pattern.lower() in stmt.lower():
                    ln = node.start_point[0]
                    results.append({
                        "file": rel_path,
                        "line": ln + 1,
                        "content": lines[ln].rstrip() if ln < len(lines) else "",
                    })
            for child in node.children:
                _walk_imports(child)

        _walk_imports(root)

    return results
