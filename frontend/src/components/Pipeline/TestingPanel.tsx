import { useState } from 'react';
import { TestTube2, CheckCircle2, XCircle, AlertCircle, FileCode2, Terminal, ShieldCheck, Layers, FileSearch, AlertTriangle, Info } from 'lucide-react';
import { DiffViewer } from './DiffViewer';
import { TestCaseEditor } from './TestCaseEditor';
import { UserDecisionPanel } from './UserDecisionPanel';
import { getLanguageFromPath } from '@utils/formatters';

// ============================================
// 分层测试阶段面板 - 展示 TesterAgent 输出
// 【修复】统一字段映射，支持多种输出结构
// 【新增】支持用户决策选项
// 【新增】展示 AI 审查报告
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
  contract_check?: {
    passed: boolean;
    missing_symbols: string[];
    total_symbols: number;
  };
  overall_success?: boolean;
  test_run_layers?: Array<{
    layer: string;
    passed: boolean;
    summary: string;
    failed_tests: string[];
  }>;
}

interface ReviewIssue {
  severity: 'high' | 'medium' | 'low';
  category: string;
  description: string;
  suggestion: string;
  file_path?: string;
  line_number?: number;
}

interface ReviewReport {
  issues: ReviewIssue[];
  overall_assessment: string;
  summary: string;
  improvement_suggestions: string[];
  risk_level: 'high' | 'medium' | 'low';
  approval_recommendation: 'approve' | 'approve_with_caution' | 'reject';
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

  // 【新增】提取 AI 审查报告
  const reviewReport: ReviewReport | undefined = outputData?.review_report as ReviewReport | undefined;

  // 获取风险等级对应的颜色
  const getRiskLevelColor = (riskLevel: string) => {
    switch (riskLevel) {
      case 'high': return 'text-status-error bg-status-error/10 border-status-error/30';
      case 'medium': return 'text-status-warning bg-status-warning/10 border-status-warning/30';
      case 'low': return 'text-status-success bg-status-success/10 border-status-success/30';
      default: return 'text-text-secondary bg-bg-tertiary border-border-default';
    }
  };

  // 获取审批建议对应的颜色
  const getApprovalColor = (recommendation: string) => {
    switch (recommendation) {
      case 'approve': return 'text-status-success';
      case 'approve_with_caution': return 'text-status-warning';
      case 'reject': return 'text-status-error';
      default: return 'text-text-secondary';
    }
  };

  // 获取审批建议文本
  const getApprovalText = (recommendation: string) => {
    switch (recommendation) {
      case 'approve': return '✅ 建议批准';
      case 'approve_with_caution': return '⚠️ 建议谨慎批准';
      case 'reject': return '❌ 建议拒绝';
      default: return '❓ 待定';
    }
  };

