"""
OmniFlowAI 企业级日志系统
提供结构化日志、请求追踪、性能监控、慢查询捕获等功能
"""

import logging
import logging.handlers
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
    """配置标准库 logging，支持文件轮转和控制台输出"""
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    # 确保日志目录存在
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'app.log')

    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []

    # 1. 文件 Handler - JSON 格式（开发和生产都写入）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=10
    )
    file_handler.setLevel(level)

    # 文件使用简单的格式化器，structlog 会处理 JSON
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 2. 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # 控制台使用简单格式
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 屏蔽噪声日志
    _silence_noisy_loggers()


def _silence_noisy_loggers():
    """屏蔽第三方库的噪声日志"""
    sql_level = logging.DEBUG if settings.DEBUG else logging.WARNING

    # SQLAlchemy
    logging.getLogger("sqlalchemy.engine").setLevel(sql_level)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)

    # Uvicorn
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

    # HTTP clients
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # AI SDKs
    logging.getLogger("anthropic").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.INFO)


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


def format_for_rich(logger, method_name: str, event_dict: EventDict) -> EventDict:
    """为 Rich 控制台格式化日志"""
    if not settings.DEBUG:
        return event_dict

    # 提取关键字段
    timestamp = event_dict.pop('timestamp', '')
    level = event_dict.get('level', 'info').upper()
    logger_name = event_dict.get('logger', 'app')
    event = event_dict.pop('event', '')

    # 构建额外字段字符串
    extras = []
    for key, value in event_dict.items():
        if key not in ['level', 'logger', 'request_id', 'pipeline_id', 'agent', 'timestamp']:
            if isinstance(value, (dict, list)):
                extras.append(f"{key}={str(value)[:100]}")
            else:
                extras.append(f"{key}={value}")

    extra_str = " ".join(extras) if extras else ""

    # 构建消息
    if extra_str:
        event_dict['message'] = f"{event}  {extra_str}"
    else:
        event_dict['message'] = event

    return event_dict


def setup_structlog():
    """配置 structlog - 统一使用无颜色格式，避免Windows编码问题"""
    processors = [
        structlog.contextvars.merge_contextvars,  # 合并 ContextVars
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_standard_fields,  # 添加标准化字段
        structlog.stdlib.ExtraAdder(),
    ]

    if settings.DEBUG:
        # 开发环境：人类可读格式，但无颜色（避免Windows编码问题）
        processors.extend([
            format_for_rich,
            structlog.dev.ConsoleRenderer(
                colors=False,  # 禁用颜色，避免Windows编码问题
                pad_level=False,
                timestamp_key='timestamp',
            )
        ])
    else:
        # 生产环境：JSON 输出
        processors.extend([
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ])

    structlog.configure(
        processors=processors,
        context_class=dict,
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
    """请求日志中间件 - 支持 correlation_id 和慢请求告警"""

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

        query_string = scope.get("query_string", b"").decode()
        start_time = time.time()

        if not is_health:
            logger.info(
                "request_started",
                method=method,
                path=path,
                query=query_string,
                client=scope.get("client", ("unknown", 0))[0],
            )

        # 包装 send 以捕获响应状态
        status_code = 200

        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as e:
            status_code = 500
            logger.error(
                "request_failed",
                method=method,
                path=path,
                error=str(e),
                exc_info=True,
            )
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            if not is_health:
                # 慢请求分级告警
                log_data = {
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                }

                if duration_ms >= 2000:
                    # 极慢请求
                    log_data.update(slow=True, very_slow=True)
                    logger.error("request_completed", **log_data)
                elif duration_ms >= 500:
                    # 慢请求
                    log_data.update(slow=True)
                    logger.warning("request_completed", **log_data)
                elif duration_ms >= 200:
                    # 正常但可观察
                    log_data.update(slow=False)
                    logger.info("request_completed", **log_data)
                else:
                    # 正常请求
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
    def log_agent_start(pipeline_id: int, agent_name: str, stage: str, **kwargs):
        """记录 Agent 启动"""
        set_pipeline_id(pipeline_id)
        set_agent(agent_name)
        logger.info(
            "agent_started",
            pipeline_id=pipeline_id,
            agent=agent_name,
            stage=stage,
            **kwargs
        )

    @staticmethod
    def log_agent_complete(
        pipeline_id: int,
        agent_name: str,
        stage: str,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
        **kwargs
    ):
        """记录 Agent 完成"""
        set_pipeline_id(pipeline_id)
        set_agent(agent_name)

        log_func = logger.info if success else logger.error
        log_func(
            "agent_completed",
            pipeline_id=pipeline_id,
            agent=agent_name,
            stage=stage,
            success=success,
            duration_ms=round(duration_ms, 2),
            error=error,
            **kwargs
        )

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
    except Exception as e:
        metrics.finish()
        logger.error(
            "performance_metric_failed",
            operation=operation,
            duration_ms=round(metrics.duration_ms, 2),
            error=str(e),
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
        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(
                "function_failed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
                error=str(e),
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
        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(
                "function_failed",
                function=func.__name__,
                duration_ms=round(duration, 2),
                module=func.__module__,
                error=str(e),
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

        op_logger.log_agent_start(pipeline_id, agent_name, stage_name)

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
    except Exception as e:
        metrics_collector.finish_agent(
            pipeline_id=pipeline_id,
            stage_name=stage_name,
            success=False,
            error=str(e),
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
