import { useState } from 'react';
import { AlertTriangle, ArrowRight, RefreshCw, ArrowLeft, CheckCircle2 } from 'lucide-react';
import { apiPost } from '@utils/axios';
import { useUIStore } from '@stores/uiStore';

// ============================================
// 用户决策面板 - 当测试失败或需要用户确认时显示
// ============================================

interface UserDecisionPanelProps {
  pipelineId: number;
  title?: string;
  message?: string;
  suggestion?: string;
  onContinue?: () => void;
  onRetry?: () => void;
  onBackToRequirement?: () => void;
  showContinue?: boolean;
  showRetry?: boolean;
  showBackToRequirement?: boolean;
}

export function UserDecisionPanel({
  pipelineId,
  title = "测试未通过",
  message = "当前测试未能完全通过，您可以选择以下操作：",
  suggestion = "建议重试或完善需求说明",
  onContinue,
  onRetry,
  onBackToRequirement,
  showContinue = true,
  showRetry = true,
  showBackToRequirement = true,
}: UserDecisionPanelProps) {
  const [isLoading, setIsLoading] = useState<string | null>(null);
  const { addToast } = useUIStore();

  // 继续进入 CODE_REVIEW
  const handleContinue = async () => {
    setIsLoading('continue');
    try {
      // 调用 API 进入 CODE_REVIEW 阶段
      const response = await apiPost(`/pipeline/${pipelineId}/approve`, {
        notes: "用户接受当前测试结果，继续进入代码审查",
      });

      if (response.success) {
        addToast({ type: 'success', message: '已进入代码审查阶段' });
        onContinue?.();
      } else {
        addToast({ type: 'error', message: response.error || '操作失败' });
      }
    } catch (error) {
      addToast({
        type: 'error',
        message: `操作失败: ${error instanceof Error ? error.message : '请重试'}`
      });
    } finally {
      setIsLoading(null);
    }
  };

  // 重试 TESTING 阶段
  const handleRetry = async () => {
    setIsLoading('retry');
    try {
      // 调用 API 重试当前阶段
      const response = await apiPost(`/pipeline/${pipelineId}/retry`, {});

      if (response.success) {
        addToast({ type: 'info', message: '已重新开始测试阶段' });
        onRetry?.();
      } else {
        addToast({ type: 'error', message: response.error || '重试失败' });
      }
    } catch (error) {
      addToast({
        type: 'error',
        message: `重试失败: ${error instanceof Error ? error.message : '请重试'}`
      });
    } finally {
      setIsLoading(null);
    }
  };

  // 回到 REQUIREMENT 阶段
  const handleBackToRequirement = async () => {
    setIsLoading('back');
    try {
      // 调用 API 驳回到 REQUIREMENT 阶段
      const response = await apiPost(`/pipeline/${pipelineId}/reject`, {
        reason: "用户决定完善需求说明",
        suggested_changes: "需要更详细的需求描述"
      });

      if (response.success) {
        addToast({ type: 'info', message: '已回到需求阶段' });
        onBackToRequirement?.();
      } else {
        addToast({ type: 'error', message: response.error || '操作失败' });
      }
    } catch (error) {
      addToast({
        type: 'error',
        message: `操作失败: ${error instanceof Error ? error.message : '请重试'}`
      });
    } finally {
      setIsLoading(null);
    }
  };

  return (
    <div className="p-4 bg-status-warning/10 border border-status-warning/30 rounded-xl">
      {/* 标题和说明 */}
      <div className="flex items-start gap-3 mb-4">
        <AlertTriangle className="w-5 h-5 text-status-warning flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-medium text-status-warning">
            {title}
          </h4>
          <p className="text-xs text-text-secondary mt-1">
            {message}
          </p>
          {suggestion && (
            <p className="text-xs text-text-tertiary mt-2">
              💡 {suggestion}
            </p>
          )}
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="space-y-2">
        {/* 选项 1：继续进入 CODE_REVIEW */}
        {showContinue && (
          <button
            onClick={handleContinue}
            disabled={isLoading !== null}
            className="w-full flex items-center justify-between px-4 py-3 bg-status-success/10 hover:bg-status-success/20 border border-status-success/30 rounded-lg transition-colors disabled:opacity-50"
          >
            <div className="flex items-center gap-3">
              <CheckCircle2 className="w-4 h-4 text-status-success" />
              <div className="text-left">
                <span className="text-sm font-medium text-status-success">
                  继续进入代码审查
                </span>
                <p className="text-xs text-text-secondary">
                  接受当前状态，进入 CODE_REVIEW 阶段
                </p>
              </div>
            </div>
            {isLoading === 'continue' ? (
              <div className="w-4 h-4 border-2 border-status-success border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-4 h-4 text-status-success" />
            )}
          </button>
        )}

        {/* 选项 2：重试 TESTING 阶段 */}
        {showRetry && (
          <button
            onClick={handleRetry}
            disabled={isLoading !== null}
            className="w-full flex items-center justify-between px-4 py-3 bg-brand-primary/10 hover:bg-brand-primary/20 border border-brand-primary/30 rounded-lg transition-colors disabled:opacity-50"
          >
            <div className="flex items-center gap-3">
              <RefreshCw className="w-4 h-4 text-brand-primary" />
              <div className="text-left">
                <span className="text-sm font-medium text-brand-primary">
                  重新生成测试
                </span>
                <p className="text-xs text-text-secondary">
                  重试 TESTING 阶段，重新生成测试用例
                </p>
              </div>
            </div>
            {isLoading === 'retry' ? (
              <div className="w-4 h-4 border-2 border-brand-primary border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-4 h-4 text-brand-primary" />
            )}
          </button>
        )}

        {/* 选项 3：回到 REQUIREMENT 阶段 */}
        {showBackToRequirement && (
          <button
            onClick={handleBackToRequirement}
            disabled={isLoading !== null}
            className="w-full flex items-center justify-between px-4 py-3 bg-bg-tertiary hover:bg-bg-secondary border border-border-default rounded-lg transition-colors disabled:opacity-50"
          >
            <div className="flex items-center gap-3">
              <ArrowLeft className="w-4 h-4 text-text-secondary" />
              <div className="text-left">
                <span className="text-sm font-medium text-text-secondary">
                  完善需求说明
                </span>
                <p className="text-xs text-text-tertiary">
                  回到 REQUIREMENT 阶段，补充需求描述
                </p>
              </div>
            </div>
            {isLoading === 'back' ? (
              <div className="w-4 h-4 border-2 border-text-secondary border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-4 h-4 text-text-secondary" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}
