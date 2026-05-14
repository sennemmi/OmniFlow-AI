import { useState, useMemo } from 'react';
import {
  ShieldCheck,
  AlertTriangle,
  AlertCircle,
  Info,
  FileWarning,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Filter,
  Bug,
  Lock,
  Zap,
  Code,
  Wrench,
  FileCode
} from 'lucide-react';
import type { ReviewReport } from '@types';

// ============================================
// 代码审查报告面板 - 展示 AI 生成的审查报告
// ============================================

interface ReviewReportPanelProps {
  report?: ReviewReport;
}

type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';
type CategoryFilter = 'all' | 'bug' | 'security' | 'performance' | 'style' | 'maintainability';

const severityConfig = {
  critical: {
    label: '严重',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    borderColor: 'border-status-error/30',
    icon: XCircle,
  },
  high: {
    label: '高',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    borderColor: 'border-status-error/30',
    icon: AlertTriangle,
  },
  medium: {
    label: '中',
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    borderColor: 'border-status-warning/30',
    icon: AlertCircle,
  },
  low: {
    label: '低',
    color: 'text-brand-primary',
    bgColor: 'bg-brand-primary/10',
    borderColor: 'border-brand-primary/30',
    icon: Info,
  },
};

const categoryConfig = {
  bug: {
    label: 'Bug',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    icon: Bug,
  },
  security: {
    label: '安全',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    icon: Lock,
  },
  performance: {
    label: '性能',
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    icon: Zap,
  },
  style: {
    label: '风格',
    color: 'text-brand-primary',
    bgColor: 'bg-brand-primary/10',
    icon: Code,
  },
  maintainability: {
    label: '可维护性',
    color: 'text-text-secondary',
    bgColor: 'bg-bg-tertiary',
    icon: Wrench,
  },
};

const riskLevelConfig = {
  critical: {
    label: '极高风险',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    borderColor: 'border-status-error',
    icon: XCircle,
  },
  high: {
    label: '高风险',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    borderColor: 'border-status-error/50',
    icon: AlertTriangle,
  },
  medium: {
    label: '中等风险',
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    borderColor: 'border-status-warning/50',
    icon: AlertCircle,
  },
  low: {
    label: '低风险',
    color: 'text-status-success',
    bgColor: 'bg-status-success/10',
    borderColor: 'border-status-success/50',
    icon: CheckCircle2,
  },
};

const recommendationConfig = {
  approve: {
    label: '建议批准',
    color: 'text-status-success',
    bgColor: 'bg-status-success/10',
    borderColor: 'border-status-success',
    icon: CheckCircle2,
  },
  approve_with_caution: {
    label: '谨慎批准',
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    borderColor: 'border-status-warning',
    icon: AlertCircle,
  },
  reject: {
    label: '建议拒绝',
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    borderColor: 'border-status-error',
    icon: XCircle,
  },
};

