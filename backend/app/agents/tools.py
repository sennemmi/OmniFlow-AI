"""
Agent 工具定义

为 CoderAgent 和 RepairerAgent 提供文件系统工具：
- glob: 查找文件
- grep: 搜索内容
- read_file: 读取文件（带 read_token）

这些工具让 Agent 能够主动、按需获取文件内容，
而不是被动接受预注入的上下文。
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from app.service.code_executor import CodeExecutorService

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
        查找匹配模式的文件

        Args:
            pattern: Glob 模式，如 "app/api/v1/*.py"
            max_results: 最大返回结果数

        Returns:
            str: 匹配的文件列表（JSON 格式）

        示例:
            >>> glob("app/api/v1/*.py")
            '["app/api/v1/health.py", "app/api/v1/users.py"]'
        """
        try:
            import fnmatch
            import os

            matches = []
            project_path = Path(self.project_path)

            # 遍历项目目录
            for root, dirs, files in os.walk(project_path):
                # 跳过 __pycache__ 等目录
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

                for filename in files:
                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(project_path)

                    # 检查是否匹配模式
                    if fnmatch.fnmatch(str(rel_path), pattern) or fnmatch.fnmatch(filename, pattern):
                        matches.append(str(rel_path).replace('\\', '/'))

                    if len(matches) >= max_results:
                        break

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

        Args:
            file_path: 文件路径（相对项目根目录）
            start_line: 起始行号（从1开始，默认1）
            end_line: 结束行号（默认-1表示文件末尾）

        Returns:
            str: 文件内容（带行号）和 read_token（JSON 格式）

        示例:
            >>> read_file("app/api/v1/health.py", 1, 50)
            '{"file": "app/api/v1/health.py", "lines": "0001 | from fastapi...", "read_token": "..."}'
        """
        try:
            # 清理路径
            clean_path = file_path.replace('backend/', '').replace('backend\\', '').lstrip('/')

            # 使用 CodeExecutorService 读取文件（带 read_token）
            read_result = self.code_executor.read_file(clean_path)

            if not read_result.success:
                error_msg = f"Error: {read_result.error}"
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

            if end_line == -1 or end_line > total_lines:
                end_line = total_lines

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
            self._file_cache[file_path] = {
                "read_token": read_result.read_token,
                "content": content,
                "timestamp": read_result.timestamp
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
                    "description": "读取文件指定行范围，返回带行号的内容和 read_token。"
                                    "【重要】修改文件前必须先调用此工具获取 read_token！",
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
                                "description": "结束行号（默认-1表示文件末尾）",
                                "default": -1
                            }
                        },
                        "required": ["file_path"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            str: 工具执行结果
        """
        tool_map = {
            "glob": self.glob,
            "grep": self.grep,
            "read_file": self.read_file
        }

        tool_func = tool_map.get(tool_name)
        if not tool_func:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            return tool_func(**arguments)
        except Exception as e:
            logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
            return json.dumps({"error": str(e)})


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
