/**
 * OmniFlowAI Injector - 搜索替换引擎
 * 与后端 SearchReplaceEngine 逻辑保持一致
 *
 * 提供搜索替换的匹配算法（精确、行号、多级回退）
 */

/**
 * 补丁接口
 */
export interface Patch {
  start_line: number;
  end_line: number;
  replace_block: string;
}

/**
 * 搜索替换引擎 - 处理代码变更的匹配和替换
 * 与后端 app/service/search_replace_engine.py 逻辑保持一致
 */
export class SearchReplaceEngine {
  /**
   * 原子化行替换逻辑 - Line-Number Based Patching Protocol 核心
   *
   * @param originalContent - 原始文件内容
   * @param startLine - 起始行号 (1-based, 包含)
   * @param endLine - 结束行号 (1-based, 包含)
   * @param replaceBlock - 新代码块
   * @returns 替换后的完整内容
   */
  static applyLinePatch(
    originalContent: string,
    startLine: number,
    endLine: number,
    replaceBlock: string
  ): string {
    const origLines = originalContent.split('\n');
    const newLines = [
      ...origLines.slice(0, startLine - 1),
      ...replaceBlock.split('\n'),
      ...origLines.slice(endLine),
    ];
    return newLines.join('\n');
  }

  /**
   * 安全地应用多个补丁 - 防止行号漂移
   *
   * 核心策略：
   * 1. 按 start_line 从大到小排序（倒序）
   * 2. 先改行号大的，再改行号小的
   * 3. 这样前面的修改不会影响后面的行号
   *
   * @param originalContent - 原始文件内容
   * @param patches - 补丁列表
   * @returns 应用所有补丁后的完整内容
   */
  static applyPatchesSafely(originalContent: string, patches: Patch[]): string {
    const lines = originalContent.split('\n');

    // 按照 start_line 从大到小排序 (关键！防止行号漂移)
    const sortedPatches = [...patches].sort((a, b) => b.start_line - a.start_line);

    for (const p of sortedPatches) {
      const s = p.start_line;
      const e = p.end_line;
      const newChunk = p.replace_block.split('\n');

      // 验证行号范围
      if (s < 1 || e > lines.length || s > e) {
        throw new Error(
          `无效的行号范围: start_line=${s}, end_line=${e}, 文件共 ${lines.length} 行`
        );
      }

      // 这里的切片操作是原子的，倒序操作保证了 s 和 e 在本次循环中依然有效
      lines.splice(s - 1, e - s + 1, ...newChunk);
    }

    return lines.join('\n');
  }

  /**
   * 计算两个字符串的相似度比率 (SequenceMatcher)
   * 简化版 difflib.SequenceMatcher
   */
  private static getSimilarityRatio(a: string, b: string): number {
    if (a === b) return 1.0;
    if (a.length === 0 || b.length === 0) return 0.0;

    // 使用简单的 LCS (最长公共子序列) 算法
    const longer = a.length > b.length ? a : b;
    const shorter = a.length > b.length ? b : a;

    if (longer.length === 0) return 1.0;

    const costs: number[] = new Array(shorter.length + 1).fill(0);

    for (let i = 0; i <= longer.length; i++) {
      let nw = 0;
      for (let j = 0; j <= shorter.length; j++) {
        if (i === 0 || j === 0) {
          nw = costs[j];
          costs[j] = i;
        } else {
          const cj =
            longer[i - 1] === shorter[j - 1]
              ? nw + 1
              : Math.max(costs[j], costs[j - 1]);
          nw = costs[j];
          costs[j] = cj;
        }
      }
    }

    const lcsLength = costs[shorter.length];
    return (2.0 * lcsLength) / (a.length + b.length);
  }

