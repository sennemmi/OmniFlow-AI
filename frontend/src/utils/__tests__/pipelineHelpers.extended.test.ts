/**
 * 高 ROI 小功能测试：前端 Pipeline Helpers 扩展测试
 *
 * 使用 Vitest 的 describe.each 进行数据驱动测试
 * 覆盖各种嵌套极深、千奇百怪的后端 JSON 结构
 */

import { describe, it, expect } from 'vitest';
import { extractAllCodeChanges, extractTestCodeChanges, isCodeStage, isTestStage } from '../pipelineHelpers';
import type { PipelineStage } from '@types';

describe('Utility: extractAllCodeChanges - 数据驱动测试', () => {
  it.each([
    {
      desc: '标准格式 - 包含新建和修改',
      input: {
        multi_agent_output: {
          files: [
            { file_path: 'new.py', content: 'print(1)' }, // 没有 original_content，应为 add
            { file_path: 'edit.py', content: 'print(2)', original_content: 'print(0)' } // 有 original，应为 modify
          ]
        }
      },
      expectedLen: 2,
      expectedFirstType: 'add',
      expectedSecondType: 'modify'
    },
    {
      desc: '极端情况 - 后端返回空对象',
      input: {},
      expectedLen: 0,
      expectedFirstType: undefined,
      expectedSecondType: undefined
    },
    {
      desc: '极端情况 - 返回 null',
      input: null,
      expectedLen: 0,
      expectedFirstType: undefined,
      expectedSecondType: undefined
    },
    {
      desc: '向下兼容 - 旧版 CoderAgent 格式',
      input: {
        coder_output: {
          files: [{ file_path: 'legacy.py', content: 'code' }]
        }
      },
      expectedLen: 1,
      expectedFirstType: 'add',
      expectedSecondType: undefined
    },
    {
      desc: '嵌套极深 - agent_outputs 嵌套',
      input: {
        multi_agent_output: {
          agent_outputs: {
            coder: {
              files: [{ file_path: 'nested.py', content: 'code' }]
            }
          }
        }
      },
      expectedLen: 0, // 当前实现不支持这种嵌套
      expectedFirstType: undefined,
      expectedSecondType: undefined
    },
    {
      desc: '混合格式 - 同时有 multi_agent_output 和 coder_output',
      input: {
        multi_agent_output: {
          files: [{ file_path: 'multi.py', content: 'code' }]
        },
        coder_output: {
          files: [{ file_path: 'coder.py', content: 'code' }]
        }
      },
      expectedLen: 1, // 应该优先使用 multi_agent_output
      expectedFirstType: 'add',
      expectedSecondType: undefined
    },
    {
      desc: '空数组 - files 为空',
      input: {
        multi_agent_output: {
          files: []
        }
      },
      expectedLen: 0,
      expectedFirstType: undefined,
      expectedSecondType: undefined
    },
    {
      desc: '缺失字段 - 缺少 file_path',
      input: {
        multi_agent_output: {
          files: [{ content: 'code without path' }]
        }
      },
      expectedLen: 1,
      expectedFirstType: 'add',
      expectedSecondType: undefined
    },
    {
      desc: 'Windows 路径 - 反斜杠',
      input: {
        multi_agent_output: {
          files: [{ file_path: 'app\\service\\user.py', content: 'code' }]
        }
      },
      expectedLen: 1,
      expectedFirstType: 'add',
      expectedSecondType: undefined
    },
    {
      desc: '特殊字符 - 中文路径',
      input: {
        multi_agent_output: {
          files: [{ file_path: 'app/文件.py', content: 'code' }]
        }
      },
      expectedLen: 1,
      expectedFirstType: 'add',
      expectedSecondType: undefined
    }
  ])('处理 $desc', ({ input, expectedLen, expectedFirstType, expectedSecondType }) => {
    const result = extractAllCodeChanges(input as Record<string, unknown>);

    expect(result).toHaveLength(expectedLen);
    if (expectedLen > 0 && expectedFirstType) {
      expect(result[0].changeType).toBe(expectedFirstType);
    }
    if (expectedLen > 1 && expectedSecondType) {
      expect(result[1].changeType).toBe(expectedSecondType);
    }
  });
});

describe('Utility: extractTestCodeChanges - 数据驱动测试', () => {
  it.each([
    {
      desc: '标准测试文件格式',
      input: {
        test_files: [
          { file_path: 'tests/test_user.py', content: 'test code' }
        ]
      },
      expectedLen: 1,
      expectedFileName: 'tests/test_user.py'
    },
    {
      desc: 'testing_result 嵌套',
      input: {
        testing_result: {
          test_files: [
            { file_path: 'tests/test_api.py', content: 'test' }
          ]
        }
      },
      expectedLen: 1,
      expectedFileName: 'tests/test_api.py'
    },
    {
      desc: 'agent_outputs.tester 嵌套',
      input: {
        multi_agent_output: {
          agent_outputs: {
            tester: {
              test_files: [
                { file_path: 'tests/test_nested.py', content: 'test' }
              ]
            }
          }
        }
      },
      expectedLen: 1,
      expectedFileName: 'tests/test_nested.py'
    },
    {
      desc: '空输入',
      input: {},
      expectedLen: 0,
      expectedFileName: undefined
    },
    {
      desc: '从 files 中过滤测试文件',
      input: {
        files: [
          { file_path: 'app/main.py', content: 'code' },
          { file_path: 'tests/test_main.py', content: 'test' }
        ]
      },
      expectedLen: 1,
      expectedFileName: 'tests/test_main.py'
    }
  ])('处理 $desc', ({ input, expectedLen, expectedFileName }) => {
    const result = extractTestCodeChanges(input as Record<string, unknown>);

    expect(result).toHaveLength(expectedLen);
    if (expectedLen > 0 && expectedFileName) {
      expect(result[0].fileName).toBe(expectedFileName);
    }
  });
});

describe('Utility: isCodeStage - 边界情况', () => {
  it.each([
    { name: 'CODING', expected: true, desc: '标准编码阶段' },
    { name: 'CODE_REVIEW', expected: true, desc: '代码审查阶段' },
    { name: 'coding', expected: true, desc: '小写编码' },
    { name: '编码', expected: true, desc: '中文编码' },
    { name: 'REQUIREMENT', expected: false, desc: '需求阶段' },
    { name: 'TESTING', expected: false, desc: '测试阶段' },
    { name: '', expected: false, desc: '空字符串' },
    { name: undefined, expected: false, desc: 'undefined' }
  ])('阶段 "$name" ($desc) 应该返回 $expected', ({ name, expected }) => {
    const stage = name ? {
      id: 1,
      name,
      status: 'running',
      input_data: {},
      output_data: {},
      created_at: new Date().toISOString()
    } as PipelineStage : null;

    expect(isCodeStage(stage)).toBe(expected);
  });
});

describe('Utility: isTestStage - 边界情况', () => {
  it.each([
    { name: 'UNIT_TESTING', expected: true, desc: '分层测试阶段' },
    { name: 'testing', expected: true, desc: '小写测试' },
    { name: '测试', expected: true, desc: '中文测试' },
    { name: 'CODING', expected: false, desc: '编码阶段' },
    { name: 'CODE_REVIEW', expected: false, desc: '审查阶段' },
    { name: '', expected: false, desc: '空字符串' }
  ])('阶段 "$name" ($desc) 应该返回 $expected', ({ name, expected }) => {
    const stage = name ? {
      id: 1,
      name,
      status: 'running',
      input_data: {},
      output_data: {},
      created_at: new Date().toISOString()
    } as PipelineStage : null;

    expect(isTestStage(stage)).toBe(expected);
  });
});

describe('边界情况：极端嵌套 JSON 结构', () => {
  it('应该处理循环引用风险', () => {
    // 虽然实际不太可能发生，但测试一下健壮性
    const circular: Record<string, unknown> = { files: [] };
    circular.self = circular;

    // 不应该抛出异常
    expect(() => extractAllCodeChanges(circular)).not.toThrow();
  });

  it('应该处理超深层嵌套', () => {
    // 创建深层嵌套对象
    let deep: Record<string, unknown> = { files: [{ file_path: 'deep.py', content: 'code' }] };
    for (let i = 0; i < 100; i++) {
      deep = { nested: deep };
    }

    // 不应该抛出异常
    expect(() => extractAllCodeChanges(deep)).not.toThrow();
  });

  it('应该处理超大数组', () => {
    const hugeArray = {
      multi_agent_output: {
        files: Array(1000).fill(null).map((_, i) => ({
          file_path: `file${i}.py`,
          content: `code ${i}`
        }))
      }
    };

    const result = extractAllCodeChanges(hugeArray);
    expect(result).toHaveLength(1000);
  });
});
