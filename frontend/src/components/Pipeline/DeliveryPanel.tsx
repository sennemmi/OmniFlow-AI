import { GitBranch, GitCommit, ExternalLink, CheckCircle2, FileEdit, Clock } from 'lucide-react';

// ============================================
// 交付阶段面板 - 展示 Delivery 输出
// 【修复】增加空值保护，防止字段缺失导致白屏
// ============================================

interface ExecutionSummary {
  success: number;
  total: number;
}

interface DeliveryPanelProps {
  outputData?: Record<string, unknown>;
}

export function DeliveryPanel({ outputData }: DeliveryPanelProps) {
  if (!outputData) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无交付数据
      </div>
    );
  }

  // 【修复】使用可选链和默认值，防止字段缺失导致白屏
  const gitBranch = (outputData.git_branch as string) || '';
  const commitHash = (outputData.commit_hash as string) || '';
  const prUrl = (outputData.pr_url as string) || '';
  const prCreated = (outputData.pr_created as boolean) ?? false;
  const executionSummary = outputData.execution_summary as ExecutionSummary | undefined;

  return (
    <div className="space-y-6">
      {/* 成功提示 */}
      <div className="p-4 bg-status-success/10 border border-status-success/30 rounded-xl">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-status-success flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-status-success">
              ✅ Pipeline 执行成功完成
            </h4>
            <p className="text-xs text-text-secondary mt-1">
              代码已成功提交到 Git 仓库并创建 Pull Request
            </p>
          </div>
        </div>
      </div>

      {/* 交付物信息 */}
      <div className="space-y-4">
        <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-brand-primary" />
          交付物信息
        </h4>

        {/* Git 分支 */}
        {gitBranch ? (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Git 分支</span>
              </div>
              <code className="text-sm font-mono text-brand-primary">{gitBranch}</code>
            </div>
          </div>
        ) : (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Git 分支</span>
              </div>
              <span className="text-sm text-text-tertiary">未创建</span>
            </div>
          </div>
        )}

        {/* Commit Hash */}
        {commitHash ? (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitCommit className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Commit Hash</span>
              </div>
              <code className="text-sm font-mono text-text-secondary">
                {commitHash.slice(0, 8)}
              </code>
            </div>
          </div>
        ) : (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitCommit className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Commit Hash</span>
              </div>
              <span className="text-sm text-text-tertiary">未知</span>
            </div>
          </div>
        )}

        {/* PR 链接 */}
        {prUrl ? (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ExternalLink className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Pull Request</span>
              </div>
              <a
                href={prUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-brand-primary hover:underline"
              >
                查看 PR
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>
        ) : (
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ExternalLink className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs text-text-tertiary">Pull Request</span>
              </div>
              <span className="text-sm text-text-tertiary">未创建</span>
            </div>
          </div>
        )}

        {/* PR 创建状态 */}
        <div className={`p-3 rounded-lg border ${
          prCreated
            ? 'bg-status-success/5 border-status-success/20'
            : 'bg-status-warning/5 border-status-warning/20'
        }`}>
          <div className="flex items-center gap-2">
            {prCreated ? (
              <CheckCircle2 className="w-4 h-4 text-status-success" />
            ) : (
              <Clock className="w-4 h-4 text-status-warning" />
            )}
            <span className={`text-sm ${
              prCreated ? 'text-status-success' : 'text-status-warning'
            }`}>
              {prCreated ? 'PR 创建成功' : 'PR 创建失败或未创建'}
            </span>
          </div>
        </div>
      </div>

      {/* 变更统计 */}
      {executionSummary && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FileEdit className="w-4 h-4 text-brand-primary" />
            变更统计
          </h4>
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-bg-secondary rounded-lg border border-border-default text-center">
              <div className="text-2xl font-semibold text-status-success">
                {executionSummary.success ?? 0}
              </div>
              <div className="text-xs text-text-tertiary mt-1">成功处理文件</div>
            </div>
            <div className="p-3 bg-bg-secondary rounded-lg border border-border-default text-center">
              <div className="text-2xl font-semibold text-text-primary">
                {executionSummary.total ?? 0}
              </div>
              <div className="text-xs text-text-tertiary mt-1">总文件数</div>
            </div>
          </div>
          {(executionSummary.total ?? 0) > 0 && (
            <div className="p-3 bg-bg-secondary rounded-lg">
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">成功率</span>
                <span className="font-medium text-text-primary">
                  {Math.round(((executionSummary.success ?? 0) / (executionSummary.total || 1)) * 100)}%
                </span>
              </div>
              <div className="mt-2 h-2 bg-bg-tertiary rounded-full overflow-hidden">
                <div
                  className="h-full bg-status-success rounded-full transition-all"
                  style={{
                    width: `${((executionSummary.success ?? 0) / (executionSummary.total || 1)) * 100}%`
                  }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
