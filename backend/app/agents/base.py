"""
Agent 基类
统一 LLM 调用逻辑 - 唯一能调用 LLM 的地方

原则：
- 严禁在 agents/ 之外的地方编写模型调用逻辑
- 支持 ModelScope (魔搭) 和 OpenAI 运行时切换
- 保持 Pydantic 解析逻辑不变
- 自动捕获 Token 和耗时指标
"""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TypeVar, Generic

import litellm
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import agent_metrics_context, MetricsCollector
from app.core.sse_log_buffer import push_log


# 禁用 litellm 的详细日志
litellm.set_verbose = False


class AgentError(Exception):
    """Agent 错误"""
    pass


class LLMCallError(AgentError):
    """LLM 调用错误"""
    pass


class JSONParseError(AgentError):
    """JSON 解析错误"""
    pass


T = TypeVar('T', bound=BaseModel)


class BaseAgent(ABC, Generic[T]):
    """
    Agent 基类
    
    统一 LLM 调用逻辑，支持：
    - ModelScope (魔搭) 和 OpenAI 运行时切换
    - 自动 Token 和耗时统计
    - JSON 输出解析和校验
    - 重试机制
    
    八荣八耻：
    - 严禁在 agents/ 之外的地方编写模型调用逻辑
    """
    
    MAX_RETRIES: int = 3
    
    def __init__(self, agent_name: str):
        """
        初始化 Agent
        
        Args:
            agent_name: Agent 名称（用于日志和指标）
        """
        self.agent_name = agent_name
        self.metrics_collector = MetricsCollector()
    
    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """系统 Prompt，子类必须实现"""
        pass
    
    @abstractmethod
    def build_user_prompt(self, **kwargs) -> str:
        """构建用户 Prompt，子类必须实现"""
        pass
    
    @abstractmethod
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出，子类必须实现"""
        pass
    
    @abstractmethod
    def validate_output(self, output: Dict[str, Any]) -> T:
        """校验输出，子类必须实现"""
        pass
    
    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        统一 LLM 调用方法（异步）

        根据配置自动选择 ModelScope 或 OpenAI
        使用 litellm.acompletion 避免阻塞事件循环

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 Token 数

        Returns:
            Dict: 包含 content, usage, reasoning 的完整响应

        Raises:
            LLMCallError: 调用失败
        """
        try:
            # 从配置获取 API 参数
            api_key = settings.llm_api_key
            api_base = settings.llm_api_base
            model = settings.llm_model

            # 检查 API Key
            if not api_key:
                provider = "ModelScope" if settings.USE_MODELSCOPE else "OpenAI"
                raise LLMCallError(f"{provider} API Key 未配置")

            # 调用 litellm 异步接口，避免阻塞事件循环
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens
            )

            # 提取响应内容
            if not response or not response.choices:
                raise LLMCallError("LLM 返回空响应")

            # 构建返回结果
            result = {
                "content": response.choices[0].message.content,
                "usage": response.usage if hasattr(response, 'usage') else None,
                "reasoning": None
            }

            # 尝试提取推理过程（如果模型支持）
            message = response.choices[0].message
            if hasattr(message, 'reasoning_content') and message.reasoning_content:
                result["reasoning"] = message.reasoning_content
            elif hasattr(message, 'reasoning') and message.reasoning:
                result["reasoning"] = message.reasoning

            return result

        except Exception as e:
            raise LLMCallError(f"LLM 调用失败: {e}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON
        
        剥离 Markdown 代码块，提取纯 JSON
        
        Args:
            response: LLM 响应字符串
            
        Returns:
            Dict: 解析后的 JSON
            
        Raises:
            JSONParseError: 解析失败
        """
        try:
            # 去除 Markdown 代码块标记
            json_str = re.sub(r'^```json\s*', '', response.strip())
            json_str = re.sub(r'^```\s*', '', json_str)
            json_str = re.sub(r'```\s*$', '', json_str)
            json_str = json_str.strip()
            
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise JSONParseError(f"JSON 解析失败: {e}\n响应内容: {response[:500]}")
    
    async def execute(
        self,
        pipeline_id: int,
        stage_name: str,
        **prompt_kwargs
    ) -> Dict[str, Any]:
        """
        执行 Agent

        完整的执行流程：
        1. 构建 Prompt
        2. 调用 LLM（带重试）
        3. 解析 JSON
        4. 校验输出
        5. 记录指标（Token、耗时、推理过程）

        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            **prompt_kwargs: Prompt 构建参数

        Returns:
            Dict: {success, output, error, metrics, input_tokens, output_tokens, duration_ms, reasoning}
        """
        retry_count = 0
        last_error = None
        total_input_tokens = 0
        total_output_tokens = 0
        reasoning_content = None

        # 记录开始时间
        start_time = time.perf_counter()

        # 使用上下文管理器记录指标
        with agent_metrics_context(self.agent_name, stage_name, pipeline_id) as metrics:
            while retry_count <= self.MAX_RETRIES:
                try:
                    # 1. 构建 Prompt
                    user_prompt = self.build_user_prompt(**prompt_kwargs)
                    messages = [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]

                    # 推送思考开始日志
                    await push_log(
                        pipeline_id,
                        "thought",
                        f"[{self.agent_name}] 开始分析需求...",
                        stage=stage_name
                    )

                    # 2. 调用 LLM（异步）
                    llm_response = await self._call_llm(messages)
                    response_content = llm_response["content"]

                    # 3. 提取 Token 和推理过程
                    if llm_response.get("usage"):
                        total_input_tokens = llm_response["usage"].prompt_tokens
                        total_output_tokens = llm_response["usage"].completion_tokens

                    if llm_response.get("reasoning"):
                        reasoning_content = llm_response["reasoning"]
                        # 推送推理过程
                        await push_log(
                            pipeline_id,
                            "thought",
                            f"[{self.agent_name}] 推理过程:\n{reasoning_content[:500]}",
                            stage=stage_name
                        )

                    # 4. 解析输出
                    parsed_output = self.parse_output(response_content)

                    # 5. 校验输出
                    validated_output = self.validate_output(parsed_output)

                    # 6. 计算耗时
                    end_time = time.perf_counter()
                    duration_ms = int((end_time - start_time) * 1000)

                    # 7. 记录指标
                    metrics.input_tokens = total_input_tokens
                    metrics.output_tokens = total_output_tokens
                    metrics.retry_count = retry_count

                    # 推送完成日志
                    await push_log(
                        pipeline_id,
                        "thought",
                        f"[{self.agent_name}] 分析完成，耗时 {duration_ms}ms，输入 {total_input_tokens} tokens，输出 {total_output_tokens} tokens",
                        stage=stage_name
                    )

                    return {
                        "success": True,
                        "output": validated_output.model_dump(),
                        "error": None,
                        "retry_count": retry_count,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "duration_ms": duration_ms,
                        "reasoning": reasoning_content
                    }

                except (LLMCallError, JSONParseError, ValidationError) as e:
                    last_error = str(e)
                    retry_count += 1
                    metrics.retry_count = retry_count

                    # 推送错误日志
                    await push_log(
                        pipeline_id,
                        "thought",
                        f"[{self.agent_name}] 第 {retry_count} 次尝试失败: {str(e)[:200]}",
                        stage=stage_name
                    )

                    if retry_count > self.MAX_RETRIES:
                        break

            # 所有重试失败
            end_time = time.perf_counter()
            duration_ms = int((end_time - start_time) * 1000)

            return {
                "success": False,
                "output": None,
                "error": f"执行失败（重试{retry_count}次）: {last_error}",
                "retry_count": retry_count,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "duration_ms": duration_ms,
                "reasoning": reasoning_content
            }


class MockAgent(BaseAgent[BaseModel]):
    """
    模拟 Agent 基类
    
    用于测试，不实际调用 LLM
    """
    
    def __init__(self, agent_name: str, mock_response: Dict[str, Any]):
        super().__init__(agent_name)
        self._mock_response = mock_response
    
    @property
    def system_prompt(self) -> str:
        return "Mock system prompt"
    
    def build_user_prompt(self, **kwargs) -> str:
        return "Mock user prompt"
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        return self._mock_response
    
    def validate_output(self, output: Dict[str, Any]) -> BaseModel:
        return BaseModel(**output)
    
    async def _call_llm(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        return {
            "content": json.dumps(self._mock_response),
            "usage": None,
            "reasoning": None
        }


def get_llm_provider_info() -> Dict[str, str]:
    """
    获取当前 LLM 供应商信息
    
    Returns:
        Dict: 供应商信息
    """
    return {
        "provider": "ModelScope" if settings.USE_MODELSCOPE else "OpenAI",
        "model": settings.llm_model,
        "api_base": settings.llm_api_base
    }
