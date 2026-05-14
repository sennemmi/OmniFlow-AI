import { useState } from 'react';
import { Code2, FilePlus, FileEdit, FileMinus, GitCommit, FileSearch, AlertTriangle, AlertCircle, Info } from 'lucide-react';
import { DiffViewer } from './DiffViewer';
import { getLanguageFromPath } from '@utils/formatters';
import { extractAllCodeChanges, type CodeChange } from '@utils/pipelineHelpers';

// ============================================
// 代码生成阶段面板 - 展示 CoderAgent 输出
// 【修复】统一调用 pipelineHelpers，消除重复提取逻辑
// 【新增】展示 AI 审查报告（从 UNIT_TESTING 阶段获取）
// ============================================

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

interface CodingPanelProps {
  outputData?: Record<string, unknown>;
  codeChanges?: CodeChange[]; // 【新增】可选的代码变更数据（来自 diff 接口）
  reviewReport?: ReviewReport; // 【新增】AI 审查报告（从 UNIT_TESTING 阶段传入）
}

export function CodingPanel({ outputData, codeChanges: propCodeChanges, reviewReport }: CodingPanelProps) {
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);

  // 【修复】优先使用传入的 codeChanges（来自 diff 接口），否则从 outputData 提取
  const codeChanges: CodeChange[] = propCodeChanges && propCodeChanges.length > 0
    ? propCodeChanges
    : extractAllCodeChanges(outputData);

  // 【修复】从多种可能的字段路径提取摘要
  const summary = (() => {
    if (!outputData) return undefined;
    // 优先从 coder_output.summary 提取
    const coderOutput = outputData.coder_output as Record<string, unknown> | undefined;
    return (coderOutput?.summary as string) || (outputData.summary as string) || undefined;
  })();

  // 统计变更
  const stats = {
    added: codeChanges.filter(c => c.changeType === 'add').length,
    modified: codeChanges.filter(c => c.changeType === 'modify').length,
    deleted: codeChanges.filter(c => c.changeType === 'delete').length,
  };

  const currentChange = codeChanges[selectedFileIndex];

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

  if (codeChanges.length === 0) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无代码变更数据
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 【新增】AI 审查报告（从 UNIT_TESTING 阶段传入） */}
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

      {/* 变更摘要 */}
      {summary && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <GitCommit className="w-4 h-4 text-brand-primary" />
            变更摘要
          </h4>
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <p className="text-sm text-text-secondary">
              {summary}
            </p>
          </div>
        </div>
      )}

      {/* 变更统计 */}
      <div className="flex items-center gap-4 p-3 bg-bg-secondary rounded-lg">
        <div className="flex items-center gap-2">
          <FilePlus className="w-4 h-4 text-status-success" />
          <span className="text-sm text-text-secondary">
            新增 <span className="font-medium text-status-success">{stats.added}</span> 个文件
          </span>
        </div>
        <div className="w-px h-4 bg-border-default" />
        <div className="flex items-center gap-2">
          <FileEdit className="w-4 h-4 text-status-warning" />
          <span className="text-sm text-text-secondary">
            修改 <span className="font-medium text-status-warning">{stats.modified}</span> 个文件
          </span>
        </div>
        <div className="w-px h-4 bg-border-default" />
        <div className="flex items-center gap-2">
          <FileMinus className="w-4 h-4 text-status-error" />
          <span className="text-sm text-text-secondary">
            删除 <span className="font-medium text-status-error">{stats.deleted}</span> 个文件
          </span>
        </div>
        <div className="flex-1" />
        <div className="text-sm text-text-tertiary">
          共 {codeChanges.length} 个文件
        </div>
      </div>

      {/* 文件选择 Tab */}
      {codeChanges.length > 1 && (
        <div className="flex gap-1 overflow-x-auto pb-1">
          {codeChanges.map((change, i) => (
            <button
              key={change.fileName}
              onClick={() => setSelectedFileIndex(i)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono whitespace-nowrap transition-colors
                ${i === selectedFileIndex
                  ? 'bg-brand-primary text-white'
                  : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'
                }`}
            >
              {change.changeType === 'add' && <span className="text-status-success font-bold">+</span>}
              {change.changeType === 'modify' && <span className="text-status-warning">~</span>}
              {change.changeType === 'delete' && <span className="text-status-error font-bold">-</span>}
              {change.fileName.split('/').pop()}
            </button>
          ))}
        </div>
      )}

      {/* Diff 查看器 */}
      {currentChange && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-3 py-2 bg-bg-secondary rounded-lg">
            <Code2 className="w-4 h-4 text-brand-primary" />
            <code className="text-xs text-text-secondary flex-1 truncate">
              {currentChange.fileName}
            </code>
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${
              currentChange.changeType === 'add'
                ? 'bg-status-success/10 text-status-success'
                : currentChange.changeType === 'delete'
                ? 'bg-status-error/10 text-status-error'
                : 'bg-status-warning/10 text-status-warning'
            }`}>
              {currentChange.changeType === 'add' ? '新增' : currentChange.changeType === 'delete' ? '删除' : '修改'}
            </span>
          </div>
          <DiffViewer
            oldCode={currentChange.oldCode}
            newCode={currentChange.newCode}
            oldFileName={currentChange.changeType === 'add' ? '/dev/null' : currentChange.fileName}
            newFileName={currentChange.changeType === 'delete' ? '/dev/null' : currentChange.fileName}
            language={getLanguageFromPath(currentChange.fileName)}
            splitView={true}
          />
        </div>
      )}
    </div>
  );
}
