"""
Token 预算分配器

解决的问题：
  即使有了好工具，ArchitectAgent 的上下文窗口也是有限的。
  如果不加控制，project_card + 工具调用结果 + 注入文件内容
  很容易超过 100K token，导致截断或报错。

策略：
  核心文件（入口点）  30% 预算 → 全量摘要
  高相关文件（RAG命中） 50% 预算 → 签名 + 关键函数
  低优先文件          20% 预算 → 仅文件名 + 一行注释
"""

import ast
import logging
from typing import Dict, List, Any, Tuple

import tiktoken

logger = logging.getLogger(__name__)


# ============================================================
# tiktoken 精确 Token 估算
# ============================================================

def get_encoding(model_name: str = "gpt-4") -> tiktoken.Encoding:
    """根据模型名获取合适的 tiktoken 编码器，如果无法识别则回退到 cl100k_base"""
    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def estimate_tokens(text: str, model_name: str = "gpt-4") -> int:
    """向后兼容的模块级 token 估算函数"""
    encoding = get_encoding(model_name)
    return len(encoding.encode(text))


# ============================================================
# Token 预算分配器
# ============================================================

class TokenBudgetAllocator:
    """
    为 ArchitectAgent 的 build_user_prompt 分配上下文预算。

    保证 Prompt 中的代码上下文部分不超过 max_budget_tokens。
    """

    def __init__(
        self,
        max_budget_tokens: int = 12000,
        entry_ratio: float = 0.30,
        relevant_ratio: float = 0.50,
        model_name: str = "gpt-4",
        # low priority 隐含: 1 - entry_ratio - relevant_ratio
    ):
        self.max_budget_tokens = max_budget_tokens
        self.entry_budget = int(max_budget_tokens * entry_ratio)
        self.relevant_budget = int(max_budget_tokens * relevant_ratio)
        self.low_budget = max_budget_tokens - self.entry_budget - self.relevant_budget
        self.encoding = get_encoding(model_name)

    def estimate_tokens(self, text: str) -> int:
        """使用 tiktoken 精确计算 token 数"""
        return len(self.encoding.encode(text))

    def allocate(
        self,
        project_card: Dict[str, Any],
        injected_files: Dict[str, str],
        affected_files: List[str],
    ) -> str:
        """
        根据文件重要性分配 Token 预算，生成压缩后的上下文字符串。

        Args:
            project_card:   ProjectCardBuilder.build() 的解析结果
            injected_files: {file_path: content} 已读取的文件内容
            affected_files: ArchitectAgent 认为需要修改的文件列表

        Returns:
            str: 压缩后的上下文，格式化为 Markdown 供 Prompt 使用
        """
        entry_files = {e["file"] for e in project_card.get("entry_points", [])}
        affected_set = set(affected_files)

        # 分级
        tier_entry:    List[Tuple[str, str]] = []
        tier_relevant: List[Tuple[str, str]] = []
        tier_low:      List[str]             = []

        all_known_files = set(injected_files.keys()) | affected_set
        for f in sorted(all_known_files):
            content = injected_files.get(f, "")
            if f in entry_files:
                tier_entry.append((f, content))
            elif f in affected_set or content:
                tier_relevant.append((f, content))
            else:
                tier_low.append(f)

        # 未被注入的 affected_files 也放入 low tier
        for f in affected_set:
            if f not in injected_files and f not in {x for x, _ in tier_entry + tier_relevant}:
                tier_low.append(f)

        sections: List[str] = []

        # --- 核心文件（全量摘要）---
        if tier_entry:
            sections.append("### 核心文件（入口，高改动风险）")
            used = 0
            for fpath, content in tier_entry:
                if used >= self.entry_budget:
                    sections.append(f"- `{fpath}` （预算已用完，请用 read_chunk 按需读取）")
                    continue
                compressed = self._compress_to_budget(
                    fpath, content, self.entry_budget - used, mode="summary"
                )
                sections.append(compressed)
                used += self.estimate_tokens(compressed)

        # --- 高相关文件（签名 + 关键函数）---
        if tier_relevant:
            sections.append("\n### 相关文件（需要修改/参考）")
            used = 0
            for fpath, content in tier_relevant:
                if used >= self.relevant_budget:
                    sections.append(f"- `{fpath}` （预算已用完，请用 read_chunk 按需读取）")
                    continue
                compressed = self._compress_to_budget(
                    fpath, content, self.relevant_budget - used, mode="signatures"
                )
                sections.append(compressed)
                used += self.estimate_tokens(compressed)

        # --- 低优先级文件（仅文件名）---
        if tier_low:
            sections.append("\n### 其他相关文件（仅列出路径，需要时用 read_chunk 读取）")
            for fpath in tier_low[:20]:  # 最多列 20 个
                sections.append(f"- `{fpath}`")

        return "\n".join(sections)

    def _compress_to_budget(
        self,
        fpath: str,
        content: str,
        budget_tokens: int,
        mode: str = "summary",
    ) -> str:
        """
        将单个文件内容压缩到预算范围内。

        mode:
          "summary"    → imports + 顶层符号签名（不含实现）
          "signatures" → 只有顶层符号签名（更紧凑）
          "full"       → 全量（用于小文件）
        """
        if not content:
            return f"**`{fpath}`** — （内容未读取，用 `read_chunk(\"{fpath}\")` 获取摘要）"

        # 先试试能否放下全量
        if self.estimate_tokens(content) <= budget_tokens:
            lines_count = content.count("\n")
            return f"**`{fpath}`** （{lines_count} 行）\n```python\n{content}\n```"

        # 压缩为摘要
        compressed = self._extract_signatures(content, include_imports=(mode == "summary"))
        if self.estimate_tokens(compressed) <= budget_tokens:
            return f"**`{fpath}`** （摘要）\n```python\n{compressed}\n```"

        # 再压缩：只保留签名行（去掉 ... 展开）
        sig_only = "\n".join(
            line for line in compressed.splitlines()
            if not line.strip() == "..."
        )
        # 硬截断（最后的退路，但在 AST 模式下几乎不会到这里）
        if self.estimate_tokens(sig_only) > budget_tokens:
            max_chars = budget_tokens * 3
            sig_only = sig_only[:max_chars] + "\n# ... (预算截断)"

        return f"**`{fpath}`** （签名摘要）\n```python\n{sig_only}\n```"

    @staticmethod
    def _extract_signatures(code: str, include_imports: bool = True) -> str:
        """从代码中提取 import 区域和顶层符号签名"""
        try:
            import ast as _ast
            lines = code.splitlines()
            tree = _ast.parse(code)

            out: List[str] = []

            if include_imports:
                # 提取 import 行（去重）
                import_lines = []
                for node in _ast.walk(tree):
                    if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                        for ln in range(node.lineno - 1,
                                        min(getattr(node, "end_lineno", node.lineno), len(lines))):
                            import_lines.append(lines[ln])
                if import_lines:
                    out.extend(dict.fromkeys(import_lines))
                    out.append("")

            # 提取顶层符号签名
            for node in _ast.iter_child_nodes(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    start = node.lineno - 1
                    # 读到冒号所在行
                    for i in range(start, min(start + 8, len(lines))):
                        out.append(lines[i])
                        if ":" in lines[i] and not lines[i].strip().startswith("#"):
                            out.append("    ...")
                            break
                    out.append("")

            return "\n".join(out)
        except Exception:
            # 解析失败：按行截断（退化方案）
            return "\n".join(code.splitlines()[:40]) + "\n# ... (解析失败，截断到40行)"
