"""
Agent 输出处理工具函数

提供从 Agent 输出中提取文件列表、处理 CoderOutput 等功能
"""

from typing import Any, Dict, List, Optional

from app.agents.coder import CoderOutput


def extract_code_files(agent_output: Any) -> List[Dict]:
    """
    从 CoderAgent 输出中提取代码文件列表

    Args:
        agent_output: Agent 输出（CoderOutput 或 dict）

    Returns:
        代码文件列表
    """
    if isinstance(agent_output, CoderOutput):
        return [f.model_dump() for f in agent_output.files]
    elif isinstance(agent_output, dict):
        return agent_output.get("files", [])
    return []


def extract_test_files(agent_output: Any) -> List[Dict]:
    """
    从 TesterAgent 输出中提取测试文件列表

    Args:
        agent_output: Agent 输出（dict）

    Returns:
        测试文件列表
    """
    if isinstance(agent_output, dict):
        return agent_output.get("test_files", [])
    return []


def extract_key_mismatches(agent_output: Any) -> List[Dict]:
    """
    从 CoderAgent 输出中提取键名不匹配列表

    Args:
        agent_output: Agent 输出

    Returns:
        键名不匹配列表
    """
    if hasattr(agent_output, 'key_mismatches'):
        return agent_output.key_mismatches
    elif isinstance(agent_output, dict):
        return agent_output.get("key_mismatches", [])
    return []


def get_agent_output_dict(agent_output: Any) -> Dict:
    """
    将 Agent 输出转换为字典

    Args:
        agent_output: Agent 输出

    Returns:
        字典格式的输出
    """
    if isinstance(agent_output, CoderOutput):
        return agent_output.model_dump()
    elif isinstance(agent_output, dict):
        return agent_output
    return {}


def print_code_files_summary(code_files: List[Dict]) -> None:
    """
    打印代码文件摘要

    Args:
        code_files: 代码文件列表
    """
    if not code_files:
        print("   ⚠️ 未生成任何文件")
        return

    print(f"   📦 生成 {len(code_files)} 个文件变更:")
    for fc in code_files:
        fp = fc.get("file_path", "")
        change_type = fc.get("change_type", "")
        has_search = bool(fc.get("search_block", ""))
        has_content = bool(fc.get("content", ""))
        print(f"      - {fp} ({change_type}, search_block={has_search}, content={has_content})")


def merge_files_content(code_files: List[Dict], test_files: List[Dict]) -> List[Dict]:
    """
    合并代码文件和测试文件

    Args:
        code_files: 代码文件列表
        test_files: 测试文件列表

    Returns:
        合并后的文件列表
    """
    merged = []

    for f in code_files:
        merged.append({
            "file_path": f.get("file_path", ""),
            "content": f.get("content", ""),
            "change_type": f.get("change_type", "modify")
        })

    for tf in test_files:
        merged.append({
            "file_path": tf.get("file_path", ""),
            "content": tf.get("content", ""),
            "change_type": "add"
        })

    return merged
