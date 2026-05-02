"""
EventBus / NotificationService

职责：
- 统一事件分发
- 分离"记录后端日志"和"推送前端 SSE"两个动作
- 支持多种通知渠道（SSE、Webhook 等）

设计原则：
- 日志模块只负责纯粹的日志记录
- EventBus 负责消息分发到各个消费者
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from datetime import datetime

import structlog

from app.core.sse_log_buffer import push_log as _push_log_to_buffer


@dataclass
class LogEvent:
    """日志事件"""
    pipeline_id: int
    level: str
    message: str
    stage: str = ""
    timestamp: datetime = None
    extra: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.extra is None:
            self.extra = {}


class EventHandler(ABC):
    """事件处理器接口"""

    @abstractmethod
    async def handle(self, event: LogEvent) -> None:
        """处理事件"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称"""
        pass


class SSEPushHandler(EventHandler):
    """
    SSE 推送处理器

    将日志推送到前端 SSE 缓冲区
    """

    @property
    def name(self) -> str:
        return "sse_push"

    async def handle(self, event: LogEvent) -> None:
        """推送日志到 SSE buffer"""
        try:
            # 如果有异常，把异常简述发给前端，但不需要把整个长篇堆栈发给前端
            frontend_msg = event.message
            if event.extra.get("exc_info"):
                frontend_msg = f"{event.message} (查看后端日志获取详情)"

            await _push_log_to_buffer(
                event.pipeline_id,
                event.level,
                frontend_msg,
                stage=event.stage,
                **event.extra
            )
        except Exception as e:
            # 推送失败不应影响主流程
            print(f"[EventBus] SSE push failed: {e}")


class StructlogHandler(EventHandler):
    """
    Structlog 日志处理器

    记录后端结构化日志
    """

    def __init__(self):
        self._logger = structlog.get_logger()

    @property
    def name(self) -> str:
        return "structlog"

    async def handle(self, event: LogEvent) -> None:
        """记录结构化日志"""
        try:
            log_func = getattr(
                self._logger,
                event.level if event.level in ['info', 'debug', 'warning', 'error'] else 'info'
            )

            # 确保在上下文中携带 pipeline_id 和 stage
            with structlog.contextvars.bound_contextvars(
                pipeline_id=event.pipeline_id,
                stage=event.stage
            ):
                log_func(event.message, **event.extra)
        except Exception as e:
            # 日志记录失败不应影响主流程
            print(f"[EventBus] Structlog failed: {e}")


class EventBus:
    """
    事件总线

    负责分发事件到所有注册的处理器
    """

    def __init__(self):
        self._handlers: Dict[str, EventHandler] = {}
        self._lock = asyncio.Lock()

    def register(self, handler: EventHandler) -> None:
        """注册事件处理器"""
        self._handlers[handler.name] = handler

    def unregister(self, name: str) -> None:
        """注销事件处理器"""
        self._handlers.pop(name, None)

    async def emit(self, event: LogEvent) -> None:
        """
        发射事件到所有处理器

        Args:
            event: 日志事件
        """
        # 并发执行所有处理器
        tasks = [
            self._safe_handle(handler, event)
            for handler in self._handlers.values()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(self, handler: EventHandler, event: LogEvent) -> None:
        """安全地执行处理器（捕获异常）"""
        try:
            await handler.handle(event)
        except Exception as e:
            print(f"[EventBus] Handler {handler.name} failed: {e}")

    def get_registered_handlers(self) -> List[str]:
        """获取所有已注册的处理器名称"""
        return list(self._handlers.keys())


# 全局 EventBus 实例
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 实例（单例）"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        # 默认注册 SSE 和 Structlog 处理器
        _event_bus.register(SSEPushHandler())
        _event_bus.register(StructlogHandler())
    return _event_bus


def reset_event_bus() -> None:
    """重置 EventBus（用于测试）"""
    global _event_bus
    _event_bus = None


# =============================================================================
# 便捷的日志发射函数
# =============================================================================

async def emit_log(
    pipeline_id: int,
    level: str,
    msg: str,
    stage: str = "",
    exc_info: bool = False,
    **kwargs
) -> None:
    """
    统一日志出口：分发到所有注册的处理器

    使用示例：
        await emit_log(pipeline_id, "info", "代码生成完成", stage="CODING", files_count=5)
    """
    event = LogEvent(
        pipeline_id=pipeline_id,
        level=level,
        message=msg,
        stage=stage,
        extra={"exc_info": exc_info, **kwargs}
    )
    await get_event_bus().emit(event)


async def emit_info(pipeline_id: int, msg: str, stage: str = "", **kwargs) -> None:
    """发射 INFO 级别日志"""
    await emit_log(pipeline_id, "info", msg, stage=stage, **kwargs)


async def emit_debug(pipeline_id: int, msg: str, stage: str = "", **kwargs) -> None:
    """发射 DEBUG 级别日志"""
    await emit_log(pipeline_id, "debug", msg, stage=stage, **kwargs)


async def emit_warning(pipeline_id: int, msg: str, stage: str = "", **kwargs) -> None:
    """发射 WARNING 级别日志"""
    await emit_log(pipeline_id, "warning", msg, stage=stage, **kwargs)


async def emit_error(pipeline_id: int, msg: str, stage: str = "", exc_info: bool = False, **kwargs) -> None:
    """发射 ERROR 级别日志"""
    await emit_log(pipeline_id, "error", msg, stage=stage, exc_info=exc_info, **kwargs)


async def emit_thought(pipeline_id: int, agent_name: str, content: str, **kwargs) -> None:
    """
    发射 Agent 推理日志

    Args:
        pipeline_id: Pipeline ID
        agent_name: Agent 名称
        content: 推理内容
    """
    await emit_log(
        pipeline_id,
        level="thought",
        msg=content,
        stage=agent_name,
        is_thought=True,
        **kwargs
    )
