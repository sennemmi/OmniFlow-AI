"""
Agent 工具定义入口

为 CoderAgent 和 RepairerAgent 提供文件系统工具：
- glob: 查找文件
- grep: 搜索内容
- read_file: 读取文件（带 read_token）
- replace_lines: 替换代码行（需携带 read_token）
- read_chunk: 按 AST 边界读取代码块
- grep_ast: 结构化代码搜索
- semantic_search: 语义检索
- generate_project_card: 生成项目契约卡

这些工具让 Agent 能够主动、按需获取文件内容，
并通过工具调用执行受控的写入操作。
"""

import json
import logging
from typing import Dict, Any, List, Optional

from app.agents.agent_tools_core import AgentToolsCore
from app.agents.agent_tools_advanced import AgentToolsAdvanced
from app.agents.project_card_builder import ProjectCardBuilder
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class AgentTools:
    """
    Agent 工具集合（入口类）

    代理到底层核心工具与高级工具，保持向后兼容的 API。
    """

    def __init__(self, project_path: str, file_service=None):
        self._core = AgentToolsCore(project_path, file_service=file_service)
        self._advanced = AgentToolsAdvanced(project_path, file_service=file_service)
        self.project_path = project_path

    # =====================================================================
    # 内部状态代理（供外部如 ArchitectAgent 访问）
    # =====================================================================

    @property
    def _file_cache(self) -> Dict[str, Dict[str, Any]]:
        """代理到底层核心工具的 _file_cache，保持向后兼容"""
        return self._core._file_cache

    @property
    def _file_service(self):
        """代理到底层核心工具的 _file_service"""
        return self._core._file_service

    @property
    def _sandbox_mode(self) -> bool:
        """代理到底层核心工具的 _sandbox_mode"""
        return self._core._sandbox_mode

    # =====================================================================
    # 核心工具代理
    # =====================================================================

    def glob(self, pattern: str, max_results: int = 20) -> str:
        return self._core.glob(pattern, max_results)

    def grep(self, pattern: str, path: str = "", max_results: int = 10) -> str:
        return self._core.grep(pattern, path, max_results)

    def read_file(self, file_path: str, start_line: int = 1, end_line: int = -1) -> str:
        return self._core.read_file(file_path, start_line, end_line)

    def get_read_token(self, file_path: str) -> Optional[str]:
        return self._core.get_read_token(file_path)

    async def replace_lines(
        self,
        file_path: str,
        search_block: str,
        replace_block: str,
        read_token: str,
        pipeline_id: Optional[int] = None
    ) -> str:
        return await self._core.replace_lines(
            file_path, search_block, replace_block, read_token, pipeline_id
        )

    # =====================================================================
    # 高级工具代理
    # =====================================================================

    def read_chunk(
        self,
        file_path: str,
        symbol_name: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        return self._advanced.read_chunk(file_path, symbol_name, start_line, end_line)

    def grep_ast(
        self,
        pattern: str,
        search_path: str = ".",
        search_type: str = "text",
        max_results: int = 15,
    ) -> str:
        return self._advanced.grep_ast(pattern, search_path, search_type, max_results)

    async def semantic_search(self, query: str, top_k: int = 5) -> str:
        return await self._advanced.semantic_search(query, top_k)

    # =====================================================================
    # 项目结构摘要
    # =====================================================================

    def generate_project_summary(self, relative_root: str = ".", max_files: int = 30) -> str:
        return self.generate_project_card(max_files=max_files)

    def generate_project_card(self, max_depth: int = 3, max_files: int = 60) -> str:
        try:
            from pathlib import Path
            builder = ProjectCardBuilder(Path(self.project_path))
            return builder.build(max_depth=max_depth, max_files=max_files)
        except Exception as e:
            logger.error(f"[generate_project_card] Error: {e}")
            return json.dumps({"error": str(e)})

    # =====================================================================
    # 工具定义与执行
    # =====================================================================

    @property
    def tool_definitions(self) -> List[Dict[str, Any]]:
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
        sync_tool_map = {
            "glob": self.glob,
            "grep": self.grep,
            "read_file": self.read_file
        }
        async_tool_map = {
            "replace_lines": self.replace_lines
        }

        if tool_name in sync_tool_map:
            tool_func = sync_tool_map[tool_name]
            try:
                if pipeline_id:
                    await push_log(pipeline_id, "info", f"🔧 调用工具: {tool_name} - {arguments}", stage="CODING")
                result = tool_func(**arguments)
                if pipeline_id:
                    result_data = json.loads(result)
                    if result_data.get("success", True):
                        await push_log(pipeline_id, "success", f"✅ 工具 {tool_name} 执行成功", stage="CODING")
                    else:
                        await push_log(pipeline_id, "warning", f"⚠️ 工具 {tool_name} 执行失败: {result_data.get('error', '未知错误')}", stage="CODING")
                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(pipeline_id, "error", f"❌ 工具 {tool_name} 执行异常: {str(e)}", stage="CODING")
                return json.dumps({"error": str(e)})

        if tool_name in async_tool_map:
            tool_func = async_tool_map[tool_name]
            try:
                if pipeline_id:
                    await push_log(pipeline_id, "info", f"🔧 调用工具: {tool_name} - {arguments.get('file_path', '')}", stage="CODING")
                if tool_name == "replace_lines":
                    arguments["pipeline_id"] = pipeline_id
                result = await tool_func(**arguments)
                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(pipeline_id, "error", f"❌ 工具 {tool_name} 执行异常: {str(e)}", stage="CODING")
                return json.dumps({"error": str(e)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# 便捷函数
def get_agent_tools(project_path: str, file_service=None) -> AgentTools:
    return AgentTools(project_path, file_service=file_service)
