"""
Agent 调试工具模块

提供 Agent 输入输出保存功能，用于调试和分析
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid


class AgentDebugger:
    """
    Agent 调试器
    
    用于保存每个 Agent 的输入输出到 JSON 文件，便于调试和分析
    
    Usage:
        debugger = AgentDebugger(enabled=True, output_dir="./debug_output")
        
        # 保存 Agent 输入输出
        debugger.save_agent_io(
            agent_name="ArchitectAgent",
            stage="analyze",
            input_data={"requirement": "...", "file_tree": {...}},
            output_data={"success": True, "output": {...}},
            metadata={"duration_ms": 1500, "tokens": 2000}
        )
    """
    
    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "./agent_debug_output",
        session_id: Optional[str] = None
    ):
        """
        初始化调试器
        
        Args:
            enabled: 是否启用调试输出
            output_dir: 输出目录
            session_id: 会话 ID，用于区分不同的测试运行
        """
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.call_counter = 0
        
        if self.enabled:
            self._ensure_output_dir()
            self._save_session_info()
    
    def _ensure_output_dir(self):
        """确保输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        session_dir = self.output_dir / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
    
    def _save_session_info(self):
        """保存会话信息"""
        session_info = {
            "session_id": self.session_id,
            "start_time": datetime.now().isoformat(),
            "output_dir": str(self.output_dir / self.session_id)
        }
        
        info_file = self.output_dir / self.session_id / "_session_info.json"
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump(session_info, f, indent=2, ensure_ascii=False)
    
    def _serialize(self, obj: Any, max_depth: int = 10) -> Any:
        """
        序列化对象为 JSON 兼容格式
        
        处理 Pydantic 模型、Path、datetime 等类型
        """
        if max_depth <= 0:
            return str(obj)
        
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {k: self._serialize(v, max_depth - 1) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._serialize(item, max_depth - 1) for item in obj]
        elif hasattr(obj, "model_dump"):
            return self._serialize(obj.model_dump(), max_depth - 1)
        elif hasattr(obj, "to_dict"):
            return self._serialize(obj.to_dict(), max_depth - 1)
        elif hasattr(obj, "__dict__"):
            return self._serialize(obj.__dict__, max_depth - 1)
        elif isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        else:
            return str(obj)
    
    def _truncate_content(self, content: str, max_chars: int = 50000) -> str:
        """
        截断过长的内容
        
        Args:
            content: 原始内容
            max_chars: 最大字符数
            
        Returns:
            str: 截断后的内容
        """
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + f"\n... [已截断，原内容共 {len(content)} 字符]"
    
    def save_agent_io(
        self,
        agent_name: str,
        stage: str,
        input_data: Any,
        output_data: Any,
        metadata: Optional[Dict] = None,
        success: bool = True,
        error: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        system_prompt: Optional[str] = None
    ) -> Optional[str]:
        """
        保存 Agent 输入输出
        
        Args:
            agent_name: Agent 名称（如 ArchitectAgent, CoderAgent）
            stage: 阶段名称（如 analyze, design, generate_code）
            input_data: 输入数据
            output_data: 输出数据
            metadata: 元数据（如耗时、Token 数等）
            success: 是否成功
            error: 错误信息（如果有）
            tool_calls: 工具调用列表（包含工具名、参数、结果）
            system_prompt: Agent 的系统提示（包含 CONVENTIONS.md 等）
            
        Returns:
            str: 保存的文件路径，如果未启用则返回 None
        """
        if not self.enabled:
            return None
        
        self.call_counter += 1
        
        # 序列化并截断过长的内容
        serialized_input = self._serialize(input_data)
        serialized_output = self._serialize(output_data)
        
        # 截断 output_data 中的长字符串
        if isinstance(serialized_output, dict):
            serialized_output = self._truncate_dict_strings(serialized_output)
        
        # 截断 system_prompt（如果过长）
        truncated_system_prompt = None
        if system_prompt:
            truncated_system_prompt = self._truncate_content(system_prompt, max_chars=20000)
        
        record = {
            "seq": self.call_counter,
            "timestamp": datetime.now().isoformat(),
            "agent_name": agent_name,
            "stage": stage,
            "success": success,
            "error": error,
            "system_prompt": truncated_system_prompt,
            "input": serialized_input,
            "output": serialized_output,
            "tool_calls": self._serialize(tool_calls) if tool_calls else [],
            "metadata": metadata or {}
        }
        
        filename = f"{self.call_counter:03d}_{agent_name}_{stage}.json"
        filepath = self.output_dir / self.session_id / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    def _truncate_dict_strings(self, d: Any, max_chars: int = 50000) -> Any:
        """
        递归截断字典中的长字符串
        """
        if isinstance(d, dict):
            return {k: self._truncate_dict_strings(v, max_chars) for k, v in d.items()}
        elif isinstance(d, list):
            return [self._truncate_dict_strings(item, max_chars) for item in d]
        elif isinstance(d, str):
            return self._truncate_content(d, max_chars)
        else:
            return d
    
    def save_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_args: Dict,
        tool_result: Any,
        success: bool = True
    ) -> Optional[str]:
        """
        保存单个工具调用（可选，用于细粒度调试）
        
        Args:
            agent_name: Agent 名称
            tool_name: 工具名称
            tool_args: 工具参数
            tool_result: 工具返回结果
            success: 是否成功
            
        Returns:
            str: 保存的文件路径
        """
        if not self.enabled:
            return None
        
        tool_record = {
            "timestamp": datetime.now().isoformat(),
            "agent_name": agent_name,
            "tool_name": tool_name,
            "tool_args": self._serialize(tool_args),
            "tool_result": self._serialize(tool_result),
            "success": success
        }
        
        filename = f"tool_{self.call_counter:03d}_{tool_name}.json"
        filepath = self.output_dir / self.session_id / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(tool_record, f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    def save_summary(self) -> Optional[str]:
        """
        保存会话摘要
        
        Returns:
            str: 摘要文件路径
        """
        if not self.enabled:
            return None
        
        summary = {
            "session_id": self.session_id,
            "end_time": datetime.now().isoformat(),
            "total_calls": self.call_counter,
            "agents_called": []
        }
        
        session_dir = self.output_dir / self.session_id
        for f in session_dir.glob("*.json"):
            if f.name.startswith("_"):
                continue
            with open(f, "r", encoding="utf-8") as fp:
                record = json.load(fp)
                summary["agents_called"].append({
                    "seq": record.get("seq"),
                    "agent": record.get("agent_name"),
                    "stage": record.get("stage"),
                    "success": record.get("success"),
                    "tool_calls_count": len(record.get("tool_calls", []))
                })
        
        summary_file = session_dir / "_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        return str(summary_file)


def create_debugger_from_env() -> AgentDebugger:
    """
    从环境变量创建调试器
    
    环境变量:
        AGENT_DEBUG_ENABLED: 是否启用调试（默认 False）
        AGENT_DEBUG_OUTPUT_DIR: 输出目录（默认 ./agent_debug_output）
    """
    enabled = os.environ.get("AGENT_DEBUG_ENABLED", "false").lower() in ("true", "1", "yes")
    output_dir = os.environ.get("AGENT_DEBUG_OUTPUT_DIR", "./agent_debug_output")
    
    return AgentDebugger(enabled=enabled, output_dir=output_dir)