  return (
    <div className="space-y-4">
      {/* 【新增】AI 审查报告 */}
      {reviewReport && (
        <div className={`p-4 rounded-xl border ${getRiskLevelColor(reviewReport.risk_level)}`}>
          <div className="flex items-start gap-3">
            <FileSearch className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">🤖 AI 代码审查报告</h4>
                <span className={`text-xs font-medium ${getApprovalColor(reviewReport.approval_recommendation)}`}>
                  {getApprovalText(reviewReport.approval_recommendation)}
                </span>
              </div>

              {/* 风险等级 */}
              <div className="mt-2 flex items-center gap-2">
                <span className="text-xs text-text-secondary">风险等级:</span>
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                  reviewReport.risk_level === 'high' ? 'bg-status-error text-white' :
                  reviewReport.risk_level === 'medium' ? 'bg-status-warning text-white' :
                  'bg-status-success text-white'
                }`}>
                  {reviewReport.risk_level === 'high' ? '高风险' :
                   reviewReport.risk_level === 'medium' ? '中风险' : '低风险'}
                </span>
              </div>

              {/* 总体评估 */}
              {reviewReport.overall_assessment && (
                <p className="text-xs text-text-secondary mt-2">
                  {reviewReport.overall_assessment}
                </p>
              )}

              {/* 问题列表 */}
              {reviewReport.issues && reviewReport.issues.length > 0 && (
                <div className="mt-3 space-y-2">
                  <p className="text-xs font-medium text-text-primary">
                    发现问题 ({reviewReport.issues.length}):
                  </p>
                  {reviewReport.issues.slice(0, 5).map((issue, idx) => (
                    <div
                      key={idx}
                      className={`p-2 rounded text-xs ${
                        issue.severity === 'high' ? 'bg-status-error/10 border border-status-error/20' :
                        issue.severity === 'medium' ? 'bg-status-warning/10 border border-status-warning/20' :
                        'bg-status-success/10 border border-status-success/20'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        {issue.severity === 'high' ? (
                          <AlertTriangle className="w-3 h-3 text-status-error" />
                        ) : issue.severity === 'medium' ? (
                          <AlertCircle className="w-3 h-3 text-status-warning" />
                        ) : (
                          <Info className="w-3 h-3 text-status-success" />
                        )}
                        <span className="font-medium">{issue.category}</span>
                        <span className="text-text-tertiary">|</span>
                        <span className={
                          issue.severity === 'high' ? 'text-status-error' :
                          issue.severity === 'medium' ? 'text-status-warning' :
                          'text-status-success'
                        }>
                          {issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低'}优先级
                        </span>
                      </div>
                      <p className="text-text-secondary mt-1">{issue.description}</p>
                      {issue.suggestion && (
                        <p className="text-text-tertiary mt-0.5">💡 {issue.suggestion}</p>
                      )}
                    </div>
                  ))}
                  {reviewReport.issues.length > 5 && (
                    <p className="text-xs text-text-tertiary">
                      ... 还有 {reviewReport.issues.length - 5} 个问题
                    </p>
                  )}
                </div>
              )}

              {/* 改进建议 */}
              {reviewReport.improvement_suggestions && reviewReport.improvement_suggestions.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-text-primary">改进建议:</p>
                  <ul className="mt-1 space-y-0.5">
                    {reviewReport.improvement_suggestions.map((suggestion, idx) => (
                      <li key={idx} className="text-xs text-text-secondary flex items-start gap-1">
                        <span className="text-brand-primary">•</span>
                        {suggestion}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 测试结果摘要 */}
      {testingResult && (
        <div className={`p-4 rounded-xl border ${
          testingResult.overall_success || testingResult.test_run_success
            ? 'bg-status-success/10 border-status-success/30'
            : testingResult.test_generated
            ? 'bg-status-warning/10 border-status-warning/30'
            : 'bg-status-error/10 border-status-error/30'
        }`}>
          <div className="flex items-start gap-3">
            {testingResult.overall_success || testingResult.test_run_success ? (
              <CheckCircle2 className="w-5 h-5 text-status-success flex-shrink-0 mt-0.5" />
            ) : testingResult.test_generated ? (
              <AlertCircle className="w-5 h-5 text-status-warning flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-5 h-5 text-status-error flex-shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h4 className={`text-sm font-medium ${
                testingResult.overall_success || testingResult.test_run_success
                  ? 'text-status-success'
                  : testingResult.test_generated
                  ? 'text-status-warning'
                  : 'text-status-error'
              }`}>
                {testingResult.overall_success
                  ? '✅ 契约检查通过且所有测试通过'
                  : testingResult.test_run_success
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

      {/* 契约检查结果 */}
      {testingResult?.contract_check && (
        <div className={`p-4 rounded-xl border ${
          testingResult.contract_check.passed
            ? 'bg-status-success/10 border-status-success/30'
            : 'bg-status-error/10 border-status-error/30'
        }`}>
          <div className="flex items-start gap-3">
            <ShieldCheck className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
              testingResult.contract_check.passed ? 'text-status-success' : 'text-status-error'
            }`} />
            <div className="flex-1">
              <h4 className={`text-sm font-medium ${
                testingResult.contract_check.passed ? 'text-status-success' : 'text-status-error'
              }`}>
                {testingResult.contract_check.passed
                  ? `✅ 契约检查通过 (${testingResult.contract_check.total_symbols} 个符号)`
                  : `❌ 契约检查失败 (${testingResult.contract_check.missing_symbols.length} 个符号未实现)`}
              </h4>
              {!testingResult.contract_check.passed && testingResult.contract_check.missing_symbols.length > 0 && (
                <div className="mt-2 space-y-1">
                  <p className="text-xs text-text-secondary">未实现的符号：</p>
                  <ul className="text-xs text-status-error space-y-0.5">
                    {testingResult.contract_check.missing_symbols.map((sym, idx) => (
                      <li key={idx}>• {sym}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 分层测试详情 */}
      {testingResult?.test_run_layers && testingResult.test_run_layers.length > 0 && (
        <div className="p-4 bg-bg-secondary rounded-xl border border-border-default">
          <div className="flex items-center gap-2 mb-3">
            <Layers className="w-4 h-4 text-brand-primary" />
            <h4 className="text-sm font-medium text-text-primary">分层测试结果</h4>
          </div>
          <div className="space-y-2">
            {testingResult.test_run_layers.map((layer, idx) => (
              <div key={idx} className={`flex items-center justify-between p-2 rounded-lg ${
                layer.passed ? 'bg-status-success/10' : 'bg-status-error/10'
              }`}>
                <div className="flex items-center gap-2">
                  {layer.passed ? (
                    <CheckCircle2 className="w-4 h-4 text-status-success" />
                  ) : (
                    <XCircle className="w-4 h-4 text-status-error" />
                  )}
                  <span className="text-xs font-medium text-text-primary">{layer.layer}</span>
                </div>
                <span className={`text-xs ${layer.passed ? 'text-status-success' : 'text-status-error'}`}>
                  {layer.passed ? '通过' : '失败'}
                </span>
              </div>
            ))}
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

      {/* 【新增】测试失败时显示用户决策选项 */}
      {pipelineId && testingResult && !testingResult.test_run_success && testingResult.test_generated && (
        <UserDecisionPanel
          pipelineId={pipelineId}
          title="测试未通过"
          message="当前测试未能完全通过，您可以选择以下操作："
          suggestion="建议重试或完善需求说明"
        />
      )}
    </div>
  );
}
