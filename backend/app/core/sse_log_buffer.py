"""
SSE Real-time Log Push - Memory Buffer Management
Solves circular import issues, independent module

Enhanced version with:
- Backend system metrics logging
- Complete error stack traces
- Performance monitoring
- Resource usage tracking
"""

import asyncio
import json
import time
import traceback
import psutil
from datetime import datetime
from typing import Dict, Optional, Tuple, Any, List
from dataclasses import dataclass, asdict

# Global buffer dictionary, key = pipeline_id
_log_buffers: Dict[int, asyncio.Queue] = {}

# Record buffer creation time for TTL cleanup
_buffer_creation_time: Dict[int, float] = {}

# Configuration constants
MAX_BUFFER_SIZE = 500  # Maximum queue capacity (increased from 200)
BUFFER_TTL_SECONDS = 3600  # 1 hour TTL to prevent memory leaks


@dataclass
class LogEntry:
    """Structured log entry"""
    ts: str
    level: str
    msg: str
    stage: str
    source: str = "backend"  # "frontend" | "backend" | "system"
    extra: Dict[str, Any] = None
    
    def to_dict(self) -> Dict:
        result = {
            "ts": self.ts,
            "level": self.level,
            "msg": self.msg,
            "stage": self.stage,
            "source": self.source,
        }
        if self.extra:
            result.update(self.extra)
        return result


def get_or_create_buffer(pipeline_id: int) -> asyncio.Queue:
    """Get or create pipeline log buffer"""
    _cleanup_expired_buffers()
    
    if pipeline_id not in _log_buffers:
        _log_buffers[pipeline_id] = asyncio.Queue(maxsize=MAX_BUFFER_SIZE)
        _buffer_creation_time[pipeline_id] = time.time()
    return _log_buffers[pipeline_id]


def remove_buffer(pipeline_id: int) -> None:
    """Remove pipeline log buffer"""
    _log_buffers.pop(pipeline_id, None)
    _buffer_creation_time.pop(pipeline_id, None)


def _cleanup_expired_buffers():
    """Clean up expired buffers to prevent memory leaks"""
    current_time = time.time()
    expired_ids = [
        pid for pid, created_at in _buffer_creation_time.items()
        if current_time - created_at > BUFFER_TTL_SECONDS
    ]
    for pid in expired_ids:
        _log_buffers.pop(pid, None)
        _buffer_creation_time.pop(pid, None)
        print(f"[SSE Log Buffer] Cleaned expired buffer: pipeline_id={pid}")


async def push_log(pipeline_id: int, level: str, msg: str, stage: str = "", **extra) -> None:
    """
    Push real-time log to buffer, called in Agent code
    
    Protection mechanisms:
    1. Auto-create buffer if not exists
    2. Drop oldest data if buffer is full
    3. Auto-cleanup if buffer expired
    """
    buf = get_or_create_buffer(pipeline_id)
    entry = LogEntry(
        ts=datetime.now().strftime("%H:%M:%S"),
        level=level,
        msg=msg,
        stage=stage,
        source=extra.pop("source", "backend"),
        extra=extra if extra else None
    )

    try:
        if buf.full():
            try:
                buf.get_nowait()  # Drop oldest data
            except asyncio.QueueEmpty:
                pass

        buf.put_nowait(json.dumps(entry.to_dict(), ensure_ascii=False))
    except asyncio.QueueFull:
        pass  # Drop if full, don't block Agent
    except Exception as e:
        print(f"[SSE Log Buffer] push_log error: {e}")


async def push_thought(pipeline_id: int, agent_name: str, content: str) -> None:
    """
    Push Agent reasoning logic (Chain of Thought)
    """
    await push_log(
        pipeline_id,
        level="thought",
        msg=content,
        stage=agent_name,
        is_thought=True
    )


async def push_system_log(pipeline_id: int, msg: str, level: str = "info") -> None:
    """
    Push system-level log (backend infrastructure)
    """
    await push_log(
        pipeline_id,
        level=level,
        msg=msg,
        stage="SYSTEM",
        source="system"
    )


async def push_performance_metrics(pipeline_id: int, operation: str, duration_ms: int, **extra) -> None:
    """
    Push performance metrics
    """
    metrics_str = f"{operation} completed in {duration_ms}ms"
    if extra:
        metrics_str += f" | {', '.join(f'{k}={v}' for k, v in extra.items())}"
    
    await push_log(
        pipeline_id,
        level="info",
        msg=metrics_str,
        stage="METRICS",
        source="system",
        duration_ms=duration_ms,
        **extra
    )


