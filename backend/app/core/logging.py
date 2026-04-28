"""
OmniFlowAI 企业级日志系统
提供结构化日志、请求追踪、性能监控、慢查询捕获等功能

日志级别规范（分级治理）：
- DEBUG: HTTP 请求出入参、数据库详细 SQL（仅开发环境）
- INFO:  状态流转（如 [REQUIREMENT -> DESIGN]）、Agent 成功结束、请求完成
- WARNING: 预期内的异常（如 AI 测试未通过触发 Auto-Fix）
- ERROR: 需要人类介入（API Key 欠费、数据库断开、三次 Auto-Fix 失败）
         必须附带 exc_info=True

默认级别: INFO（减少控制台噪音）
"""

import logging
import logging.config
import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from functools import wraps

import structlog
from structlog.types import EventDict

from app.core.config import settings

# =============================================================================
# ContextVars - 请求级 correlation_id
# =============================================================================

_request_id_var: ContextVar[str] = ContextVar('request_id', default='-')
_pipeline_id_var: ContextVar[Optional[int]] = ContextVar('pipeline_id', default=None)
_agent_var: ContextVar[Optional[str]] = ContextVar('agent', default=None)


def set_request_id(rid: str) -> None:
    """设置当前请求的 request_id"""
    _request_id_var.set(rid)


def set_pipeline_id(pid: Optional[int]) -> None:
    """设置当前 pipeline_id"""
    _pipeline_id_var.set(pid)


def set_agent(agent: Optional[str]) -> None:
    """设置当前 agent 名称"""
    _agent_var.set(agent)


def get_request_id() -> str:
    """获取当前 request_id"""
    return _request_id_var.get()


def get_pipeline_id() -> Optional[int]:
    """获取当前 pipeline_id"""
    return _pipeline_id_var.get()


def get_agent() -> Optional[str]:
    """获取当前 agent 名称"""
    return _agent_var.get()


def clear_context() -> None:
    """清除所有上下文变量"""
    _request_id_var.set('-')
    _pipeline_id_var.set(None)
    _agent_var.set(None)


# =============================================================================
# 标准库 logging 配置
# =============================================================================

def setup_logging():
    """
    配置标准库 logging，使用 dictConfig 精准屏蔽噪音
    核心：第三方库强制使用 INFO/WARNING，防止底层 DEBUG 追踪泄露
    """
    # 1. 使用 dictConfig 精准控制各 logger 级别
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                "format": "%(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "plain",
                "stream": sys.stdout,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
        "loggers": {
            # 核心：精准屏蔽这些"话痨"
            "sqlalchemy.engine": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "sqlalchemy.pool": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "sqlalchemy.dialects": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "litellm": {"level": "ERROR", "handlers": ["console"], "propagate": False},
            "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "watchfiles": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpx": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpcore": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "anthropic": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "openai": {"level": "INFO", "handlers": ["console"], "propagate": False},
        },
    })


# 初始化标准库 logging
setup_logging()


# =============================================================================
# Structlog Processors
# =============================================================================

def add_standard_fields(logger, method_name: str, event_dict: EventDict) -> EventDict:
    """添加标准化字段到每条日志"""
    from app.core.timezone import now_iso

    # 确保基本字段存在
    event_dict.setdefault('timestamp', now_iso())
    event_dict.setdefault('logger', logger.name if hasattr(logger, 'name') else 'app')

    # 从 ContextVars 读取并注入
    event_dict['request_id'] = _request_id_var.get()

    pipeline_id = _pipeline_id_var.get()
    if pipeline_id is not None:
        event_dict['pipeline_id'] = pipeline_id

    agent = _agent_var.get()
    if agent is not None:
        event_dict['agent'] = agent

    return event_dict


def setup_structlog():
    """配置 structlog - 启用 Rich 彩色渲染"""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
        add_standard_fields,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.DEBUG:
        # 开发环境：启用 Rich 彩色渲染
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.rich_traceback
            )
        )
    else:
        # 生产环境：JSON 输出
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


setup_structlog()

# 获取 structlog logger
logger = structlog.get_logger()


# =============================================================================
# 日志级别快捷方法（保持向后兼容）
# =============================================================================

def debug(msg: str, **kwargs):
    """DEBUG 级别日志"""
    logger.debug(msg, **kwargs)


