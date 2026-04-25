import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Plus,
  Search,
  GitBranch,
  Clock,
  Play,
  RotateCcw,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { apiGet } from '@utils/axios';
import { useUIStore } from '@stores/uiStore';
import { PipelineCompletionModal } from '@components/Pipeline/PipelineCompletionModal';
import {
  StatCard,
  PendingApprovalCard,
  PipelineListItemRow,
  CreatePipelineModal,
  type Template,
} from '@components/Console';
import type { PipelineListItem, SystemStats, PipelineListResponse } from '@types';

// ============================================
// 控制台首页 - 飞书文档风格（企业级 SaaS 体验）
// ============================================

export function Console() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const { addToast } = useUIStore();
  const navigate = useNavigate();

  // 获取统计数据
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
    refetchInterval: 30000,
  });

  // 获取流水线列表
  const { data: pipelinesData, isLoading } = useQuery<PipelineListResponse>({
    queryKey: ['pipelines'],
    queryFn: () => apiGet('/pipelines'),
  });

  // 提取流水线数组
  const pipelines = pipelinesData?.pipelines || [];

  // 分离待审批和已完成/失败的流水线
  const pendingPipelines = pipelines.filter((p) => p.status === 'paused');
  const otherPipelines = pipelines.filter((p) => p.status !== 'paused');

  // 过滤其他流水线
  const filteredOtherPipelines = otherPipelines.filter(
    (p) => (p.description?.toLowerCase() || '').includes(searchQuery.toLowerCase())
  );

  // 快捷操作：Cmd+K 打开创建弹窗
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsModalOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 打开创建弹窗（带模板）
  const handleOpenModal = (template?: Template) => {
    setSelectedTemplate(template || null);
    setIsModalOpen(true);
  };

  return (
    <div className="space-y-8">
      {/* 页面标题 + 创建按钮 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">控制台</h1>
          <p className="text-text-secondary mt-1">管理和监控您的研发流水线</p>
        </div>
        <button onClick={() => handleOpenModal()} className="btn-primary">
          <Plus className="w-4 h-4 mr-2" />
          创建流水线
        </button>
      </div>

      {/* 统计卡片 */}
      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="总流水线"
          value={String(stats?.total_pipelines || 0)}
          trend="+12% 本月"
          icon={GitBranch}
        />
        <StatCard
          title="运行中"
          value={String(stats?.running_pipelines || 0)}
          icon={Play}
        />
        <StatCard
          title="已完成"
          value={String(stats?.completed_pipelines || 0)}
          trend="98% 成功率"
          icon={Clock}
        />
        <StatCard
          title="平均耗时"
          value={`${stats?.avg_duration || 0}min`}
          icon={RotateCcw}
        />
      </div>

      {/* 待您审批区块 */}
      {pendingPipelines.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-status-warning" />
              待您审批
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-status-warning/10 text-status-warning">
                {pendingPipelines.length}
              </span>
            </h2>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            {pendingPipelines.map((pipeline) => (
              <PendingApprovalCard
                key={pipeline.id}
                pipeline={pipeline}
                onClick={() => navigate(`/console/pipelines/${pipeline.id}`)}
              />
            ))}
          </div>
        </div>
      )}

      {/* 所有流水线列表（紧凑表格风格） */}
      <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card">
        {/* 列表头部 */}
        <div className="flex items-center justify-between p-4 border-b border-border-default">
          <h2 className="text-lg font-semibold text-text-primary">所有流水线</h2>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索流水线..."
              className="pl-9 pr-4 py-2 bg-bg-secondary border border-border-default rounded-md text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary w-64"
            />
          </div>
        </div>

        {/* 列表内容 */}
        {isLoading ? (
          <div className="p-12 flex items-center justify-center">
            <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
          </div>
        ) : filteredOtherPipelines?.length === 0 && pendingPipelines.length === 0 ? (
          <div className="p-12 text-center">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-secondary flex items-center justify-center">
              <GitBranch className="w-8 h-8 text-text-tertiary" />
            </div>
            <p className="text-text-secondary">暂无流水线</p>
            <button
              onClick={() => handleOpenModal()}
              className="mt-4 text-brand-primary text-sm font-medium hover:underline"
            >
              创建第一个流水线
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border-default">
            {filteredOtherPipelines?.map((pipeline) => (
              <PipelineListItemRow
                key={pipeline.id}
                pipeline={pipeline}
                onClick={() => navigate(`/console/pipelines/${pipeline.id}`)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 创建弹窗 */}
      <CreatePipelineModal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedTemplate(null);
        }}
        initialTemplate={selectedTemplate}
      />

      {/* Pipeline 完成弹窗 */}
      <PipelineCompletionModal />
    </div>
  );
}