async def push_resource_usage(pipeline_id: int) -> None:
    """
    Push system resource usage (CPU, Memory, Disk)
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        await push_log(
            pipeline_id,
            level="info",
            msg=f"Resource Usage - CPU: {cpu_percent:.1f}% | Memory: {memory.percent:.1f}% | Disk: {disk.percent:.1f}%",
            stage="SYSTEM",
            source="system",
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            disk_percent=disk.percent,
            memory_available_mb=memory.available // (1024 * 1024),
        )
    except Exception as e:
        await push_log(
            pipeline_id,
            level="warning",
            msg=f"Failed to get resource usage: {str(e)}",
            stage="SYSTEM",
            source="system"
        )


async def push_error_details(pipeline_id: int, error: Exception, context: str = "") -> None:
    """
    Push detailed error information including full stack trace
    """
    error_type = type(error).__name__
    error_msg = str(error)
    stack_trace = traceback.format_exc()
    
    # Push main error message
    await push_log(
        pipeline_id,
        level="error",
        msg=f"ERROR [{error_type}]: {error_msg}" + (f" | Context: {context}" if context else ""),
        stage="ERROR",
        source="system",
        error_type=error_type,
        error_message=error_msg,
        context=context
    )
    
    # Push stack trace as separate log entries (split if too long)
    if stack_trace and stack_trace != "NoneType: None\n":
        lines = stack_trace.strip().split('\n')
        for i, line in enumerate(lines[:50]):  # Limit to 50 lines
            await push_log(
                pipeline_id,
                level="error",
                msg=f"  {line}",
                stage="STACK_TRACE",
                source="system",
                trace_line=i + 1
            )


async def push_stage_start(pipeline_id: int, stage_name: str, input_data: Dict = None) -> None:
    """
    Push stage start log with input summary
    """
    msg = f"Stage [{stage_name}] STARTED"
    if input_data:
        # Summarize input data keys
        keys = list(input_data.keys())[:5]  # Limit to first 5 keys
        msg += f" | Input keys: {', '.join(keys)}"
        if len(input_data) > 5:
            msg += f" (+{len(input_data) - 5} more)"
    
    await push_log(
        pipeline_id,
        level="info",
        msg=msg,
        stage=stage_name,
        source="system"
    )
    
    # Also push resource usage at stage start
    await push_resource_usage(pipeline_id)


async def push_stage_complete(pipeline_id: int, stage_name: str, success: bool, output_summary: Dict = None, duration_ms: int = 0) -> None:
    """
    Push stage completion log
    """
    status = "COMPLETED" if success else "FAILED"
    msg = f"Stage [{stage_name}] {status}"
    if duration_ms > 0:
        msg += f" in {duration_ms}ms"
    if output_summary:
        keys = list(output_summary.keys())[:3]
        msg += f" | Output: {', '.join(keys)}"
    
    await push_log(
        pipeline_id,
        level="success" if success else "error",
        msg=msg,
        stage=stage_name,
        source="system",
        duration_ms=duration_ms,
        success=success
    )


async def push_llm_call(pipeline_id: int, agent_name: str, prompt_length: int, response_length: int = 0, 
                        input_tokens: int = 0, output_tokens: int = 0, duration_ms: int = 0, error: str = None) -> None:
    """
    Push LLM call metrics
    """
    if error:
        await push_log(
            pipeline_id,
            level="error",
            msg=f"LLM Call [{agent_name}] FAILED: {error}",
            stage=agent_name,
            source="system",
            prompt_length=prompt_length,
            error=error
        )
    else:
        msg = f"LLM Call [{agent_name}] OK"
        if duration_ms > 0:
            msg += f" | Time: {duration_ms}ms"
        if input_tokens > 0 or output_tokens > 0:
            msg += f" | Tokens: {input_tokens} in / {output_tokens} out"
        if response_length > 0:
            msg += f" | Response: {response_length} chars"
            
        await push_log(
            pipeline_id,
            level="info",
            msg=msg,
            stage=agent_name,
            source="system",
            prompt_length=prompt_length,
            response_length=response_length,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms
        )


def get_buffer_stats(pipeline_id: int) -> Optional[Dict]:
    """Get buffer statistics (for debugging)"""
    if pipeline_id not in _log_buffers:
        return None
    
    buf = _log_buffers[pipeline_id]
    created_at = _buffer_creation_time.get(pipeline_id, 0)
    
    return {
        "pipeline_id": pipeline_id,
        "size": buf.qsize(),
        "maxsize": buf.maxsize,
        "created_at": datetime.fromtimestamp(created_at).isoformat() if created_at else None,
        "ttl_seconds": BUFFER_TTL_SECONDS,
    }


def get_all_buffer_stats() -> Dict[int, Dict]:
    """Get all buffer statistics"""
    return {
        pid: get_buffer_stats(pid)
        for pid in _log_buffers.keys()
    }
