"""
弹性 resilience 组件

提供统一的重试策略、错误分类和熔断保护机制。

核心功能：
1. 错误分类：将错误分为 TRANSIENT、RECOVERABLE、FATAL 三类
2. 智能重试：指数退避 + 随机抖动
3. 熔断保护：防止级联故障
4. 用户感知分级：静默处理、熔断通知、致命错误
"""

import asyncio
import random
import logging
import time
from typing import Callable, Any, Optional, TypeVar, Generic, Dict
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorCategory(Enum):
    """错误分类"""
    TRANSIENT = "transient"      # 瞬时错误，可无感重试（网络抖动）
    RECOVERABLE = "recoverable"  # 需要一定时间恢复，可延迟重试（服务过载）
    FATAL = "fatal"              # 不可重试（API Key 失效、参数错误）


class CircuitBreakerState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态，允许请求
    OPEN = "open"          # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，允许一次试探请求


class ResilienceError(Exception):
    """弹性组件基础异常"""
    pass


class CircuitBreakerOpenError(ResilienceError):
    """熔断器打开异常"""
    pass


class RetryExhaustedError(ResilienceError):
    """重试次数耗尽异常"""
    pass


def classify_api_error(error: Exception) -> ErrorCategory:
    """
    解析各类异常，判定其可重试级别

    分类逻辑：
    - TRANSIENT: 网络层瞬时错误，立即重试
    - RECOVERABLE: 服务端错误，延迟重试
    - FATAL: 客户端错误或配置错误，不重试
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # 1. 检查 LLM 提供商的空响应或瞬态错误
    if any(kw in error_str for kw in ['empty choices', 'empty response', 'no choices']):
        return ErrorCategory.RECOVERABLE

    # 2. 检查超时错误
    if any(kw in error_str for kw in ['timed out', 'timeout', 'time out']):
        return ErrorCategory.TRANSIENT

    # 3. 检查连接错误
    if any(kw in error_str for kw in ['connection', 'connect', 'network']):
        return ErrorCategory.TRANSIENT

    # 4. 检查 HTTP 状态码
    if hasattr(error, 'status'):
        status = error.status
        # 服务端错误：可重试
        if status in [429, 500, 502, 503, 504]:
            return ErrorCategory.RECOVERABLE
        # 客户端错误（除限流外）：不可重试
        if 400 <= status < 500 and status != 429:
            return ErrorCategory.FATAL

    # 5. 检查特定异常类型
    if isinstance(error, (ConnectionError, TimeoutError)):
        return ErrorCategory.TRANSIENT

    if isinstance(error, (PermissionError, ValueError, TypeError)):
        return ErrorCategory.FATAL

    # 6. 检查 API Key 相关错误
    if any(kw in error_str for kw in ['api key', 'authentication', 'unauthorized', 'forbidden']):
        return ErrorCategory.FATAL

    # 7. 检查余额/配额相关错误
    if any(kw in error_str for kw in ['quota', 'balance', 'insufficient', 'limit exceeded']):
        return ErrorCategory.FATAL

    # 8. 检查模型相关错误
    if any(kw in error_str for kw in ['model not found', 'invalid model']):
        return ErrorCategory.FATAL

    # 默认视为可恢复错误（保守策略）
    logger.warning(f"Unknown error type '{error_type}', classified as RECOVERABLE: {error}")
    return ErrorCategory.RECOVERABLE


class RetryExecutor:
    """
    智能重试执行器

    特性：
    - 指数退避 + 随机抖动
    - 错误分类（TRANSIENT/RECOVERABLE/FATAL）
    - 熔断器保护
    - 用户感知分级（静默/通知/终止）

    使用示例：
        executor = RetryExecutor(max_retries=3, base_delay=1.0)
        result = await executor.execute(my_async_function, arg1, arg2)
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset: float = 60.0,
        name: str = "default"
    ):
        """
        初始化重试执行器

        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
            circuit_breaker_threshold: 熔断阈值（连续失败次数）
            circuit_breaker_reset: 熔断重置时间（秒）
            name: 执行器名称（用于日志）
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_reset = circuit_breaker_reset
        self.name = name

        # 熔断器状态
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._circuit_state = CircuitBreakerState.CLOSED

        # 统计
        self._success_count = 0
        self._retry_count = 0

    @property
    def circuit_state(self) -> CircuitBreakerState:
        """获取熔断器状态"""
        if self._circuit_state == CircuitBreakerState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.circuit_breaker_reset:
                self._circuit_state = CircuitBreakerState.HALF_OPEN
                logger.info(f"[{self.name}] Circuit breaker entering HALF_OPEN state")
        return self._circuit_state

    def _is_circuit_open(self) -> bool:
        """检查熔断器是否打开"""
        return self.circuit_state == CircuitBreakerState.OPEN

    def _record_success(self):
        """记录成功"""
        self._success_count += 1
        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            # 半开状态下成功，关闭熔断器
            self._circuit_state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            logger.info(f"[{self.name}] Circuit breaker CLOSED after successful retry")
        elif self._failure_count > 0:
            # 正常状态下成功，减少失败计数
            self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self):
        """记录失败"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.circuit_breaker_threshold:
            if self._circuit_state != CircuitBreakerState.OPEN:
                self._circuit_state = CircuitBreakerState.OPEN
                logger.warning(
                    f"[{self.name}] Circuit breaker OPENED after {self._failure_count} failures"
                )

    def _calculate_delay(self, attempt: int, category: ErrorCategory) -> float:
        """
        计算重试延迟

        策略：
        - TRANSIENT: 立即重试或短延迟（0.1-0.5s）
        - RECOVERABLE: 指数退避 + 抖动
        """
        if category == ErrorCategory.TRANSIENT:
            # 瞬时错误：短延迟
            return random.uniform(0.1, 0.5)

        # 可恢复错误：指数退避
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        jitter = random.uniform(0, delay * 0.1)  # 10% 抖动
        return delay + jitter

    async def execute(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs
    ) -> Any:
        """
        执行函数，自动重试可恢复错误，熔断后直接拒绝

        Args:
            func: 要执行的异步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果

        Raises:
            CircuitBreakerOpenError: 熔断器打开
            RetryExhaustedError: 重试次数耗尽
            Exception: 致命错误
        """
        # 检查熔断器
        if self._is_circuit_open():
            logger.error(f"[{self.name}] Circuit breaker is OPEN, refusing to execute")
            raise CircuitBreakerOpenError(
                f"Service temporarily unavailable. Please try again in {self.circuit_breaker_reset}s"
            )

        attempt = 0
        last_error = None

        while attempt <= self.max_retries:
            try:
                # 执行函数
                result = await func(*args, **kwargs)

                # 记录成功
                self._record_success()

                # 如果有重试，记录成功恢复
                if attempt > 0:
                    logger.info(
                        f"[{self.name}] Function succeeded after {attempt} retries"
                    )

                return result

            except Exception as e:
                last_error = e
                category = classify_api_error(e)

                # 致命错误：立即抛出
                if category == ErrorCategory.FATAL:
                    logger.error(f"[{self.name}] Fatal error, no retry: {e}")
                    raise

                # 记录失败
                self._record_failure()

                attempt += 1

                # 超过最大重试次数
                if attempt > self.max_retries:
                    logger.error(
                        f"[{self.name}] Retry limit ({self.max_retries}) reached: {e}"
                    )
                    raise RetryExhaustedError(
                        f"Operation failed after {self.max_retries} retries: {e}"
                    ) from e

                # 计算延迟
                delay = self._calculate_delay(attempt, category)

                # 【用户感知分级】静默处理：只记录日志，不向用户推送
                logger.info(
                    f"[{self.name}] Retry {attempt}/{self.max_retries} after {delay:.2f}s "
                    f"due to {category.name} error: {e}"
                )

                self._retry_count += 1

                # 延迟后重试
                await asyncio.sleep(delay)

        # 不应该到达这里
        raise RetryExhaustedError(f"Unexpected exit from retry loop: {last_error}")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "name": self.name,
            "success_count": self._success_count,
            "retry_count": self._retry_count,
            "failure_count": self._failure_count,
            "circuit_state": self._circuit_state.value,
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
        }


