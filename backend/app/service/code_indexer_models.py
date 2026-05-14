"""
Code indexer data models
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class CodeChunk:
    """代码块数据类"""
    file_path: str
    name: str
    content: str
    type: str  # "function", "class", "method"
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    signature: Optional[str] = None  # 函数/类签名

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_searchable_text(self) -> str:
        """获取用于向量检索的文本（包含名称、文档、签名）"""
        parts = [self.name, self.type]
        if self.docstring:
            parts.append(self.docstring)
        if self.signature:
            parts.append(self.signature)
        # 添加代码内容的前 500 字符作为上下文
        parts.append(self.content[:500])
        return "\n".join(parts)


@dataclass
class FileContext:
    """完整文件上下文数据类 - 新增"""
    file_path: str
    content: str
    file_type: str  # "python", "javascript", "typescript", "other"
    size_bytes: int
    last_modified: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_summary(self, max_lines: int = 50) -> str:
        """获取文件内容摘要（前 N 行）"""
        lines = self.content.splitlines()
        if len(lines) <= max_lines:
            return self.content
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} 行省略)"

