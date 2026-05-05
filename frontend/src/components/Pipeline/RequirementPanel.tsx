import { FileText, CheckCircle2, Clock, FolderTree, Target } from 'lucide-react';

// ============================================
// 需求分析阶段面板 - 展示 ArchitectAgent 输出
// ============================================

interface RequirementPanelProps {
  outputData?: Record<string, unknown>;
}

export function RequirementPanel({ outputData }: RequirementPanelProps) {
  if (!outputData) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无需求分析数据
      </div>
    );
  }

  const featureDescription = outputData.feature_description as string | undefined;
  const acceptanceCriteria = outputData.acceptance_criteria as string[] | undefined;
  const affectedFiles = outputData.affected_files as string[] | undefined;
  const estimatedEffort = outputData.estimated_effort as string | undefined;
  const technicalDesign = outputData.technical_design as string | undefined;

  return (
    <div className="space-y-6">
      {/* 功能描述 */}
      {featureDescription && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Target className="w-4 h-4 text-brand-primary" />
            功能描述
          </h4>
          <div className="p-4 bg-bg-secondary rounded-xl border border-border-default">
            <p className="text-sm text-text-secondary leading-relaxed">
              {featureDescription}
            </p>
          </div>
        </div>
      )}

      {/* 验收标准 */}
      {acceptanceCriteria && acceptanceCriteria.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-status-success" />
            验收标准 ({acceptanceCriteria.length} 条)
          </h4>
          <div className="space-y-2">
            {acceptanceCriteria.map((criteria, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 p-3 bg-status-success/5 border border-status-success/20 rounded-lg"
              >
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-status-success/10 text-status-success text-xs font-medium flex items-center justify-center">
                  {idx + 1}
                </span>
                <span className="text-sm text-text-secondary">{criteria}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 受影响文件 */}
      {affectedFiles && affectedFiles.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-brand-primary" />
            受影响文件 ({affectedFiles.length} 个)
          </h4>
          <div className="p-3 bg-bg-secondary rounded-xl border border-border-default">
            <div className="space-y-1">
              {affectedFiles.map((file, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-2 text-sm font-mono text-text-secondary"
                >
                  <span className="text-text-tertiary">•</span>
                  <span className="truncate">{file}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 工作量评估 */}
      {estimatedEffort && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Clock className="w-4 h-4 text-status-warning" />
            工作量评估
          </h4>
          <div className="p-3 bg-status-warning/5 border border-status-warning/20 rounded-lg">
            <span className="text-sm text-text-secondary">{estimatedEffort}</span>
          </div>
        </div>
      )}

      {/* 技术设计预览 */}
      {technicalDesign && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FileText className="w-4 h-4 text-brand-primary" />
            技术设计预览
          </h4>
          <div className="p-4 bg-bg-secondary rounded-xl border border-border-default max-h-48 overflow-y-auto">
            <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono">
              {technicalDesign.length > 500 ? technicalDesign.slice(0, 500) + '...' : technicalDesign}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
