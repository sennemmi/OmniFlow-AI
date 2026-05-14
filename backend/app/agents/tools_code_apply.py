# app/agents/tools_code_apply.py

import difflib
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CodeApplyTool:
    """
    第一阶段核心工具: 结构化 search/replace 执行器

    与现有 search_replace_engine 的关键区别:
    - 不执行任何模糊匹配 — 只做精确匹配
    - 失败时返回结构化的错误信息(而非 None)
    - 错误信息包含: 为什么失败、哪里有相似内容、建议如何修正
    """

    @staticmethod
    def execute(
        file_path: str,
        search_block: str,
        replace_block: str,
        file_content: str
    ) -> str:
        """
        执行精确 search/replace,失败时返回结构化错误

        Returns:
            JSON 字符串:
            - 成功: {"success": true, "message": "替换成功"}
            - 失败: {"success": false, "error_type": "...", "error_detail": "...", "suggestion": "..."}
        """
        # 1. 精确匹配
        if search_block in file_content:
            # 唯一性检查(Claude Code 原则)
            occurrences = file_content.count(search_block)
            if occurrences > 1:
                # 找到所有出现位置,给出具体行号
                lines = file_content.splitlines()
                positions = []
                for i, line in enumerate(lines):
                    if search_block.splitlines()[0] in line:
                        positions.append(i + 1)
                return json.dumps({
                    "success": False,
                    "error_type": "non_unique_search_block",
                    "error_detail": f"search_block 在文件中出现了 {occurrences} 次,出现在行: {positions[:5]}",
                    "suggestion": "请增加更多上下文使 search_block 唯一,或使用更具体的代码片段"
                })

            # 精确匹配成功,执行替换
            new_content = file_content.replace(search_block, replace_block, 1)
            return json.dumps({"success": True, "message": "替换成功", "new_content": new_content})

        # 2. 精确匹配失败 → 执行诊断
        diagnosis = CodeApplyTool._diagnose_mismatch(search_block, file_content)
        return json.dumps(diagnosis)

    @staticmethod
    def _diagnose_mismatch(search_block: str, file_content: str) -> Dict[str, Any]:
        """
        诊断 search_block 不匹配的原因

        四级诊断:
        1. 换行符差异(\r\n vs \n)
        2. 缩进差异(空格数量)
        3. 模糊匹配(找到最相似的片段)
        4. 完全找不到
        """
        # Level 1: 换行符归一化后匹配?
        norm_file = file_content.replace("\r\n", "\n")
        norm_search = search_block.replace("\r\n", "\n")
        if norm_search in norm_file:
            return {
                "success": False,
                "error_type": "newline_mismatch",
                "error_detail": "换行符差异: search_block 使用 \\n, 文件使用 \\r\\n (或相反)",
                "suggestion": "请确保 search_block 的换行符与文件一致。可用 read_file 读取原文件确认换行格式。"
            }

        # Level 2: 缩进模糊匹配(忽略每行首尾空白)
        def strip_lines(text):
            return [line.strip() for line in text.splitlines() if line.strip()]

        file_stripped = strip_lines(norm_file)
        search_stripped = strip_lines(norm_search)
        if search_stripped and len(file_stripped) >= len(search_stripped):
            for i in range(len(file_stripped) - len(search_stripped) + 1):
                if file_stripped[i : i + len(search_stripped)] == search_stripped:
                    return {
                        "success": False,
                        "error_type": "indentation_mismatch",
                        "error_detail": f"内容匹配但缩进不同。在文件第 {i+1} 行附近找到相似内容,但缩进不一致。",
                        "suggestion": "请检查 search_block 的缩进是否与文件一致(可能是空格 vs Tab 或缩进层级错误)。"
                    }

        # Level 3: 查找最相似的片段
        lines = norm_file.splitlines()
        search_lines = norm_search.splitlines()
        best_ratio = 0.0
        best_pos = -1
        for i in range(len(lines) - len(search_lines) + 1):
            window = "\n".join(lines[i : i + len(search_lines)])
            ratio = difflib.SequenceMatcher(None, window, norm_search).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = i

        if best_ratio > 0.5:
            actual_snippet = "\n".join(lines[best_pos : best_pos + min(5, len(search_lines))])
            return {
                "success": False,
                "error_type": "fuzzy_mismatch",
                "error_detail": f"最相似片段在第 {best_pos+1} 行(相似度 {best_ratio:.0%})",
                "actual_snippet": actual_snippet[:500],
                "suggestion": f"search_block 与文件内容的相似度为 {best_ratio:.0%}。请用 read_file 读取目标行附近的代码,确保 search_block 精确复制。"
            }

        # Level 4: 完全找不到
        return {
            "success": False,
            "error_type": "no_match",
            "error_detail": "search_block 在文件中完全找不到",
            "suggestion": "请用 read_file 重新读取文件,确认文件内容和行号是否正确。文件可能已被修改。"
        }
