"""
Agent 工具定义

为 CoderAgent 和 RepairerAgent 提供文件系统工具：
- glob: 查找文件
- grep: 搜索内容
- read_file: 读取文件（带 read_token）
- replace_lines: 替换代码行（需携带 read_token）

这些工具让 Agent 能够主动、按需获取文件内容，
并通过工具调用执行受控的写入操作。
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from app.service.code_executor import CodeExecutorService
from app.service.search_replace_engine import search_replace_engine
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class AgentTools:
    """
    Agent 工具集合

    提供文件系统操作工具，支持 Agent 按需获取上下文
    """

    def __init__(self, project_path: str):
        """
        初始化工具集合

        Args:
            project_path: 项目根目录路径
        """
        self.project_path = project_path
        self.code_executor = CodeExecutorService(project_path)
        # 缓存已读取的文件内容和 read_token
        self._file_cache: Dict[str, Dict[str, Any]] = {}

    # =========================================================================
    # Tool 1: glob - 查找文件
    # =========================================================================

    def glob(self, pattern: str, max_results: int = 20) -> str:
        """
        查找匹配模式的文件（支持递归通配符 **）

        Args:
            pattern: Glob 模式，如 "app/api/v1/*.py" 或 "**/health.py"
            max_results: 最大返回结果数

        Returns:
            str: 匹配的文件列表（JSON 格式）

        示例:
            >>> glob("app/api/v1/*.py")
            '["app/api/v1/health.py", "app/api/v1/users.py"]'
            >>> glob("**/health.py")
            '["app/api/v1/health.py", "app/core/health.py"]'
        """
        try:
            matches = []
            project_path = Path(self.project_path)

            # 【修复】自动剥离 backend/ 前缀，避免 LLM 传入错误路径
            clean_pattern = pattern
            if clean_pattern.startswith('backend/'):
                clean_pattern = clean_pattern[8:]  # 去掉 'backend/'
            elif clean_pattern.startswith('backend\\'):
                clean_pattern = clean_pattern[9:]  # 去掉 'backend\\'

            # 使用 pathlib 的 glob/rglob 支持递归通配符 **
            # 如果模式包含 **，使用 rglob；否则使用 glob
            if '**' in clean_pattern:
                # rglob 会自动递归所有子目录
                glob_iter = project_path.rglob(clean_pattern.replace('**/', '').replace('**', ''))
            else:
                glob_iter = project_path.glob(clean_pattern)

            for p in glob_iter:
                # 跳过目录和隐藏文件
                if not p.is_file():
                    continue
                if p.name.startswith('.') or '__pycache__' in str(p) or 'node_modules' in str(p):
                    continue

                rel_path = p.relative_to(project_path).as_posix()
                matches.append(rel_path)

                if len(matches) >= max_results:
                    break

            result = {
                "pattern": pattern,
                "matches": matches[:max_results],
                "count": len(matches[:max_results])
            }

            logger.info(f"[glob] Pattern '{pattern}' found {result['count']} matches")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[glob] Error: {e}")
            return json.dumps({"error": str(e), "pattern": pattern})

    # =========================================================================
    # Tool 2: grep - 搜索内容
    # =========================================================================

    def grep(self, pattern: str, path: str = "", max_results: int = 10) -> str:
        """
        在文件中搜索匹配的行

        Args:
            pattern: 搜索模式（正则表达式）
            path: 限制搜索的文件路径（可选）
            max_results: 最大返回结果数

        Returns:
            str: 匹配结果（JSON 格式）

        示例:
            >>> grep("def health", "app/api/v1")
            '[{"file": "app/api/v1/health.py", "line": 10, "content": "def health_check():"}]'
        """
        try:
            import re
            import os

            matches = []
            project_path = Path(self.project_path)

            # 编译正则表达式
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                return json.dumps({"error": f"Invalid regex: {e}"})

            # 确定搜索范围
            if path:
                search_path = project_path / path
                if not search_path.exists():
                    return json.dumps({"error": f"Path not found: {path}"})
            else:
                search_path = project_path

            # 遍历文件
            for root, dirs, files in os.walk(search_path):
                # 跳过 __pycache__ 等目录
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

                for filename in files:
                    if not filename.endswith('.py'):
                        continue

                    file_path = Path(root) / filename
                    rel_path = file_path.relative_to(project_path)

                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for line_num, line in enumerate(f, 1):
                                if regex.search(line):
                                    matches.append({
                                        "file": str(rel_path).replace('\\', '/'),
                                        "line": line_num,
                                        "content": line.strip()[:200]  # 限制长度
                                    })

                                    if len(matches) >= max_results:
                                        break

                        if len(matches) >= max_results:
                            break

                    except Exception as e:
                        logger.warning(f"[grep] Error reading {file_path}: {e}")
                        continue

                if len(matches) >= max_results:
                    break

            result = {
                "pattern": pattern,
                "path": path or "整个项目",
                "matches": matches[:max_results],
                "count": len(matches[:max_results])
            }

            logger.info(f"[grep] Pattern '{pattern}' found {result['count']} matches")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[grep] Error: {e}")
            return json.dumps({"error": str(e)})

    # =========================================================================
    # Tool 3: read_file - 读取文件（核心工具）
    # =========================================================================

    def read_file(self, file_path: str, start_line: int = 1, end_line: int = -1) -> str:
        """
        读取文件指定行范围，返回带行号的内容和 read_token

        【核心工具】Agent 必须通过此工具读取文件，
        获取的 read_token 用于后续的写入操作。

        【硬限制】每次最多读取 100 行，超出自动截断

        Args:
            file_path: 文件路径（相对项目根目录）
            start_line: 起始行号（从1开始，默认1）
            end_line: 结束行号（默认-1表示文件末尾，但会被限制为最多100行）

        Returns:
            str: 文件内容（带行号）和 read_token（JSON 格式）

        示例:
            >>> read_file("app/api/v1/health.py", 1, 50)
            '{"file": "app/api/v1/health.py", "lines": "0001 | from fastapi...", "read_token": "..."}'
        """
        try:
            # 【硬限制】每次最多读取 100 行
            MAX_LINES_PER_READ = 100
            auto_limited = False

            # 清理路径
            clean_path = file_path.replace('backend/', '').replace('backend\\', '').lstrip('/')

            # 使用 CodeExecutorService 读取文件（带 read_token）
            read_result = self.code_executor.read_file(clean_path)

            if not read_result.exists:
                error_msg = f"Error: {read_result.error or 'File not found'}"
                logger.error(f"[read_file] Failed to read {file_path}: {error_msg}")
                return json.dumps({
                    "file": file_path,
                    "error": error_msg,
                    "exists": False
                })

            content = read_result.content

            # 处理行号范围
            lines = content.splitlines()
            total_lines = len(lines)

            # 如果没指定 end_line，默认只读前 100 行
            if end_line == -1:
                end_line = start_line + MAX_LINES_PER_READ - 1
                auto_limited = True

            # 如果范围超过限制，截断并警告
            if end_line - start_line + 1 > MAX_LINES_PER_READ:
                end_line = start_line + MAX_LINES_PER_READ - 1
                auto_limited = True
                logger.warning(f"[read_file] 行数范围过大，自动截断为 {start_line}-{end_line}")

            # 确保行号有效
            start_line = max(1, start_line)
            end_line = max(start_line, min(end_line, total_lines))

            # 提取指定行
            selected_lines = lines[start_line - 1:end_line]

            # 格式化为带行号的文本
            formatted_lines = []
            for i, line in enumerate(selected_lines):
                line_num = start_line + i
                formatted_lines.append(f"{line_num:04d} | {line}")

            # 缓存 read_token
            import time
            self._file_cache[file_path] = {
                "read_token": read_result.read_token,
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
                "read_token": read_result.read_token,
                "hint": "使用此 read_token 进行后续的写入操作"
            }

            # 如果被截断，明确告知还有多少行没读，引导 LLM 继续读
            if auto_limited and end_line < total_lines:
                result["warning"] = (
                    f"文件共 {total_lines} 行，本次只显示 {start_line}-{end_line} 行。"
                    f"如需查看后续内容，请调用 read_file('{file_path}', {end_line+1}, {min(end_line+100, total_lines)})"
                )

            logger.info(f"[read_file] Read {file_path} lines {start_line}-{end_line}, "
                       f"read_token: {read_result.read_token[:20]}...")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[read_file] Error: {e}")
            return json.dumps({
                "file": file_path,
                "error": str(e),
                "exists": False
            })

    def get_read_token(self, file_path: str) -> Optional[str]:
        """
        获取已缓存的 read_token

        Args:
            file_path: 文件路径

        Returns:
            Optional[str]: read_token 或 None
        """
        cache = self._file_cache.get(file_path)
        if cache:
            return cache.get("read_token")
        return None

    # =========================================================================
    # Tool 4: replace_lines - 替换代码行（写入工具）
    # =========================================================================

    async def replace_lines(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        read_token: str,
        pipeline_id: Optional[int] = None
    ) -> str:
        """
        替换文件中的代码行（受控写入操作）

        【核心写入工具】Agent 必须通过此工具执行代码修改，
        而不是直接输出代码块。工具会验证 search_block 匹配、
        执行原子替换，并返回操作结果。

        Args:
            file_path: 文件路径（相对项目根目录）
            search_block: 要搜索的原始代码块（必须精确匹配）
            replace_block: 替换后的新代码块
            read_token: 通过 read_file 工具获取的读取凭证
            pipeline_id: Pipeline ID（用于日志推送）

        Returns:
            str: 操作结果（JSON 格式）

        示例:
            >>> replace_lines(
            ...     "app/api/v1/health.py",
            ...     "def health_check():\n    return {'status': 'ok'}",
            ...     "def health_check():\n    return {'status': 'ok', 'version': '1.0.0'}",
            ...     "token_abc123"
            ... )
        """
        try:
            # 清理路径
            clean_path = file_path.replace('backend/', '').replace('backend\\', '').lstrip('/')

            # 1. 验证 read_token 有效性
            cached = self._file_cache.get(file_path)
            if not cached or cached.get("read_token") != read_token:
                error_msg = "无效的 read_token：文件可能已被修改，请先重新读取文件"
                logger.error(f"[replace_lines] {error_msg}")
                return json.dumps({
                    "success": False,
                    "file": file_path,
                    "error": error_msg,
                    "error_type": "invalid_token"
                })

            # 2. 获取当前文件内容（通过 read_token 关联的缓存）
            current_content = cached.get("content", "")

            # 3. 验证 search_block 是否匹配当前文件内容
            if search_block not in current_content:
                # 尝试模糊匹配给出提示
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, search_block, current_content).ratio()

                error_msg = (
                    f"search_block 与文件内容不匹配。\n"
                    f"相似度: {similarity:.2%}\n"
                    f"请重新使用 read_file 工具读取文件，确保 search_block 精确匹配当前内容。"
                )
                logger.error(f"[replace_lines] {error_msg}")

                if pipeline_id:
                    await push_log(
                        pipeline_id,
                        "warning",
                        f"文件替换失败: {file_path} - search_block 不匹配",
                        stage="CODING"
                    )

                return json.dumps({
                    "success": False,
                    "file": file_path,
                    "error": error_msg,
                    "error_type": "search_mismatch",
                    "similarity": similarity
                })

            # 4. 执行替换
            new_content = current_content.replace(search_block, replace_block, 1)

            # 5. 验证替换后的内容（AST 语法检查等）
            if file_path.endswith('.py'):
                try:
                    import ast
                    ast.parse(new_content)
                except SyntaxError as e:
                    error_msg = f"替换后代码存在语法错误: {e}"
                    logger.error(f"[replace_lines] {error_msg}")
                    return json.dumps({
                        "success": False,
                        "file": file_path,
                        "error": error_msg,
                        "error_type": "syntax_error"
                    })

            # 6. 写入文件
            full_path = Path(self.project_path) / clean_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_content, encoding='utf-8')

            # 7. 更新缓存
            self._file_cache[file_path] = {
                "read_token": read_token,
                "content": new_content,
                "timestamp": cached.get("timestamp")
            }

            # 8. 推送前端日志
            if pipeline_id:
                await push_log(
                    pipeline_id,
                    "info",
                    f"✏️ 已修改文件: {file_path}",
                    stage="CODING"
                )

            # 计算变更统计
            old_lines = search_block.count('\n') + 1
            new_lines = replace_block.count('\n') + 1

            logger.info(f"[replace_lines] Successfully replaced {old_lines} lines with {new_lines} lines in {file_path}")

            return json.dumps({
                "success": True,
                "file": file_path,
                "lines_changed": {
                    "removed": old_lines,
                    "added": new_lines
                },
                "message": f"成功替换 {old_lines} 行为 {new_lines} 行"
            }, ensure_ascii=False)

        except Exception as e:
            error_msg = f"替换操作失败: {str(e)}"
            logger.error(f"[replace_lines] {error_msg}")

            if pipeline_id:
                await push_log(
                    pipeline_id,
                    "error",
                    f"文件修改失败: {file_path} - {str(e)}",
                    stage="CODING"
                )

            return json.dumps({
                "success": False,
                "file": file_path,
                "error": error_msg,
                "error_type": "execution_error"
            })

    # =========================================================================
    # 工具定义（用于 LLM 工具调用）
    # =========================================================================

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
        """
        获取工具定义列表（用于 OpenAI/其他 LLM 的工具调用）

        Returns:
            List[Dict]: 工具定义列表
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "glob",
                    "description": "查找匹配模式的文件。用于发现项目中的文件。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Glob 模式，如 'app/api/v1/*.py'"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "最大返回结果数（默认20）",
                                "default": 20
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep",
                    "description": "在文件中搜索匹配的行。用于查找代码片段。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "正则表达式模式，如 'def health'"
                            },
                            "path": {
                                "type": "string",
                                "description": "限制搜索的文件路径（可选）",
                                "default": ""
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "最大返回结果数（默认10）",
                                "default": 10
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "读取文件指定行范围，返回带行号的内容和 read_token。"
                        "【重要】每次最多读 80 行，禁止不指定行号读整个文件！"
                        "大文件请先用 grep 定位行号，再分段读取。"
                        "修改文件前必须先调用此工具获取 read_token！"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "文件路径（相对项目根目录），如 'app/api/v1/health.py'"
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "起始行号（从1开始，默认1）",
                                "default": 1
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "结束行号（必须指定！建议 start_line + 80 以内）"
                            }
                        },
                        "required": ["file_path", "end_line"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "replace_lines",
                    "description": "替换文件中的代码行。【核心写入工具】必须先调用 read_file 获取 read_token，"
                                    "然后使用此工具执行实际的代码替换。工具会验证 search_block 匹配并执行原子替换。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "文件路径（相对项目根目录），如 'app/api/v1/health.py'"
                            },
                            "search_block": {
                                "type": "string",
                                "description": "要搜索的原始代码块，必须精确匹配文件内容（包括空格和换行）"
                            },
                            "replace_block": {
                                "type": "string",
                                "description": "替换后的新代码块"
                            },
                            "read_token": {
                                "type": "string",
                                "description": "通过 read_file 工具获取的读取凭证，用于验证操作权限"
                            }
                        },
                        "required": ["file_path", "search_block", "replace_block", "read_token"]
                    }
                }
            }
        ]

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], pipeline_id: Optional[int] = None) -> str:
        """
        执行工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            str: 工具执行结果
        """
        # 同步工具映射
        sync_tool_map = {
            "glob": self.glob,
            "grep": self.grep,
            "read_file": self.read_file
        }

        # 异步工具映射
        async_tool_map = {
            "replace_lines": self.replace_lines
        }

        # 执行同步工具
        if tool_name in sync_tool_map:
            tool_func = sync_tool_map[tool_name]
            try:
                # 推送工具调用日志
                if pipeline_id:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"🔧 调用工具: {tool_name} - {arguments}",
                        stage="CODING"
                    )
                result = tool_func(**arguments)
                # 推送工具结果日志
                if pipeline_id:
                    result_data = json.loads(result)
                    if result_data.get("success", True):
                        await push_log(
                            pipeline_id,
                            "success",
                            f"✅ 工具 {tool_name} 执行成功",
                            stage="CODING"
                        )
                    else:
                        await push_log(
                            pipeline_id,
                            "warning",
                            f"⚠️ 工具 {tool_name} 执行失败: {result_data.get('error', '未知错误')}",
                            stage="CODING"
                        )
                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(
                        pipeline_id,
                        "error",
                        f"❌ 工具 {tool_name} 执行异常: {str(e)}",
                        stage="CODING"
                    )
                return json.dumps({"error": str(e)})

        # 执行异步工具
        if tool_name in async_tool_map:
            tool_func = async_tool_map[tool_name]
            try:
                # 推送工具调用日志
                if pipeline_id:
                    await push_log(
                        pipeline_id,
                        "info",
                        f"🔧 调用工具: {tool_name} - {arguments.get('file_path', '')}",
                        stage="CODING"
                    )
                # 为 replace_lines 添加 pipeline_id
                if tool_name == "replace_lines":
                    arguments["pipeline_id"] = pipeline_id
                result = await tool_func(**arguments)
                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(
                        pipeline_id,
                        "error",
                        f"❌ 工具 {tool_name} 执行异常: {str(e)}",
                        stage="CODING"
                    )
                return json.dumps({"error": str(e)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# 便捷函数
def get_agent_tools(project_path: str) -> AgentTools:
    """
    获取 AgentTools 实例

    Args:
        project_path: 项目路径

    Returns:
        AgentTools: 工具实例
    """
    return AgentTools(project_path)
