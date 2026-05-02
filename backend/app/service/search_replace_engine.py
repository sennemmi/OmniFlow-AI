"""
搜索替换引擎

提供搜索替换的匹配算法（精确、行号、多级回退）
"""

import difflib
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class SearchReplaceEngine:
    """搜索替换引擎 - 处理代码变更的匹配和替换"""

    @staticmethod
    def apply_line_patch(original_content: str, start_line: int, end_line: int, replace_block: str) -> str:
        """
        原子化行替换逻辑 - Line-Number Based Patching Protocol 核心

        Args:
            original_content: 原始文件内容
            start_line: 起始行号 (1-based, 包含)
            end_line: 结束行号 (1-based, 包含)
            replace_block: 新代码块

        Returns:
            str: 替换后的完整内容
        """
        orig_lines = original_content.splitlines()
        new_lines = orig_lines[:start_line - 1] + replace_block.splitlines() + orig_lines[end_line:]
        return "\n".join(new_lines)

    @staticmethod
    def apply_patches_safely(original_content: str, patches: List[Dict[str, Any]]) -> str:
        """
        安全地应用多个补丁 - 防止行号漂移

        核心策略：
        1. 按 start_line 从大到小排序（倒序）
        2. 先改行号大的，再改行号小的
        3. 这样前面的修改不会影响后面的行号

        Args:
            original_content: 原始文件内容
            patches: 补丁列表，每个补丁包含 start_line, end_line, replace_block

        Returns:
            str: 应用所有补丁后的完整内容
        """
        lines = original_content.splitlines()

        # 按照 start_line 从大到小排序 (关键！防止行号漂移)
        sorted_patches = sorted(patches, key=lambda x: x.get('start_line', 0), reverse=True)

        for p in sorted_patches:
            s = p['start_line']
            e = p['end_line']
            new_chunk = p['replace_block'].splitlines()

            # 验证行号范围
            if s < 1 or e > len(lines) or s > e:
                raise ValueError(f"无效的行号范围: start_line={s}, end_line={e}, 文件共 {len(lines)} 行")

            # 这里的切片操作是原子的，倒序操作保证了 s 和 e 在本次循环中依然有效
            lines[s-1:e] = new_chunk

        return "\n".join(lines)

    @staticmethod
    def get_best_match_hint(original_lines: List[str], search_block: str, start_line: int) -> str:
        """
        最接近匹配算法 - 当行号不匹配时给出智能提示

        Args:
            original_lines: 原始文件的行列表
            search_block: AI 预期的代码块
            start_line: AI 提供的起始行号

        Returns:
            str: 给 AI 的提示信息
        """
        if not search_block.strip():
            return "提示：expected_original 为空，无法验证"

        search_lines = search_block.strip().splitlines()
        if not search_lines:
            return "提示：expected_original 为空，无法验证"

        # 在预期行号附近搜索最相似的代码段
        search_window = 10  # 前后搜索 10 行
        search_start = max(0, start_line - 1 - search_window)
        search_end = min(len(original_lines), start_line - 1 + search_window + len(search_lines))

        best_ratio = 0.0
        best_match_start = -1

        # 滑动窗口找最佳匹配
        for i in range(search_start, search_end - len(search_lines) + 1):
            window = original_lines[i:i + len(search_lines)]
            window_text = "\n".join(window)
            search_text = "\n".join(search_lines)

            ratio = difflib.SequenceMatcher(None, window_text, search_text).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_start = i

        if best_ratio > 0.8:
            # 找到高度相似的代码
            actual_line = best_match_start + 1
            if actual_line != start_line:
                return f"提示：行号偏移。你指定的 start_line={start_line}，但实际匹配的代码在第 {actual_line} 行"
            else:
                return "提示：代码内容有细微差异，请检查缩进或空格"
        elif best_ratio > 0.5:
            return f"提示：在指定位置附近找到相似度 {best_ratio:.0%} 的代码，请检查行号"
        else:
            # 检查是否是缩进问题
            first_search_line = search_lines[0] if search_lines else ""
            for i, line in enumerate(original_lines[search_start:search_end], start=search_start + 1):
                stripped_search = first_search_line.strip()
                stripped_actual = line.strip()
                if stripped_search and stripped_actual and stripped_search == stripped_actual:
                    # 内容匹配但缩进可能不同
                    search_indent = len(first_search_line) - len(first_search_line.lstrip())
                    actual_indent = len(line) - len(line.lstrip())
                    if search_indent != actual_indent:
                        return f"提示：第 {i} 行内容匹配但缩进不同。原文件是 {actual_indent} 个空格，你提供了 {search_indent} 个"

            return "提示：无法找到匹配的代码块，请重新检查行号和代码内容"

    @staticmethod
    def apply_search_replace(
        original: str,
        search_block: str,
        replace_block: str,
        fallback_start: Optional[int] = None,
        fallback_end: Optional[int] = None
    ) -> Optional[str]:
        """
        搜索替换引擎，支持三级匹配和行号回退

        匹配策略（按优先级）：
        1. 【Claude Code 原则】唯一性校验：search_block 在文件中必须恰好出现一次
        2. 精确匹配：完全一致的代码块
        3. 换行符归一化：处理 \r\n vs \n 的差异
        4. 行级别宽松匹配：忽略首尾空格
        5. 行号回退：当搜索块匹配失败时，使用备用行号

        Args:
            original: 原始文件内容
            search_block: 要搜索的代码块
            replace_block: 替换后的代码块
            fallback_start: 备用起始行号（1-based）
            fallback_end: 备用结束行号（1-based，包含）

        Returns:
            Optional[str]: 替换后的内容，失败返回 None
        """
        if not search_block:
            logger.warning("[SearchReplace] search_block 为空，跳过替换")
            return None

        original_lines_count = len(original.splitlines())
        search_block_lines_count = len(search_block.splitlines())
        logger.info(f"[SearchReplace] 开始搜索替换: 原文件 {original_lines_count} 行, 搜索块 {search_block_lines_count} 行")

        # 【Claude Code 原则】唯一性校验：search_block 在文件中必须恰好出现一次
        occurrences = original.count(search_block)
        if occurrences > 1:
            logger.error(f"[SearchReplace] 唯一性校验失败: search_block 在文件中出现 {occurrences} 次，必须确保唯一")
            return None

        # 第1级：精确匹配
        if search_block in original:
            logger.info("[SearchReplace] 第1级匹配成功: 精确匹配")
            return original.replace(search_block, replace_block, 1)
        logger.debug("[SearchReplace] 第1级匹配失败: 精确匹配未找到")

        # 第2级：换行符归一化匹配
        orig_norm = original.replace('\r\n', '\n')
        search_norm = search_block.replace('\r\n', '\n')
        repl_norm = replace_block.replace('\r\n', '\n')
        if search_norm in orig_norm:
            logger.info("[SearchReplace] 第2级匹配成功: 换行符归一化匹配")
            return orig_norm.replace(search_norm, repl_norm, 1)
        logger.debug("[SearchReplace] 第2级匹配失败: 换行符归一化匹配未找到")

        # 第3级：行级别宽松匹配（忽略首尾空格）
        def clean_lines(text: str) -> List[str]:
            return [line.strip() for line in text.splitlines() if line.strip()]

        orig_lines_clean = clean_lines(orig_norm)
        search_lines_clean = clean_lines(search_norm)
        repl_lines = repl_norm.splitlines()

        search_len = len(search_lines_clean)
        if search_len > 0 and len(orig_lines_clean) >= search_len:
            logger.debug(f"[SearchReplace] 第3级匹配: 清洗后原文件 {len(orig_lines_clean)} 行, 搜索块 {search_len} 行")
            match_found = False
            for i in range(len(orig_lines_clean) - search_len + 1):
                window = orig_lines_clean[i:i + search_len]
                if window == search_lines_clean:
                    match_found = True
                    # 找到匹配，计算在原文件中的实际位置
                    orig_lines = orig_norm.splitlines()
                    match_start = 0
                    matched_count = 0

                    logger.info(f"[SearchReplace] 第3级匹配成功: 清洗后行索引 {i}-{i+search_len}")

                    for j, line in enumerate(orig_lines):
                        if line.strip() and matched_count < i:
                            matched_count += 1
                            if matched_count == i:
                                match_start = j
                                break

                    # 计算匹配结束位置
                    match_end = match_start
                    matched_count = 0
                    for j in range(match_start, len(orig_lines)):
                        if orig_lines[j].strip():
                            matched_count += 1
                            if matched_count == search_len:
                                match_end = j
                                break

                    logger.info(f"[SearchReplace] 映射到原文件行号: {match_start+1}-{match_end+1} (共 {len(orig_lines)} 行)")

                    # 执行替换
                    new_lines = orig_lines[:match_start] + repl_lines + orig_lines[match_end + 1:]
                    return '\n'.join(new_lines)
            if not match_found:
                logger.debug(f"[SearchReplace] 第3级匹配失败: 未找到匹配的清洗后代码块")
        else:
            logger.warning(f"[SearchReplace] 第3级匹配跳过: 搜索块为空或比原文件长")

        # 第4级：行号回退
        if fallback_start and fallback_end:
            lines = orig_norm.splitlines()
            total_lines = len(lines)
            logger.info(f"[SearchReplace] 第4级匹配: 尝试 fallback 行号 {fallback_start}-{fallback_end} (文件共 {total_lines} 行)")
            if 1 <= fallback_start <= fallback_end <= total_lines:
                new_lines = lines[:fallback_start - 1] + repl_norm.splitlines() + lines[fallback_end:]
                logger.info(f"[SearchReplace] 第4级匹配成功: fallback 行号替换 {fallback_start}-{fallback_end}")
                return '\n'.join(new_lines)
            else:
                logger.warning(f"[SearchReplace] 第4级匹配失败: fallback 行号 {fallback_start}-{fallback_end} 超出范围 (文件共 {total_lines} 行)")
        else:
            logger.debug(f"[SearchReplace] 第4级匹配跳过: 未提供 fallback 行号")

        logger.error("[SearchReplace] 所有匹配级别都失败，搜索替换完全失败")
        return None  # 完全失败

    @staticmethod
    def flexible_search_replace(original_text: str, search_block: str, replace_block: str) -> Optional[str]:
        """多级模糊匹配替换算法 (Aider 简化版) - 向后兼容"""
        return SearchReplaceEngine.apply_search_replace(original_text, search_block, replace_block, None, None)


# 单例实例
search_replace_engine = SearchReplaceEngine()