def info(msg: str, **kwargs):
    """INFO 级别日志"""
    logger.info(msg, **kwargs)


def warning(msg: str, **kwargs):
    """WARNING 级别日志"""
    logger.warning(msg, **kwargs)


def error(msg: str, **kwargs):
    """ERROR 级别日志"""
    logger.error(msg, **kwargs)


def critical(msg: str, **kwargs):
    """CRITICAL 级别日志"""
    logger.critical(msg, **kwargs)


# =============================================================================
# 请求日志中间件（增强版）
# =============================================================================

class RequestLogMiddleware:
    """请求日志中间件 - 支持 correlation_id 和慢请求告警，屏蔽轮询噪音"""

    # 健康检查路径 - 只记录 DEBUG 级别
    HEALTH_PATHS = {'/api/v1/health', '/health', '/favicon.ico'}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = scope.get("state", {}).get("request_id", str(uuid.uuid4()))
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "")

        # 设置 ContextVar
        set_request_id(request_id)

        # 健康检查路径只记录 DEBUG
        is_health = path in self.HEALTH_PATHS
        if is_health:
            logger.debug(
                "health_check",
                method=method,
                path=path,
            )

        # 优化 1：检测 SSE 接口
        is_sse = "logs" in path

        # 优化 2：检测轮询请求
        is_polling = "status" in path or "stats" in path

        start_time = time.time()

        # 包装 send 以捕获响应状态
        status_code = 200

        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception:
            status_code = 500
            logger.error(
                "request_failed",
                method=method,
                path=path,
                exc_info=True,
            )
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            if not is_health:
                log_data = {
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                }

                if is_sse:
                    # SSE 永远不报 slow_error，除非状态码不是 200
                    if status_code == 200:
                        logger.debug("sse_closed", **log_data)
                    else:
                        logger.error("sse_failed", **log_data)
                elif is_polling and status_code == 200:
                    # 轮询请求平时不打印，除非出错或慢
                    if duration_ms >= 2000:
                        logger.error("polling_slow", slow=True, **log_data)
                    # 正常轮询不记录，减少噪音
                else:
                    # 正常的业务请求慢查询逻辑
                    if duration_ms >= 2000:
                        logger.error("request_completed", slow=True, **log_data)
                    elif duration_ms >= 500:
                        logger.warning("request_completed", slow=True, **log_data)
                    else:
                        logger.info("request_completed", **log_data)

            # 清除 ContextVar
            clear_context()


# =============================================================================
# SQLAlchemy 慢查询捕获
# =============================================================================

def setup_sqlalchemy_logging(engine):
    """设置 SQLAlchemy 慢查询监听"""
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        """监听 SQL 执行，捕获慢查询"""
        execution_time = context.execution_time if hasattr(context, 'execution_time') else 0

        if execution_time and execution_time > 0.1:  # 100ms
            # 简化 SQL 语句
            simplified = " ".join(statement.split())[:200]

            logger.warning(
                "slow_query",
                query=simplified,
                duration_ms=round(execution_time * 1000, 2),
                threshold_ms=100,
            )


# =============================================================================
# 业务操作日志
# =============================================================================

