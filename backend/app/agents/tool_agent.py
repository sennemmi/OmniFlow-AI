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
    """

    # 最大工具调用次数，防止无限循环
    MAX_TOOL_CALLS = 10

    def __init__(self, agent_name: str = "ToolUsingAgent"):
        super().__init__(agent_name=agent_name)
        self._agent_tools: Optional[AgentTools] = None

    def _get_agent_tools(self, project_path: str) -> AgentTools:
        """获取或创建 AgentTools 实例"""
        if self._agent_tools is None or self._agent_tools.project_path != project_path:
            self._agent_tools = get_agent_tools(project_path)
        return self._agent_tools

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        project_path: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        调用 LLM，支持工具调用循环

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            project_path: 项目路径（用于工具执行）
            temperature: 温度参数
            max_tokens: 最大 Token 数

        Returns:
            Dict: {content, input_tokens, output_tokens, tool_calls}
        """
        # 获取工具定义
        agent_tools = self._get_agent_tools(project_path)
        tools = agent_tools.tool_definitions

        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0

        while tool_call_count < self.MAX_TOOL_CALLS:
            try:
                # 调用 LLM（带工具）
                import litellm

                response = await litellm.acompletion(
                    model=settings.llm_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",  # 允许模型选择是否使用工具
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=settings.llm_api_key,
                    api_base=settings.llm_api_base
                )

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
                    messages.append({
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
                    })

                    # 执行工具调用
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        logger.info(f"[{self.agent_name}] Executing tool: {tool_name}({tool_args})")

                        # 执行工具
                        result = agent_tools.execute_tool(tool_name, tool_args)

                        # 添加工具结果到消息
                        messages.append({
                            "role": "tool",
                            "content": result,
                            "tool_call_id": tool_call.id
                        })

                    # 继续循环，让 LLM 基于工具结果继续思考
                    continue

                # 不是工具调用，返回最终答案
                return {
                    "content": message.content,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "tool_calls": tool_call_count
                }

            except Exception as e:
                logger.error(f"[{self.agent_name}] LLM call with tools failed: {e}")
                raise

        # 达到最大工具调用次数
        logger.warning(f"[{self.agent_name}] Max tool calls ({self.MAX_TOOL_CALLS}) reached")
        return {
            "content": "Error: Too many tool calls",
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "tool_calls": tool_call_count,
            "error": "Max tool calls reached"
        }

    async def execute(
        self,
        pipeline_id: int,
        stage_name: str,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行 Agent（支持工具调用）

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            initial_state: 初始状态（必须包含 project_path）

        Returns:
            Dict: 执行结果
        """
        start_time = logging.info(f"[{self.agent_name}] Starting execution with tools")

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
                project_path=project_path
            )

            # 解析输出
            raw_output = result["content"]
            parsed_output = self.parse_output(raw_output)

            # 验证输出
            validated_output = self.validate_output(parsed_output)

            if validated_output is None:
                return {
                    "success": False,
                    "error": "Output validation failed",
                    "raw_output": raw_output[:500]
                }

            return {
                "success": True,
                "output": validated_output,
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "tool_calls": result.get("tool_calls", 0),
                "raw_output": raw_output
            }

        except Exception as e:
            logger.error(f"[{self.agent_name}] Execution failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
