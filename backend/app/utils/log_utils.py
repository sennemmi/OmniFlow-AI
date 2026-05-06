"""
Log utility functions

Provides unified logging and push functionality
Consistent with E2E test scripts and Pipeline
"""

import asyncio
import logging
import functools
import time
from typing import Any, Callable, Dict, List, Optional, Coroutine

from app.core.sse_log_buffer import (
    push_log, push_system_log, push_performance_metrics,
    push_resource_usage, push_error_details, push_stage_start,
    push_stage_complete, push_llm_call
)

logger = logging.getLogger(__name__)


class PipelineLogger:
    """
    Pipeline dedicated logger
    
    Wraps push_log calls, simplifies logging process
    """
    
    def __init__(self, pipeline_id: int, stage: str):
        self.pipeline_id = pipeline_id
        self.stage = stage
    
    async def info(self, message: str, **extra):
        """Log info level message"""
        await push_log(self.pipeline_id, "info", message, stage=self.stage, **extra)
    
    async def success(self, message: str, **extra):
        """Log success level message"""
        await push_log(self.pipeline_id, "success", message, stage=self.stage, **extra)
    
    async def warning(self, message: str, **extra):
        """Log warning level message"""
        await push_log(self.pipeline_id, "warning", message, stage=self.stage, **extra)
    
    async def error(self, message: str, **extra):
        """Log error level message"""
        await push_log(self.pipeline_id, "error", message, stage=self.stage, **extra)
    
    async def debug(self, message: str, **extra):
        """Log debug level message"""
        await push_log(self.pipeline_id, "debug", message, stage=self.stage, **extra)
    
    async def system(self, message: str, level: str = "info"):
        """Log system-level message"""
        await push_system_log(self.pipeline_id, message, level)
    
    async def metrics(self, operation: str, duration_ms: int, **extra):
        """Log performance metrics"""
        await push_performance_metrics(self.pipeline_id, operation, duration_ms, **extra)
    
    async def resource_usage(self):
        """Log system resource usage"""
        await push_resource_usage(self.pipeline_id)
    
    async def error_details(self, error: Exception, context: str = ""):
        """Log detailed error with stack trace"""
        await push_error_details(self.pipeline_id, error, context)
    
    async def stage_start(self, input_data: Dict = None):
        """Log stage start"""
        await push_stage_start(self.pipeline_id, self.stage, input_data)
    
    async def stage_complete(self, success: bool, output_summary: Dict = None, duration_ms: int = 0):
        """Log stage completion"""
        await push_stage_complete(self.pipeline_id, self.stage, success, output_summary, duration_ms)
    
    async def llm_call(self, agent_name: str, prompt_length: int, response_length: int = 0,
                       input_tokens: int = 0, output_tokens: int = 0, duration_ms: int = 0, error: str = None):
        """Log LLM call metrics"""
        await push_llm_call(self.pipeline_id, agent_name, prompt_length, response_length,
                           input_tokens, output_tokens, duration_ms, error)
    
    def create_callback(self, level: str = "info") -> Callable[[str], None]:
        """
        Create callback function for use in tool functions
        
        Args:
            level: Log level
            
        Returns:
            Callback function
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
    Create log callback function
    
    Args:
        pipeline_id: Pipeline ID
        stage: Stage name
        level: Log level
        
    Returns:
        Callback function
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
    Batch log messages
    
    Args:
        pipeline_id: Pipeline ID
        stage: Stage name
        messages: List of log messages, each containing "level" and "message" keys
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
    Log context manager
    
    Automatically log start and end logs in code blocks
    """
    
    def __init__(
        self,
        pipeline_id: int,
        stage: str,
        operation: str,
        log_start: bool = True,
        log_end: bool = True,
        log_metrics: bool = True
    ):
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.operation = operation
        self.log_start = log_start
        self.log_end = log_end
        self.log_metrics = log_metrics
        self.logger = PipelineLogger(pipeline_id, stage)
        self.start_time = None
    
    async def __aenter__(self):
        self.start_time = time.perf_counter()
        if self.log_start:
            await self.logger.info(f"Starting: {self.operation}")
            await self.logger.resource_usage()
        return self.logger
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.perf_counter() - self.start_time) * 1000) if self.start_time else 0
        
        if self.log_end:
            if exc_type:
                await self.logger.error(f"Failed: {self.operation} - {exc_val}")
                await self.logger.error_details(exc_val, context=self.operation)
            else:
                await self.logger.success(f"Completed: {self.operation}")
        
        if self.log_metrics and not exc_type:
            await self.logger.metrics(self.operation, duration_ms)


def log_execution_time(pipeline_id: int, stage: str, operation: str = None):
    """
    Decorator to log function execution time
    
    Args:
        pipeline_id: Pipeline ID
        stage: Stage name
        operation: Operation name (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            logger = PipelineLogger(pipeline_id, stage)
            start_time = time.perf_counter()
            
            try:
                await logger.info(f"Starting: {op_name}")
                result = await func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                await logger.success(f"Completed: {op_name} in {duration_ms}ms")
                await logger.metrics(op_name, duration_ms)
                return result
            except Exception as e:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                await logger.error(f"Failed: {op_name} after {duration_ms}ms - {str(e)}")
                await logger.error_details(e, context=op_name)
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            logger = PipelineLogger(pipeline_id, stage)
            start_time = time.perf_counter()
            
            try:
                asyncio.create_task(logger.info(f"Starting: {op_name}"))
                result = func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                asyncio.create_task(logger.success(f"Completed: {op_name} in {duration_ms}ms"))
                asyncio.create_task(logger.metrics(op_name, duration_ms))
                return result
            except Exception as e:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                asyncio.create_task(logger.error(f"Failed: {op_name} after {duration_ms}ms - {str(e)}"))
                asyncio.create_task(logger.error_details(e, context=op_name))
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator
