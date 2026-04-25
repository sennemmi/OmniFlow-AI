import type { PipelineStage } from '@types';

// 代码变更接口
export interface CodeChange {
  oldCode: string;
  newCode: string;
  fileName: string;
  isNew: boolean;       // 新建文件
  changeType: string;   // add / modify / delete
}

// 提取所有代码变更（支持多文件，增强容错）
export function extractAllCodeChanges(
  outputData: Record<string, unknown> | undefined,
  inputData?: Record<string, unknown> | undefined
): CodeChange[] {
  // 尝试从 output_data 或 input_data.coding_output 中寻找数据
  const sourceData = outputData || (inputData?.coding_output as Record<string, unknown>) || inputData;
  if (!sourceData) return [];

  const extractFromFiles = (files: Array<Record<string, string>>): CodeChange[] => {
    return files
      .filter(f => {
        // 过滤掉测试文件，单独显示
        const path = f.file_path || '';
        return !path.includes('test_') && !path.startsWith('tests/');
      })
      .map(f => ({
        oldCode: f.original_content ?? '',          // null/undefined → 空字符串（新建文件）
        newCode: f.content ?? '',
        fileName: f.file_path || 'unknown',
        isNew: f.original_content == null,          // null 或 undefined 都视为新建
        changeType: f.change_type || (f.original_content == null ? 'add' : 'modify'),
      }));
  };

  // 新版 multi_agent_output
  const multiAgent = sourceData.multi_agent_output as Record<string, unknown> | undefined;
  if (Array.isArray(multiAgent?.files) && (multiAgent!.files as unknown[]).length > 0) {
    return extractFromFiles(multiAgent!.files as Array<Record<string, string>>);
  }

  // 旧版 coder_output
  const coderOut = sourceData.coder_output as Record<string, unknown> | undefined;
  if (Array.isArray(coderOut?.files) && (coderOut!.files as unknown[]).length > 0) {
    return extractFromFiles(coderOut!.files as Array<Record<string, string>>);
  }

  // 直接从 sourceData.files 读取（兼容 CODE_REVIEW 阶段的 input_data）
  if (Array.isArray(sourceData.files) && (sourceData.files as unknown[]).length > 0) {
    return extractFromFiles(sourceData.files as Array<Record<string, string>>);
  }

  return [];
}

// 判断是否是代码阶段
export function isCodeStage(stage: PipelineStage | null): boolean {
  if (!stage) return false;
  const name = stage.name?.toLowerCase() || '';
  return name.includes('code') ||
         name.includes('编码') ||
         stage.icon === 'coder' ||
         stage.name === 'CODING' ||
         stage.name === 'CODE_REVIEW';
}
