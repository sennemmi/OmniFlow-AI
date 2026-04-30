"""
LLM Provider 策略模式实现

职责：
- 定义 LLMProvider 接口
- 实现不同供应商的 Provider（ModelScope、OpenAI 等）
- 提供 Provider 工厂
- 集成智能重试机制（resilience）

设计原则：
- 新增 provider 不需要修改基类
- BaseAgent 只依赖注入的 provider 接口
- 自动重试可恢复错误，熔断保护
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging

import litellm

from app.core.config import settings
from app.core.resilience import RetryExecutor, ResilienceManager, RetryConfig, CircuitBreakerOpenError

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """
    LLM Provider 接口

    所有 LLM 供应商必须实现此接口
    """

    @abstractmethod
    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        调用 LLM

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大 Token 数

        Returns:
            Dict: {content, input_tokens, output_tokens}

        Raises:
            LLMCallError: 调用失败
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名称"""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """当前使用的模型名称"""
        pass


class LLMCallError(Exception):
    """LLM 调用错误"""
    pass


class ModelScopeProvider(LLMProvider):
    """
    ModelScope (魔搭) Provider

    使用 OpenAI 兼容接口，集成智能重试机制
    """

    def __init__(self):
        self._client = None
        # 【智能重试】初始化重试执行器
        self._retry_executor = ResilienceManager.get_executor(
            name="modelscope_provider",
            **RetryConfig.LLM_ROBUST
        )

    @property
    def provider_name(self) -> str:
        return "ModelScope"

    @property
    def model_name(self) -> str:
        return settings.llm_model

    def _get_client(self):
        """懒加载 AsyncOpenAI 客户端"""
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                base_url=settings.llm_api_base,
                api_key=settings.llm_api_key
            )
        return self._client

    async def _do_call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """实际调用 ModelScope API（内部方法，供重试执行器调用）"""
        client = self._get_client()

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )

        # 【详细日志】记录完整响应结构以诊断问题
        logger.debug(f"[{self.provider_name}] Raw response: {response}")

        if not response:
            raise LLMCallError("LLM 返回 None 响应")

        if not response.choices:
            # 【详细日志】记录 response 结构以诊断空 choices 问题
            usage_info = response.usage if hasattr(response, 'usage') else None
            logger.error(
                f"[{self.provider_name}] Empty choices detected! "
                f"This is typically an API intermittent issue (rate limiting or service unavailable). "
                f"usage={usage_info}, model={settings.llm_model}"
            )
            # 返回一个可重试的错误信号
            raise LLMCallError(
                f"API 间歇性错误：LLM 返回空响应 (usage: {usage_info}). "
                f"这通常是 ModelScope API 的临时问题，建议自动重试。"
            )

        # 检查 message content 是否为空
        message = response.choices[0].message
        if not message.content or not message.content.strip():
            logger.warning(f"[{self.provider_name}] Message content is empty! message: {message}, finish_reason: {response.choices[0].finish_reason}")
            # 某些模型可能返回 reasoning 内容而不是 content
            reasoning_content = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)
            if reasoning_content:
                logger.info(f"[{self.provider_name}] Found reasoning content, using as fallback")
                return {
                    "content": reasoning_content,
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0
                }
            raise LLMCallError(f"LLM 返回空内容 (finish_reason: {response.choices[0].finish_reason})")

        # 提取 Token 信息
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0
        else:
            # 降级：通过内容长度粗略估算（1字符≈0.3 token）
            content = response.choices[0].message.content or ""
            input_tokens = int(len(user_prompt) * 0.3)
            output_tokens = int(len(content) * 0.3)
            logger.warning(
                f"[{self.provider_name}] response.usage is None, "
                f"using estimated tokens: input={input_tokens}, output={output_tokens}"
            )

        logger.info(
            f"[{self.provider_name}] response.usage: {response.usage}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}"
        )

        return {
            "content": response.choices[0].message.content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        调用 ModelScope API（带智能重试）

        【智能重试】自动处理以下错误：
        - Empty choices（API 间歇性错误）
        - 网络超时
        - 服务端错误（500, 502, 503, 504）
        """
        if not settings.llm_api_key:
            raise LLMCallError("ModelScope API Key 未配置")

        try:
            # 【智能重试】使用 RetryExecutor 执行调用
            return await self._retry_executor.execute(
                self._do_call,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens
            )
        except CircuitBreakerOpenError as e:
            # 【用户感知分级】熔断通知
            logger.error(f"[{self.provider_name}] Circuit breaker open: {e}")
            raise LLMCallError(
                "服务端暂时不稳定，系统正在冷却，请稍后再试..."
            ) from e
        except Exception as e:
            # 【用户感知分级】致命错误或重试耗尽
            logger.error(f"[{self.provider_name}] Call failed after retries: {e}")
            raise


class OpenAIProvider(LLMProvider):
    """
    OpenAI Provider

    使用 LiteLLM 异步接口，集成智能重试机制
    """

    def __init__(self):
        # 【智能重试】初始化重试执行器
        self._retry_executor = ResilienceManager.get_executor(
            name="openai_provider",
            **RetryConfig.LLM_ROBUST
        )

    @property
    def provider_name(self) -> str:
        return "OpenAI"

    @property
    def model_name(self) -> str:
        return settings.llm_model

    async def _do_call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """实际调用 OpenAI API (via LiteLLM)（内部方法，供重试执行器调用）"""
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # 【详细日志】记录完整响应结构以诊断问题
        logger.debug(f"[{self.provider_name}] Raw response: {response}")

        if not response:
            raise LLMCallError("LLM 返回 None 响应")

        if not response.choices:
            logger.error(f"[{self.provider_name}] Empty choices! response: {response}")
            raise LLMCallError(f"LLM 返回空 choices，可能原因：API 限流、内容被过滤。usage: {getattr(response, 'usage', 'N/A')}")

        # 检查 message content 是否为空
        message = response.choices[0].message
        if not message.content or not message.content.strip():
            logger.warning(f"[{self.provider_name}] Message content is empty! finish_reason: {response.choices[0].finish_reason}")
            # 某些模型可能返回 reasoning 内容
            reasoning_content = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)
            if reasoning_content:
                logger.info(f"[{self.provider_name}] Found reasoning content, using as fallback")
                return {
                    "content": reasoning_content,
                    "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "output_tokens": response.usage.completion_tokens if response.usage else 0
                }
            raise LLMCallError(f"LLM 返回空内容 (finish_reason: {response.choices[0].finish_reason})")

        # 提取 Token 信息
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0
        else:
            # 降级：通过内容长度粗略估算（1字符≈0.3 token）
            content = response.choices[0].message.content or ""
            input_tokens = int(len(user_prompt) * 0.3)
            output_tokens = int(len(content) * 0.3)
            logger.warning(
                f"[{self.provider_name}] response.usage is None, "
                f"using estimated tokens: input={input_tokens}, output={output_tokens}"
            )

        logger.info(
            f"[{self.provider_name}] response.usage: {response.usage}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}"
        )

        return {
            "content": response.choices[0].message.content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        调用 OpenAI API (via LiteLLM)（带智能重试）

        【智能重试】自动处理以下错误：
        - Empty choices（API 间歇性错误）
        - 网络超时
        - 服务端错误（500, 502, 503, 504）
        """
        if not settings.llm_api_key:
            raise LLMCallError("OpenAI API Key 未配置")

        try:
            # 【智能重试】使用 RetryExecutor 执行调用
            return await self._retry_executor.execute(
                self._do_call,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens
            )
        except CircuitBreakerOpenError as e:
            # 【用户感知分级】熔断通知
            logger.error(f"[{self.provider_name}] Circuit breaker open: {e}")
            raise LLMCallError(
                "服务端暂时不稳定，系统正在冷却，请稍后再试..."
            ) from e
        except Exception as e:
            # 【用户感知分级】致命错误或重试耗尽
            logger.error(f"[{self.provider_name}] Call failed after retries: {e}")
            raise


class LLMProviderFactory:
    """
    LLM Provider 工厂

    根据配置创建对应的 Provider 实例
    """

    _providers: Dict[str, type] = {
        "modelscope": ModelScopeProvider,
        "openai": OpenAIProvider,
    }

    _instances: Dict[str, LLMProvider] = {}

    @classmethod
    def get_provider(cls, provider_type: Optional[str] = None) -> LLMProvider:
        """
        获取 Provider 实例（单例模式）

        Args:
            provider_type: Provider 类型，None 则根据配置自动选择

        Returns:
            LLMProvider: Provider 实例
        """
        if provider_type is None:
            # 安全访问配置，避免属性错误
            use_modelscope = getattr(settings, 'USE_MODELSCOPE', True)
            provider_type = "modelscope" if use_modelscope else "openai"

        provider_type = provider_type.lower()

        if provider_type not in cls._instances:
            provider_class = cls._providers.get(provider_type)
            if not provider_class:
                raise LLMCallError(f"未知的 Provider 类型: {provider_type}")
            cls._instances[provider_type] = provider_class()

        return cls._instances[provider_type]

    @classmethod
    def register_provider(cls, name: str, provider_class: type) -> None:
        """
        注册自定义 Provider

        Args:
            name: Provider 名称
            provider_class: Provider 类（必须继承 LLMProvider）
        """
        if not issubclass(provider_class, LLMProvider):
            raise ValueError(f"Provider 类必须继承 LLMProvider: {provider_class}")
        cls._providers[name.lower()] = provider_class
        # 清除已缓存的实例
        cls._instances.pop(name.lower(), None)

    @classmethod
    def clear_cache(cls) -> None:
        """清除 Provider 实例缓存（用于测试）"""
        cls._instances.clear()


# 便捷函数
def get_llm_provider() -> LLMProvider:
    """
    获取当前配置的 LLM Provider

    Returns:
        LLMProvider: Provider 实例
    """
    return LLMProviderFactory.get_provider()


def get_llm_provider_info() -> Dict[str, str]:
    """
    获取当前 LLM 供应商信息

    Returns:
        Dict: 供应商信息
    """
    provider = get_llm_provider()
    return {
        "provider": provider.provider_name,
        "model": provider.model_name,
        "api_base": settings.llm_api_base
    }