class OperationLogger:
    """业务操作日志记录器"""

    @staticmethod
    def log_pipeline_create(pipeline_id: int, description: str, **kwargs):
        """记录 Pipeline 创建"""
        set_pipeline_id(pipeline_id)
        logger.info(
            "pipeline_created",
            pipeline_id=pipeline_id,
            description=description[:100],
            **kwargs
        )
        set_pipeline_id(None)

    @staticmethod
    def log_pipeline_status_change(
        pipeline_id: int,
        old_status: str,
        new_status: str,
        stage: Optional[str] = None,
        **kwargs
    ):
        """记录 Pipeline 状态变更"""
        set_pipeline_id(pipeline_id)
        logger.info(
            "pipeline_status_changed",
            pipeline_id=pipeline_id,
            old_status=old_status,
            new_status=new_status,
            stage=stage,
            **kwargs
        )
        set_pipeline_id(None)

    @staticmethod
    def log_pipeline_approve(pipeline_id: int, stage: str, notes: Optional[str] = None, **kwargs):
        """记录 Pipeline 审批"""
        set_pipeline_id(pipeline_id)
        logger.info(
            "pipeline_approved",
            pipeline_id=pipeline_id,
            stage=stage,
            notes=notes,
            **kwargs
        )
        set_pipeline_id(None)

    @staticmethod
    def log_pipeline_reject(pipeline_id: int, stage: str, reason: str, **kwargs):
        """记录 Pipeline 驳回"""
        set_pipeline_id(pipeline_id)
        logger.info(
            "pipeline_rejected",
            pipeline_id=pipeline_id,
            stage=stage,
            reason=reason[:200],
            **kwargs
        )
        set_pipeline_id(None)

    @staticmethod
    def log_agent_complete(
        pipeline_id: int,
        agent_name: str,
        stage: str,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """记录 Agent 完成（包含入参信息）"""
        set_pipeline_id(pipeline_id)
        set_agent(agent_name)

        log_func = logger.info if success else logger.error
        log_data = {
            "pipeline_id": pipeline_id,
            "agent": agent_name,
            "stage": stage,
            "success": success,
            "duration_ms": round(duration_ms, 2),
            "error": error,
            **kwargs
        }

        if input_data:
            log_data["input"] = input_data

        log_func("agent_completed", **log_data)

        set_agent(None)
        set_pipeline_id(None)

    @staticmethod
    def log_git_operation(
        operation: str,
        branch: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
        **kwargs
    ):
        """记录 Git 操作"""
        log_func = logger.info if success else logger.error
        log_func(
            f"git_{operation}",
            branch=branch,
            success=success,
            error=error,
            **kwargs
        )

    @staticmethod
    def log_pr_create(
        pipeline_id: int,
        pr_url: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
        **kwargs
    ):
        """记录 PR 创建"""
        set_pipeline_id(pipeline_id)
        log_func = logger.info if success else logger.error
        log_func(
            "pr_created",
            pipeline_id=pipeline_id,
            pr_url=pr_url,
            success=success,
            error=error,
            **kwargs
        )
        set_pipeline_id(None)


# 全局操作日志实例
op_logger = OperationLogger()


# =============================================================================
# 性能监控
# =============================================================================

@dataclass
class PerformanceMetrics:
    """性能指标"""
    operation: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(self):
        """完成记录"""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms else None,
            **self.metadata
        }


@contextmanager
def log_performance(operation: str, **metadata):
    """
    性能监控上下文管理器

    使用示例：
        with log_performance("database_query", table="pipelines"):
            result = await session.execute(query)
    """
    metrics = PerformanceMetrics(operation=operation, metadata=metadata)
    try:
        yield metrics
        metrics.finish()
        logger.info(
            "performance_metric",
            operation=operation,
            duration_ms=round(metrics.duration_ms, 2),
            **metadata
        )
    except Exception:
        metrics.finish()
        logger.error(
            "performance_metric_failed",
            operation=operation,
            duration_ms=round(metrics.duration_ms, 2),
            exc_info=True,
            **metadata
        )
        raise


def log_execution_time(func: Callable) -> Callable:
    """
    函数执行时间装饰器

    使用示例：
        @log_execution_time
        async def my_function():
            pass
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            logger.info(
                "function_executed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
            )
            return result
        except Exception:
            duration = (time.time() - start) * 1000
            logger.error(
                "function_failed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
                exc_info=True,
            )
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            logger.info(
                "function_executed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
            )
            return result
        except Exception:
            duration = (time.time() - start) * 1000
            logger.error(
                "function_failed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
                exc_info=True,
            )
            raise

    import asyncio
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


# =============================================================================
# 错误日志
# =============================================================================

def log_exception(
    exc: Exception,
    context: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
):
    """
    记录异常详细信息

    Args:
        exc: 异常对象
        context: 上下文信息
        request_id: 请求 ID
    """
    exc_type = type(exc).__name__
    exc_message = str(exc)
    exc_traceback = traceback.format_exc()

    log_data = {
        "exception_type": exc_type,
        "exception_message": exc_message,
        "traceback": exc_traceback,
    }

    if request_id:
        log_data["request_id"] = request_id

    if context:
        log_data["context"] = context

    logger.error("exception_occurred", **log_data)


# =============================================================================
# 数据库查询日志
# =============================================================================

class SQLQueryLogger:
    """SQL 查询日志记录器"""

    @staticmethod
    def log_query(
        query: str,
        parameters: Optional[tuple] = None,
        duration_ms: Optional[float] = None,
        rows_affected: Optional[int] = None,
        **kwargs
    ):
        """记录 SQL 查询"""
        # 简化查询语句（去除多余空白）
        simplified_query = " ".join(query.split())[:200]

        logger.debug(
            "sql_query_executed",
            query=simplified_query,
            parameters=parameters,
            duration_ms=round(duration_ms, 2) if duration_ms else None,
            rows_affected=rows_affected,
            **kwargs
        )


sql_logger = SQLQueryLogger()


# =============================================================================
# 保持向后兼容 - MetricsCollector
# =============================================================================

from typing import List


@dataclass
class AgentMetrics:
    """Agent 执行指标（兼容旧版）"""
    agent_name: str
    stage_name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    retry_count: int = 0
    success: bool = False
    error: Optional[str] = None

    def finish(self, success: bool = True, error: Optional[str] = None):
        """完成记录"""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        from app.core.timezone import now_iso
        return {
            "agent_name": self.agent_name,
            "stage_name": self.stage_name,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "retry_count": self.retry_count,
            "success": self.success,
            "error": self.error,
            "timestamp": now_iso()
        }


class MetricsCollector:
    """指标收集器（兼容旧版）"""

    def __init__(self):
        self.metrics: Dict[str, AgentMetrics] = {}

    def start_agent(
        self,
        agent_name: str,
        stage_name: str,
        pipeline_id: int
    ) -> AgentMetrics:
        """开始记录 Agent 执行"""
        key = f"{pipeline_id}:{stage_name}"
        metrics = AgentMetrics(
            agent_name=agent_name,
            stage_name=stage_name
        )
        self.metrics[key] = metrics

        return metrics

    def finish_agent(
        self,
        pipeline_id: int,
        stage_name: str,
        success: bool = True,
        error: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        retry_count: int = 0
    ) -> Optional[AgentMetrics]:
        """完成 Agent 执行记录"""
        key = f"{pipeline_id}:{stage_name}"
        metrics = self.metrics.get(key)

        if metrics:
            metrics.input_tokens = input_tokens
            metrics.output_tokens = output_tokens
            metrics.total_tokens = input_tokens + output_tokens
            metrics.retry_count = retry_count
            metrics.finish(success=success, error=error)

            op_logger.log_agent_complete(
                pipeline_id=pipeline_id,
                agent_name=metrics.agent_name,
                stage=stage_name,
                success=success,
                duration_ms=metrics.duration_ms or 0,
                error=error,
                total_tokens=metrics.total_tokens,
            )

        return metrics

    def get_metrics(self, pipeline_id: int, stage_name: str) -> Optional[AgentMetrics]:
        """获取指定阶段的指标"""
        key = f"{pipeline_id}:{stage_name}"
        return self.metrics.get(key)


# 全局指标收集器
metrics_collector = MetricsCollector()


@contextmanager
def agent_metrics_context(
    agent_name: str,
    stage_name: str,
    pipeline_id: int
):
    """
    Agent 指标记录上下文管理器（兼容旧版）
    """
    metrics = metrics_collector.start_agent(agent_name, stage_name, pipeline_id)
    try:
        yield metrics
        metrics_collector.finish_agent(
            pipeline_id=pipeline_id,
            stage_name=stage_name,
            success=True,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            retry_count=metrics.retry_count
        )
    except Exception:
        metrics_collector.finish_agent(
            pipeline_id=pipeline_id,
            stage_name=stage_name,
            success=False,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            retry_count=metrics.retry_count
        )
        raise


# =============================================================================
# 兼容旧版函数
# =============================================================================

def log_pipeline_event(
    pipeline_id: int,
    event: str,
    stage: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """记录 Pipeline 事件（兼容旧版）"""
    set_pipeline_id(pipeline_id)
    log_data = {
        "pipeline_id": pipeline_id,
        "event": event,
    }

    if stage:
        log_data["stage"] = stage

    if details:
        log_data.update(details)

    logger.info("pipeline_event", **log_data)
    set_pipeline_id(None)


def log_api_request(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float
):
    """记录 API 请求（兼容旧版）"""
    logger.info(
        "api_request",
        request_id=request_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=round(duration_ms, 2)
    )
