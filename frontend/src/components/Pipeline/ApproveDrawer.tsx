import { useState, useRef, useMemo } from 'react';
import { X, CheckCircle2, XCircle, FileText, User, Clock, AlertCircle, Loader2, BarChart3 } from 'lucide-react';
import { useQueryClient, useQuery } from '@tanstack/react-query';
import { usePipelineStore } from '@stores/pipelineStore';
import { useUIStore } from '@stores/uiStore';
import { apiPost, apiGet } from '@utils/axios';
import { getLanguageFromPath, extractTechnicalDesign } from '@utils/formatters';
import { extractAllCodeChanges, isCodeStage, isTestStage, extractTestCodeChanges } from '@utils/pipelineHelpers';
import { DiffViewer } from './DiffViewer';
import { MetricsPanel } from './MetricsPanel';
import type { Pipeline, PipelineStage } from '@types';

// 审批请求超时时间（毫秒）
const APPROVE_TIMEOUT = 10000; // 10秒

// ============================================
// 审批抽屉 - 从右侧滑出（集成 Diff 和二次确认）
// ============================================

export function ApproveDrawer() {
  const { selectedStage, isApproveDrawerOpen, closeApproveDrawer, selectedPipeline: storedPipeline } = usePipelineStore();
  const { addToast } = useUIStore();
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showDiff, setShowDiff] = useState(true);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [selectedTestFileIndex, setSelectedTestFileIndex] = useState(0);
  const [showTimeoutWarning, setShowTimeoutWarning] = useState(false);
  const [showMetrics, setShowMetrics] = useState(true);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 修复：用实时查询数据替代 store 快照
  const pipelineId = storedPipeline?.id;
  const { data: livePipeline } = useQuery<Pipeline>({
    queryKey: ['pipeline', String(pipelineId)],
    queryFn: () => apiGet<Pipeline>(`/pipeline/${pipelineId}/status`),
    enabled: !!pipelineId && isApproveDrawerOpen,
    refetchInterval: 2000,
    staleTime: 0,
  });

  // 优先使用实时数据，fallback 到 store 快照
  const selectedPipeline = livePipeline ?? storedPipeline;

  // 修复：从实时 pipeline 数据中找到最新的 stage 状态
  const liveSelectedStage = selectedPipeline?.stages?.find(
    (s: PipelineStage) => s.name === selectedStage?.name
  ) ?? selectedStage;

  // 判断是否是代码阶段（包括 CODE_REVIEW）
  const codeStage = isCodeStage(liveSelectedStage);
  const testStage = isTestStage(liveSelectedStage);

  // 使用 diff 接口获取完整代码数据（解决 API 截断问题）
  const { data: diffData, isLoading: isDiffLoading } = useQuery({
    queryKey: ['pipeline-diff', selectedPipeline?.id],
    queryFn: () => apiGet(`/pipeline/${selectedPipeline?.id}/diff`),
    enabled: !!selectedPipeline?.id && (selectedStage?.name === 'CODE_REVIEW' || selectedStage?.name === 'CODING'),
  });

  // 提取所有代码变更（优先使用 diff 接口数据）
  const allCodeChanges = useMemo(() => {
    // 修复：axios 拦截器已经去掉了外层包装，直接读取 files 即可
    const diffPayload = diffData as any;
    const files = diffPayload?.files || diffPayload?.data?.files;

    if (files && Array.isArray(files)) {
      return files.map((f: any) => ({
        fileName: f.file_path,
        newCode: f.content ?? '',
        oldCode: f.original_content ?? '',
        isNew: !f.original_content,
        changeType: f.change_type || 'modify',
      }));
    }

    // 否则使用原来的逻辑（从 stage 数据中提取）
    return extractAllCodeChanges(
      liveSelectedStage?.output_data as Record<string, unknown> | undefined,
      liveSelectedStage?.input_data as Record<string, unknown> | undefined
    );
  }, [diffData, liveSelectedStage]);

  // 提取测试代码变更
  const testCodeChanges = useMemo(() => {
    return extractTestCodeChanges(
      liveSelectedStage?.output_data as Record<string, unknown> | undefined,
      liveSelectedStage?.input_data as Record<string, unknown> | undefined
    );
  }, [liveSelectedStage]);

  const currentChange = allCodeChanges[selectedFileIndex];
  const currentTestChange = testCodeChanges[selectedTestFileIndex];

  // 提前返回：如果抽屉未打开或没有选中阶段，不渲染任何内容
  if (!isApproveDrawerOpen || !selectedStage) return null;

  // 提取技术设计文档
  const technicalDesignContent = extractTechnicalDesign(selectedStage);

  const handleApproveClick = () => {
    // 增加合法性检查
    if (!selectedPipeline || selectedPipeline?.status !== 'paused') {
      addToast({ type: 'warning', message: '当前流水线状态不可审批' });
      return;
    }
    // 允许当前阶段匹配，或者允许在 CODE_REVIEW 时操作 CODING 节点
    const isMatch = selectedStage?.name === selectedPipeline?.current_stage ||
                      (selectedStage?.name === 'CODING' && selectedPipeline?.current_stage === 'CODE_REVIEW');

    if (!isMatch) {
      addToast({ type: 'warning', message: '当前阶段不是待审批阶段' });
      return;
    }

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

      // 1. 发送请求给后端
      const response = await apiPost<any>(`/pipeline/${selectedPipeline.id}/approve`, {
        notes: feedback
      });

      // --- 重点：以下部分是点击后的处理逻辑 ---

      // 2. 清除超时定时器
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      // 3. 发送通知（Toast）
      if (response.async || response.data?.async) {
        addToast({ type: 'info', message: '任务已在后台启动' });
      } else {
        addToast({ type: 'success', message: '操作成功' });
      }

      // 5. 触发全局事件
      document.dispatchEvent(new CustomEvent('pipeline:approve', {
        detail: { stageId: selectedStage.id }
      }));

      // 6.【关键】不要 await 刷新，让它在后台慢慢跑
      queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      // 7. 延迟关闭抽屉，让用户看到反馈
      setTimeout(() => {
        closeApproveDrawer();
        setShowConfirm(false);
        setFeedback('');
        setSelectedFileIndex(0);
        setSelectedTestFileIndex(0);
      }, 300);

    } catch (error) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      addToast({ type: 'error', message: `审批失败: ${error instanceof Error ? error.message : '请重试'}` });
      setShowConfirm(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    // 增加合法性检查
    if (!selectedPipeline || selectedPipeline?.status !== 'paused') {
      addToast({ type: 'warning', message: '当前流水线状态不可审批' });
      return;
    }
    // 允许当前阶段匹配，或者允许在 CODE_REVIEW 时操作 CODING 节点
    const isMatch = selectedStage?.name === selectedPipeline?.current_stage ||
                      (selectedStage?.name === 'CODING' && selectedPipeline?.current_stage === 'CODE_REVIEW');

    if (!isMatch) {
      addToast({ type: 'warning', message: '当前阶段不是待审批阶段' });
      return;
    }

    if (!feedback.trim()) {
      addToast({ type: 'warning', message: '请先输入拒绝理由' });
      return;
    }

    setIsSubmitting(true);
    try {
      if (!selectedPipeline) {
        throw new Error('未选择流水线');
      }

      // 1. 发送拒绝请求
      await apiPost(`/pipeline/${selectedPipeline.id}/reject`, {
        reason: feedback,
        suggested_changes: undefined
      });

      // 2. 后台刷新
      queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      // 3. 发送事件和通知
      document.dispatchEvent(new CustomEvent('pipeline:reject', {
        detail: { stageId: selectedStage.id, feedback }
      }));
      addToast({ type: 'warning', message: '已拒绝，流程回退中' });

      // 4. 延迟关闭抽屉，让用户看到反馈
      setTimeout(() => {
        closeApproveDrawer();
        setFeedback('');
        setShowConfirm(false);
        setSelectedFileIndex(0);
        setSelectedTestFileIndex(0);
      }, 300);

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
    setSelectedTestFileIndex(0);
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

          {/* 可观测性指标面板 */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-brand-primary" />
                执行指标
              </h4>
              <button
                onClick={() => setShowMetrics(!showMetrics)}
                className="text-xs text-brand-primary hover:underline"
              >
                {showMetrics ? '隐藏' : '显示'}
              </button>
            </div>
            {showMetrics && (
              <MetricsPanel stage={selectedStage} />
            )}
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

          {/* 测试代码展示（如果是测试阶段） */}
          {testStage && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-status-warning" />
                  测试代码
                  {testCodeChanges.length > 0 && (
                    <span className="text-xs text-text-tertiary font-normal">
                      ({testCodeChanges.length} 个文件)
                    </span>
                  )}
                </h4>
                {testCodeChanges.length > 0 && (
                  <button
                    onClick={() => setShowDiff(!showDiff)}
                    className="text-xs text-brand-primary hover:underline"
                  >
                    {showDiff ? '隐藏' : '显示'}
                  </button>
                )}
              </div>

              {/* 没有生成测试文件的提示 */}
              {testCodeChanges.length === 0 && (
                <div className="p-4 bg-bg-secondary rounded-xl border border-border-default">
                  <div className="flex items-center gap-2 text-text-secondary">
                    <svg className="w-5 h-5 text-status-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span className="text-sm">未生成测试文件</span>
                  </div>
                  <p className="text-xs text-text-tertiary mt-2">
                    TestAgent 未能为此阶段生成单元测试代码。可能是由于代码结构不适合自动化测试，或 LLM 返回格式不正确。
                  </p>
                </div>
              )}

              {/* 测试文件选择 tab — 多于 1 个时显示 */}
              {testCodeChanges.length > 1 && (
                <div className="flex gap-1 overflow-x-auto pb-1">
                  {testCodeChanges.map((change, i) => (
                    <button
                      key={change.fileName}
                      onClick={() => setSelectedTestFileIndex(i)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono whitespace-nowrap transition-colors
                        ${i === selectedTestFileIndex
                          ? 'bg-status-warning text-white'
                          : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'
                        }`}
                    >
                      <span className="text-status-success font-bold">+</span>
                      {change.fileName.split('/').pop()}
                    </button>
                  ))}
                </div>
              )}

              {testCodeChanges.length > 0 && showDiff && currentTestChange && (
                <div className="space-y-1">
                  {/* 文件路径 + 状态标签 */}
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-bg-secondary rounded-lg">
                    <code className="text-xs text-text-secondary flex-1 truncate">
                      {currentTestChange.fileName}
                    </code>
                    <span className="text-xs px-2 py-0.5 rounded font-medium bg-status-success/10 text-status-success">
                      新建测试文件
                    </span>
                  </div>

                  <DiffViewer
                    oldCode={''}
                    newCode={currentTestChange.newCode}
                    oldFileName={'/dev/null'}
                    newFileName={currentTestChange.fileName}
                    language={getLanguageFromPath(currentTestChange.fileName)}
                    splitView={false}
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

          {/* 可审批状态：显示审批按钮 */}
          {selectedPipeline?.status === 'paused' &&
          (selectedStage?.name === selectedPipeline?.current_stage ||
           (selectedStage?.name === 'CODING' && selectedPipeline?.current_stage === 'CODE_REVIEW')) ? (
            <>
              <button
                onClick={handleReject}
                disabled={isSubmitting}
                className="inline-flex items-center gap-2 px-5 py-2.5 border border-status-error text-status-error rounded-lg text-sm font-medium hover:bg-status-error/10 transition-colors disabled:opacity-50"
              >
                <XCircle className="w-4 h-4" />
                拒绝
              </button>
              <button
                onClick={handleApproveClick}
                disabled={isSubmitting}
                className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                  showConfirm
                    ? 'bg-status-warning text-white'
                    : 'bg-brand-primary text-white hover:bg-brand-primary-hover'
                } disabled:opacity-50`}
              >
                {isSubmitting ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />处理中...</>
                ) : showConfirm ? (
                  <><AlertCircle className="w-4 h-4" />确认批准？</>
                ) : (
                  <><CheckCircle2 className="w-4 h-4" />批准</>
                )}
              </button>
            </>
          ) : (
            /* 不可操作的状态标签（历史阶段或非当前审批阶段） */
            <>
              {/* 状态优先级：running > success > failed/rejected > 其他 */}
              {liveSelectedStage?.status === 'running' ? (
                <span className="px-5 py-2.5 bg-blue-50 text-blue-600 rounded-lg text-sm font-medium border border-blue-200">
                  运行中
                </span>
              ) : liveSelectedStage?.status === 'success' ? (
                <span className="px-5 py-2.5 bg-status-success/10 text-status-success rounded-lg text-sm font-medium border border-status-success/30">
                  已通过
                </span>
              ) : liveSelectedStage?.status === 'failed' || (liveSelectedStage?.output_data as any)?.rejection_feedback ? (
                <span className="px-5 py-2.5 bg-status-error/10 text-status-error rounded-lg text-sm font-medium border border-status-error/30">
                  已拒绝
                </span>
              ) : (
                <span className="px-5 py-2.5 bg-bg-tertiary text-text-tertiary rounded-lg text-sm font-medium border border-border-default">
                  等待中
                </span>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
