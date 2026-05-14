"""
Agent 调试工具 (AgentDebugUtils)

统一 E2E 测试和 Pipeline 中的 Agent 调试记录。
提供全局 AgentDebugger 实例。
"""

import logging
import os
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentDebugger:
    """
    统一的 Agent 调试器

    职责：
    1. 记录 Agent 输入输出
    2. 记录 Agent 调用链
    3. 保存调试信息到文件
    4. 提供统一的日志格式

    使用场景：
    - E2E 测试脚本
    - Pipeline 各 StageHandler
    - 任何需要调试 Agent 的地方
    """

    def __init__(self, enabled: bool = True, output_dir: str = "./debug_output", session_id: Optional[str] = None):
        self.enabled = enabled
        # 确保 output_dir 是 Path 对象（兼容旧 E2E 测试脚本）
        self.output_dir = Path(output_dir)
        # 兼容旧 E2E 测试脚本，添加 session_id
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        self._call_chain: list = []

        # 创建带 session_id 的子目录
        self.session_output_dir = self.output_dir / self.session_id
        if enabled and not self.session_output_dir.exists():
            try:
                self.session_output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"Failed to create debug output directory: {e}")
                self.session_output_dir = Path(output_dir)

    def save_agent_io(
        self,
        agent_name: str,
        stage: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        success: bool = False,
        error: Optional[str] = None,
        tool_calls: Optional[list] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        保存 Agent 输入输出

        Args:
            agent_name: Agent 名称
            stage: 阶段名称
            input_data: 输入数据
            output_data: 输出数据
            metadata: 元数据（token 数、耗时等）
            success: 是否成功
            error: 错误信息
            tool_calls: 工具调用记录
            system_prompt: 系统提示词
        """
        if not self.enabled:
            return

        try:
            timestamp = datetime.now().isoformat()

            debug_entry = {
                "timestamp": timestamp,
                "agent_name": agent_name,
                "stage": stage,
                "success": success,
                "error": error,
                "input": input_data,
                "output": output_data,
                "metadata": metadata or {},
                "tool_calls": tool_calls or [],
                "system_prompt": system_prompt,
            }

            # 添加到调用链
            self._call_chain.append({
                "timestamp": timestamp,
                "agent_name": agent_name,
                "stage": stage,
                "success": success,
            })

            # 保存到文件（使用 session_output_dir）
            filename = f"{agent_name}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = self.session_output_dir / filename

            import json
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(debug_entry, f, ensure_ascii=False, indent=2, default=str)

            logger.debug(f"Saved agent debug info to {filepath}")

        except Exception as e:
            logger.warning(f"Failed to save agent debug info: {e}")

    def get_call_chain(self) -> list:
        """获取 Agent 调用链"""
        return self._call_chain.copy()

    def clear_call_chain(self) -> None:
        """清空调用链"""
        self._call_chain.clear()

    def log_summary(self) -> Dict[str, Any]:
        """
        生成调试摘要

        Returns:
            Dict: 调试摘要信息
        """
        if not self._call_chain:
            return {"total_calls": 0, "success_rate": 0}

        total = len(self._call_chain)
        successful = sum(1 for call in self._call_chain if call.get("success"))

        return {
            "total_calls": total,
            "successful_calls": successful,
            "failed_calls": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "call_chain": self._call_chain,
        }

    def save_summary(self) -> Optional[str]:
        """
        保存调试摘要到文件（兼容旧 E2E 测试脚本）

        Returns:
            Optional[str]: 摘要文件路径
        """
        if not self.enabled:
            return None

        try:
            summary = self.log_summary()
            summary["session_id"] = self.session_id
            summary["saved_at"] = datetime.now().isoformat()

            filename = f"summary_{self.session_id}.json"
            filepath = self.session_output_dir / filename

            import json
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to save summary: {e}")
            return None


# 全局单例实例（从环境变量读取配置）
_global_debugger: Optional[AgentDebugger] = None


def get_agent_debugger() -> AgentDebugger:
    """
    获取全局 AgentDebugger 实例

    Returns:
        AgentDebugger: 全局调试器实例
    """
    global _global_debugger

    if _global_debugger is None:
        enabled = getattr(settings, 'AGENT_DEBUG_ENABLED', True)
        output_dir = getattr(settings, 'AGENT_DEBUG_OUTPUT_DIR', './debug_output')
        _global_debugger = AgentDebugger(enabled=enabled, output_dir=output_dir)

    return _global_debugger


def reset_agent_debugger() -> None:
    """重置全局调试器实例"""
    global _global_debugger
    _global_debugger = None
