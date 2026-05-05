import { useState } from 'react';
import { TestTube2, CheckCircle2, XCircle, AlertCircle, FileCode2, Terminal } from 'lucide-react';
import { DiffViewer } from './DiffViewer';
import { TestCaseEditor } from './TestCaseEditor';
import { getLanguageFromPath } from '@utils/formatters';

// ============================================
// 单元测试阶段面板 - 展示 TesterAgent 输出
// 【修复】统一字段映射，支持多种输出结构
// ============================================

interface TestFile {
  file_path: string;
  content: string;
}

interface TestingResult {
  test_generated?: boolean;
  test_run_success?: boolean;
  test_error?: string;
  retry_count?: number;
  summary?: string;
}

interface TestingPanelProps {
  outputData?: Record<string, unknown>;
  pipelineId?: number;
}

export function TestingPanel({ outputData, pipelineId }: TestingPanelProps) {
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);

  if (!outputData) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无测试数据
      </div>
    );
  }

  // 【修复】从多种可能的字段路径提取测试文件
  const testFiles: TestFile[] = (() => {
    // 1. 尝试从顶层 test_files 提取
    const topLevelFiles = outputData.test_files as TestFile[] | undefined;
    if (topLevelFiles && Array.isArray(topLevelFiles)) {
      return topLevelFiles;
    }

    // 2. 尝试从 testing_result.test_files 提取
    const testingResult = outputData.testing_result as Record<string, unknown> | undefined;
    if (testingResult?.test_files && Array.isArray(testingResult.test_files)) {
      return testingResult.test_files as TestFile[];
    }

    return [];
  })();

  // 【修复】从多种可能的字段路径提取测试结果
  const testingResult: TestingResult = (() => {
    // 1. 尝试从顶层 testing_result 提取
    const topLevelResult = outputData.testing_result as TestingResult | undefined;
    if (topLevelResult) {
      return topLevelResult;
    }

    // 2. 从 outputData 直接提取相关字段
    return {
      test_generated: outputData.test_generated as boolean | undefined,
      test_run_success: outputData.test_run_success as boolean | undefined,
      test_error: outputData.test_error as string | undefined,
      retry_count: outputData.retry_count as number | undefined,
      summary: outputData.summary as string | undefined,
    };
  })();

  const currentTestFile = testFiles?.[selectedFileIndex];

  return (
    <div className="space-y-4">
      {/* 测试结果摘要 */}
      {testingResult && (
        <div className={`p-4 rounded-xl border ${
          testingResult.test_run_success
            ? 'bg-status-success/10 border-status-success/30'
            : testingResult.test_generated
            ? 'bg-status-warning/10 border-status-warning/30'
            : 'bg-status-error/10 border-status-error/30'
        }`}>
          <div className="flex items-start gap-3">
            {testingResult.test_run_success ? (
              <CheckCircle2 className="w-5 h-5 text-status-success flex-shrink-0 mt-0.5" />
            ) : testingResult.test_generated ? (
              <AlertCircle className="w-5 h-5 text-status-warning flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-5 h-5 text-status-error flex-shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h4 className={`text-sm font-medium ${
                testingResult.test_run_success
                  ? 'text-status-success'
                  : testingResult.test_generated
                  ? 'text-status-warning'
                  : 'text-status-error'
              }`}>
                {testingResult.test_run_success
                  ? '✅ 所有测试通过'
                  : testingResult.test_generated
                  ? '⚠️ 测试未通过'
                  : '❌ 未生成测试文件'}
              </h4>
              {testingResult.test_error && (
                <p className="text-xs text-text-secondary mt-1">{testingResult.test_error}</p>
              )}
              {testingResult.retry_count !== undefined && testingResult.retry_count > 0 && (
                <p className="text-xs text-text-tertiary mt-1">
                  重试次数: {testingResult.retry_count}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 测试文件统计 */}
      {testFiles && testFiles.length > 0 && (
        <div className="flex items-center gap-2 p-3 bg-bg-secondary rounded-lg">
          <TestTube2 className="w-4 h-4 text-brand-primary" />
          <span className="text-sm text-text-secondary">
            生成测试文件: <span className="font-medium text-text-primary">{testFiles.length}</span> 个
          </span>
        </div>
      )}

      {/* 测试文件选择 */}
      {testFiles && testFiles.length > 0 && (
        <div className="space-y-3">
          {testFiles.length > 1 && (
            <div className="flex gap-1 overflow-x-auto pb-1">
              {testFiles.map((file, i) => (
                <button
                  key={file.file_path}
                  onClick={() => setSelectedFileIndex(i)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono whitespace-nowrap transition-colors
                    ${i === selectedFileIndex
                      ? 'bg-brand-primary text-white'
                      : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'
                    }`}
                >
                  <FileCode2 className="w-3.5 h-3.5" />
                  {file.file_path.split('/').pop()}
                </button>
              ))}
            </div>
          )}

          {/* 测试文件内容 */}
          {currentTestFile && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 px-3 py-2 bg-bg-secondary rounded-lg">
                <FileCode2 className="w-4 h-4 text-brand-primary" />
                <code className="text-xs text-text-secondary flex-1 truncate">
                  {currentTestFile.file_path}
                </code>
                <span className="text-xs px-2 py-0.5 rounded font-medium bg-status-success/10 text-status-success">
                  测试文件
                </span>
              </div>
              <DiffViewer
                oldCode=""
                newCode={currentTestFile.content}
                oldFileName="/dev/null"
                newFileName={currentTestFile.file_path}
                language={getLanguageFromPath(currentTestFile.file_path)}
                splitView={false}
              />
            </div>
          )}

          {/* 测试用例编辑器 */}
          {currentTestFile && pipelineId && (
            <div className="pt-4 border-t border-border-default">
              <TestCaseEditor
                pipelineId={pipelineId}
                filePath={currentTestFile.file_path}
                initialContent={currentTestFile.content}
                language={getLanguageFromPath(currentTestFile.file_path)}
              />
            </div>
          )}
        </div>
      )}

      {/* 失败日志 */}
      {testingResult?.test_error && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Terminal className="w-4 h-4 text-status-error" />
            错误日志
          </h4>
          <div className="p-3 bg-bg-secondary rounded-xl border border-status-error/30 max-h-48 overflow-y-auto">
            <pre className="text-xs text-status-error whitespace-pre-wrap font-mono">
              {testingResult.test_error}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
