import { useState, useRef, useMemo, useEffect } from 'react';
import { X, CheckCircle2, XCircle, FileText, User, Clock, AlertCircle, Loader2, BarChart3, Download, ShieldCheck } from 'lucide-react';
import { useQueryClient, useQuery } from '@tanstack/react-query';
import { usePipelineStore } from '@stores/pipelineStore';
import { useUIStore } from '@stores/uiStore';
import { apiPost, apiGet } from '@utils/axios';
import { getLanguageFromPath } from '@utils/formatters';
import { extractAllCodeChanges, extractTestCodeChanges } from '@utils/pipelineHelpers';
import { formatMetricDuration, getStageMetrics } from '@utils/pipelineMetrics';
import { DiffViewer } from './DiffViewer';
import { TestCaseEditor } from './TestCaseEditor';
import { RequirementPanel } from './RequirementPanel';
import { DesignPanel } from './DesignPanel';
import { CodingPanel } from './CodingPanel';
import { TestingPanel } from './TestingPanel';
import { DeliveryPanel } from './DeliveryPanel';
import { ReviewReportPanel } from './ReviewReportPanel';
import { exportPipelineReport } from '@utils/pipelineReport';
import type { Pipeline, PipelineStage, ReviewReport } from '@types';

// 审批请求超时时间（毫秒）
const APPROVE_TIMEOUT = 10000; // 10秒

// ============================================
// 审批抽屉 - 从右侧滑出（集成 Diff 和二次确认）
// 【新流程】支持分别审批 CODER 和 TESTER
// ============================================

