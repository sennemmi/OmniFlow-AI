"""
可观测性模块
记录 Token 消耗、耗时等指标
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime

import structlog

# 配置 structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@dataclass
class AgentMetrics:
    """Agent 执行指标"""
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
            "timestamp": datetime.utcnow().isoformat()
        }


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self.metrics: Dict[str, AgentMetrics] = {}
    
    def start_agent(
        self,
        agent_name: str,
        stage_name: str,
        pipeline_id: int
    ) -> AgentMetrics:
        """
        开始记录 Agent 执行
        
        Args:
            agent_name: Agent 名称
            stage_name: 阶段名称
            pipeline_id: Pipeline ID
            
        Returns:
            AgentMetrics: 指标对象
        """
        key = f"{pipeline_id}:{stage_name}"
        metrics = AgentMetrics(
            agent_name=agent_name,
            stage_name=stage_name
        )
        self.metrics[key] = metrics
        
        logger.info(
            "agent_started",
            agent=agent_name,
            stage=stage_name,
            pipeline_id=pipeline_id
        )
        
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
        """
        完成 Agent 执行记录
        
        Args:
            pipeline_id: Pipeline ID
            stage_name: 阶段名称
            success: 是否成功
            error: 错误信息
            input_tokens: 输入 Token 数
            output_tokens: 输出 Token 数
            retry_count: 重试次数
            
        Returns:
            AgentMetrics: 完成的指标对象
        """
        key = f"{pipeline_id}:{stage_name}"
        metrics = self.metrics.get(key)
        
        if metrics:
            metrics.input_tokens = input_tokens
            metrics.output_tokens = output_tokens
            metrics.total_tokens = input_tokens + output_tokens
            metrics.retry_count = retry_count
            metrics.finish(success=success, error=error)
            
            logger.info(
                "agent_finished",
                agent=metrics.agent_name,
                stage=stage_name,
                pipeline_id=pipeline_id,
                duration_ms=metrics.duration_ms,
                total_tokens=metrics.total_tokens,
                success=success
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
    Agent 指标记录上下文管理器
    
    使用示例：
        with agent_metrics_context("ArchitectAgent", "REQUIREMENT", 1) as metrics:
            # 执行 Agent
            result = await agent.analyze(...)
            # 设置 Token 数
            metrics.input_tokens = 100
            metrics.output_tokens = 200
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


def log_pipeline_event(
    pipeline_id: int,
    event: str,
    stage: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    记录 Pipeline 事件
    
    Args:
        pipeline_id: Pipeline ID
        event: 事件名称
        stage: 阶段名称
        details: 详细信息
    """
    log_data = {
        "pipeline_id": pipeline_id,
        "event": event,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if stage:
        log_data["stage"] = stage
    
    if details:
        log_data["details"] = details
    
    logger.info("pipeline_event", **log_data)


def log_api_request(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float
):
    """
    记录 API 请求
    
    Args:
        request_id: 请求 ID
        method: HTTP 方法
        path: 请求路径
        status_code: 状态码
        duration_ms: 耗时（毫秒）
    """
    logger.info(
        "api_request",
        request_id=request_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms
    )