export function ReviewReportPanel({ report }: ReviewReportPanelProps) {
  const [expandedIssues, setExpandedIssues] = useState<Set<number>>(new Set());
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');

  if (!report) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无审查报告数据
      </div>
    );
  }

  const { issues, overall_assessment, improvement_suggestions, risk_level, approval_recommendation } = report;

  // 过滤问题
  const filteredIssues = useMemo(() => {
    return issues.filter((issue) => {
      const severityMatch = severityFilter === 'all' || issue.severity === severityFilter;
      const categoryMatch = categoryFilter === 'all' || issue.category === categoryFilter;
      return severityMatch && categoryMatch;
    });
  }, [issues, severityFilter, categoryFilter]);

  // 统计
  const stats = useMemo(() => {
    return {
      critical: issues.filter((i) => i.severity === 'critical').length,
      high: issues.filter((i) => i.severity === 'high').length,
      medium: issues.filter((i) => i.severity === 'medium').length,
      low: issues.filter((i) => i.severity === 'low').length,
      total: issues.length,
    };
  }, [issues]);

  const toggleIssue = (index: number) => {
    const newExpanded = new Set(expandedIssues);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedIssues(newExpanded);
  };

  const RiskIcon = riskLevelConfig[risk_level as keyof typeof riskLevelConfig]?.icon || AlertCircle;
  const riskConfig = riskLevelConfig[risk_level as keyof typeof riskLevelConfig] || riskLevelConfig.low;
  const recConfig = recommendationConfig[approval_recommendation as keyof typeof recommendationConfig] || recommendationConfig.approve;

  return (
    <div className="space-y-4">
      {/* 总体评估卡片 */}
      <div className={`p-4 rounded-xl border ${riskConfig.borderColor} ${riskConfig.bgColor}`}>
        <div className="flex items-start gap-3">
          <RiskIcon className={`w-5 h-5 ${riskConfig.color} flex-shrink-0 mt-0.5`} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-sm font-semibold ${riskConfig.color}`}>{riskConfig.label}</span>
              <span className="text-text-tertiary">·</span>
              <span className={`text-sm font-medium ${recConfig.color}`}>{recConfig.label}</span>
            </div>
            <p className="text-sm text-text-secondary leading-relaxed">{overall_assessment}</p>
          </div>
        </div>
      </div>

      {/* 问题统计 */}
      {stats.total > 0 && (
        <div className="grid grid-cols-4 gap-2">
          <button
            onClick={() => setSeverityFilter(severityFilter === 'critical' ? 'all' : 'critical')}
            className={`p-2 rounded-lg text-center transition-colors ${
              severityFilter === 'critical' ? 'bg-status-error/20' : 'bg-bg-secondary hover:bg-bg-tertiary'
            }`}
          >
            <div className="text-lg font-semibold text-status-error">{stats.critical}</div>
            <div className="text-xs text-text-tertiary">严重</div>
          </button>
          <button
            onClick={() => setSeverityFilter(severityFilter === 'high' ? 'all' : 'high')}
            className={`p-2 rounded-lg text-center transition-colors ${
              severityFilter === 'high' ? 'bg-status-error/20' : 'bg-bg-secondary hover:bg-bg-tertiary'
            }`}
          >
            <div className="text-lg font-semibold text-status-error">{stats.high}</div>
            <div className="text-xs text-text-tertiary">高</div>
          </button>
          <button
            onClick={() => setSeverityFilter(severityFilter === 'medium' ? 'all' : 'medium')}
            className={`p-2 rounded-lg text-center transition-colors ${
              severityFilter === 'medium' ? 'bg-status-warning/20' : 'bg-bg-secondary hover:bg-bg-tertiary'
            }`}
          >
            <div className="text-lg font-semibold text-status-warning">{stats.medium}</div>
            <div className="text-xs text-text-tertiary">中</div>
          </button>
          <button
            onClick={() => setSeverityFilter(severityFilter === 'low' ? 'all' : 'low')}
            className={`p-2 rounded-lg text-center transition-colors ${
              severityFilter === 'low' ? 'bg-brand-primary/20' : 'bg-bg-secondary hover:bg-bg-tertiary'
            }`}
          >
            <div className="text-lg font-semibold text-brand-primary">{stats.low}</div>
            <div className="text-xs text-text-tertiary">低</div>
          </button>
        </div>
      )}

      {/* 过滤器 */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="w-4 h-4 text-text-tertiary" />
        <span className="text-xs text-text-tertiary">筛选:</span>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as SeverityFilter)}
          className="text-xs px-2 py-1 bg-bg-secondary border border-border-default rounded-lg text-text-secondary focus:outline-none focus:border-brand-primary"
        >
          <option value="all">全部严重级别</option>
          <option value="critical">严重</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as CategoryFilter)}
          className="text-xs px-2 py-1 bg-bg-secondary border border-border-default rounded-lg text-text-secondary focus:outline-none focus:border-brand-primary"
        >
          <option value="all">全部分类</option>
          <option value="bug">Bug</option>
          <option value="security">安全</option>
          <option value="performance">性能</option>
          <option value="style">风格</option>
          <option value="maintainability">可维护性</option>
        </select>
        {(severityFilter !== 'all' || categoryFilter !== 'all') && (
          <button
            onClick={() => {
              setSeverityFilter('all');
              setCategoryFilter('all');
            }}
            className="text-xs text-brand-primary hover:underline"
          >
            清除筛选
          </button>
        )}
      </div>

      {/* 问题列表 */}
      <div className="space-y-2">
        {filteredIssues.length === 0 ? (
          <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm text-center">
            {issues.length === 0 ? (
              <div className="flex flex-col items-center gap-2">
                <ShieldCheck className="w-8 h-8 text-status-success" />
                <span>未发现明显问题</span>
              </div>
            ) : (
              <span>没有符合筛选条件的问题</span>
            )}
          </div>
        ) : (
          filteredIssues.map((issue) => {
            const originalIndex = issues.indexOf(issue);
            const isExpanded = expandedIssues.has(originalIndex);
            const severity = severityConfig[issue.severity] || severityConfig.low;
            const category = categoryConfig[issue.category] || categoryConfig.style;
            const SeverityIcon = severity.icon;
            const CategoryIcon = category.icon;

            return (
              <div
                key={originalIndex}
                className={`border rounded-lg overflow-hidden transition-all ${severity.borderColor} ${severity.bgColor}`}
              >
                <button
                  onClick={() => toggleIssue(originalIndex)}
                  className="w-full px-4 py-3 flex items-start gap-3 text-left"
                >
                  <SeverityIcon className={`w-4 h-4 ${severity.color} flex-shrink-0 mt-0.5`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded ${category.bgColor} ${category.color}`}>
                        <CategoryIcon className="w-3 h-3 inline mr-1" />
                        {category.label}
                      </span>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded bg-bg-primary ${severity.color}`}>
                        {severity.label}
                      </span>
                      {issue.file_path && (
                        <span className="text-xs text-text-tertiary font-mono truncate">
                          <FileCode className="w-3 h-3 inline mr-1" />
                          {issue.file_path.split('/').pop()}
                          {issue.line_number && `:${issue.line_number}`}
                        </span>
                      )}
                    </div>
                    <p className={`text-sm mt-1 ${isExpanded ? 'text-text-primary' : 'text-text-secondary truncate'}`}>
                      {issue.description}
                    </p>
                  </div>
                  {isExpanded ? (
                    <ChevronUp className="w-4 h-4 text-text-tertiary flex-shrink-0" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-text-tertiary flex-shrink-0" />
                  )}
                </button>

                {isExpanded && (
                  <div className="px-4 pb-4 pt-0">
                    <div className="pl-7 space-y-3">
                      {/* 代码片段 */}
                      {issue.code_snippet && (
                        <div className="bg-bg-primary rounded-lg p-3 overflow-x-auto">
                          <pre className="text-xs font-mono text-text-secondary">
                            <code>{issue.code_snippet}</code>
                          </pre>
                        </div>
                      )}

                      {/* 修复建议 */}
                      <div className="flex items-start gap-2">
                        <FileWarning className="w-4 h-4 text-status-warning flex-shrink-0 mt-0.5" />
                        <div>
                          <div className="text-xs font-medium text-text-secondary mb-1">修复建议</div>
                          <p className="text-sm text-text-primary">{issue.suggestion}</p>
                        </div>
                      </div>

                      {/* 文件位置 */}
                      {issue.file_path && (
                        <div className="text-xs text-text-tertiary font-mono">
                          位置: {issue.file_path}
                          {issue.line_number && `:${issue.line_number}`}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 改进建议 */}
      {improvement_suggestions && improvement_suggestions.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Wrench className="w-4 h-4 text-brand-primary" />
            改进建议
          </h4>
          <ul className="space-y-2">
            {improvement_suggestions.map((suggestion) => (
              <li key={suggestion} className="flex items-start gap-2 text-sm text-text-secondary">
                <span className="text-brand-primary mt-1">•</span>
                <span>{suggestion}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