export function ApproveDrawer() {
  const { selectedStage, isApproveDrawerOpen, closeApproveDrawer, selectedPipeline: storedPipeline } = usePipelineStore();
  const { addToast } = useUIStore();
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [selectedTestFileIndex, setSelectedTestFileIndex] = useState(0);
  const [showTimeoutWarning, setShowTimeoutWarning] = useState(false);
  const [showMetrics, setShowMetrics] = useState(true);
  const [activeTab, setActiveTab] = useState<'coder' | 'tester' | 'review'>('coder');
  const [coderDecision, setCoderDecision] = useState<'accept' | 'reject' | null>(null);
  const [testerDecision, setTesterDecision] = useState<'accept' | 'reject' | null>(null);
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

  // 【并发执行支持】根据选中的阶段名称获取对应的后端阶段数据
  // CODING 和 UNIT_TESTING 是分开的两个阶段，需要分别获取
  const liveSelectedStage = useMemo(() => {
    if (!selectedPipeline?.stages || !selectedStage) return selectedStage;

    // 根据前端阶段名称找到对应的后端阶段
    const stageNameMap: Record<string, string> = {
      'CODING': 'CODING',
      'UNIT_TESTING': 'UNIT_TESTING',
      'CODE_REVIEW': 'CODING', // CODE_REVIEW 显示 CODING 的数据
      'REQUIREMENT': 'REQUIREMENT',
      'DESIGN': 'DESIGN',
      'DELIVERY': 'DELIVERY'
    };

    const targetBackendName = stageNameMap[selectedStage.name];
    return selectedPipeline.stages.slice().reverse().find(
      (s: PipelineStage) => s.name === targetBackendName
    ) ?? selectedStage;
  }, [selectedPipeline, selectedStage]);

  // 获取 CODING 阶段数据
  const codingStage = useMemo(() => {
    if (!selectedPipeline?.stages) return null;
    return selectedPipeline.stages.slice().reverse().find(
      (s: PipelineStage) => s.name === 'CODING'
    );
  }, [selectedPipeline]);

  // 获取 UNIT_TESTING 阶段数据
  const testingStage = useMemo(() => {
    if (!selectedPipeline?.stages) return null;
    return selectedPipeline.stages.slice().reverse().find(
      (s: PipelineStage) => s.name === 'UNIT_TESTING'
    );
  }, [selectedPipeline]);

  // 判断是否是代码阶段（包括 CODE_REVIEW）
  // 判断是否处于 CODE_REVIEW 审批阶段
  const isCodeReviewStage = selectedPipeline?.current_stage === 'CODE_REVIEW';
  const showUnifiedApproval = isCodeReviewStage;

  // 使用 diff 接口获取完整代码数据（解决 API 截断问题）
  const { data: diffData } = useQuery({
    queryKey: ['pipeline-diff', selectedPipeline?.id],
    queryFn: () => apiGet(`/pipeline/${selectedPipeline?.id}/diff`),
    enabled: !!selectedPipeline?.id && (selectedStage?.name === 'CODE_REVIEW' || selectedStage?.name === 'CODING'),
  });

  // 提取代码变更（仅用于 CODING 阶段，过滤掉测试文件）
  const allCodeChanges = useMemo(() => {
    // CODING 阶段才需要显示代码文件
    if (selectedStage?.name !== 'CODING' && selectedStage?.name !== 'CODE_REVIEW') {
      return [];
    }

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
      codingStage?.output_data as Record<string, unknown> | undefined,
      codingStage?.input_data as Record<string, unknown> | undefined
    );
  }, [diffData, codingStage, selectedStage?.name]);

  // 提取测试代码变更
  const testCodeChanges = useMemo(() => {
    const testingOutput = testingStage?.output_data as Record<string, unknown> | undefined;
    if (!testingOutput) return [];

    const testFiles = testingOutput.test_files as Array<{file_path: string; content: string}> | undefined;
    if (testFiles && Array.isArray(testFiles)) {
      return testFiles.map((f) => ({
        fileName: f.file_path,
        newCode: f.content ?? '',
        oldCode: '',
        isNew: true,
        changeType: 'add' as const,
      }));
    }

    return extractTestCodeChanges(
      testingOutput,
      testingStage?.input_data as Record<string, unknown> | undefined
    );
  }, [testingStage]);

  // 获取测试结果摘要
  const testingResult = useMemo(() => {
    const output = testingStage?.output_data as Record<string, unknown> | undefined;
    if (!output) return null;

    const result = output.testing_result as Record<string, unknown> | undefined;
    return {
      testGenerated: result?.test_generated ?? false,
      testRunSuccess: result?.test_run_success ?? false,
      testError: result?.test_error as string | undefined,
      retryCount: (result?.retry_count as number) ?? 0,
    };
  }, [testingStage]);

  // 【新增】获取 AI 审查报告
  const reviewReport = useMemo<ReviewReport | undefined>(() => {
    // 从 CODE_REVIEW 阶段的 output_data 获取
    const reviewStage = selectedPipeline?.stages?.slice().reverse().find(
      (s: PipelineStage) => s.name === 'CODE_REVIEW'
    );
    const output = reviewStage?.output_data as Record<string, unknown> | undefined;
    return output?.review_report as ReviewReport | undefined;
  }, [selectedPipeline]);

  const currentChange = allCodeChanges[selectedFileIndex];
  const currentTestChange = testCodeChanges[selectedTestFileIndex];

  // 提前返回：如果抽屉未打开或没有选中阶段，不渲染任何内容
  if (!isApproveDrawerOpen || !selectedStage) return null;

  // 提取技术设计文档
  // 【新流程】处理统一审批
  const handleUnifiedApprove = async () => {
    if (!coderDecision || !testerDecision) {
      addToast({ type: 'warning', message: '请分别选择对 CODER 和 TESTER 的审批决定' });
      return;
    }

    if ((coderDecision === 'reject' || testerDecision === 'reject') && !feedback.trim()) {
      addToast({ type: 'warning', message: '拒绝时必须填写反馈理由' });
      return;
    }

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

      const approveCoding = coderDecision === 'accept';
      const approveTesting = testerDecision === 'accept';

      // 调用新的统一审批 API
      const response = await apiPost<any>(`/pipeline/${selectedPipeline.id}/approve-code-review`, {
        approve_coding: approveCoding,
        approve_testing: approveTesting,
        feedback: feedback
      });

      // 清除超时定时器
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      // 发送通知
      if (response.async || response.data?.async) {
        addToast({ type: 'info', message: '任务已在后台启动' });
      } else {
        addToast({ type: 'success', message: '审批成功' });
      }

      // 触发全局事件
      document.dispatchEvent(new CustomEvent('pipeline:approve', {
        detail: { stageId: selectedStage.id }
      }));

      // 刷新数据
      queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      // 延迟关闭抽屉
      setTimeout(() => {
        closeApproveDrawer();
        setShowConfirm(false);
        setFeedback('');
        setCoderDecision(null);
        setTesterDecision(null);
        setSelectedFileIndex(0);
        setSelectedTestFileIndex(0);
      }, 300);

    } catch (error) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      addToast({ type: 'error', message: `审批失败: ${error instanceof Error ? error.message : '请重试'}` });
    } finally {
      setIsSubmitting(false);
    }
  };

  // 旧版审批（非 CODE_REVIEW 阶段）
  const handleApproveClick = () => {
    // 增加合法性检查
    if (!selectedPipeline || selectedPipeline?.status !== 'paused') {
      addToast({ type: 'warning', message: '当前流水线状态不可审批' });
      return;
    }

    const isMatch = selectedStage?.name === selectedPipeline?.current_stage;

    if (!isMatch) {
      addToast({ type: 'warning', message: '当前阶段不是待审批阶段' });
      return;
    }

    if (!showConfirm) {
      setShowConfirm(true);
      return;
    }
    handleLegacyApprove();
  };

  const handleLegacyApprove = async () => {
    setIsSubmitting(true);
    setShowTimeoutWarning(false);

    timeoutRef.current = setTimeout(() => {
      setShowTimeoutWarning(true);
    }, APPROVE_TIMEOUT);

    try {
      if (!selectedPipeline) {
        throw new Error('未选择流水线');
      }

      const response = await apiPost<any>(`/pipeline/${selectedPipeline.id}/approve`, {
        notes: feedback
      });

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }

      if (response.async || response.data?.async) {
        addToast({ type: 'info', message: '任务已在后台启动' });
      } else {
        addToast({ type: 'success', message: '操作成功' });
      }

      document.dispatchEvent(new CustomEvent('pipeline:approve', {
        detail: { stageId: selectedStage.id }
      }));

      queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });

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
    if (!selectedPipeline || selectedPipeline?.status !== 'paused') {
      addToast({ type: 'warning', message: '当前流水线状态不可审批' });
      return;
    }

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

      await apiPost(`/pipeline/${selectedPipeline.id}/reject`, {
        reason: feedback,
        suggested_changes: undefined
      });

      queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });

      document.dispatchEvent(new CustomEvent('pipeline:reject', {
        detail: { stageId: selectedStage.id, feedback }
      }));
      addToast({ type: 'warning', message: '已拒绝，流程回退中' });

      setTimeout(() => {
        closeApproveDrawer();
        setFeedback('');
        setShowConfirm(false);
        setCoderDecision(null);
        setTesterDecision(null);
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
    setShowConfirm(false);
    setFeedback('');
    setCoderDecision(null);
    setTesterDecision(null);
    setActiveTab('coder');
    setSelectedFileIndex(0);
    setSelectedTestFileIndex(0);
    closeApproveDrawer();
  };

  // 【修复】抽屉打开时重置决策状态，避免残留上次选项
  useEffect(() => {
    if (isApproveDrawerOpen) {
      setCoderDecision(null);
      setTesterDecision(null);
      setFeedback('');
      setShowConfirm(false);
      setActiveTab('coder');
      setSelectedFileIndex(0);
      setSelectedTestFileIndex(0);
    }
  }, [isApproveDrawerOpen]);

  // 【快捷键支持】Ctrl+Enter 批准, Ctrl+R 驳回
  useEffect(() => {
    if (!isApproveDrawerOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + Enter: 快速批准
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (showUnifiedApproval) {
          // CODE_REVIEW 阶段需要确保两个决策都已做出
          if (coderDecision && testerDecision) {
            handleUnifiedApprove();
          } else {
            addToast({ type: 'warning', message: '请先完成 CODER 和 TESTER 的审批决策' });
          }
        } else {
          handleApproveClick();
        }
      }

      // Ctrl/Cmd + R: 快速驳回
      if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        e.preventDefault();
        if (feedback.trim()) {
          handleReject();
        } else {
          addToast({ type: 'warning', message: '请先填写拒绝理由' });
          // 聚焦到反馈输入框
          const feedbackTextarea = document.querySelector('textarea[placeholder*="审批意见"]') as HTMLTextAreaElement;
          feedbackTextarea?.focus();
        }
      }

      // Ctrl/Cmd + E: 导出报告
      if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
        e.preventDefault();
        if (selectedPipeline) {
          exportPipelineReport(selectedPipeline);
          addToast({ type: 'success', message: '报告已导出' });
        }
      }

      // Escape: 关闭抽屉
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isApproveDrawerOpen, showUnifiedApproval, coderDecision, testerDecision, feedback, selectedPipeline]);

  // 判断是否显示统一审批 UI（CODE_REVIEW 阶段）
  return (
    <>
      {/* 遮罩层 */}
      <div
        className="fixed inset-0 bg-text-primary/30 backdrop-blur-sm z-40 transition-opacity"
        onClick={handleClose}
      />

      {/* 抽屉 */}
      <div className="fixed top-0 right-0 h-full w-[600px] max-w-full bg-bg-primary shadow-feishu-hover z-50 flex flex-col animate-in slide-in-from-right duration-300">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-default">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-primary-light flex items-center justify-center">
              <FileText className="w-5 h-5 text-brand-primary" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-text-primary">阶段审批</h3>
              <p className="text-sm text-text-secondary">
                {showUnifiedApproval ? '代码审查（CODER + TESTER）' : selectedStage.name}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* 导出报告按钮 */}
            {selectedPipeline && (
              <button
                onClick={() => {
                  exportPipelineReport(selectedPipeline);
                  addToast({ type: 'success', message: '报告已导出' });
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-primary bg-brand-primary-light rounded-lg hover:bg-brand-primary/20 transition-colors"
                title="导出 Pipeline 报告"
              >
                <Download className="w-4 h-4" />
                导出报告
              </button>
            )}
            <button
              onClick={handleClose}
              className="p-2 rounded-md text-text-tertiary hover:text-text-primary hover:bg-bg-secondary transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-auto p-6 space-y-6">
          {/* 阶段信息 */}
          <div className="flex items-center gap-4 p-4 bg-bg-secondary rounded-xl">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-text-tertiary" />
              <span className="text-sm text-text-secondary">{
                (() => {
                  const agentNames: Record<string, string> = {
                    REQUIREMENT: 'AI 架构师',
                    DESIGN: 'AI 设计师',
                    CODING: 'AI 程序员',
                    CODE_REVIEW: 'AI 程序员 + AI 测试员',
                    UNIT_TESTING: 'AI 测试员',
                    DELIVERY: '交付系统',
                  };
                  return agentNames[selectedStage?.name || ''] || 'AI Agent';
                })()
              }</span>
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

          {/* 【新流程】CODE_REVIEW 阶段显示分栏审批 UI */}
          {showUnifiedApproval && (
            <div className="space-y-4">
              {/* 分栏 Tab */}
              <div className="flex border-b border-border-default">
                <button
                  onClick={() => setActiveTab('coder')}
                  className={`flex-1 px-4 py-3 text-sm font-medium transition-colors relative ${
                    activeTab === 'coder'
                      ? 'text-brand-primary'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center justify-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-500" />
                    CODER 代码
                    {coderDecision === 'accept' && <CheckCircle2 className="w-4 h-4 text-status-success" />}
                    {coderDecision === 'reject' && <XCircle className="w-4 h-4 text-status-error" />}
                  </div>
                  {activeTab === 'coder' && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-primary" />
                  )}
                </button>
                <button
                  onClick={() => setActiveTab('tester')}
                  className={`flex-1 px-4 py-3 text-sm font-medium transition-colors relative ${
                    activeTab === 'tester'
                      ? 'text-brand-primary'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center justify-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-status-warning" />
                    TESTER 测试
                    {testerDecision === 'accept' && <CheckCircle2 className="w-4 h-4 text-status-success" />}
                    {testerDecision === 'reject' && <XCircle className="w-4 h-4 text-status-error" />}
                  </div>
                  {activeTab === 'tester' && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-primary" />
                  )}
                </button>
                <button
                  onClick={() => setActiveTab('review')}
                  className={`flex-1 px-4 py-3 text-sm font-medium transition-colors relative ${
                    activeTab === 'review'
                      ? 'text-brand-primary'
                      : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center justify-center gap-2">
                    <ShieldCheck className="w-4 h-4" />
                    AI 审查报告
                    {reviewReport && reviewReport.issues.length > 0 && (
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                        reviewReport.issues.some(i => i.severity === 'critical' || i.severity === 'high')
                          ? 'bg-status-error text-white'
                          : 'bg-status-warning text-white'
                      }`}>
                        {reviewReport.issues.length}
                      </span>
                    )}
                  </div>
                  {activeTab === 'review' && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-primary" />
                  )}
                </button>
              </div>

              {/* CODER 内容 */}
              {activeTab === 'coder' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-text-primary">
                      代码文件 ({allCodeChanges.length} 个)
                    </h4>
                    {/* CODER 审批决策 */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-tertiary">审批：</span>
                      <button
                        onClick={() => setCoderDecision('accept')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          coderDecision === 'accept'
                            ? 'bg-status-success text-white'
                            : 'bg-bg-tertiary text-text-secondary hover:text-status-success'
                        }`}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" />
                        接受
                      </button>
                      <button
                        onClick={() => setCoderDecision('reject')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          coderDecision === 'reject'
                            ? 'bg-status-error text-white'
                            : 'bg-bg-tertiary text-text-secondary hover:text-status-error'
                        }`}
                      >
                        <XCircle className="w-3.5 h-3.5 inline mr-1" />
                        拒绝
                      </button>
                    </div>
                  </div>

                  {/* 代码文件列表 */}
                  {allCodeChanges.length > 0 ? (
                    <div className="space-y-3">
                      {/* 文件选择 tab */}
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
                              {change.isNew
                                ? <span className="text-status-success font-bold">+</span>
                                : <span className="text-status-warning">~</span>
                              }
                              {change.fileName.split('/').pop()}
                            </button>
                          ))}
                        </div>
                      )}

                      {/* Diff 展示 */}
                      {currentChange && (
                        <div className="space-y-1">
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
                  ) : (
                    <div className="p-4 bg-bg-secondary rounded-xl text-text-secondary text-sm">
                      暂无代码文件
                    </div>
                  )}
                </div>
              )}

              {/* TESTER 内容 */}
              {activeTab === 'tester' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-text-primary">
                      测试文件 ({testCodeChanges.length} 个)
                    </h4>
                    {/* TESTER 审批决策 */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-tertiary">审批：</span>
                      <button
                        onClick={() => setTesterDecision('accept')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          testerDecision === 'accept'
                            ? 'bg-status-success text-white'
                            : 'bg-bg-tertiary text-text-secondary hover:text-status-success'
                        }`}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" />
                        接受
                      </button>
                      <button
                        onClick={() => setTesterDecision('reject')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          testerDecision === 'reject'
                            ? 'bg-status-error text-white'
                            : 'bg-bg-tertiary text-text-secondary hover:text-status-error'
                        }`}
                      >
                        <XCircle className="w-3.5 h-3.5 inline mr-1" />
                        拒绝
                      </button>
                    </div>
                  </div>

                  {/* 测试结果摘要 */}
                  {testingResult && (
                    <div className={`p-3 rounded-lg text-sm ${
                      testingResult.testRunSuccess
                        ? 'bg-status-success/10 text-status-success border border-status-success/30'
                        : testingResult.testGenerated
                        ? 'bg-status-warning/10 text-status-warning border border-status-warning/30'
                        : 'bg-bg-secondary text-text-secondary'
                    }`}>
                      <div className="flex items-center gap-2">
                        {testingResult.testRunSuccess ? (
                          <CheckCircle2 className="w-4 h-4" />
                        ) : (
                          <AlertCircle className="w-4 h-4" />
                        )}
                        <span>
                          {testingResult.testRunSuccess
                            ? '✅ 所有测试通过'
                            : testingResult.testGenerated
                            ? `⚠️ 测试未通过${testingResult.testError ? `: ${testingResult.testError}` : ''}`
                            : '❌ 未生成测试文件'}
                        </span>
                      </div>
                      {testingResult.retryCount > 0 && (
                        <div className="text-xs mt-1 text-text-tertiary">
                          重试次数: {testingResult.retryCount}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 测试文件选择 tab - 多个文件时显示 */}
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

                  {/* 【测试用例编辑器】人工编辑测试代码 */}
                  {currentTestChange && selectedPipeline && (
                    <div className="pt-4 border-t border-border-default">
                      <TestCaseEditor
                        pipelineId={selectedPipeline.id}
                        filePath={currentTestChange.fileName}
                        initialContent={currentTestChange.newCode}
                        language={getLanguageFromPath(currentTestChange.fileName)}
                        onSave={(newContent) => {
                          // 更新本地状态
                          const updatedChanges = [...testCodeChanges];
                          updatedChanges[selectedTestFileIndex] = {
                            ...currentTestChange,
                            newCode: newContent
                          };
                          // 触发刷新
                          queryClient.invalidateQueries({ queryKey: ['pipeline', String(selectedPipeline.id)] });
                        }}
                        onTestRun={(success) => {
                          // 更新测试结果状态
                          addToast({
                            type: success ? 'success' : 'warning',
                            message: success ? '测试已通过，可以提交审批' : '测试未通过，请继续修改'
                          });
                        }}
                      />
                    </div>
                  )}

                  {/* 测试文件列表（当没有选中文件时显示） */}
                  {testCodeChanges.length === 0 && (
                    <div className="p-4 bg-bg-secondary rounded-xl text-text-secondary text-sm">
                      未生成测试文件
                    </div>
                  )}
                </div>
              )}

              {/* 【新增】AI 审查报告内容 */}
              {activeTab === 'review' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-brand-primary" />
                      AI 代码审查报告
                    </h4>
                    {reviewReport && (
                      <span className={`text-xs px-2 py-1 rounded-lg ${
                        reviewReport.approval_recommendation === 'approve'
                          ? 'bg-status-success/10 text-status-success'
                          : reviewReport.approval_recommendation === 'reject'
                          ? 'bg-status-error/10 text-status-error'
                          : 'bg-status-warning/10 text-status-warning'
                      }`}>
                        {reviewReport.approval_recommendation === 'approve'
                          ? '建议批准'
                          : reviewReport.approval_recommendation === 'reject'
                          ? '建议拒绝'
                          : '谨慎批准'}
                      </span>
                    )}
                  </div>
                  <ReviewReportPanel report={reviewReport} />
                </div>
              )}

              {/* 审批意见（统一） */}
              <div className="pt-4 border-t border-border-default">
                <h4 className="text-sm font-medium text-text-primary mb-3 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-status-warning" />
                  审批意见
                  {(coderDecision === 'reject' || testerDecision === 'reject') && (
                    <span className="text-xs text-status-error">（拒绝时必须填写）</span>
                  )}
                </h4>
                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="请输入您的审批意见..."
                  className="w-full h-24 px-4 py-3 bg-bg-primary border border-border-default rounded-lg text-sm text-text-primary placeholder:text-text-tertiary resize-none focus:outline-none focus:border-brand-primary focus:ring-2 focus:ring-brand-primary/20 transition-all"
                />
              </div>
            </div>
          )}

          {/* 非 CODE_REVIEW 阶段的阶段特定内容 */}
          {!showUnifiedApproval && (
            <>
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
                  <MetricsPanel stage={liveSelectedStage ?? selectedStage} />
                )}
              </div>

              {/* 【阶段特定内容】根据阶段名称渲染不同面板 */}
              {selectedStage?.name === 'REQUIREMENT' && (
                <RequirementPanel outputData={(liveSelectedStage ?? selectedStage).output_data as Record<string, unknown> | undefined} />
              )}

              {selectedStage?.name === 'DESIGN' && (
                <DesignPanel outputData={(liveSelectedStage ?? selectedStage).output_data as Record<string, unknown> | undefined} />
              )}

              {(selectedStage?.name === 'CODING' || selectedStage?.name === 'CODE_REVIEW') && (
                <CodingPanel
                  outputData={codingStage?.output_data as Record<string, unknown> | undefined}
                />
              )}

              {selectedStage?.name === 'UNIT_TESTING' && (
                <TestingPanel
                  outputData={testingStage?.output_data as Record<string, unknown> | undefined}
                  pipelineId={selectedPipeline?.id}
                />
              )}

              {selectedStage?.name === 'DELIVERY' && (
                <DeliveryPanel outputData={(liveSelectedStage ?? selectedStage).output_data as Record<string, unknown> | undefined} />
              )}

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
            </>
          )}

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

          {/* 【新流程】CODE_REVIEW 阶段显示统一审批按钮 */}
          {showUnifiedApproval ? (
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
                onClick={handleUnifiedApprove}
                disabled={isSubmitting || !coderDecision || !testerDecision}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-brand-primary text-white rounded-lg text-sm font-medium hover:bg-brand-primary-hover transition-all disabled:opacity-50"
              >
                {isSubmitting ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />处理中...</>
                ) : (
                  <><CheckCircle2 className="w-4 h-4" />确认审批</>
                )}
              </button>
            </>
          ) : (
            /* 原有审批按钮（非 CODE_REVIEW 阶段） */
            selectedPipeline?.status === 'paused' &&
            selectedStage?.name === selectedPipeline?.current_stage ? (
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
              /* 不可操作的状态标签 */
              <>
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
            )
          )}
        </div>
      </div>
    </>
  );
}

function MetricsPanel({ stage }: { stage: PipelineStage }) {
  const metrics = getStageMetrics(stage);

  const items = [
    { label: 'Input tokens', value: metrics.inputTokens.toLocaleString() },
    { label: 'Output tokens', value: metrics.outputTokens.toLocaleString() },
    { label: 'Duration', value: formatMetricDuration(metrics.durationMs) },
    { label: 'Retries', value: metrics.retryCount.toLocaleString() },
  ];

  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((item) => (
        <div key={item.label} className="p-3 bg-bg-secondary rounded-lg border border-border-default">
          <div className="text-xs text-text-tertiary">{item.label}</div>
          <div className="mt-1 text-sm font-semibold text-text-primary">{item.value}</div>
        </div>
      ))}
      {metrics.reasoning && (
        <div className="col-span-2 p-3 bg-bg-secondary rounded-lg border border-border-default">
          <div className="text-xs text-text-tertiary mb-1">Reasoning</div>
          <p className="text-xs text-text-secondary whitespace-pre-wrap max-h-24 overflow-y-auto">
            {metrics.reasoning}
          </p>
        </div>
      )}
    </div>
  );
}