  /**
   * 最接近匹配算法 - 当行号不匹配时给出智能提示
   *
   * @param originalLines - 原始文件的行列表
   * @param searchBlock - AI 预期的代码块
   * @param startLine - AI 提供的起始行号
   * @returns 给 AI 的提示信息
   */
  static getBestMatchHint(
    originalLines: string[],
    searchBlock: string,
    startLine: number
  ): string {
    if (!searchBlock.trim()) {
      return '提示：expected_original 为空，无法验证';
    }

    const searchLines = searchBlock.trim().split('\n').filter((line) => line.trim());
    if (searchLines.length === 0) {
      return '提示：expected_original 为空，无法验证';
    }

    // 在预期行号附近搜索最相似的代码段
    const searchWindow = 10; // 前后搜索 10 行
    const searchStart = Math.max(0, startLine - 1 - searchWindow);
    const searchEnd = Math.min(
      originalLines.length,
      startLine - 1 + searchWindow + searchLines.length
    );

    let bestRatio = 0.0;
    let bestMatchStart = -1;

    // 滑动窗口找最佳匹配
    for (let i = searchStart; i <= searchEnd - searchLines.length; i++) {
      const window = originalLines.slice(i, i + searchLines.length);
      const windowText = window.join('\n');
      const searchText = searchLines.join('\n');

      const ratio = this.getSimilarityRatio(windowText, searchText);
      if (ratio > bestRatio) {
        bestRatio = ratio;
        bestMatchStart = i;
      }
    }

    if (bestRatio > 0.8) {
      // 找到高度相似的代码
      const actualLine = bestMatchStart + 1;
      if (actualLine !== startLine) {
        return `提示：行号偏移。你指定的 start_line=${startLine}，但实际匹配的代码在第 ${actualLine} 行`;
      } else {
        return '提示：代码内容有细微差异，请检查缩进或空格';
      }
    } else if (bestRatio > 0.5) {
      return `提示：在指定位置附近找到相似度 ${Math.round(bestRatio * 100)}% 的代码，请检查行号`;
    } else {
      // 检查是否是缩进问题
      const firstSearchLine = searchLines[0] || '';
      for (let i = searchStart; i < searchEnd; i++) {
        const line = originalLines[i];
        const strippedSearch = firstSearchLine.trim();
        const strippedActual = line.trim();
        if (strippedSearch && strippedActual && strippedSearch === strippedActual) {
          // 内容匹配但缩进可能不同
          const searchIndent = firstSearchLine.length - firstSearchLine.trimStart().length;
          const actualIndent = line.length - line.trimStart().length;
          if (searchIndent !== actualIndent) {
            return `提示：第 ${i + 1} 行内容匹配但缩进不同。原文件是 ${actualIndent} 个空格，你提供了 ${searchIndent} 个`;
          }
        }
      }

      return '提示：无法找到匹配的代码块，请重新检查行号和代码内容';
    }
  }

  /**
   * 搜索替换引擎，支持四级匹配和行号回退
   *
   * 匹配策略（按优先级）：
   * 1. 【Claude Code 原则】唯一性校验：search_block 在文件中必须恰好出现一次
   * 2. 精确匹配：完全一致的代码块
   * 3. 换行符归一化：处理 \r\n vs \n 的差异
   * 4. 行级别宽松匹配：忽略首尾空格
   * 5. 行号回退：当搜索块匹配失败时，使用备用行号
   *
   * @param original - 原始文件内容
   * @param searchBlock - 要搜索的代码块
   * @param replaceBlock - 替换后的代码块
   * @param fallbackStart - 备用起始行号（1-based）
   * @param fallbackEnd - 备用结束行号（1-based，包含）
   * @returns 替换后的内容，失败返回 null
   */
  static applySearchReplace(
    original: string,
    searchBlock: string,
    replaceBlock: string,
    fallbackStart?: number,
    fallbackEnd?: number
  ): string | null {
    if (!searchBlock) {
      console.warn('[SearchReplace] search_block 为空，跳过替换');
      return null;
    }

    const originalLinesCount = original.split('\n').length;
    const searchBlockLinesCount = searchBlock.split('\n').length;
    console.info(
      `[SearchReplace] 开始搜索替换: 原文件 ${originalLinesCount} 行, 搜索块 ${searchBlockLinesCount} 行`
    );

    // 【Claude Code 原则】唯一性校验：search_block 在文件中必须恰好出现一次
    const occurrences = original.split(searchBlock).length - 1;
    if (occurrences > 1) {
      console.error(
        `[SearchReplace] 唯一性校验失败: search_block 在文件中出现 ${occurrences} 次，必须确保唯一`
      );
      return null;
    }

    // 第1级：精确匹配
    if (original.includes(searchBlock)) {
      console.info('[SearchReplace] 第1级匹配成功: 精确匹配');
      return original.replace(searchBlock, replaceBlock);
    }
    console.debug('[SearchReplace] 第1级匹配失败: 精确匹配未找到');

    // 第2级：换行符归一化匹配
    const origNorm = original.replace(/\r\n/g, '\n');
    const searchNorm = searchBlock.replace(/\r\n/g, '\n');
    const replNorm = replaceBlock.replace(/\r\n/g, '\n');
    if (origNorm.includes(searchNorm)) {
      console.info('[SearchReplace] 第2级匹配成功: 换行符归一化匹配');
      // 保留原始换行符格式：如果原始使用 \r\n，则替换后也用 \r\n
      const usesCRLF = original.includes('\r\n');
      const result = origNorm.replace(searchNorm, replNorm);
      return usesCRLF ? result.replace(/\n/g, '\r\n') : result;
    }
    console.debug('[SearchReplace] 第2级匹配失败: 换行符归一化匹配未找到');

    // 第3级：行级别宽松匹配（忽略首尾空格）
    const cleanLines = (text: string): string[] =>
      text
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line);

