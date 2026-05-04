"""
日志工具函数

提供统一的日志记录和推送功能
与 E2E 测试脚本和 Pipeline 保持一致
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Coroutine

from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class PipelineLogger:
    """
    Pipeline 专用日志记录器
    
    封装 push_log 调用，简化日志记录流程
    """
    
    def __init__(self, pipeline_id: int, stage: str):
        self.pipeline_id = pipeline_id
        self.stage = stage
    
    async def info(self, message: str):
        """记录 info 级别日志"""
        await push_log(self.pipeline_id, "info", message, stage=self.stage)
    
    async def success(self, message: str):
        """记录 success 级别日志"""
        await push_log(self.pipeline_id, "success", message, stage=self.stage)
    
    async def warning(self, message: str):
        """记录 warning 级别日志"""
        await push_log(self.pipeline_id, "warning", message, stage=self.stage)
    
    async def error(self, message: str):
        """记录 error 级别日志"""
        await push_log(self.pipeline_id, "error", message, stage=self.stage)
    
    async def debug(self, message: str):
        """记录 debug 级别日志"""
        await push_log(self.pipeline_id, "debug", message, stage=self.stage)
    
    def create_callback(self, level: str = "info") -> Callable[[str], None]:
        """
        创建回调函数，用于工具函数中
        
        Args:
            level: 日志级别
            
        Returns:
            回调函数
        """
        async def callback(message: str):
            await push_log(self.pipeline_id, level, message, stage=self.stage)
        
        def sync_callback(message: str):
            asyncio.create_task(callback(message))
        
        return sync_callback


def create_log_callback(
    pipeline_id: int,
    stage: str,
    level: str = "info"
) -> Callable[[str], None]:
    """
    创建日志回调函数
    
    Args:
        pipeline_id: Pipeline ID
        stage: 阶段名称
        level: 日志级别
        
    Returns:
        回调函数
    """
    async def callback(message: str):
        await push_log(pipeline_id, level, message, stage=stage)
    
    def sync_callback(message: str):
        asyncio.create_task(callback(message))
    
    return sync_callback


async def log_batch(
    pipeline_id: int,
    stage: str,
    messages: List[Dict[str, str]]
):
    """
    批量记录日志
    
    Args:
        pipeline_id: Pipeline ID
        stage: 阶段名称
        messages: 日志消息列表，每个元素包含 "level" 和 "message" 键
    """
    for msg in messages:
        await push_log(
            pipeline_id,
            msg.get("level", "info"),
            msg["message"],
            stage=stage
        )


class LogContext:
    """
    日志上下文管理器
    
    用于在代码块中自动记录开始和结束日志
    """
    
    def __init__(
        self,
        pipeline_id: int,
        stage: str,
        operation: str,
        log_start: bool = True,
        log_end: bool = True
    ):
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.operation = operation
        self.log_start = log_start
        self.log_end = log_end
        self.logger = PipelineLogger(pipeline_id, stage)
    
    async def __aenter__(self):
        if self.log_start:
            await self.logger.info(f"开始: {self.operation}")
        return self.logger
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.log_end:
            if exc_type:
                await self.logger.error(f"失败: {self.operation} - {exc_val}")
            else:
                await self.logger.success(f"完成: {self.operation}")
