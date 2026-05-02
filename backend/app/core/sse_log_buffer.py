"""
SSE 实时日志推送 - 内存 Buffer 管理
解决循环导入问题，独立模块
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

# 全局 buffer 字典，key = pipeline_id
_log_buffers: Dict[int, asyncio.Queue] = {}

# 记录 buffer 创建时间，用于 TTL 清理
_buffer_creation_time: Dict[int, float] = {}

# 配置常量
MAX_BUFFER_SIZE = 200  # 最大队列容量
BUFFER_TTL_SECONDS = 3600  # 1小时 TTL，防止内存泄漏


def get_or_create_buffer(pipeline_id: int) -> asyncio.Queue:
    """获取或创建 pipeline 的日志 buffer"""
    # 检查并清理过期的 buffer
    _cleanup_expired_buffers()
    
    if pipeline_id not in _log_buffers:
        _log_buffers[pipeline_id] = asyncio.Queue(maxsize=MAX_BUFFER_SIZE)
        _buffer_creation_time[pipeline_id] = time.time()
    return _log_buffers[pipeline_id]


def remove_buffer(pipeline_id: int) -> None:
    """移除 pipeline 的日志 buffer"""
    _log_buffers.pop(pipeline_id, None)
    _buffer_creation_time.pop(pipeline_id, None)


def _cleanup_expired_buffers():
    """清理过期的 buffer，防止内存泄漏"""
    current_time = time.time()
    expired_ids = [
        pid for pid, created_at in _buffer_creation_time.items()
        if current_time - created_at > BUFFER_TTL_SECONDS
    ]
    for pid in expired_ids:
        _log_buffers.pop(pid, None)
        _buffer_creation_time.pop(pid, None)
        print(f"[SSE Log Buffer] 清理过期 buffer: pipeline_id={pid}")


async def push_log(pipeline_id: int, level: str, msg: str, stage: str = "", **extra) -> None:
    """
    推送实时日志到 buffer，在 Agent 代码里调用此函数

    保护机制：
    1. 如果 buffer 不存在，自动创建
    2. 如果 buffer 已满，丢弃最旧的数据
    3. 如果 buffer 过期，自动清理
    """
    # 如果 buffer 不存在，检查是否需要创建
    if pipeline_id not in _log_buffers:
        # 只有在有活跃 SSE 连接时才创建 buffer
        # 这里简化处理：直接创建，但通过 TTL 自动清理
        pass

    buf = get_or_create_buffer(pipeline_id)
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "msg": msg,
        "stage": stage,
        **extra
    }

    try:
        # 如果队列已满，先丢弃最旧的数据
        if buf.full():
            try:
                buf.get_nowait()  # 丢弃最旧的数据
            except asyncio.QueueEmpty:
                pass

        buf.put_nowait(json.dumps(entry, ensure_ascii=False))
    except asyncio.QueueFull:
        pass  # 满了就丢弃，不阻塞 Agent
    except Exception as e:
        # 记录错误但不影响主流程
        print(f"[SSE Log Buffer] push_log error: {e}")


async def push_thought(pipeline_id: int, agent_name: str, content: str) -> None:
    """
    专门推送 Agent 的推理逻辑（Chain of Thought）

    Args:
        pipeline_id: Pipeline ID
        agent_name: Agent 名称
        content: 推理内容
    """
    await push_log(
        pipeline_id,
        level="thought",
        msg=content,
        stage=agent_name,
        is_thought=True
    )


def get_buffer_stats(pipeline_id: int) -> Optional[Dict]:
    """获取 buffer 统计信息（用于调试）"""
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
    """获取所有 buffer 的统计信息"""
    return {
        pid: get_buffer_stats(pid)
        for pid in _log_buffers.keys()
    }
