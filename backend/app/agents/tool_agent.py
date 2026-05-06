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
        # 获取工具定义（传入 pipeline_id 以便 install_dependency 工具使用）
        agent_tools = self._get_agent_tools(project_path, pipeline_id)
        tools = agent_tools.tool_definitions

        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        tool_results = []  # 记录所有工具执行结果
        consecutive_code_apply_failures = 0  # code_apply 连续失败计数
        switched_to_legacy_mode = False  # 是否已切换到 LEGACY 模式

        # 【重试机制】空内容重试计数
        empty_content_retries = 0

        while tool_call_count < self.MAX_TOOL_CALLS:
            try:
                # 调用 LLM（带工具）
                import litellm

                # 【关键】区分工具调用和最终输出的 max_tokens
                # 工具调用阶段使用较小值（1000），最终输出阶段使用传入的值
                has_recent_tool_calls = any(
                    m.get("role") == "assistant" and m.get("tool_calls")
                    for m in messages[-3:]  # 检查最近3条消息是否有工具调用
                )
                # 最终输出：没有最近工具调用，或者已经达到最大工具调用次数
                is_final_output = not has_recent_tool_calls or tool_call_count >= self.MAX_TOOL_CALLS - 1

                if is_final_output and max_tokens:
                    # 最终输出阶段，使用完整的 max_tokens
                    current_max_tokens = max_tokens
                    logger.info(f"[{self.agent_name}] 最终输出阶段，使用 max_tokens={max_tokens}")
                else:
                    # 工具调用阶段，使用较小的 max_tokens 节省预算
                    current_max_tokens = 1000
                    logger.debug(f"[{self.agent_name}] 工具调用阶段，使用 max_tokens=1000")

                # 构建调用参数
                call_params = {
                    "model": settings.llm_model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",  # 允许模型选择是否使用工具
                    "temperature": temperature,
                    "max_tokens": current_max_tokens,
                    "api_key": settings.llm_api_key,
                    "api_base": settings.llm_api_base,
                    "custom_llm_provider": "openai"  # 强制使用 OpenAI 兼容方式
                }

                # 【结构化输出】最终输出阶段，如果指定了 response_format，则使用结构化输出
                if is_final_output and response_format:
                    call_params["response_format"] = response_format
                    logger.info(f"[{self.agent_name}] 最终输出阶段使用结构化输出: {response_format}")

                response = await litellm.acompletion(**call_params)

                # 记录 Token 使用
                if response.usage:
                    total_input_tokens += response.usage.prompt_tokens or 0
                    total_output_tokens += response.usage.completion_tokens or 0

                message = response.choices[0].message

                # 检查是否是工具调用
                if message.tool_calls:
                    tool_call_count += 1
                    logger.info(f"[{self.agent_name}] Tool call #{tool_call_count}")

                    # 添加助手消息（包含 tool_calls）
                    # 【DeepSeek Thinking Mode】需要传递 reasoning_content
                    assistant_message = {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in message.tool_calls
                        ]
                    }
                    # 如果存在 reasoning_content，添加到消息中（DeepSeek 需要）
                    reasoning_content = getattr(message, 'reasoning_content', None)
                    if reasoning_content:
                        assistant_message["reasoning_content"] = reasoning_content
                    messages.append(assistant_message)

                    # 执行工具调用（支持异步工具）
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        # 【权限控制】检查工具是否在允许列表中
                        available_tools = {t["function"]["name"] for t in tools}
                        if tool_name not in available_tools:
                            logger.warning(f"[{self.agent_name}] 工具 {tool_name} 不在可用列表中，跳过执行")
                            result = json.dumps({
                                "success": False,
                                "error": f"工具 {tool_name} 不可用。可用工具: {', '.join(available_tools)}"
                            })
                            tool_results.append({
                                "tool": tool_name,
                                "arguments": tool_args,
                                "result": {"success": False, "error": "工具不可用"},
                                "success": False
                            })
                            continue

                        logger.info(f"[{self.agent_name}] Executing tool: {tool_name}({tool_args})")

                        # 执行工具（传入 pipeline_id 用于日志推送）
                        result = await agent_tools.execute_tool(tool_name, tool_args, pipeline_id)

                        # 记录工具结果
                        try:
                            result_data = json.loads(result)
                            tool_results.append({
                                "tool": tool_name,
                                "arguments": tool_args,
                                "result": result_data,
                                "success": result_data.get("success", True)
                            })

                            # 【智能回退】检测 code_apply 连续失败
                            if tool_name == "code_apply":
                                if not result_data.get("success", False):
                                    consecutive_code_apply_failures += 1
                                    logger.warning(
                                        f"[{self.agent_name}] code_apply 连续失败 {consecutive_code_apply_failures} 次"
                                    )

                                    if consecutive_code_apply_failures >= 3 and not switched_to_legacy_mode:
                                        # 自动切换到 LEGACY 模式
                                        switched_to_legacy_mode = True
                                        logger.warning(
                                            f"[{self.agent_name}] code_apply 连续失败 {consecutive_code_apply_failures} 次,"
                                            f"切换到 LEGACY 模式(生成完整文件)"
                                        )
                                        # 注入切换指令到 messages
                                        messages.append({
                                            "role": "user",
                                            "content": (
                                                "【流程切换通知】由于 code_apply 工具多次失败,"
                                                "系统已自动切换为 LEGACY 模式。请直接输出完整的 JSON 格式,"
                                                "包含所有文件的 search_block/replace_block。"
                                            )
                                        })
                                else:
                                    # 成功后重置计数器
                                    consecutive_code_apply_failures = 0
                        except:
                            tool_results.append({
                                "tool": tool_name,
                                "arguments": tool_args,
                                "result": result,
                                "success": True
                            })

                        # 【层面一】工具返回内容截断，防止上下文爆炸
                        MAX_TOOL_RESULT_CHARS = 8000  # 约 2000 tokens

                        tool_content = result
                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            # 解析 JSON，只截断 lines 字段，保留元信息
                            try:
                                result_obj = json.loads(result)
                                if "lines" in result_obj:
                                    lines_text = result_obj["lines"]
                                    if len(lines_text) > MAX_TOOL_RESULT_CHARS:
                                        kept_lines = lines_text[:MAX_TOOL_RESULT_CHARS]
                                        result_obj["lines"] = kept_lines + f"\n... [已截断，原文件共 {result_obj.get('total_lines', '?')} 行，超出部分省略]"
                                        result_obj["truncated"] = True
                                        tool_content = json.dumps(result_obj, ensure_ascii=False)
                            except (json.JSONDecodeError, KeyError):
                                tool_content = result[:MAX_TOOL_RESULT_CHARS] + "\n... [内容已截断]"

                        # 添加工具结果到消息
                        messages.append({
                            "role": "tool",
                            "content": tool_content,
                            "tool_call_id": tool_call.id
                        })

                    # 【层面二】防止总消息历史过大
                    MAX_CONTEXT_CHARS = 60000  # Kimi-K2.5 约 128K tokens，留 50% 安全边距

                    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
                    if total_chars > MAX_CONTEXT_CHARS:
                        logger.warning(
                            f"[{self.agent_name}] 上下文过大 ({total_chars} chars)，"
                            f"停止工具调用，请求 LLM 输出简短结论"
                        )
                        # 【修复】不再直接返回 fallback，而是让 LLM 基于已有信息输出简短 JSON
                        # 添加提示消息，要求 LLM 输出简短结论
                        messages.append({
                            "role": "user",
                            "content": "上下文已接近上限，请立即基于以上信息输出简短 JSON 结论（不要详细设计，只输出核心字段），不要再调用工具。"
                        })
                        # 继续循环，让 LLM 输出最终答案
                        continue

                    # 继续循环，让 LLM 基于工具结果继续思考
                    continue

                # 不是工具调用，返回最终答案
                # 【调试】记录 message.content 的详细信息
                if message.content:
                    logger.info(f"[{self.agent_name}] LLM 返回内容长度: {len(message.content)} 字符")
                    logger.info(f"[{self.agent_name}] LLM 返回内容前200字符: {repr(message.content[:200])}")
                    logger.info(f"[{self.agent_name}] LLM 返回内容后200字符: {repr(message.content[-200:])}")
                    # 检查 finish_reason
                    if hasattr(response.choices[0], 'finish_reason'):
                        finish_reason = response.choices[0].finish_reason
                        logger.info(f"[{self.agent_name}] LLM finish_reason: {finish_reason}")
                        if finish_reason == 'length':
                            logger.error(f"[{self.agent_name}] LLM 输出因长度限制被截断！")
                else:
                    logger.warning(f"[{self.agent_name}] LLM 返回空内容")
                    # 【重试机制】如果返回空内容且未达到最大重试次数，则重试
                    if empty_content_retries < max_retries:
                        empty_content_retries += 1
                        logger.warning(f"[{self.agent_name}] 空内容重试 {empty_content_retries}/{max_retries}")
                        # 添加提示消息，要求 LLM 输出有效内容
                        messages.append({
                            "role": "user",
                            "content": "你刚才没有返回任何内容。请确保输出有效的 JSON 格式的回答，不要返回空内容。"
                        })
                        continue  # 继续循环，重新调用 LLM
                    else:
                        logger.error(f"[{self.agent_name}] 空内容重试次数已达上限 ({max_retries})，放弃重试")
                
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

                # 【层面三】识别"上下文超限"导致的空响应（不可重试，重试只会再次超限）
                is_context_overflow = (
                    "choices': None" in error_str or
                    "choices is None" in error_str or
                    ("completion_tokens': 0" in error_str and "prompt_tokens': 0" in error_str) or
                    "context length exceeded" in error_str.lower() or
                    "maximum context length" in error_str.lower()
                )

                if is_context_overflow:
                    logger.warning(
                        f"[{self.agent_name}] 检测到上下文超限（choices=None），"
                        f"已完成 {tool_call_count} 次工具调用，尝试从已有结果构建输出"
                    )
                    # 不抛异常，而是尝试从已有工具结果降级输出
                    fallback = self._build_output_from_tool_results(tool_results)
                    if fallback:
                        return {
                            "content": None,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                            "tool_calls": tool_call_count,
                            "tool_results": tool_results,
                            "fallback_output": fallback,  # 标记为降级输出
                            "error": "context_overflow_with_fallback"
                        }
                    # 没有 fallback，才真正抛出
                    raise RuntimeError(
                        f"上下文超限且无法降级：已读取文件过多或单文件过大。"
                        f"工具调用次数={tool_call_count}"
                    ) from e

                # 其他错误正常抛出
                raise

        # 达到最大工具调用次数 - 不再直接返回错误，而是让 AI 直接输出内容
        logger.warning(f"[{self.agent_name}] Max tool calls ({self.MAX_TOOL_CALLS}) reached, forcing final output")

        # 添加提示消息，要求 AI 立即输出最终答案，不再使用工具
        messages.append({
            "role": "user",
            "content": f"已达到最大工具调用次数（{self.MAX_TOOL_CALLS}次）。请基于已获取的信息立即输出最终答案，不要再使用任何工具。直接输出 JSON 格式的结果。"
        })

        # 继续调用 LLM，让 AI 直接输出内容
        try:
            import litellm

            logger.info(f"[{self.agent_name}] 调用 LLM 输出最终答案（工具调用已达上限）")

            # 构建调用参数
            final_call_params = {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": 0.0,
                # 【防截断补丁】在逃生舱模式下，必须给予足够的 Token 输出超长文件
                "max_tokens": 16384,
                "api_key": settings.llm_api_key,
                "api_base": settings.llm_api_base,
                "custom_llm_provider": "openai"
            }
            
            # 【关键】如果指定了 response_format，在最终输出阶段使用它
            if response_format:
                final_call_params["response_format"] = response_format
                logger.info(f"[{self.agent_name}] 强制输出阶段使用结构化输出: {response_format}")

            response = await litellm.acompletion(**final_call_params)

            # 记录 Token 使用
            if response.usage:
                total_input_tokens += response.usage.prompt_tokens or 0
                total_output_tokens += response.usage.completion_tokens or 0

            message = response.choices[0].message
            content = message.content or ""

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
            # 如果强制输出也失败，返回错误
            return {
                "content": "",
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": tool_call_count,
                "tool_results": tool_results,
                "error": f"Max tool calls reached and final output failed: {e}"
            }

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
                        "injected_files": injected_files,  # ← 新增：即使失败也传递已读取的文件内容
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "tool_calls": result.get("tool_calls", 0),
                        "tool_results": result.get("tool_results", [])
                    }
            
            parsed_output = self.parse_output(raw_output)

            # 验证输出
            validated_output = self.validate_output(parsed_output)

            if validated_output is None:
                return {
                    "success": False,
                    "error": "Output validation failed",
                    "raw_output": raw_output[:500]
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
