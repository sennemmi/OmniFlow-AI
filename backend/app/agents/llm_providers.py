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
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        调用 LLM

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大 Token 数
            response_format: 响应格式，如 {"type": "json_object"}

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


class OpenAICompatibleProvider(LLMProvider):
    """
    OpenAI 兼容 Provider 基类

    为所有使用 OpenAI 兼容接口的 Provider 提供通用实现。
    子类只需配置 provider_name、model、api_key、api_base 即可。
    """

    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str,
        api_base: str,
        retry_name: str,
        use_openai_prefix: bool = True,
        custom_llm_provider: Optional[str] = None
    ):
        """
        初始化 OpenAI 兼容 Provider

        Args:
            provider_name: Provider 显示名称
            model: 模型名称
            api_key: API 密钥
            api_base: API 基础 URL
            retry_name: 重试执行器名称
            use_openai_prefix: 是否在模型名前加 openai/ 前缀
            custom_llm_provider: 自定义 LLM Provider 标识
        """
        self._provider_name = provider_name
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._use_openai_prefix = use_openai_prefix
        self._custom_llm_provider = custom_llm_provider

        # 【智能重试】初始化重试执行器
        self._retry_executor = ResilienceManager.get_executor(
            name=retry_name,
            **RetryConfig.LLM_ROBUST
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    async def _do_call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """实际调用 API（使用 LiteLLM 路由）"""
        # 构建模型名称
        model = f"openai/{self._model}" if self._use_openai_prefix else self._model

        # 构建调用参数
        call_params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "api_key": self._api_key,
            "api_base": self._api_base,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # 如果指定了 custom_llm_provider，添加到参数中
        if self._custom_llm_provider:
            call_params["custom_llm_provider"] = self._custom_llm_provider

        # 如果指定了 response_format，添加到参数中
        if response_format:
            call_params["response_format"] = response_format
            logger.info(f"[{self.provider_name}] 使用结构化输出: {response_format}")

        response = await litellm.acompletion(**call_params)

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
                f"usage={usage_info}, model={self._model}"
            )
            # 返回一个可重试的错误信号
            raise LLMCallError(
                f"API 间歇性错误：LLM 返回空响应 (usage: {usage_info}). "
                f"这通常是 {self.provider_name} API 的临时问题，建议自动重试。"
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
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        调用 API（带智能重试）

        【智能重试】自动处理以下错误：
        - Empty choices（API 间歇性错误）
        - 网络超时
        - 服务端错误（500, 502, 503, 504）
        """
        if not self._api_key:
            raise LLMCallError(f"{self.provider_name} API Key 未配置")

        try:
            # 【智能重试】使用 RetryExecutor 执行调用
            return await self._retry_executor.execute(
                self._do_call,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                response_format
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


class ModelScopeProvider(OpenAICompatibleProvider):
    """
    ModelScope (魔搭) Provider

    使用 OpenAI 兼容接口，集成智能重试机制
    """

    def __init__(self):
        super().__init__(
            provider_name="ModelScope",
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            retry_name="modelscope_provider",
            use_openai_prefix=True
        )


class OpenAIProvider(OpenAICompatibleProvider):
    """
    OpenAI Provider

    使用 LiteLLM 异步接口，集成智能重试机制
    """

    def __init__(self):
        super().__init__(
            provider_name="OpenAI",
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            retry_name="openai_provider",
            use_openai_prefix=False,
            custom_llm_provider="openai"
        )


class MiMoProvider(OpenAICompatibleProvider):
    """
    MiMo (小米米墨) Provider

    使用 OpenAI 兼容接口，集成智能重试机制
    """

    def __init__(self):
        super().__init__(
            provider_name="MiMo",
            model=settings.MIMO_DEFAULT_MODEL,
            api_key=settings.MIMO_API_KEY,
            api_base=settings.MIMO_API_BASE,
            retry_name="mimo_provider",
            use_openai_prefix=True
        )


class LLMProviderFactory:
    """
    LLM Provider 工厂

    根据配置创建对应的 Provider 实例
    """

    _providers: Dict[str, type] = {
        "modelscope": ModelScopeProvider,
        "openai": OpenAIProvider,
        "mimo": MiMoProvider,
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
            # 使用 LLM_PROVIDER 配置
            provider_type = settings.LLM_PROVIDER.lower()

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


async def call_with_tools(
    model: str,
    messages: list,
    tools: list,
    api_key: str,
    api_base: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> Any:
    """
    专门用于工具调用的方法。
    使用 LiteLLM 路由 + 手动调用，支持工具调用功能。

    Args:
        model: 模型名称（应包含 openai/ 前缀）
        messages: 消息列表
        tools: 工具定义列表
        api_key: API 密钥
        api_base: API 基础 URL
        temperature: 温度参数
        max_tokens: 最大 Token 数

    Returns:
        LiteLLM 响应对象
    """
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        api_base=api_base,
    )

    return response