    const origLinesClean = cleanLines(origNorm);
    const searchLinesClean = cleanLines(searchNorm);
    const replLines = replNorm.split('\n');

    const searchLen = searchLinesClean.length;
    if (searchLen > 0 && origLinesClean.length >= searchLen) {
      console.debug(
        `[SearchReplace] 第3级匹配: 清洗后原文件 ${origLinesClean.length} 行, 搜索块 ${searchLen} 行`
      );
      let matchFound = false;
      for (let i = 0; i <= origLinesClean.length - searchLen; i++) {
        const window = origLinesClean.slice(i, i + searchLen);
        if (JSON.stringify(window) === JSON.stringify(searchLinesClean)) {
          matchFound = true;
          // 找到匹配，计算在原文件中的实际位置
          const origLines = origNorm.split('\n');
          let matchStart = 0;
          let matchedCount = 0;

          console.info(`[SearchReplace] 第3级匹配成功: 清洗后行索引 ${i}-${i + searchLen}`);

          for (let j = 0; j < origLines.length; j++) {
            if (origLines[j].trim() && matchedCount < i) {
              matchedCount++;
              if (matchedCount === i) {
                matchStart = j;
                break;
              }
            }
          }

          // 计算匹配结束位置
          let matchEnd = matchStart;
          matchedCount = 0;
          for (let j = matchStart; j < origLines.length; j++) {
            if (origLines[j].trim()) {
              matchedCount++;
              if (matchedCount === searchLen) {
                matchEnd = j;
                break;
              }
            }
          }

          console.info(
            `[SearchReplace] 映射到原文件行号: ${matchStart + 1}-${matchEnd + 1} (共 ${origLines.length} 行)`
          );

          // 执行替换：保留原始缩进
          const usesCRLF = original.includes('\r\n');
          const newLines = [
            ...origLines.slice(0, matchStart),
            ...replLines,
            ...origLines.slice(matchEnd + 1),
          ];
          const result = newLines.join('\n');
          return usesCRLF ? result.replace(/\n/g, '\r\n') : result;
        }
      }
      if (!matchFound) {
        console.debug('[SearchReplace] 第3级匹配失败: 未找到匹配的清洗后代码块');
      }
    } else {
      console.warn('[SearchReplace] 第3级匹配跳过: 搜索块为空或比原文件长');
    }

    // 第4级：行号回退
    if (fallbackStart !== undefined && fallbackEnd !== undefined) {
      const lines = origNorm.split('\n');
      const totalLines = lines.length;
      console.info(
        `[SearchReplace] 第4级匹配: 尝试 fallback 行号 ${fallbackStart}-${fallbackEnd} (文件共 ${totalLines} 行)`
      );
      if (1 <= fallbackStart && fallbackStart <= fallbackEnd && fallbackEnd <= totalLines) {
        const newLines = [
          ...lines.slice(0, fallbackStart - 1),
          ...replNorm.split('\n'),
          ...lines.slice(fallbackEnd),
        ];
        console.info(`[SearchReplace] 第4级匹配成功: fallback 行号替换 ${fallbackStart}-${fallbackEnd}`);
        return newLines.join('\n');
      } else {
        console.warn(
          `[SearchReplace] 第4级匹配失败: fallback 行号 ${fallbackStart}-${fallbackEnd} 超出范围 (文件共 ${totalLines} 行)`
        );
      }
    } else {
      console.debug('[SearchReplace] 第4级匹配跳过: 未提供 fallback 行号');
    }

    console.error('[SearchReplace] 所有匹配级别都失败，搜索替换完全失败');
    return null; // 完全失败
  }

  /**
   * 多级模糊匹配替换算法 (Aider 简化版) - 向后兼容
   */
  static flexibleSearchReplace(originalText: string, searchBlock: string, replaceBlock: string): string | null {
    return this.applySearchReplace(originalText, searchBlock, replaceBlock, undefined, undefined);
  }
}

// 单例实例
export const searchReplaceEngine = new SearchReplaceEngine();

// 便捷导出
export const applySearchReplace = SearchReplaceEngine.applySearchReplace.bind(SearchReplaceEngine);
export const applyPatchesSafely = SearchReplaceEngine.applyPatchesSafely.bind(SearchReplaceEngine);
export const applyLinePatch = SearchReplaceEngine.applyLinePatch.bind(SearchReplaceEngine);
