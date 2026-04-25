import { useState, useRef, useEffect } from 'react';
import { X, CheckCircle2, XCircle, FileText, User, Clock, AlertCircle, Loader2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { usePipelineStore } from '@stores/pipelineStore';
import { useUIStore } from '@stores/uiStore';
import { apiPost } from '@utils/axios';
import { getLanguageFromPath, extractTechnicalDesign } from '@utils/formatters';
import { extractAllCodeChanges, isCodeStage, type CodeChange } from '@utils/pipelineHelpers';
import { DiffViewer } from './DiffViewer';
import type { ApproveRequest, RejectRequest } from '@types';

// 审批请求超时时间（毫秒）
const APPROVE_TIMEOUT = 10000; // 10秒

// ============================================
// 审批抽屉 - 从右侧滑出（集成 Diff 和二次确认）
// ============================================

export function ApproveDrawer() {
  const { selectedStage, isApproveDrawerOpen, closeApproveDrawer, selectedPipeline } = usePipelineStore();
  const { addToast } = useUIStore();
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showDiff, setShowDiff] = useState(true);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [showTimeoutWarning, setShowTimeoutWarning] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // 判断是否是代码阶段（包括 CODE_REVIEW）
  const codeStage = isCodeStage(selectedStage);

  // 提取所有代码变更（支持多文件，增强容错）
  const allCodeChanges = extractAllCodeChanges(
    selectedStage?.output_data as Record<string, unknown> | undefined,
    selectedStage?.input_data as Record<string, unknown> | undefined
  );
  const currentChange = allCodeChanges[selectedFileIndex];

  // 提取技术设计文档
  const technicalDesignContent = extractTechnicalDesign(selectedStage);

  if (!isApproveDrawerOpen || !selectedStage) return null;

  const handleApproveClick = () => {
    if (!showConfirm) {
      setShowConfirm(true);   // 第一次：按钮文字变为"确认批准"
      return;
    }
    handleApprove();
  };

  const handleApprove = async () => {
    setIsSubmitting(true);
    setShowTimeoutWarning(false);

    // 设置超时提示定时器
    timeoutRef.current = setTimeout(() => {
      setShowTimeoutWarning(true);
    }, APPROVE_TIMEOUT);

    try {
      if (!selectedPipeline) {
        throw new Error('未选择流水线');
      }

      const response = await apiPost(`/pipeline/${selectedPipeline.id}/approve`, {
        notes: feedback
      });

      // 清除超时定时器
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      // 检查是否是异步任务启动
      if (response.data?.async) {
        addToast({ type: 'info', message: '代码生成任务已在后台启动，请通过日志监控进度' });
      } else {
        addToast({ type: 'success', message: '已批准该阶段，进入下一阶段...' });
      }

      // 立即强制刷新 - 统一使用 string 类型的 id
      await queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      await queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      document.dispatchEvent(new CustomEvent('pipeline:approve', {
        detail: { stageId: selectedStage.id }
      }));

      closeApproveDrawer();
      setShowConfirm(false);
      setFeedback('');
      setSelectedFileIndex(0);
    } catch (error) {
      // 清除超时定时器
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      addToast({ type: 'error', message: `审批失败: ${error instanceof Error ? error.message : '请重试'}` });
      setShowConfirm(false);
    } finally {
      setIsSubmitting(false);
      setShowTimeoutWarning(false);
    }
  };

  const handleReject = async () => {
    if (!feedback.trim()) {
      addToast({ type: 'warning', message: '请先输入拒绝理由' });
      return;
    }

    setIsSubmitting(true);
    try {
      if (!selectedPipeline) {
        throw new Error('未选择流水线');
      }

      await apiPost(`/pipeline/${selectedPipeline.id}/reject`, {
        reason: feedback,
        suggested_changes: undefined
      });

      // 同样立即刷新
      await queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      await queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      document.dispatchEvent(new CustomEvent('pipeline:reject', {
        detail: { stageId: selectedStage.id, feedback }
      }));

      addToast({ type: 'warning', message: '已拒绝该阶段，流程回退中...' });
      closeApproveDrawer();
      setShowConfirm(false);
      setFeedback('');
      setSelectedFileIndex(0);
    } catch (error) {
      addToast({ type: 'error', message: `操作失败: ${error instanceof Error ? error.message : '请重试'}` });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setShowConfirm(false);   // 重置状态
    setFeedback('');
    setSelectedFileIndex(0);
    closeApproveDrawer();
  };

  return (
    <>
      {/* 遮罩层 */}
      <div
        className="fixed inset-0 bg-text-primary/30 backdrop-blur-sm z-40 transition-opacity"
        onClick={handleClose}
      />

      {/* 抽屉 */}
      <div className="fixed top-0 right-0 h-full w-[560px] max-w-full bg-bg-primary shadow-feishu-hover z-50 flex flex-col animate-in slide-in-from-right duration-300">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-default">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-primary-light flex items-center justify-center">
              <FileText className="w-5 h-5 text-brand-primary" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-text-primary">阶段审批</h3>
              <p className="text-sm text-text-secondary">{selectedStage.name}</p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-2 rounded-md text-text-tertiary hover:text-text-primary hover:bg-bg-secondary transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-auto p-6 space-y-6">
          {/* 阶段信息 */}
          <div className="flex items-center gap-4 p-4 bg-bg-secondary rounded-xl">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-text-tertiary" />
              <span className="text-sm text-text-secondary">AI 架构师</span>
            </div>
            <div className="w-px h-4 bg-border-default" />
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-text-tertiary" />
              <span className="text-sm text-text-secondary">
                {selectedStage.created_at
                ? new Date(selectedStage.created_at).toLocaleString('zh-CN')
                : '待定'}
              </span>
            </div>
          </div>

          {/* 代码 Diff 对比（如果是代码阶段且有代码变更） */}
          {codeStage && allCodeChanges.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-brand-primary" />
                  代码变更
                  <span className="text-xs text-text-tertiary font-normal">
                    ({allCodeChanges.length} 个文件)
                  </span>
                </h4>
                <button
                  onClick={() => setShowDiff(!showDiff)}
                  className="text-xs text-brand-primary hover:underline"
                >
                  {showDiff ? '隐藏' : '显示'}
                </button>
              </div>

              {/* 文件选择 tab — 多于 1 个时显示 */}
              {allCodeChanges.length > 1 && (
                <div className="flex gap-1 overflow-x-auto pb-1">
                  {allCodeChanges.map((change, i) => (
                    <button
                      key={change.fileName}
                      onClick={() => setSelectedFileIndex(i)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono whitespace-nowrap transition-colors
                        ${i === selectedFileIndex
                          ? 'bg-brand-primary text-white'
                          : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'
                        }`}
                    >
                      {/* 新建文件显示 + 标记，修改显示铅笔 */}
                      {change.isNew
                        ? <span className="text-status-success font-bold">+</span>
                        : <span className="text-status-warning">~</span>
                      }
                      {change.fileName.split('/').pop()}  {/* 只显示文件名，不显示路径 */}
                    </button>
                  ))}
                </div>
              )}

              {showDiff && currentChange && (
                <div className="space-y-1">
                  {/* 文件路径 + 状态标签 */}
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-bg-secondary rounded-lg">
                    <code className="text-xs text-text-secondary flex-1 truncate">
                      {currentChange.fileName}
                    </code>
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      currentChange.isNew
                        ? 'bg-status-success/10 text-status-success'
                        : 'bg-status-warning/10 text-status-warning'
                    }`}>
                      {currentChange.isNew ? '新建文件' : '修改'}
                    </span>
                  </div>

                  <DiffViewer
                    oldCode={currentChange.isNew ? '' : currentChange.oldCode}
                    newCode={currentChange.newCode}
                    oldFileName={currentChange.isNew ? '/dev/null' : currentChange.fileName}
                    newFileName={currentChange.fileName}
                    language={getLanguageFromPath(currentChange.fileName)}
                    splitView={true}
                  />
                </div>
              )}
            </div>
          )}

          {/* 技术设计文档 */}
          <div>
            <h4 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-brand-primary" />
              技术设计文档
            </h4>
            <div className="p-4 bg-bg-secondary rounded-xl border border-border-default">
              {technicalDesignContent ? (
                <div className="prose prose-sm max-w-none prose-headings:text-text-primary prose-p:text-text-secondary prose-code:text-brand-primary prose-pre:bg-bg-tertiary">
                  <pre className="whitespace-pre-wrap text-sm text-text-secondary font-mono">
                    {technicalDesignContent}
                  </pre>
                </div>
              ) : (
                <p className="text-sm text-text-tertiary italic">暂无技术设计文档 (请等待 Agent 运行完成)</p>
              )}
            </div>
          </div>

          {/* 审批意见 */}
          <div>
            <h4 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-status-warning" />
              审批意见
              <span className="text-xs text-text-tertiary font-normal">（拒绝时必须填写）</span>
            </h4>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="请输入您的审批意见..."
              className="w-full h-24 px-4 py-3 bg-bg-primary border border-border-default rounded-lg text-sm text-text-primary placeholder:text-text-tertiary resize-none focus:outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20 transition-all"
            />
          </div>

          {/* 超时警告提示 */}
          {showTimeoutWarning && (
            <div className="p-4 bg-status-warning/10 border border-status-warning/30 rounded-xl">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-status-warning flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-medium text-status-warning">任务处理时间较长</h4>
                  <p className="text-xs text-text-secondary mt-1">
                    代码生成任务可能仍在后台运行中。请不要关闭页面，可以通过日志流监控任务进度。
                    如果长时间未响应，请检查后端日志。
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-default bg-bg-secondary">
          <button
            onClick={handleClose}
            className="px-5 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
          >
            取消
          </button>

          <button
            onClick={handleReject}
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 px-5 py-2.5 border border-status-error text-status-error rounded-lg text-sm font-medium hover:bg-status-error/10 transition-colors disabled:opacity-50"
          >
            <XCircle className="w-4 h-4" />
            拒绝
          </button>

          {/* 批准按钮（带二次确认动效） */}
          <button
            onClick={handleApproveClick}
            disabled={isSubmitting}
            className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all
              ${showConfirm
                ? 'bg-status-warning text-white'
                : 'bg-brand-primary text-white hover:bg-brand-primary-hover'}
              disabled:opacity-50`}
          >
            {isSubmitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" />处理中...</>
            ) : showConfirm ? (
              <><AlertCircle className="w-4 h-4" />确认批准？</>
            ) : (
              <><CheckCircle2 className="w-4 h-4" />批准</>
            )}
          </button>
        </div>
      </div>
    </>
  );
}
