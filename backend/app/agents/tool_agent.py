"""
支持工具调用的 Agent 基类

实现 ReAct 模式：
1. Agent 调用 LLM，可以请求使用工具
2. 系统执行工具，返回结果
3. Agent 基于工具结果继续思考或输出最终答案

支持的工具：
- glob: 查找文件
- grep: 搜索内容
- read_file: 读取文件（带 read_token）
"""

import json
import logging
from typing import Dict, Any, List, Optional, TypeVar, Generic
from abc import abstractmethod

from app.agents.base import LangGraphAgent, BaseAgentState
from app.agents.tools import AgentTools, get_agent_tools
from app.core.config import settings
from app.agents.llm_providers import MiMoProvider

def _get_thinking_param() -> Dict[str, Any]:
    """获取思考模式参数，如果是 MiMo 则关闭思考模式"""
    provider = settings.LLM_PROVIDER.lower()
    if provider == "mimo":
        return {"thinking": {"type": "disabled"}}
    return {}

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ToolUsingAgent(LangGraphAgent[T]):
    """
    支持工具调用的 Agent 基类

    特性：
    - 支持工具调用循环（ReAct 模式）
    - 自动处理 tool_calls 响应
    - 集成 Read Token 机制
    - 支持 Sandbox 模式（通过 file_service 操作容器内文件）
    """

    # 最大工具调用次数，防止无限循环
    MAX_TOOL_CALLS = 10

    def __init__(self, agent_name: str = "ToolUsingAgent"):
        super().__init__(agent_name=agent_name)
        self._agent_tools: Optional[AgentTools] = None
        self._file_service = None  # SandboxFileService 实例

    def set_file_service(self, file_service):
        """设置 SandboxFileService 实例（用于 Sandbox 模式）"""
        self._file_service = file_service
        # 如果已有 AgentTools 实例，需要重新创建
        if self._agent_tools is not None:
            self._agent_tools = None

    def _get_agent_tools(self, project_path: str, pipeline_id: int = 0) -> AgentTools:
        """获取或创建 AgentTools 实例"""
        # 【权限控制】根据 Agent 名称确定角色
        agent_role = None
        if "repair" in self.agent_name.lower():
            agent_role = "repairer"

        logger.info(
            f"[{self.agent_name}] _get_agent_tools: agent_name={self.agent_name!r}, "
            f"agent_role={agent_role!r}, "
            f"cached_role={self._agent_tools._agent_role if self._agent_tools else None!r}, "
            f"will_recreate={self._agent_tools is None or self._agent_tools.project_path != project_path or self._agent_tools._pipeline_id != pipeline_id or (self._agent_tools._agent_role != agent_role)}"
        )

        if (self._agent_tools is None or
            self._agent_tools.project_path != project_path or
            self._agent_tools._pipeline_id != pipeline_id or
            self._agent_tools._agent_role != agent_role):
            self._agent_tools = get_agent_tools(
                project_path,
                file_service=self._file_service,
                pipeline_id=pipeline_id,
                agent_role=agent_role
            )
            logger.info(f"[{self.agent_name}] AgentTools 已重新创建, agent_role={agent_role!r}")
        return self._agent_tools

    def _build_llm_call_params(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float,
        current_max_tokens: int,
        response_format: Optional[Dict[str, Any]],
        is_final_output: bool,
    ) -> Dict[str, Any]:
        """构建 litellm 调用参数"""
        params = {
            "model": settings.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": current_max_tokens,
            "api_key": settings.llm_api_key,
            "api_base": settings.llm_api_base,
            "custom_llm_provider": "openai",
            **_get_thinking_param(),  # MiMo 关闭思考模式，避免多轮工具调用时的400错误
        }
        if is_final_output and response_format:
            params["response_format"] = response_format
            logger.info(f"[{self.agent_name}] 最终输出阶段使用结构化输出: {response_format}")
        return params

    def _is_context_overflow_error(self, error_str: str) -> bool:
        """检测是否是上下文超限错误"""
        return (
            "choices': None" in error_str
            or "choices is None" in error_str
            or ("completion_tokens': 0" in error_str and "prompt_tokens': 0" in error_str)
            or "context length exceeded" in error_str.lower()
            or "maximum context length" in error_str.lower()
        )

    async def _execute_tool_calls(
        self,
        message,
        tools: List[Dict],
        agent_tools: "AgentTools",
        pipeline_id: int,
        messages: List[Dict],
    ) -> tuple[List[Dict], int, bool, bool]:
        """执行单次 LLM 响应中的所有 tool_calls。
        返回 (tool_results, consecutive_code_apply_failures, switched_to_legacy, should_continue)
        """
        tool_results = []
        consecutive_failures = 0
        switched_to_legacy = False

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            available_tools = {t["function"]["name"] for t in tools}
            if tool_name not in available_tools:
                logger.warning(f"[{self.agent_name}] 工具 {tool_name} 不可用，跳过")
                result = json.dumps({"success": False, "error": f"工具 {tool_name} 不可用"})
                tool_results.append({"tool": tool_name, "arguments": tool_args, "result": {"success": False, "error": "工具不可用"}, "success": False})
                continue

            logger.info(f"[{self.agent_name}] Executing tool: {tool_name}({tool_args})")
            result = await agent_tools.execute_tool(tool_name, tool_args, pipeline_id)

            try:
                result_data = json.loads(result)
                tool_results.append({"tool": tool_name, "arguments": tool_args, "result": result_data, "success": result_data.get("success", True)})
                if tool_name == "code_apply":
                    if not result_data.get("success", False):
                        consecutive_failures += 1
                        if consecutive_failures >= 3 and not switched_to_legacy:
                            switched_to_legacy = True
                            logger.warning(f"[{self.agent_name}] code_apply 连续失败，切换到 LEGACY 模式")
                            messages.append({
                                "role": "user",
                                "content": "【流程切换通知】code_apply 多次失败，系统已切换为 LEGACY 模式。请直接输出完整 JSON 格式。"
                            })
                    else:
                        consecutive_failures = 0
            except Exception:
                tool_results.append({"tool": tool_name, "arguments": tool_args, "result": result, "success": True})

            # 截断过长的工具结果
            MAX_TOOL_RESULT_CHARS = 8000
            tool_content = result
            if len(result) > MAX_TOOL_RESULT_CHARS:
                try:
                    result_obj = json.loads(result)
                    if "lines" in result_obj and len(result_obj["lines"]) > MAX_TOOL_RESULT_CHARS:
                        result_obj["lines"] = result_obj["lines"][:MAX_TOOL_RESULT_CHARS] + "\n... [已截断]"
                        result_obj["truncated"] = True
                        tool_content = json.dumps(result_obj, ensure_ascii=False)
                except (json.JSONDecodeError, KeyError):
                    tool_content = result[:MAX_TOOL_RESULT_CHARS] + "\n... [内容已截断]"

            messages.append({"role": "tool", "content": tool_content, "tool_call_id": tool_call.id})

        # 检查总上下文是否过大
        MAX_CONTEXT_CHARS = 60000
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        should_continue = True
        if total_chars > MAX_CONTEXT_CHARS:
            logger.warning(f"[{self.agent_name}] 上下文过大 ({total_chars} chars)，请求 LLM 输出简短结论")
            messages.append({
                "role": "user",
                "content": "上下文已接近上限，请立即基于以上信息输出简短 JSON 结论，不要再调用工具。"
            })

        return tool_results, consecutive_failures, switched_to_legacy, should_continue

    async def _force_final_output(
        self,
        messages: List[Dict],
        response_format: Optional[Dict[str, Any]],
        total_input_tokens: int,
        total_output_tokens: int,
        tool_call_count: int,
        tool_results: List[Dict],
    ) -> Dict[str, Any]:
        """达到最大工具调用次数后强制输出最终答案"""
        import litellm

        logger.warning(f"[{self.agent_name}] Max tool calls ({self.MAX_TOOL_CALLS}) reached, forcing final output")
        messages.append({
            "role": "user",
            "content": f"已达到最大工具调用次数（{self.MAX_TOOL_CALLS}次）。请基于已获取的信息立即输出最终答案，不要再使用任何工具。直接输出 JSON 格式的结果。"
        })

        try:
            final_call_params = {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 16384,
                "api_key": settings.llm_api_key,
                "api_base": settings.llm_api_base,
                "custom_llm_provider": "openai",
                **_get_thinking_param(),  # MiMo 关闭思考模式，避免多轮工具调用时的400错误
            }
            if response_format:
                final_call_params["response_format"] = response_format

            response = await litellm.acompletion(**final_call_params)
            if response.usage:
                total_input_tokens += response.usage.prompt_tokens or 0
                total_output_tokens += response.usage.completion_tokens or 0

            content = response.choices[0].message.content or ""
            logger.info(f"[{self.agent_name}] 最终输出内容长度: {len(content)} 字符")

            return {
                "content": content,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": tool_call_count,
                "tool_results": tool_results,
                "note": f"工具调用达到上限({self.MAX_TOOL_CALLS})后强制输出"
            }
        except Exception as e:
            logger.error(f"[{self.agent_name}] 强制输出时出错: {e}")
            return {
                "content": "",
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": tool_call_count,
                "tool_results": tool_results,
                "error": f"Max tool calls reached and final output failed: {e}"
            }

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        project_path: str,
        pipeline_id: int = 0,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        调用 LLM，支持工具调用循环（包含写入工具）

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            project_path: 项目路径（用于工具执行）
            pipeline_id: Pipeline ID（用于日志推送）
            temperature: 温度参数
            max_tokens: 最大 Token 数（仅用于最终输出，工具调用使用较小值）
            max_retries: 空内容重试次数
            response_format: 响应格式，如 {"type": "json_object"}

        Returns:
            Dict: {content, input_tokens, output_tokens, tool_calls, tool_results}
        """
        agent_tools = self._get_agent_tools(project_path, pipeline_id)
        tools = agent_tools.tool_definitions

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        tool_results: List[Dict] = []
        consecutive_code_apply_failures = 0
        switched_to_legacy_mode = False
        empty_content_retries = 0

        while tool_call_count < self.MAX_TOOL_CALLS:
            try:
                import litellm

                has_recent_tool_calls = any(
                    m.get("role") == "assistant" and m.get("tool_calls")
                    for m in messages[-3:]
                )
                is_final_output = not has_recent_tool_calls or tool_call_count >= self.MAX_TOOL_CALLS - 1

                current_max_tokens = (max_tokens if (is_final_output and max_tokens) else 1000)
                if is_final_output and max_tokens:
                    logger.info(f"[{self.agent_name}] 最终输出阶段，使用 max_tokens={max_tokens}")

                call_params = self._build_llm_call_params(
                    messages, tools, temperature, current_max_tokens, response_format, is_final_output
                )

                response = await litellm.acompletion(**call_params)

                if response.usage:
                    total_input_tokens += response.usage.prompt_tokens or 0
                    total_output_tokens += response.usage.completion_tokens or 0

                message = response.choices[0].message

                if message.tool_calls:
                    tool_call_count += 1
                    logger.info(f"[{self.agent_name}] Tool call #{tool_call_count}")

                    assistant_message = {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in message.tool_calls
                        ]
                    }
                    reasoning_content = getattr(message, 'reasoning_content', None)
                    if reasoning_content:
                        assistant_message["reasoning_content"] = reasoning_content
                    messages.append(assistant_message)

                    new_tool_results, consecutive_code_apply_failures, switched, should_continue = await self._execute_tool_calls(
                        message, tools, agent_tools, pipeline_id, messages
                    )
                    tool_results.extend(new_tool_results)
                    if switched:
                        switched_to_legacy_mode = True
                    if not should_continue:
                        logger.warning(f"[{self.agent_name}] 上下文过大，停止工具调用")
                        break
                    continue

                # 非工具调用 — 返回最终答案
                if message.content:
                    logger.info(f"[{self.agent_name}] LLM 返回内容长度: {len(message.content)} 字符")
                    if hasattr(response.choices[0], 'finish_reason') and response.choices[0].finish_reason == 'length':
                        logger.error(f"[{self.agent_name}] LLM 输出因长度限制被截断！")
                elif empty_content_retries < max_retries:
                    empty_content_retries += 1
                    logger.warning(f"[{self.agent_name}] 空内容重试 {empty_content_retries}/{max_retries}")
                    messages.append({"role": "user", "content": "你刚才没有返回任何内容。请确保输出有效的 JSON 格式的回答。"})
                    continue
                else:
                    logger.error(f"[{self.agent_name}] 空内容重试已达上限 ({max_retries})")

                return {
                    "content": message.content,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "tool_calls": tool_call_count,
                    "tool_results": tool_results
                }

            except Exception as e:
                error_str = str(e)
                logger.error(f"[{self.agent_name}] LLM call with tools failed: {e}")

                if self._is_context_overflow_error(error_str):
                    logger.warning(f"[{self.agent_name}] 上下文超限，尝试降级输出")
                    fallback = self._build_output_from_tool_results(tool_results)
                    if fallback:
                        return {
                            "content": None,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "tool_calls": tool_call_count,
                            "tool_results": tool_results,
                            "fallback_output": fallback,
                            "error": "context_overflow_with_fallback"
                        }
                    raise RuntimeError(
                        f"上下文超限且无法降级：工具调用次数={tool_call_count}"
                    ) from e
                raise

        return await self._force_final_output(
            messages, response_format, total_input_tokens, total_output_tokens,
            tool_call_count, tool_results
        )

    async def execute(
        self,
        pipeline_id: int,
        stage_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行 Agent（支持工具调用）

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            initial_state: 初始状态（必须包含 project_path）
            max_tokens: 最大 Token 数（默认 None，表示不限制）
            response_format: 响应格式，如 {"type": "json_object"}

        Returns:
            Dict: 执行结果
        """
        logger.info(f"[{self.agent_name}] Starting execution with tools")

        try:
            # 获取 project_path
            project_path = initial_state.get("project_path", "/workspace/backend")

            # 构建提示
            system_prompt = self.system_prompt
            user_prompt = self.build_user_prompt(initial_state)

            # 调用 LLM（带工具）
            result = await self._call_llm_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                project_path=project_path,
                pipeline_id=pipeline_id,
                max_tokens=max_tokens,
                response_format=response_format
            )
            
            # 【调试】记录 _call_llm_with_tools 返回的 tool_results
            logger.info(f"[{self.agent_name}] _call_llm_with_tools 返回的 tool_calls: {result.get('tool_calls', 0)}")
            logger.info(f"[{self.agent_name}] _call_llm_with_tools 返回的 tool_results 数量: {len(result.get('tool_results', []))}")
            if result.get("tool_results"):
                logger.info(f"[{self.agent_name}] tool_results 第一项: {result.get('tool_results')[0]}")

            # 提取本次工具调用中读取过的文件内容（用于传递给下游 Agent）
            injected_files = {}
            if self._agent_tools:
                for file_path, cached in self._agent_tools._file_cache.items():
                    content = cached.get("content")
                    if content:
                        # 统一路径格式，移除 backend/ 前缀
                        clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                        injected_files[clean_path] = content

            # 【层面三续】处理上下文超限降级输出
            if result.get("error") == "context_overflow_with_fallback":
                fallback = result.get("fallback_output")
                output_dict = fallback.model_dump() if hasattr(fallback, 'model_dump') else fallback
                return {
                    "success": True,   # 降级成功，不是失败
                    "output": output_dict,
                    "injected_files": injected_files,  # ← 新增：传递读取的文件内容
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                    "tool_calls": result.get("tool_calls", 0),
                    "tool_results": result.get("tool_results", []),
                    "note": "上下文超限，基于已读文件降级输出"
                }

            # 检查是否达到最大工具调用次数
            if result.get("error") == "Max tool calls reached":
                logger.warning(f"[{self.agent_name}] 达到最大工具调用次数，尝试从工具结果构建输出")
                # 尝试从工具结果构建一个有效的输出
                fallback_output = self._build_output_from_tool_results(result.get("tool_results", []))
                if fallback_output:
                    # 将 Pydantic 模型转换为字典
                    output_dict = fallback_output.model_dump() if hasattr(fallback_output, 'model_dump') else fallback_output
                    return {
                        "success": True,
                        "output": output_dict,
                        "injected_files": injected_files,  # ← 新增：传递读取的文件内容
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                        "tool_calls": result.get("tool_calls", 0),
                        "tool_results": result.get("tool_results", []),
                        "raw_output": result["content"],
                        "note": "从工具调用结果构建的输出（达到最大工具调用次数）"
                    }
                else:
                    return {
                        "success": False,
                        "error": "达到最大工具调用次数，且无法从工具结果构建有效输出",
                        "injected_files": injected_files,  # ← 新增：即使失败也传递已读取的文件内容
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                        "tool_calls": result.get("tool_calls", 0),
                        "tool_results": result.get("tool_results", []),
                        "raw_output": result["content"][:500]
                    }

            # 解析输出
            raw_output = result.get("content")
            
            # 【调试】记录 raw_output 的详细信息
            if raw_output:
                logger.info(f"[{self.agent_name}] raw_output 长度: {len(raw_output)} 字符")
                logger.info(f"[{self.agent_name}] raw_output 前200字符: {repr(raw_output[:200])}")
                logger.info(f"[{self.agent_name}] raw_output 后200字符: {repr(raw_output[-200:])}")
                # 检查是否是不完整的 JSON
                if raw_output.strip().startswith('{') and not raw_output.strip().endswith('}'):
                    logger.error(f"[{self.agent_name}] raw_output 可能是不完整的 JSON（以 {{ 开头但不以 }} 结尾）")
            else:
                logger.warning(f"[{self.agent_name}] raw_output 为 None 或空字符串")
                # 【DEBUG】打印 result 的完整内容
                logger.info(f"[{self.agent_name}] result 完整内容: {json.dumps({k: str(v)[:200] for k, v in result.items()}, ensure_ascii=False)}")
            
            # 【修复】检查 content 是否为空
            if not raw_output:
                logger.warning(f"[{self.agent_name}] LLM 返回空内容，尝试从工具结果构建输出")
                fallback = self._build_output_from_tool_results(result.get("tool_results", []))
                if fallback:
                    output_dict = fallback.model_dump() if hasattr(fallback, 'model_dump') else fallback
                    return {
                        "success": True,
                        "output": output_dict,
                        "injected_files": injected_files,  # ← 新增：传递读取的文件内容
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "tool_calls": result.get("tool_calls", 0),
                        "tool_results": result.get("tool_results", []),
                        "note": "LLM 返回空内容，从工具结果构建输出"
                    }
                else:
                    return {
                        "success": False,
                        "error": "LLM 返回空内容，且无法从工具结果构建输出",
                        "injected_files": injected_files,
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "tool_calls": result.get("tool_calls", 0),
                        "tool_results": result.get("tool_results", []),
                        "partial_success": len(result.get("tool_results", [])) > 0
                    }
            
            parsed_output = self.parse_output(raw_output)

            # 验证输出
            validated_output = self.validate_output(parsed_output)

            if validated_output is None:
                return {
                    "success": False,
                    "error": "Output validation failed",
                    "raw_output": raw_output[:500],
                    "tool_results": result.get("tool_results", []),
                    "tool_calls": result.get("tool_calls", 0)
                }

            # 将 Pydantic 模型转换为字典
            output_dict = validated_output.model_dump() if hasattr(validated_output, 'model_dump') else validated_output

            return {
                "success": True,
                "output": output_dict,
                "injected_files": injected_files,  # ← 新增：传递读取的文件内容
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "tool_calls": result.get("tool_calls", 0),
                "tool_results": result.get("tool_results", []),
                "raw_output": raw_output
            }

        except Exception as e:
            logger.error(f"[{self.agent_name}] Execution failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _build_output_from_tool_results(self, tool_results: List[Dict[str, Any]]) -> Optional[Any]:
        """
        从工具调用结果构建输出（当达到最大工具调用次数时使用）

        子类可以重写此方法，根据工具执行结果构建一个有效的输出对象。
        默认返回 None，表示无法从工具结果构建输出。

        Args:
            tool_results: 工具执行结果列表

        Returns:
            Optional[Any]: 构建的输出对象，或 None
        """
        return None
