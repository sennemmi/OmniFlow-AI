"""
AgentTools 核心实现

提供文件系统操作工具，支持 Agent 按需获取上下文
支持两种模式：
1. 本地模式：直接操作宿主机文件系统
2. Sandbox 模式：通过 SandboxFileService 操作容器内文件
"""

import ast
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.service.code_executor import CodeExecutorService
from app.core.sse_log_buffer import push_log
from app.utils.file_operation_utils import clean_backend_prefix

logger = logging.getLogger(__name__)


class AgentToolsCore:
    """Agent 工具集合核心实现"""

    def __init__(self, project_path: str, file_service=None):
        self.project_path = project_path
        self.code_executor = CodeExecutorService(project_path)
        self._file_cache: Dict[str, Dict[str, Any]] = {}
        self._file_service = file_service
        self._sandbox_mode = file_service is not None

    # =====================================================================
    # Tool 1: glob
    # =====================================================================

    def glob(self, pattern: str, max_results: int = 20) -> str:
        try:
            if self._sandbox_mode:
                return self._glob_sandbox(pattern, max_results)
            return self._glob_local(pattern, max_results)
        except Exception as e:
            logger.error(f"[glob] Error: {e}")
            return json.dumps({"error": str(e), "pattern": pattern})

    def _glob_sandbox(self, pattern: str, max_results: int) -> str:
        import asyncio
        import concurrent.futures
        from app.service.sandbox_manager import sandbox_manager

        try:
            # project_path (backend) 挂载到 /workspace，所以直接使用 /workspace
            # 【修复】循环替换所有 backend/ 前缀，避免路径重复
            clean_pattern = clean_backend_prefix(pattern)
            WORKSPACE_ROOT = '/workspace'

            # 【修复】使用更可靠的查找策略
            if '**' in clean_pattern:
                # 对于递归模式，提取目录前缀和文件模式
                parts = clean_pattern.split('**', 1)
                if parts[0] and parts[0].strip('/'):
                    # 有特定目录前缀，如 app/**/*.py -> app
                    base_dir = f"{WORKSPACE_ROOT}/{parts[0].strip('/')}"
                else:
                    # 无特定目录前缀，如 **/*.py，限制在 backend 目录下查找
                    base_dir = f"{WORKSPACE_ROOT}/backend"
                
                # 提取文件模式（如 *.py）
                file_pattern = parts[1].lstrip('/').replace('**/', '').replace('**', '') if len(parts) > 1 else '*'
                
                # 【关键修复】使用 -name 支持递归匹配
                # find 的 -name 在递归模式下会匹配所有子目录中的文件
                if ',' in file_pattern:
                    # 处理多扩展名，如 *.py,*.txt
                    exts = file_pattern.split(',')
                    name_conditions = ' -o '.join([f"-name '{ext.strip()}'" for ext in exts])
                    cmd = f"find {base_dir} -maxdepth 5 -type f ( {name_conditions} ) 2>/dev/null | head -{max_results}"
                else:
                    # 单扩展名
                    cmd = f"find {base_dir} -maxdepth 5 -name '{file_pattern}' -type f 2>/dev/null | head -{max_results}"
            else:
                dir_path = WORKSPACE_ROOT
                file_pattern = clean_pattern
                if '/' in clean_pattern:
                    parts = clean_pattern.rsplit('/', 1)
                    dir_path = f"{WORKSPACE_ROOT}/{parts[0]}"
                    file_pattern = parts[1]
                # 非递归模式，只搜索指定目录
                cmd = f"find {dir_path} -maxdepth 1 -name '{file_pattern}' -type f 2>/dev/null | head -{max_results}"

            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # 【优化】增加超时时间到 30 秒，给 find 更多时间
                    future = executor.submit(
                        lambda: asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=30))
                    )
                    exec_result = future.result(timeout=60)
            except RuntimeError:
                exec_result = asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=30))

            matches = []
            if exec_result.exit_code == 0:
                for line in exec_result.stdout.strip().split('\n'):
                    if line:
                        rel_path = line.replace(f'{WORKSPACE_ROOT}/', '')
                        matches.append(rel_path)

            result = {"pattern": pattern, "matches": matches[:max_results], "count": len(matches[:max_results])}
            logger.info(f"[glob] Sandbox 模式: Pattern '{pattern}' found {result['count']} matches")
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[glob] Sandbox 模式执行失败: {e}")
            return json.dumps({"error": f"Sandbox glob failed: {e}", "pattern": pattern})

    def _glob_local(self, pattern: str, max_results: int) -> str:
        matches = []
        project_path = Path(self.project_path)
        clean_pattern = pattern
        if clean_pattern.startswith('backend/'):
            clean_pattern = clean_pattern[8:]
        elif clean_pattern.startswith('backend\\'):
            clean_pattern = clean_pattern[9:]

        if '**' in clean_pattern:
            glob_iter = project_path.rglob(clean_pattern.replace('**/', '').replace('**', ''))
        else:
            glob_iter = project_path.glob(clean_pattern)

        for p in glob_iter:
            if not p.is_file():
                continue
            if p.name.startswith('.') or '__pycache__' in str(p) or 'node_modules' in str(p):
                continue
            rel_path = p.relative_to(project_path).as_posix()
            matches.append(rel_path)
            if len(matches) >= max_results:
                break

        result = {"pattern": pattern, "matches": matches[:max_results], "count": len(matches[:max_results])}
        logger.info(f"[glob] Pattern '{pattern}' found {result['count']} matches")
        return json.dumps(result, ensure_ascii=False, indent=2)

    # =====================================================================
    # Tool 2: grep
    # =====================================================================

    def grep(self, pattern: str, path: str = "", max_results: int = 10) -> str:
        try:
            if self._sandbox_mode:
                return self._grep_sandbox(pattern, path, max_results)
            return self._grep_local(pattern, path, max_results)
        except Exception as e:
            logger.error(f"[grep] Error: {e}")
            return json.dumps({"error": str(e)})

    def _grep_sandbox(self, pattern: str, path: str, max_results: int) -> str:
        import asyncio
        import concurrent.futures
        from app.service.sandbox_manager import sandbox_manager

        try:
            # 【修复】循环替换所有 backend/ 前缀，避免路径重复
            clean_path = clean_backend_prefix(path)

            # 【优化】限制搜索范围，避免全盘扫描
            if clean_path:
                # 有特定路径，使用该路径
                search_dir = f"/workspace/{clean_path}"
            else:
                # 无特定路径，限制在 backend 目录下搜索
                search_dir = "/workspace/backend"
            
            escaped_pattern = pattern.replace("'", '\'"\'"\'')
            # 【优化】添加 --max-count 限制每个文件的匹配数，提高性能
            cmd = f"grep -rn --include='*.py' --max-count=5 -E '{escaped_pattern}' {search_dir} 2>/dev/null | head -{max_results}"

            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # 【优化】增加超时时间到 30 秒
                    future = executor.submit(
                        lambda: asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=30))
                    )
                    exec_result = future.result(timeout=60)
            except RuntimeError:
                exec_result = asyncio.run(sandbox_manager.exec(self._file_service.pipeline_id, cmd, timeout=30))

            matches = []
            if exec_result.exit_code == 0:
                for line in exec_result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            matches.append({
                                "file": parts[0].replace('/workspace/', ''),
                                "line": int(parts[1]),
                                "content": parts[2].strip()[:200]
                            })

            result = {"pattern": pattern, "path": path or "backend目录", "matches": matches[:max_results], "count": len(matches[:max_results])}
            logger.info(f"[grep] Sandbox 模式: Pattern '{pattern}' found {result['count']} matches")
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[grep] Sandbox 模式执行失败: {e}")
            return json.dumps({"error": f"Sandbox grep failed: {e}", "pattern": pattern})

    def _grep_local(self, pattern: str, path: str, max_results: int) -> str:
        import os
        matches = []
        project_path = Path(self.project_path)

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            logger.warning(f"[grep] Regex compile failed for pattern '{pattern}', falling back to literal search")
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        if path:
            search_path = project_path / path
            if not search_path.exists():
                return json.dumps({"error": f"Path not found: {path}"})
        else:
            search_path = project_path

        files_to_search = []
        if search_path.is_file():
            if search_path.suffix == '.py':
                files_to_search.append(search_path)
        elif search_path.is_dir():
            for root, dirs, files in os.walk(search_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]
                for filename in files:
                    if filename.endswith('.py'):
                        files_to_search.append(Path(root) / filename)
        else:
            return json.dumps({"error": f"Path is neither a file nor a directory: {path}"})

        for file_path in files_to_search:
            rel_path = file_path.relative_to(project_path)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "file": str(rel_path).replace('\\', '/'),
                                "line": line_num,
                                "content": line.strip()[:200]
                            })
                            if len(matches) >= max_results:
                                break
                if len(matches) >= max_results:
                    break
            except Exception as e:
                logger.warning(f"[grep] Error reading {file_path}: {e}")
                continue

        result = {"pattern": pattern, "path": path or "整个项目", "matches": matches[:max_results], "count": len(matches[:max_results])}
        logger.info(f"[grep] Pattern '{pattern}' found {result['count']} matches")
        return json.dumps(result, ensure_ascii=False, indent=2)

    # =====================================================================
    # Tool 3: read_file
    # =====================================================================

    def read_file(self, file_path: str, start_line: int = 1, end_line: int = -1) -> str:
        try:
            MAX_LINES_PER_READ = 100
            auto_limited = False
            clean_path = clean_backend_prefix(file_path)

            if self._sandbox_mode and self._file_service:
                content, read_token = self._read_file_sandbox(clean_path, file_path)
            else:
                content, read_token = self._read_file_local(clean_path, file_path)

            if content is None:
                return read_token  # 错误信息已 JSON 化

            lines = content.splitlines()
            total_lines = len(lines)

            if end_line == -1:
                end_line = start_line + MAX_LINES_PER_READ - 1
                auto_limited = True

            if end_line - start_line + 1 > MAX_LINES_PER_READ:
                end_line = start_line + MAX_LINES_PER_READ - 1
                auto_limited = True
                logger.warning(f"[read_file] 行数范围过大，自动截断为 {start_line}-{end_line}")

            start_line = max(1, start_line)
            end_line = max(start_line, min(end_line, total_lines))
            selected_lines = lines[start_line - 1:end_line]
            formatted_lines = [f"{start_line + i:04d} | {line}" for i, line in enumerate(selected_lines)]

            self._file_cache[file_path] = {
                "read_token": read_token,
                "content": content,
                "timestamp": time.time()
            }

            result = {
                "file": file_path,
                "exists": True,
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "lines": "\n".join(formatted_lines),
                "read_token": read_token,
                "hint": "使用此 read_token 进行后续的写入操作"
            }
            if auto_limited and end_line < total_lines:
                result["warning"] = (
                    f"文件共 {total_lines} 行，本次只显示 {start_line}-{end_line} 行。"
                    f"如需查看后续内容，请调用 read_file('{file_path}', {end_line+1}, {min(end_line+100, total_lines)})"
                )
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[read_file] Error: {e}")
            return json.dumps({"file": file_path, "error": str(e), "exists": False})

    def _read_file_sandbox(self, clean_path: str, file_path: str):
        import asyncio
        import concurrent.futures

        try:
            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(self._file_service.read_file(clean_path))
                    )
                    read_result = future.result(timeout=30)
            except RuntimeError:
                read_result = asyncio.run(self._file_service.read_file(clean_path))

            if not read_result.exists:
                return None, json.dumps({"file": file_path, "error": read_result.error or 'File not found', "exists": False})
            content = read_result.content
            read_token = f"sandbox_token_{hash(clean_path) % 1000000:06d}"
            return content, read_token
        except Exception as e:
            logger.error(f"[read_file] Sandbox 模式读取失败: {e}")
            return None, json.dumps({"file": file_path, "error": f"Sandbox read failed: {e}", "exists": False})

    def _read_file_local(self, clean_path: str, file_path: str):
        read_result = self.code_executor.read_file(clean_path)
        if not read_result.exists:
            error_msg = f"Error: {read_result.error or 'File not found'}"
            logger.error(f"[read_file] Failed to read {file_path}: {error_msg}")
            return None, json.dumps({"file": file_path, "error": error_msg, "exists": False})
        return read_result.content, read_result.read_token

    def get_read_token(self, file_path: str) -> Optional[str]:
        cache = self._file_cache.get(file_path)
        if cache:
            return cache.get("read_token")
        return None

    # =====================================================================
    # Tool 4: replace_lines
    # =====================================================================

    async def replace_lines(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        read_token: str,
        pipeline_id: Optional[int] = None
    ) -> str:
        try:
            clean_path = clean_backend_prefix(file_path)
            cached = self._file_cache.get(file_path)
            if not cached or cached.get("read_token") != read_token:
                error_msg = "无效的 read_token：文件可能已被修改，请先重新读取文件"
                logger.error(f"[replace_lines] {error_msg}")
                return json.dumps({"success": False, "file": file_path, "error": error_msg, "error_type": "invalid_token"})

            current_content = cached.get("content", "")
            if search_block not in current_content:
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, search_block, current_content).ratio()
                error_msg = (
                    f"search_block 与文件内容不匹配。\n"
                    f"相似度: {similarity:.2%}\n"
                    f"请重新使用 read_file 工具读取文件，确保 search_block 精确匹配当前内容。"
                )
                logger.error(f"[replace_lines] {error_msg}")
                if pipeline_id:
                    await push_log(pipeline_id, "warning", f"文件替换失败: {file_path} - search_block 不匹配", stage="CODING")
                return json.dumps({"success": False, "file": file_path, "error": error_msg, "error_type": "search_mismatch", "similarity": similarity})

            new_content = current_content.replace(search_block, replace_block, 1)

            if file_path.endswith('.py'):
                try:
                    ast.parse(new_content)
                except SyntaxError as e:
                    error_msg = f"替换后代码存在语法错误: {e}"
                    logger.error(f"[replace_lines] {error_msg}")
                    return json.dumps({"success": False, "file": file_path, "error": error_msg, "error_type": "syntax_error"})

            full_path = Path(self.project_path) / clean_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_content, encoding='utf-8')

            self._file_cache[file_path] = {
                "read_token": read_token,
                "content": new_content,
                "timestamp": cached.get("timestamp")
            }

            if pipeline_id:
                await push_log(pipeline_id, "info", f"✏️ 已修改文件: {file_path}", stage="CODING")

            old_lines = search_block.count('\n') + 1
            new_lines = replace_block.count('\n') + 1
            logger.info(f"[replace_lines] Successfully replaced {old_lines} lines with {new_lines} lines in {file_path}")
            return json.dumps({
                "success": True,
                "file": file_path,
                "lines_changed": {"removed": old_lines, "added": new_lines},
                "message": f"成功替换 {old_lines} 行为 {new_lines} 行"
            }, ensure_ascii=False)
        except Exception as e:
            error_msg = f"替换操作失败: {str(e)}"
            logger.error(f"[replace_lines] {error_msg}")
            if pipeline_id:
                await push_log(pipeline_id, "error", f"文件修改失败: {file_path} - {str(e)}", stage="CODING")
            return json.dumps({"success": False, "file": file_path, "error": error_msg, "error_type": "execution_error"})
