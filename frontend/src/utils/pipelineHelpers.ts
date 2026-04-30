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
  // 检查路径是否以 tests/ 开头（支持 Tests/, TESTS/ 等大小写变体）
  const isInTestsDir = lowerPath.startsWith('tests/') || lowerPath.includes('/tests/');
  return lowerPath.includes('test_') ||
         isInTestsDir ||
         lowerPath.includes('.test.') ||
         lowerPath.includes('.spec.') ||
         lowerPath.endsWith('_test.py') ||
         lowerPath.endsWith('test.py');
};

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
        // 过滤掉测试文件，单独在 UNIT_TESTING 阶段显示
        const path = f.file_path || '';
        return !isTestFile(path);
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

// 判断是否是测试阶段
export function isTestStage(stage: PipelineStage | null): boolean {
  if (!stage) return false;
  const name = stage.name?.toLowerCase() || '';
  return name.includes('test') ||
         name.includes('测试') ||
         stage.name === 'UNIT_TESTING';
}

// 提取测试代码变更（支持多文件）
export function extractTestCodeChanges(
  outputData: Record<string, unknown> | undefined,
  inputData?: Record<string, unknown> | undefined
): CodeChange[] {
  const extractFromFiles = (files: Array<Record<string, string>>): CodeChange[] => {
    return files.map(f => ({
      oldCode: f.original_content ?? '',
      newCode: f.content ?? '',
      fileName: f.file_path || 'unknown',
      isNew: f.original_content == null,
      changeType: f.change_type || (f.original_content == null ? 'add' : 'modify'),
    }));
  };

  // 1. 从 output_data.testing_result.test_files 中提取（UNIT_TESTING 阶段的标准格式）
  if (outputData?.testing_result) {
    const testingResult = outputData.testing_result as Record<string, unknown>;
    if (testingResult?.test_files && Array.isArray(testingResult.test_files)) {
      return extractFromFiles(testingResult.test_files as Array<Record<string, string>>);
    }
  }

  // 2. 从 input_data.coding_output.agent_outputs.tester 中提取（UNIT_TESTING 阶段的 input_data）
  if (inputData?.coding_output) {
    const codingOutput = inputData.coding_output as Record<string, unknown>;
    const agentOutputs = codingOutput?.agent_outputs as Record<string, unknown> | undefined;
    if (agentOutputs?.tester) {
      const testerOutput = agentOutputs.tester as Record<string, unknown>;
      if (testerOutput?.test_files && Array.isArray(testerOutput.test_files)) {
        return extractFromFiles(testerOutput.test_files as Array<Record<string, string>>);
      }
      if (testerOutput?.files && Array.isArray(testerOutput.files)) {
        return extractFromFiles(testerOutput.files as Array<Record<string, string>>);
      }
    }
  }

  // 3. 从 output_data.multi_agent_output.agent_outputs.tester 中提取（CODING 阶段的格式）
  if (outputData?.multi_agent_output) {
    const multiAgent = outputData.multi_agent_output as Record<string, unknown>;
    const agentOutputs = multiAgent?.agent_outputs as Record<string, unknown> | undefined;
    if (agentOutputs?.tester) {
      const testerOutput = agentOutputs.tester as Record<string, unknown>;
      if (testerOutput?.test_files && Array.isArray(testerOutput.test_files)) {
        return extractFromFiles(testerOutput.test_files as Array<Record<string, string>>);
      }
      if (testerOutput?.files && Array.isArray(testerOutput.files)) {
        return extractFromFiles(testerOutput.files as Array<Record<string, string>>);
      }
    }
  }

  // 4. 从 sourceData.files 中过滤测试文件（兼容旧格式）
  const sourceData = outputData || inputData;
  if (Array.isArray(sourceData?.files) && (sourceData!.files as unknown[]).length > 0) {
    const files = sourceData!.files as Array<Record<string, string>>;
    const testFiles = files.filter(f => isTestFile(f.file_path || ''));
    if (testFiles.length > 0) {
      return extractFromFiles(testFiles);
    }
  }

  return [];
}
