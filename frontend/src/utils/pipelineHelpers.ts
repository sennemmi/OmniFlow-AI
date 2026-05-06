import type { PipelineStage } from '@types';

// 代码变更接口
export interface CodeChange {
  oldCode: string;
  newCode: string;
  fileName: string;
  isNew: boolean;       // 新建文件
  changeType: string;   // add / modify / delete
}

// 判断是否是测试文件
const isTestFile = (path: string): boolean => {
  const lowerPath = path.toLowerCase();
  const isInTestsDir = lowerPath.startsWith('tests/') || lowerPath.includes('/tests/');
  return lowerPath.includes('test_') ||
         isInTestsDir ||
         lowerPath.includes('.test.') ||
         lowerPath.includes('.spec.') ||
         lowerPath.endsWith('_test.py') ||
         lowerPath.endsWith('test.py');
};

// 统一从 files 数组提取代码变更
const extractFromFiles = (
  files: Array<Record<string, string>>,
  options?: { includeTests?: boolean }
): CodeChange[] => {
  return files
    .filter(f => {
      if (options?.includeTests) return true;
      return !isTestFile(f.file_path || '');
    })
    .map(f => ({
      oldCode: f.original_content ?? '',
      newCode: f.content ?? '',
      fileName: f.file_path || 'unknown',
      isNew: f.original_content == null,
      changeType: f.change_type || (f.original_content == null ? 'add' : 'modify'),
    }));
};

// 统一查找 sourceData 中的 files 数组（按优先级）
const findFilesArray = (
  sourceData: Record<string, unknown> | undefined
): Array<Record<string, string>> | undefined => {
  if (!sourceData) return undefined;

  const candidates = [
    (sourceData.multi_agent_output as Record<string, unknown>)?.files,
    (sourceData.coder_output as Record<string, unknown>)?.files,
    sourceData.files,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate as Array<Record<string, string>>;
    }
  }
  return undefined;
};

// 提取所有代码变更（统一路径，优先读取 multi_agent_output / coder_output / files）
export function extractAllCodeChanges(
  outputData: Record<string, unknown> | undefined,
  inputData?: Record<string, unknown> | undefined
): CodeChange[] {
  const sourceData = outputData || (inputData?.coding_output as Record<string, unknown>) || inputData;
  const files = findFilesArray(sourceData);
  if (files) return extractFromFiles(files);

  // fallback：遍历 inputData 和 outputData 的 coding_output
  const fallbackSources = [
    inputData,
    inputData?.coding_output as Record<string, unknown> | undefined,
    outputData?.coding_output as Record<string, unknown> | undefined,
  ];

  for (const fallback of fallbackSources) {
    const fallbackFiles = findFilesArray(fallback);
    if (fallbackFiles) return extractFromFiles(fallbackFiles);
  }

  return [];
}

// 判断是否是代码阶段
export function isCodeStage(stage: PipelineStage | null): boolean {
  if (!stage) return false;
  const name = stage.name?.toLowerCase() || '';
  return name.includes('code') ||
         name.includes('编码') ||
         stage.name === 'CODING' ||
         stage.name === 'CODE_REVIEW';
}

// 判断是否是测试阶段
export function isTestStage(stage: PipelineStage | null): boolean {
  if (!stage) return false;
  const name = stage.name?.toLowerCase() || '';
  return name.includes('test') ||
         name.includes('测试') ||
         stage.name === 'UNIT_TESTING';
}

// 统一查找测试文件数组
const findTestFilesArray = (
  outputData: Record<string, unknown> | undefined
): Array<Record<string, string>> | undefined => {
  if (!outputData) return undefined;

  const candidates = [
    outputData.test_files,
    (outputData.testing_result as Record<string, unknown>)?.test_files,
    (outputData.multi_agent_output as Record<string, unknown>)?.agent_outputs,
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate as Array<Record<string, string>>;
    }
    // agent_outputs.tester 嵌套
    if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
      const tester = (candidate as Record<string, unknown>).tester as Record<string, unknown> | undefined;
      if (tester?.test_files && Array.isArray(tester.test_files)) {
        return tester.test_files as Array<Record<string, string>>;
      }
      if (tester?.files && Array.isArray(tester.files)) {
        return tester.files as Array<Record<string, string>>;
      }
    }
  }
  return undefined;
};

// 提取测试代码变更（统一路径）
export function extractTestCodeChanges(
  outputData: Record<string, unknown> | undefined,
  inputData?: Record<string, unknown> | undefined
): CodeChange[] {
  // 1. 优先从 outputData 的各种路径提取
  const files = findTestFilesArray(outputData);
  if (files) return extractFromFiles(files, { includeTests: true });

  // 2. 从 inputData.coding_output.agent_outputs.tester 提取
  if (inputData?.coding_output) {
    const codingOutput = inputData.coding_output as Record<string, unknown>;
    const agentOutputs = codingOutput?.agent_outputs as Record<string, unknown> | undefined;
    if (agentOutputs?.tester) {
      const testerOutput = agentOutputs.tester as Record<string, unknown>;
      if (testerOutput?.test_files && Array.isArray(testerOutput.test_files)) {
        return extractFromFiles(testerOutput.test_files as Array<Record<string, string>>, { includeTests: true });
      }
      if (testerOutput?.files && Array.isArray(testerOutput.files)) {
        return extractFromFiles(testerOutput.files as Array<Record<string, string>>, { includeTests: true });
      }
    }
  }

  // 3. 从 sourceData.files 中过滤测试文件（兼容旧格式）
  const sourceData = outputData || inputData;
  if (Array.isArray(sourceData?.files) && (sourceData!.files as unknown[]).length > 0) {
    const allFiles = sourceData!.files as Array<Record<string, string>>;
    const testFiles = allFiles.filter(f => isTestFile(f.file_path || ''));
    if (testFiles.length > 0) {
      return extractFromFiles(testFiles, { includeTests: true });
    }
  }

  return [];
}
