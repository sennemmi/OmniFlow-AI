"""
结构化 LLM 调用模块

基于 Instructor 库实现，强制 LLM 输出符合 Pydantic Schema 的结构化数据。
从根本上杜绝输出格式随意性，让接口契约与验收标准的映射成为代码可验证的事实。
"""

import instructor
import litellm
from typing import Type, TypeVar, Optional, Dict, Any
from pydantic import BaseModel

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)


class StructuredLLMClient:
    """
    结构化 LLM 客户端
    
    使用 Instructor 库包装 LiteLLM，强制 LLM 输出符合 Pydantic Model 的结构化数据。
    """
    
    def __init__(self):
        # 创建 Instructor 客户端，包装 litellm
        self.client = instructor.from_litellm(litellm.acompletion)
    
    async def generate_structured(
        self,
        response_model: Type[T],
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
        **kwargs
    ) -> tuple[T, Dict[str, Any]]:
        """
        生成结构化输出
        
        Args:
            response_model: Pydantic 模型类，定义期望的输出结构
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 模型名称（默认使用 settings.llm_model）
            temperature: 温度参数
            max_tokens: 最大 token 数
            max_retries: 最大重试次数（Instructor 会自动重试格式错误的输出）
            **kwargs: 其他传递给 litellm 的参数
            
        Returns:
            tuple[解析后的对象, 元数据字典]
            元数据包含: input_tokens, output_tokens, total_tokens, raw_response
        """
        model = model or settings.llm_model
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 使用 Instructor 调用 LLM，强制输出符合 response_model
        response, completion = await self.client.chat.completions.create_with_completion(
            model=model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            **kwargs
        )
        
        # 提取元数据
        metadata = {
            "input_tokens": completion.usage.prompt_tokens if completion.usage else 0,
            "output_tokens": completion.usage.completion_tokens if completion.usage else 0,
            "total_tokens": completion.usage.total_tokens if completion.usage else 0,
            "model": model,
            "raw_response": completion
        }
        
        return response, metadata


# 单例实例
structured_llm_client = StructuredLLMClient()


async def generate_structured_output(
    response_model: Type[T],
    system_prompt: str,
    user_prompt: str,
    **kwargs
) -> tuple[T, Dict[str, Any]]:
    """
    便捷函数：生成结构化输出
    
    示例:
        >>> from app.agents.schemas import DesignerOutputV2
        >>> output, metadata = await generate_structured_output(
        ...     response_model=DesignerOutputV2,
        ...     system_prompt="你是设计师 Agent...",
        ...     user_prompt="请设计以下功能..."
        ... )
    """
    return await structured_llm_client.generate_structured(
        response_model=response_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        **kwargs
    )
