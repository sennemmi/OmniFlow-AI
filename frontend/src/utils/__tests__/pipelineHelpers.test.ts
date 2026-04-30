import { describe, it, expect } from 'vitest';
import { extractAllCodeChanges, isCodeStage, type CodeChange } from '../pipelineHelpers';
import type { PipelineStage } from '@types';

describe('extractAllCodeChanges', () => {
  it('应该正确区分新建文件和修改文件', () => {
    const mockOutput = {
      multi_agent_output: {
        files: [
          { file_path: 'new.py', content: 'print(1)', original_content: null },
          { file_path: 'edit.py', content: 'print(2)', original_content: 'print(0)' }
        ]
      }
    };
    const result = extractAllCodeChanges(mockOutput);
    expect(result).toHaveLength(2);
    expect(result[0].isNew).toBe(true);
    expect(result[0].changeType).toBe('add');
    expect(result[1].isNew).toBe(false);
    expect(result[1].changeType).toBe('modify');
  });

  it('应该过滤掉测试文件', () => {
    const mockOutput = {
      multi_agent_output: {
        files: [
          { file_path: 'app/main.py', content: 'code', original_content: null },
          { file_path: 'tests/test_main.py', content: 'test', original_content: null },
          { file_path: 'test_utils.py', content: 'test', original_content: null }
        ]
      }
    };
    const result = extractAllCodeChanges(mockOutput);
    expect(result).toHaveLength(1);
    expect(result[0].fileName).toBe('app/main.py');
  });

  it('应该处理空输入', () => {
    expect(extractAllCodeChanges(undefined)).toEqual([]);
    expect(extractAllCodeChanges({})).toEqual([]);
    expect(extractAllCodeChanges({ multi_agent_output: {} })).toEqual([]);
  });

  it('应该兼容旧版 coder_output 格式', () => {
    const mockOutput = {
      coder_output: {
        files: [
          { file_path: 'old.py', content: 'code', original_content: null }
        ]
      }
    };
    const result = extractAllCodeChanges(mockOutput);
    expect(result).toHaveLength(1);
    expect(result[0].fileName).toBe('old.py');
  });

  it('应该正确处理文件路径', () => {
    const mockOutput = {
      multi_agent_output: {
        files: [
          { file_path: 'app/utils/helper.py', content: 'code', original_content: null }
        ]
      }
    };
    const result = extractAllCodeChanges(mockOutput);
    expect(result[0].fileName).toBe('app/utils/helper.py');
  });
});

describe('isCodeStage', () => {
  it('应该识别代码阶段', () => {
    const codeStage: PipelineStage = {
      id: 1,
      name: 'CODING',
      status: 'running',
      input_data: {},
      output_data: {},
      created_at: new Date().toISOString(),
    };
    expect(isCodeStage(codeStage)).toBe(true);
  });

  it('应该识别代码审查阶段', () => {
    const reviewStage: PipelineStage = {
      id: 2,
      name: 'CODE_REVIEW',
      status: 'pending',
      input_data: {},
      output_data: {},
      created_at: new Date().toISOString(),
    };
    expect(isCodeStage(reviewStage)).toBe(true);
  });

  it('不应该识别非代码阶段', () => {
    const reqStage: PipelineStage = {
      id: 3,
      name: 'REQUIREMENT',
      status: 'success',
      input_data: {},
      output_data: {},
      created_at: new Date().toISOString(),
    };
    expect(isCodeStage(reqStage)).toBe(false);
  });

  it('应该处理 null 输入', () => {
    expect(isCodeStage(null)).toBe(false);
  });
});
