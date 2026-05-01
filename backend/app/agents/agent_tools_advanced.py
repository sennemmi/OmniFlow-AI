"""
AgentTools 高级工具：read_chunk / grep_ast / semantic_search

基于 tree-sitter 实现多语言 AST 感知搜索与代码块读取。
"""

import ast
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.service.tree_sitter_utils import (
    get_parser,
    find_symbol_node,
    find_enclosing_node,
    extract_summary,
    list_top_symbols,
)

logger = logging.getLogger(__name__)


class AgentToolsAdvanced:
    """Agent 高级工具集合（tree-sitter 驱动）"""

    def __init__(self, project_path: str, file_service=None):
        self.project_path = project_path
        self._file_service = file_service
        self._sandbox_mode = file_service is not None

    # =====================================================================
    # read_chunk
    # =====================================================================

    def _read_content(self, file_path: str) -> tuple:
        """读取文件内容，支持本地和沙盒模式"""
        # 保持原始路径格式传给 file_service（它内部会处理 backend/ 前缀）
        original_path = file_path

        if self._sandbox_mode and self._file_service:
            import asyncio
            import concurrent.futures
            try:
                try:
                    loop = asyncio.get_running_loop()
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            lambda: asyncio.run(self._file_service.read_file(original_path))
                        )
                        read_result = future.result(timeout=30)
                except RuntimeError:
                    read_result = asyncio.run(self._file_service.read_file(original_path))

                if not read_result.exists:
                    return None, read_result.error or "File not found"
                return read_result.content, None
            except Exception as e:
                return None, str(e)
        else:
            clean_path = file_path.replace("backend/", "").lstrip("/")
            full_path = Path(self.project_path) / clean_path
            if not full_path.exists():
                return None, f"文件不存在: {clean_path}"
            return full_path.read_text(encoding="utf-8", errors="replace"), None

    def read_chunk(
        self,
        file_path: str,
        symbol_name: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        try:
            clean_path = file_path.replace("backend/", "").lstrip("/")
            raw, error = self._read_content(file_path)
            if raw is None:
                return json.dumps({"error": error or f"文件不存在: {clean_path}", "exists": False})

            lines = raw.splitlines()
            total_lines = len(lines)

            try:
                parser = get_parser(clean_path)
            except ValueError:
                parser = None

            if symbol_name:
                if parser is None:
                    return json.dumps({
                        "error": f"不支持的文件类型，无法按符号读取: {clean_path}",
                        "exists": True,
                        "available_symbols": [],
                    })
                try:
                    tree = parser.parse(bytes(raw, "utf-8"))
                    node = find_symbol_node(tree.root_node, symbol_name, clean_path)
                except Exception as e:
                    return json.dumps({
                        "error": f"文件解析失败: {e}",
                        "exists": True,
                        "available_symbols": [],
                    })

                if node is None:
                    return json.dumps({
                        "error": f"符号 '{symbol_name}' 不存在",
                        "exists": True,
                        "available_symbols": list_top_symbols(raw, parser, clean_path),
                    })

                s = node.start_point[0]
                e = node.end_point[0] + 1
                chunk = "\n".join(lines[s:e])
                return json.dumps({
                    "file": clean_path,
                    "symbol": symbol_name,
                    "start_line": s + 1,
                    "end_line": e,
                    "mode": "symbol",
                    "content": chunk,
                    "lines": e - s,
                }, ensure_ascii=False)

            if start_line is not None:
                s = max(0, start_line - 1)
                if end_line is None or end_line < start_line:
                    actual_end = min(start_line + 80, len(lines))
                else:
                    actual_end = min(end_line, len(lines))
                e = actual_end

                if parser is not None:
                    try:
                        tree = parser.parse(bytes(raw, "utf-8"))
                        start_byte = sum(len(line) + 1 for line in lines[:s])
                        end_byte = start_byte + sum(len(line) + 1 for line in lines[s:e])
                        node = find_enclosing_node(tree.root_node, start_byte, end_byte, clean_path)
                        if node is not None:
                            s = node.start_point[0]
                            e = node.end_point[0] + 1
                    except Exception:
                        pass

                if e <= s:
                    e = min(s + 10, len(lines))

                chunk = "\n".join(lines[s:e])
                return json.dumps({
                    "file": clean_path,
                    "start_line": s + 1,
                    "end_line": e,
                    "mode": "lines",
                    "content": chunk,
                    "lines": e - s,
                }, ensure_ascii=False)

            if parser is not None:
                summary = extract_summary(raw, parser, clean_path)
            else:
                summary = raw[:2000]

            return json.dumps({
                "file": clean_path,
                "mode": "summary",
                "total_lines": total_lines,
                "content": summary,
            }, ensure_ascii=False)

        except Exception as exc:
            logger.error(f"[read_chunk] 失败: {exc}")
            return json.dumps({"error": str(exc), "exists": False})

    def _list_top_symbols(self, code: str) -> List[str]:
        try:
            parser = get_parser("temp.py")
            return list_top_symbols(code, parser, "temp.py")
        except Exception:
            return []

    def _list_top_symbols_in_file(self, file_path: str) -> List[str]:
        try:
            full_path = Path(self.project_path) / file_path.replace("backend/", "").lstrip("/")
            if not full_path.exists():
                return []
            content = full_path.read_text(encoding="utf-8", errors="replace")
            return self._list_top_symbols(content)
        except Exception:
            return []

    def _extract_file_summary(self, code: str) -> str:
        try:
            parser = get_parser("temp.py")
            return extract_summary(code, parser, "temp.py")
        except Exception:
            return code[:2000]

    # =====================================================================
    # grep_ast
    # =====================================================================

    def _walk_type(self, node, node_type: str):
        if node.type == node_type:
            yield node
        for child in node.children:
            yield from self._walk_type(child, node_type)

    def _walk_symbol_types(self, node, symbol_types: tuple):
        """递归遍历所有子节点，找到属于 symbol_types 的节点"""
        if node.type in symbol_types:
            yield node
        for child in node.children:
            yield from self._walk_symbol_types(child, symbol_types)

    def _list_files(self, search_path: str) -> List[Path]:
        """列出搜索路径下的所有支持文件，兼容本地和沙盒模式"""
        clean_path = search_path.replace("backend/", "").lstrip("/")
        base = Path(self.project_path) / clean_path

        if not self._sandbox_mode:
            if not base.exists():
                return []
            supported_exts = {"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}
            target_files: List[Path] = []
            if base.is_dir():
                for ext in supported_exts:
                    target_files.extend(base.rglob(ext))
            else:
                target_files = [base]
            return [
                p for p in target_files
                if not any(part in {"__pycache__", ".git", "venv", "node_modules"} for part in p.parts)
            ]

        # sandbox 模式：使用 find 命令获取文件列表
        import asyncio
        import concurrent.futures
        from app.service.sandbox_manager import sandbox_manager

        WORKSPACE_ROOT = "/workspace"
        sandbox_path = f"{WORKSPACE_ROOT}/{clean_path}" if clean_path else WORKSPACE_ROOT
        cmd = f"find {sandbox_path} -type f \\( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \\) 2>/dev/null | sort"

        try:
            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=15))
                    )
                    exec_result = future.result(timeout=30)
            except RuntimeError:
                exec_result = asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=15))

            files: List[Path] = []
            if exec_result.exit_code == 0:
                for line in exec_result.stdout.strip().split("\n"):
                    if line:
                        # line 是容器内路径如 "/workspace/app/agents/tools.py"
                        # 转换为相对路径 "app/agents/tools.py"
                        rel = line.replace(f"{WORKSPACE_ROOT}/", "").replace(WORKSPACE_ROOT, "")
                        # 使用正斜杠创建 Path，避免 Windows 路径问题
                        files.append(Path(rel))
            return files
        except Exception as e:
            logger.error(f"[_list_files] sandbox 模式失败: {e}")
            return []

    def _prefilter_files_sandbox(self, sandbox_root: str, pattern: str) -> set:
        """sandbox 模式下用 grep -rl 预过滤，只返回包含 pattern 的文件（相对路径）"""
        import asyncio
        import concurrent.futures
        from app.service.sandbox_manager import sandbox_manager

        escaped = pattern.replace("'", "'\\''")
        cmd = (
            f"grep -rl --include='*.py' --include='*.ts' --include='*.tsx' "
            f"--include='*.js' --include='*.jsx' "
            f"-F -e '{escaped}' {sandbox_root} 2>/dev/null | head -30"
        )
        try:
            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(sandbox_manager.exec(
                            self._file_service.pipeline_id, cmd, timeout=10
                        ))
                    )
                    exec_result = future.result(timeout=20)
            except RuntimeError:
                exec_result = asyncio.run(sandbox_manager.exec(
                    self._file_service.pipeline_id, cmd, timeout=10
                ))

            matched: set = set()
            if exec_result.exit_code == 0:
                for line in exec_result.stdout.strip().split("\n"):
                    if line:
                        rel = line.replace(f"{sandbox_root}/", "").replace(sandbox_root, "").replace("\\", "/")
                        if rel:
                            matched.add(rel)
            return matched
        except Exception:
            return set()

    def grep_ast(
        self,
        pattern: str,
        search_path: str = ".",
        search_type: str = "text",
        max_results: int = 15,
    ) -> str:
        try:
            matches: List[Dict[str, Any]] = []
            target_files = self._list_files(search_path)

            if not target_files:
                return json.dumps({"pattern": pattern, "search_type": search_type, "count": 0, "matches": []})

            # 【优化】sandbox 模式下用 grep -rl 预过滤，避免逐文件 cat
            prefilter_set: Optional[set] = None
            if self._sandbox_mode and search_type != "text":
                clean_path = search_path.replace("backend/", "").lstrip("/")
                sandbox_root = f"/workspace/{clean_path}" if clean_path else "/workspace"
                prefilter_set = self._prefilter_files_sandbox(sandbox_root, pattern)

            for src_file in target_files:
                if len(matches) >= max_results:
                    break

                try:
                    if self._sandbox_mode:
                        rel = str(src_file).replace("\\", "/")
                        # 预过滤：跳过不包含 pattern 的文件
                        if prefilter_set is not None and rel not in prefilter_set:
                            continue
                        code, error = self._read_content(str(src_file))
                        if code is None:
                            continue
                    else:
                        code = src_file.read_text(encoding="utf-8", errors="replace")
                        rel = src_file.relative_to(self.project_path).as_posix()
                except Exception:
                    continue

                try:
                    parser = get_parser(str(src_file))
                except ValueError:
                    parser = None

                if parser is None or search_type == "text":
                    file_matches = self._grep_text_fallback(code, rel, pattern)
                    matches.extend(file_matches[:max_results - len(matches)])
                    continue

                try:
                    tree = parser.parse(bytes(code, "utf-8"))
                    root = tree.root_node
                except Exception:
                    continue

                lines = code.splitlines()

                if search_type == "function":
                    for node in self._walk_symbol_types(
                        root,
                        (
                            "function_definition",
                            "async_function_definition",
                            "function_declaration",
                            "method_definition",
                        ),
                    ):
                        name_node = node.child_by_field_name("name")
                        if name_node is not None:
                            name = name_node.text.decode("utf-8")
                            if pattern.lower() in name.lower():
                                matches.append({
                                    "file": rel,
                                    "line": node.start_point[0] + 1,
                                    "name": name,
                                    "content": lines[node.start_point[0]].rstrip(),
                                })

                elif search_type == "class":
                    for node in self._walk_symbol_types(
                        root,
                        ("class_definition", "class_declaration", "interface_declaration"),
                    ):
                        name_node = node.child_by_field_name("name")
                        if name_node is not None:
                            name = name_node.text.decode("utf-8")
                            if pattern.lower() in name.lower():
                                matches.append({
                                    "file": rel,
                                    "line": node.start_point[0] + 1,
                                    "name": name,
                                    "content": lines[node.start_point[0]].rstrip(),
                                })

                elif search_type == "callers":
                    for call in self._walk_type(root, "call_expression"):
                        func = call.child_by_field_name("function")
                        if func is not None:
                            func_text = func.text.decode("utf-8")
                            if func_text == pattern or func_text.endswith(f".{pattern}"):
                                ln = call.start_point[0]
                                matches.append({
                                    "file": rel,
                                    "line": ln + 1,
                                    "content": lines[ln].rstrip() if ln < len(lines) else "",
                                })

                elif search_type == "import":
                    for node in root.children:
                        if node.type in (
                            "import_statement",
                            "import_from_statement",
                            "import_declaration",
                        ):
                            import_text = node.text.decode("utf-8")
                            if pattern in import_text:
                                matches.append({
                                    "file": rel,
                                    "line": node.start_point[0] + 1,
                                    "content": import_text.strip(),
                                })

                if len(matches) >= max_results:
                    break

            return json.dumps({
                "pattern": pattern,
                "search_type": search_type,
                "count": len(matches),
                "matches": matches,
            }, ensure_ascii=False, indent=2)

        except Exception as exc:
            logger.error(f"[grep_ast] 失败: {exc}")
            return json.dumps({"error": str(exc), "matches": []})

    def _grep_text_fallback(self, code: str, rel_path: str, pattern: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        lines = code.splitlines()
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)
        for i, line in enumerate(lines):
            if rx.search(line):
                results.append({
                    "file": rel_path,
                    "line": i + 1,
                    "content": line.rstrip(),
                    "context": "\n".join(lines[max(0, i - 1):i + 3]),
                })
        return results

    # =====================================================================
    # semantic_search
    # =====================================================================

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
    ) -> str:
        try:
            from app.service.code_indexer import get_indexer

            indexer = await get_indexer(str(self.project_path), include_tests=False)
            indexer.build_index()

            search_result_str = await indexer.semantic_search(query, top_k=top_k)

            if "--- 相关代码片段" in search_result_str:
                chunks = []
                pattern = r'--- 相关代码片段 #(\d+) \(相关度: ([\d.]+)\) ---\n文件: ([^\n]+) \(第 ([\d-]+) 行\)\n类型: ([^\n]+)\n名称: ([^\n]+)'
                matches = re.findall(pattern, search_result_str)
                for match in matches:
                    idx, score, file_path, lines, chunk_type, name = match
                    chunks.append({
                        "index": int(idx),
                        "score": float(score),
                        "file_path": file_path,
                        "lines": lines,
                        "type": chunk_type,
                        "name": name,
                    })
                return json.dumps({
                    "query": query,
                    "retrieval_mode": "hybrid",
                    "count": len(chunks),
                    "chunks": chunks,
                }, ensure_ascii=False, indent=2)

            elif "未找到相关代码片段" in search_result_str or not search_result_str.strip():
                keyword_results = await indexer.search_signatures(query, top_k=top_k)
                if keyword_results and "未找到" not in keyword_results:
                    chunks = []
                    for line in keyword_results.split('\n'):
                        match = re.match(r'\d+\.\s*\[([^\]]+)\]\s+(\S+)\s*-?\s*(.*?)\s*\(([^)]+)\)', line)
                        if match:
                            chunk_type, name, signature, location = match.groups()
                            chunks.append({
                                "type": chunk_type,
                                "name": name,
                                "signature": signature.strip(),
                                "location": location,
                            })
                    if chunks:
                        return json.dumps({
                            "query": query,
                            "retrieval_mode": "keyword_fallback",
                            "count": len(chunks),
                            "chunks": chunks,
                        }, ensure_ascii=False, indent=2)

                return json.dumps({
                    "query": query,
                    "retrieval_mode": "none",
                    "count": 0,
                    "chunks": [],
                    "message": "未找到相关代码片段",
                }, ensure_ascii=False, indent=2)

            else:
                return json.dumps({
                    "query": query,
                    "retrieval_mode": "text",
                    "count": 0,
                    "chunks": [],
                    "raw_result": search_result_str[:500],
                }, ensure_ascii=False)

        except Exception as exc:
            logger.error(f"[semantic_search] 失败: {exc}")
            return json.dumps({"error": str(exc), "query": query, "chunks": []})
