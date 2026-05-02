/**
 * SearchReplaceEngine 测试
 * 验证与后端逻辑一致性
 */

import { describe, it, expect } from 'vitest';
import { SearchReplaceEngine } from '../searchReplace';

describe('SearchReplaceEngine', () => {
  describe('applyLinePatch', () => {
    it('应该正确替换指定行范围的代码', () => {
      const original = 'line1\nline2\nline3\nline4\nline5';
      const replaceBlock = 'newLine2\nnewLine3';
      const result = SearchReplaceEngine.applyLinePatch(original, 2, 3, replaceBlock);
      expect(result).toBe('line1\nnewLine2\nnewLine3\nline4\nline5');
    });

    it('应该在文件开头插入代码', () => {
      const original = 'line2\nline3';
      const replaceBlock = 'line1';
      const result = SearchReplaceEngine.applyLinePatch(original, 1, 0, replaceBlock);
      expect(result).toBe('line1\nline2\nline3');
    });

    it('应该在文件末尾追加代码', () => {
      const original = 'line1\nline2';
      const replaceBlock = 'line3\nline4';
      const result = SearchReplaceEngine.applyLinePatch(original, 3, 2, replaceBlock);
      expect(result).toBe('line1\nline2\nline3\nline4');
    });
  });

  describe('applyPatchesSafely', () => {
    it('应该按倒序应用多个补丁以防止行号漂移', () => {
      const original = 'line1\nline2\nline3\nline4\nline5\nline6';
      const patches = [
        { start_line: 2, end_line: 3, replace_block: 'new2' },
        { start_line: 5, end_line: 6, replace_block: 'new5' },
      ];
      const result = SearchReplaceEngine.applyPatchesSafely(original, patches);
      expect(result).toBe('line1\nnew2\nline4\nnew5');
    });

    it('应该正确处理重叠范围外的多个补丁', () => {
      const original = 'a\nb\nc\nd\ne';
      const patches = [
        { start_line: 1, end_line: 1, replace_block: 'A' },
        { start_line: 5, end_line: 5, replace_block: 'E' },
      ];
      const result = SearchReplaceEngine.applyPatchesSafely(original, patches);
      expect(result).toBe('A\nb\nc\nd\nE');
    });

    it('应该在行号范围无效时抛出错误', () => {
      const original = 'line1\nline2';
      const patches = [{ start_line: 5, end_line: 6, replace_block: 'new' }];
      expect(() => SearchReplaceEngine.applyPatchesSafely(original, patches)).toThrow();
    });
  });

  describe('applySearchReplace - 第1级：精确匹配', () => {
    it('应该成功替换精确匹配的代码块', () => {
      const original = 'function foo() {\n  return 1;\n}';
      const searchBlock = 'return 1;';
      const replaceBlock = 'return 2;';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBe('function foo() {\n  return 2;\n}');
    });

    it('应该在搜索块出现多次时返回null（唯一性校验）', () => {
      const original = 'return 1;\nreturn 1;';
      const searchBlock = 'return 1;';
      const replaceBlock = 'return 2;';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBeNull();
    });
  });

  describe('applySearchReplace - 第2级：换行符归一化', () => {
    it('应该处理Windows换行符', () => {
      const original = 'line1\r\nline2\r\nline3';
      const searchBlock = 'line2';
      const replaceBlock = 'newLine2';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      // 保留原始换行符格式
      expect(result).toBe('line1\r\nnewLine2\r\nline3');
    });

    it('应该处理混合换行符', () => {
      const original = 'line1\r\nline2\nline3';
      const searchBlock = 'line1\r\nline2';
      const replaceBlock = 'newLine1\nnewLine2';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBe('newLine1\nnewLine2\nline3');
    });
  });

  describe('applySearchReplace - 第3级：行级别宽松匹配', () => {
    it('应该匹配忽略首尾空格的代码', () => {
      const original = '  function foo() {  \n    return 1;  \n  }';
      const searchBlock = 'function foo() {\nreturn 1;';
      const replaceBlock = 'function bar() {\nreturn 2;';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      // 第3级匹配会保留原始缩进格式，但替换块的格式会被使用
      expect(result).toContain('function bar()');
      expect(result).toContain('return 2;');
    });

    it('应该正确处理空行', () => {
      const original = 'line1\n\nline2\n\nline3';
      const searchBlock = 'line1\nline2';
      const replaceBlock = 'new1\nnew2';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      // 第3级匹配会跳过空行，替换后空行位置可能变化
      expect(result).toContain('new1');
      expect(result).toContain('new2');
      expect(result).toContain('line3');
    });
  });

  describe('applySearchReplace - 第4级：行号回退', () => {
    it('应该在提供fallback行号时直接替换', () => {
      const original = 'line1\nline2\nline3\nline4\nline5';
      const searchBlock = 'nonexistent';
      const replaceBlock = 'newBlock';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock, 2, 4);
      expect(result).toBe('line1\nnewBlock\nline5');
    });

    it('应该在fallback行号超出范围时返回null', () => {
      const original = 'line1\nline2';
      const searchBlock = 'nonexistent';
      const replaceBlock = 'newBlock';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock, 5, 10);
      expect(result).toBeNull();
    });

    it('应该在fallback行号无效时跳过', () => {
      const original = 'line1\nline2\nline3';
      const searchBlock = 'nonexistent';
      const replaceBlock = 'newBlock';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock, 2, 1);
      expect(result).toBeNull();
    });
  });

  describe('边界情况', () => {
    it('应该在searchBlock为空时返回null', () => {
      const original = 'some content';
      const result = SearchReplaceEngine.applySearchReplace(original, '', 'replacement');
      expect(result).toBeNull();
    });

    it('应该正确处理只有一行的文件', () => {
      const original = 'single line';
      const searchBlock = 'single';
      const replaceBlock = 'multiple';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBe('multiple line');
    });

    it('应该正确处理空文件', () => {
      const original = '';
      const searchBlock = 'search';
      const replaceBlock = 'replace';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBeNull();
    });

    it('应该正确处理多行替换块', () => {
      const original = 'function foo() {\n  return 1;\n}';
      const searchBlock = 'return 1;';
      const replaceBlock = 'const x = 1;\n  return x;';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBe('function foo() {\n  const x = 1;\n  return x;\n}');
    });
  });

  describe('与后端行为一致性测试', () => {
    it('应该与Python版本的行为一致：精确匹配优先', () => {
      const original = 'def foo():\n    return 1\n\ndef bar():\n    return 2';
      const searchBlock = '    return 1';
      const replaceBlock = '    return 100';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      expect(result).toBe('def foo():\n    return 100\n\ndef bar():\n    return 2');
    });

    it('应该与Python版本的行为一致：唯一性校验', () => {
      // 这个测试验证 Claude Code 原则
      const original = 'return 42\nreturn 42';
      const searchBlock = 'return 42';
      const replaceBlock = 'return 0';
      const result = SearchReplaceEngine.applySearchReplace(original, searchBlock, replaceBlock);
      // 由于出现2次，应该返回null
      expect(result).toBeNull();
    });
  });
});
