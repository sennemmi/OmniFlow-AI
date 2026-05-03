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
from app.agents.tools_code_apply import CodeApplyTool
from app.agents.tools_edit import EditToolsExecutor
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class AgentTools:
    """
    Agent 工具集合（入口类）

    代理到底层核心工具与高级工具，保持向后兼容的 API。
    """

    def __init__(self, project_path: str, file_service=None, pipeline_id: Optional[int] = None, agent_role: Optional[str] = None):
        self._core = AgentToolsCore(project_path, file_service=file_service)
        self._advanced = AgentToolsAdvanced(project_path, file_service=file_service)
        self.project_path = project_path
        self.__file_service = file_service  # 使用双下划线避免与 property 冲突
        self._pipeline_id = pipeline_id
        self._agent_role = agent_role  # Agent 角色，用于权限控制

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
        # 优先返回实例变量，如果没有则返回核心工具的
        return self.__file_service if self.__file_service is not None else self._core._file_service

    @_file_service.setter
    def _file_service(self, value):
        """设置 file_service"""
        self.__file_service = value

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
        """
        获取工具定义列表

        【权限控制】
        - 所有 Agent 都可以使用代码操作工具
        - RepairerAgent 额外拥有 install_dependency 工具
        """
        # 基础工具（所有 Agent 可用）
        tools = [
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
            },
            {
                "type": "function",
                "function": {
                    "name": "code_apply",
                    "description": (
                        "执行精确的代码搜索替换。【极其重要】此工具只做精确匹配,不做模糊匹配。"
                        "如果 search_block 与文件内容不完全一致,工具会返回结构化的错误信息,"
                        "告诉你为什么失败以及如何修正。请先使用 read_file 读取文件,确保 search_block 精确复制。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "文件路径"},
                            "search_block": {"type": "string", "description": "要替换的代码块(必须精确匹配原文件)"},
                            "replace_block": {"type": "string", "description": "新代码块"}
                        },
                        "required": ["file_path", "search_block", "replace_block"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "func_replace",
                    "description": (
                        "替换指定函数/方法的完整实现。"
                        "比 code_apply 更适合修改整个函数的场景。"
                        "系统会自动定位函数边界,你只需要提供新的函数实现。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "func_name": {"type": "string", "description": "函数名或方法名"},
                            "new_func_body": {"type": "string", "description": "新的完整函数实现(包括 def 行)"},
                        },
                        "required": ["file_path", "func_name", "new_func_body"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "insert_after",
                    "description": "在指定行之后插入新代码",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "after_line": {"type": "integer", "description": "在此行之后插入"},
                            "code_block": {"type": "string", "description": "要插入的代码块"},
                        },
                        "required": ["file_path", "after_line", "code_block"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_lines",
                    "description": "删除指定行范围的代码",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                        },
                        "required": ["file_path", "start_line", "end_line"]
                    }
                }
            }
        ]

        # 【权限控制】RepairerAgent 额外拥有 install_dependency 工具
        if self._agent_role == "repairer":
            tools.append({
                "type": "function",
                "function": {
                    "name": "install_dependency",
                    "description": "【RepairerAgent 专用】在沙箱中安装 Python 依赖包。当测试报错 'ModuleNotFoundError: No module named xxx' 时使用此工具安装缺失的依赖。安装完成后应该立即重新运行测试。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "package_name": {
                                "type": "string",
                                "description": "依赖包名称，如 'bcrypt', 'python-jose', 'passlib', 'jwt'"
                            }
                        },
                        "required": ["package_name"]
                    }
                }
            })

        return tools

    async def install_dependency(self, package_name: str) -> str:
        """
        在沙箱中安装 Python 依赖包

        Args:
            package_name: 依赖包名称，如 'bcrypt', 'python-jose'

        Returns:
            str: JSON 格式的安装结果
        """
        from app.service.sandbox_manager import sandbox_manager

        try:
            # 获取 pipeline_id
            pipeline_id = self._pipeline_id
            if not pipeline_id:
                return json.dumps({
                    "success": False,
                    "error": "Pipeline ID 未设置，无法执行沙箱命令"
                })

            logger.info(f"[AgentTools] 安装依赖: {package_name}")

            # 在沙箱中执行 pip install
            exec_result = await sandbox_manager.exec(
                pipeline_id,
                f"pip install {package_name} --quiet 2>&1",
                timeout=120
            )

            logs = exec_result.stdout + "\n" + exec_result.stderr
            success = exec_result.exit_code == 0

            if success:
                logger.info(f"[AgentTools] 依赖 {package_name} 安装成功")
                return json.dumps({
                    "success": True,
                    "message": f"依赖 {package_name} 安装成功",
                    "package": package_name
                })
            else:
                logger.error(f"[AgentTools] 依赖 {package_name} 安装失败: {logs[:500]}")
                return json.dumps({
                    "success": False,
                    "error": f"安装失败: {logs[:500]}",
                    "package": package_name
                })

        except Exception as e:
            logger.error(f"[AgentTools] 安装依赖时出错: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "package": package_name
            })

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], pipeline_id: Optional[int] = None) -> str:
        sync_tool_map = {
            "glob": self.glob,
            "grep": self.grep,
            "read_file": self.read_file
        }
        async_tool_map = {
            "replace_lines": self.replace_lines,
            "install_dependency": self.install_dependency
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

        if tool_name == "code_apply":
            try:
                file_path = arguments.get("file_path")
                search_block = arguments.get("search_block")
                replace_block = arguments.get("replace_block")

                if pipeline_id:
                    await push_log(pipeline_id, "info", f"🔧 调用工具: {tool_name} - {file_path}", stage="CODING")

                # 读取文件内容 - 使用 _advanced._read_content 处理路径前缀
                read_result = self._advanced._read_content(file_path)
                if read_result[0] is None:
                    error_msg = read_result[1] or f"无法读取文件: {file_path}"
                    if pipeline_id:
                        await push_log(pipeline_id, "warning", f"⚠️ 工具 {tool_name} 执行失败: {error_msg}", stage="CODING")
                    return json.dumps({
                        "success": False,
                        "error": error_msg
                    })

                file_content = read_result[0]
                result = CodeApplyTool.execute(file_path, search_block, replace_block, file_content)

                if pipeline_id:
                    result_data = json.loads(result)
                    if result_data.get("success", False):
                        await push_log(pipeline_id, "success", f"✅ 工具 {tool_name} 执行成功", stage="CODING")
                    else:
                        await push_log(pipeline_id, "warning", f"⚠️ 工具 {tool_name} 执行失败: {result_data.get('error_detail', '未知错误')}", stage="CODING")

                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(pipeline_id, "error", f"❌ 工具 {tool_name} 执行异常: {str(e)}", stage="CODING")
                return json.dumps({"error": str(e)})

        # 处理新的编辑工具
        edit_tools = ["func_replace", "insert_after", "delete_lines"]
        if tool_name in edit_tools:
            try:
                file_path = arguments.get("file_path")

                if pipeline_id:
                    await push_log(pipeline_id, "info", f"🔧 调用工具: {tool_name} - {file_path}", stage="CODING")

                # 读取文件内容
                read_result = self._advanced._read_content(file_path)
                if read_result[0] is None:
                    error_msg = read_result[1] or f"无法读取文件: {file_path}"
                    if pipeline_id:
                        await push_log(pipeline_id, "warning", f"⚠️ 工具 {tool_name} 执行失败: {error_msg}", stage="CODING")
                    return json.dumps({
                        "success": False,
                        "error": error_msg
                    })

                file_content = read_result[0]

                # 执行编辑工具
                executor = EditToolsExecutor(file_service=self._file_service)
                result = await executor.execute(tool_name, arguments, file_content, file_path)

                # 解析结果
                result_data = json.loads(result)

                if pipeline_id:
                    if result_data.get("success", False):
                        await push_log(pipeline_id, "success", f"✅ 工具 {tool_name} 执行成功", stage="CODING")
                    else:
                        await push_log(pipeline_id, "warning", f"⚠️ 工具 {tool_name} 执行失败: {result_data.get('error', '未知错误')}", stage="CODING")

                # 【微提交】执行成功后自动 commit
                if result_data.get("success") and pipeline_id:
                    await self._micro_commit(pipeline_id, tool_name, arguments)

                return result
            except Exception as e:
                logger.error(f"[execute_tool] Error executing {tool_name}: {e}")
                if pipeline_id:
                    await push_log(pipeline_id, "error", f"❌ 工具 {tool_name} 执行异常: {str(e)}", stage="CODING")
                return json.dumps({"error": str(e)})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    async def _micro_commit(self, pipeline_id: int, tool_name: str, arguments: Dict[str, Any]):
        """每次成功的工具调用后自动微提交"""
        try:
            file_path = arguments.get("file_path", "unknown")

            # 构建提交信息
            if tool_name == "func_replace":
                func_name = arguments.get("func_name", "")
                commit_msg = f"micro: {tool_name} on {file_path} - func: {func_name}"
            elif tool_name == "insert_after":
                after_line = arguments.get("after_line", "")
                commit_msg = f"micro: {tool_name} on {file_path} - after line: {after_line}"
            elif tool_name == "delete_lines":
                start_line = arguments.get("start_line", "")
                end_line = arguments.get("end_line", "")
                commit_msg = f"micro: {tool_name} on {file_path} - lines: {start_line}-{end_line}"
            elif tool_name == "code_apply":
                commit_msg = f"micro: {tool_name} on {file_path}"
            else:
                commit_msg = f"micro: {tool_name} on {file_path}"

            # 在 Sandbox 中执行 git commit
            result = await sandbox_manager.exec(
                pipeline_id,
                f'cd /workspace && git add -A && git commit -m "{commit_msg}" --allow-empty',
                timeout=5
            )

            if result.exit_code == 0:
                logger.info(f"[MicroCommit] {commit_msg}")
            else:
                logger.warning(f"[MicroCommit] 提交失败: {result.stderr}")

        except Exception as e:
            logger.warning(f"[MicroCommit] 微提交异常: {e}")


# 便捷函数
def get_agent_tools(project_path: str, file_service=None, pipeline_id: int = 0, agent_role: Optional[str] = None) -> AgentTools:
    return AgentTools(project_path, file_service=file_service, pipeline_id=pipeline_id, agent_role=agent_role)
