"""
Agent 基类
统一 LLM 调用逻辑 - 唯一能调用 LLM 的地方

原则：
- 严禁在 agents/ 之外的地方编写模型调用逻辑
- 支持 ModelScope (魔搭) 和 OpenAI 运行时切换
- 保持 Pydantic 解析逻辑不变
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TypeVar, Generic

import litellm
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import agent_metrics_context, MetricsCollector


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
    
    def _call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        统一 LLM 调用方法
        
        根据配置自动选择 ModelScope 或 OpenAI
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 Token 数
            
        Returns:
            str: LLM 响应内容
            
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
            
            # 调用 litellm
            response = litellm.completion(
                model=model,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # 提取响应内容
            if response and response.choices:
                return response.choices[0].message.content
            
            raise LLMCallError("LLM 返回空响应")
            
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
        5. 记录指标
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            **prompt_kwargs: Prompt 构建参数
            
        Returns:
            Dict: {success, output, error, metrics}
        """
        retry_count = 0
        last_error = None
        
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
                    
                    # 2. 调用 LLM
                    response = self._call_llm(messages)
                    
                    # 3. 解析输出
                    parsed_output = self.parse_output(response)
                    
                    # 4. 校验输出
                    validated_output = self.validate_output(parsed_output)
                    
                    # 5. 记录 Token 数（如果响应中有）
                    # TODO: 从 litellm 响应中提取实际 Token 数
                    metrics.input_tokens = len(user_prompt) // 4  # 粗略估计
                    metrics.output_tokens = len(response) // 4
                    
                    return {
                        "success": True,
                        "output": validated_output.model_dump(),
                        "error": None,
                        "retry_count": retry_count
                    }
                    
                except (LLMCallError, JSONParseError, ValidationError) as e:
                    last_error = str(e)
                    retry_count += 1
                    metrics.retry_count = retry_count
                    
                    if retry_count > self.MAX_RETRIES:
                        break
            
            # 所有重试失败
            return {
                "success": False,
                "output": None,
                "error": f"执行失败（重试{retry_count}次）: {last_error}",
                "retry_count": retry_count
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
    
    def _call_llm(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return json.dumps(self._mock_response)


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