class ResilienceManager:
    """
    弹性管理器

    管理多个 RetryExecutor 实例，提供统一的弹性能力
    """

    _executors: Dict[str, RetryExecutor] = {}

    @classmethod
    def get_executor(
        cls,
        name: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        **kwargs
    ) -> RetryExecutor:
        """
        获取或创建 RetryExecutor

        Args:
            name: 执行器名称
            max_retries: 最大重试次数
            base_delay: 基础延迟
            **kwargs: 其他参数

        Returns:
            RetryExecutor 实例
        """
        if name not in cls._executors:
            cls._executors[name] = RetryExecutor(
                name=name,
                max_retries=max_retries,
                base_delay=base_delay,
                **kwargs
            )
        return cls._executors[name]

    @classmethod
    def get_stats(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有执行器的统计信息"""
        return {
            name: executor.get_stats()
            for name, executor in cls._executors.items()
        }

    @classmethod
    def reset(cls, name: Optional[str] = None):
        """重置执行器状态"""
        if name:
            if name in cls._executors:
                del cls._executors[name]
        else:
            cls._executors.clear()


# 便捷装饰器
def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    name: Optional[str] = None
):
    """
    重试装饰器

    使用示例：
        @with_retry(max_retries=3, base_delay=1.0)
        async def my_async_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        executor_name = name or func.__name__
        executor = ResilienceManager.get_executor(
            name=executor_name,
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay
        )

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await executor.execute(func, *args, **kwargs)

        return wrapper
    return decorator


# 预定义的常用配置
class RetryConfig:
    """常用重试配置"""

    # LLM 调用配置：对延迟敏感，快速重试
    LLM_FAST = {
        "max_retries": 3,
        "base_delay": 0.5,
        "max_delay": 10.0,
        "circuit_breaker_threshold": 10,
    }

    # LLM 调用配置：容忍延迟，稳健重试
    LLM_ROBUST = {
        "max_retries": 5,
        "base_delay": 1.0,
        "max_delay": 30.0,
        "circuit_breaker_threshold": 5,
    }

    # 外部 API 调用配置
    EXTERNAL_API = {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 20.0,
        "circuit_breaker_threshold": 5,
    }

    # 测试运行配置
    TEST_RUN = {
        "max_retries": 2,
        "base_delay": 2.0,
        "max_delay": 10.0,
        "circuit_breaker_threshold": 3,
    }

    # 数据库操作配置
    DATABASE = {
        "max_retries": 3,
        "base_delay": 0.5,
        "max_delay": 5.0,
        "circuit_breaker_threshold": 10,
    }
