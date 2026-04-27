import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Plus,
  GitBranch,
  Clock,
  Play,
  TrendingUp,
  TrendingDown,
  Activity,
  CheckCircle2,
  XCircle,
  ArrowRight,
  BarChart3,
  Cpu,
  Database,
  Server,
  AlertCircle,
  Sparkles,
  ChevronRight,
  RefreshCw,
  Flame,
  Target,
  Zap,
} from 'lucide-react';
import { apiGet } from '@utils/axios';
import { PipelineCompletionModal } from '@components/Pipeline/PipelineCompletionModal';
import { CreatePipelineModal, type Template } from '@components/Console';
import type { PipelineListItem, SystemStats, PipelineListResponse } from '@types';

// ============================================
// 控制台首页 - 企业级 Dashboard
// ============================================

export function Console() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const navigate = useNavigate();

  // 获取统计数据
  const { data: stats, refetch: refetchStats } = useQuery<SystemStats>({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
    refetchInterval: 30000,
  });

  // 获取流水线列表
  const { data: pipelinesData, isLoading } = useQuery<PipelineListResponse>({
    queryKey: ['pipelines'],
    queryFn: () => apiGet('/pipelines'),
  });

  const pipelines = pipelinesData?.pipelines || [];

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

  // 打开创建弹窗
  const handleOpenModal = (template?: Template) => {
    setSelectedTemplate(template || null);
    setIsModalOpen(true);
  };

  // 计算平均耗时
  const avgDuration = stats?.avg_duration ? Number(stats.avg_duration.toFixed(2)) : 0;

  // 获取最近的流水线
  const recentPipelines = pipelines.slice(0, 5);

  // 获取待审批的流水线
  const pendingPipelines = pipelines.filter((p) => p.status === 'paused').slice(0, 3);

  return (
    <div className="space-y-8">
      {/* 页面头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">控制台概览</h1>
          <p className="text-slate-500 mt-1">实时监控您的 AI 研发流水线运行状态</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetchStats()}
            className="p-2.5 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-all"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            onClick={() => navigate('/console/analytics')}
            className="inline-flex items-center gap-2 px-4 py-2.5 border border-slate-200 text-slate-700 font-medium rounded-lg hover:bg-slate-50 transition-all"
          >
            <BarChart3 className="w-4 h-4" />
            查看报表
          </button>
          <button
            onClick={() => handleOpenModal()}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-all shadow-sm hover:shadow-md"
          >
            <Plus className="w-5 h-5" />
            创建流水线
          </button>
        </div>
      </div>

      {/* 核心指标卡片 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="总流水线"
          value={String(stats?.total_pipelines || 0)}
          subtitle="较上月 +12.5%"
          trend="up"
          icon={GitBranch}
          color="blue"
        />
        <MetricCard
          title="运行中"
          value={String(stats?.running_pipelines || 0)}
          subtitle="活跃任务"
          trend="neutral"
          icon={Play}
          color="indigo"
        />
        <MetricCard
          title="成功率"
          value="98.5%"
          subtitle="较上月 +2.3%"
          trend="up"
          icon={CheckCircle2}
          color="emerald"
        />
        <MetricCard
          title="平均耗时"
          value={`${avgDuration}min`}
          subtitle="较上月 -5.2%"
          trend="down"
          icon={Clock}
          color="amber"
        />
      </div>

      {/* 主内容区 */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* 左侧：占 2/3 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 快速开始 */}
          <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-700 p-8 text-white">
            <div className="absolute top-0 right-0 w-64 h-64 bg-white/10 rounded-full -translate-y-1/2 translate-x-1/2 blur-3xl" />
            <div className="absolute bottom-0 left-0 w-48 h-48 bg-white/5 rounded-full translate-y-1/2 -translate-x-1/2 blur-2xl" />
            
            <div className="relative">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-5 h-5 text-blue-200" />
                <span className="text-blue-100 text-sm font-medium">AI 驱动研发</span>
              </div>
              <h2 className="text-2xl font-bold mb-2">开始您的 AI 流水线之旅</h2>
              <p className="text-blue-100 mb-6 max-w-lg">
                描述您的需求，AI 将自动完成架构设计、代码生成、测试验证和部署发布。让研发效率提升 10 倍。
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => handleOpenModal()}
                  className="px-5 py-2.5 bg-white text-blue-600 font-medium rounded-xl hover:bg-blue-50 transition-all shadow-lg"
                >
                  立即创建
                </button>
                <button
                  onClick={() => navigate('/console/documents')}
                  className="px-5 py-2.5 bg-white/10 text-white font-medium rounded-xl hover:bg-white/20 transition-all"
                >
                  查看文档
                </button>
              </div>
            </div>
          </div>

          {/* 最近活动 */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center">
                  <Activity className="w-5 h-5 text-slate-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900">最近活动</h3>
                  <p className="text-sm text-slate-500">最近 5 条流水线记录</p>
                </div>
              </div>
              <button
                onClick={() => navigate('/console/pipelines')}
                className="text-sm text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
              >
                查看全部
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <div className="divide-y divide-slate-100">
              {isLoading ? (
                <div className="p-8 flex items-center justify-center">
                  <RefreshCw className="w-6 h-6 text-blue-600 animate-spin" />
                </div>
              ) : recentPipelines.length === 0 ? (
                <div className="p-8 text-center text-slate-500">
                  暂无流水线记录
                </div>
              ) : (
                recentPipelines.map((pipeline) => (
                  <RecentActivityItem
                    key={pipeline.id}
                    pipeline={pipeline}
                    onClick={() => navigate(`/console/pipelines/${pipeline.id}`)}
                  />
                ))
              )}
            </div>
          </div>
        </div>

        {/* 右侧：占 1/3 */}
        <div className="space-y-6">
          {/* 系统状态 */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-slate-900">系统状态</h3>
              <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                运行正常
              </span>
            </div>
            <div className="space-y-4">
              <SystemStatusItem
                icon={Server}
                label="API 服务"
                status="正常"
                statusColor="emerald"
              />
              <SystemStatusItem
                icon={Cpu}
                label="AI 引擎"
                status="正常"
                statusColor="emerald"
              />
              <SystemStatusItem
                icon={Database}
                label="数据库"
                status="正常"
                statusColor="emerald"
              />
              <SystemStatusItem
                icon={Flame}
                label="消息队列"
                status="正常"
                statusColor="emerald"
              />
            </div>

            {/* CPU 使用率 */}
            <div className="mt-6 pt-4 border-t border-slate-100">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-slate-600">CPU 使用率</span>
                <span className="text-sm font-medium text-slate-900">{stats?.cpu_usage || 0}%</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-500"
                  style={{ width: `${stats?.cpu_usage || 0}%` }}
                />
              </div>
            </div>
          </div>

          {/* 待审批 */}
          {pendingPipelines.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <AlertCircle className="w-5 h-5 text-amber-600" />
                <h3 className="font-semibold text-amber-900">待您审批</h3>
                <span className="px-2 py-0.5 bg-amber-200 text-amber-800 text-xs font-medium rounded-full">
                  {pendingPipelines.length}
                </span>
              </div>
              <div className="space-y-3">
                {pendingPipelines.map((pipeline) => (
                  <div
                    key={pipeline.id}
                    onClick={() => navigate(`/console/pipelines/${pipeline.id}`)}
                    className="p-3 bg-white border border-amber-200 rounded-lg cursor-pointer hover:shadow-md transition-all"
                  >
                    <p className="text-sm font-medium text-slate-900 line-clamp-1">
                      {pipeline.description}
                    </p>
                    <p className="text-xs text-slate-500 mt-1">
                      等待审批 · {pipeline.current_stage}
                    </p>
                  </div>
                ))}
              </div>
              <button
                onClick={() => navigate('/console/pipelines')}
                className="w-full mt-4 py-2 text-sm text-amber-700 font-medium hover:text-amber-800 transition-colors"
              >
                查看全部待审批
              </button>
            </div>
          )}

          {/* 快捷入口 */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
            <h3 className="font-semibold text-slate-900 mb-4">快捷入口</h3>
            <div className="space-y-2">
              <QuickLink
                icon={Target}
                label="流水线管理"
                description="查看和管理所有流水线"
                onClick={() => navigate('/console/pipelines')}
              />
              <QuickLink
                icon={BarChart3}
                label="数据分析"
                description="查看执行统计和趋势"
                onClick={() => navigate('/console/analytics')}
              />
              <QuickLink
                icon={Zap}
                label="工作区"
                description="管理代码和文件"
                onClick={() => navigate('/console/workspace')}
              />
            </div>
          </div>
        </div>
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

// 指标卡片组件
interface MetricCardProps {
  title: string;
  value: string;
  subtitle: string;
  trend: 'up' | 'down' | 'neutral';
  icon: React.ElementType;
  color: 'blue' | 'indigo' | 'emerald' | 'amber' | 'red';
}

function MetricCard({ title, value, subtitle, trend, icon: Icon, color }: MetricCardProps) {
  const colorClasses = {
    blue: {
      bg: 'bg-blue-50',
      icon: 'text-blue-600',
      border: 'border-blue-100',
    },
    indigo: {
      bg: 'bg-indigo-50',
      icon: 'text-indigo-600',
      border: 'border-indigo-100',
    },
    emerald: {
      bg: 'bg-emerald-50',
      icon: 'text-emerald-600',
      border: 'border-emerald-100',
    },
    amber: {
      bg: 'bg-amber-50',
      icon: 'text-amber-600',
      border: 'border-amber-100',
    },
    red: {
      bg: 'bg-red-50',
      icon: 'text-red-600',
      border: 'border-red-100',
    },
  };

  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Activity;
  const trendColor = trend === 'up' ? 'text-emerald-600' : trend === 'down' ? 'text-emerald-600' : 'text-slate-400';

  return (
    <div className={`bg-white border ${colorClasses[color].border} rounded-xl p-6 shadow-sm hover:shadow-md transition-all`}>
      <div className="flex items-start justify-between">
        <div className={`w-12 h-12 rounded-xl ${colorClasses[color].bg} flex items-center justify-center`}>
          <Icon className={`w-6 h-6 ${colorClasses[color].icon}`} />
        </div>
        {trend !== 'neutral' && (
          <div className={`flex items-center gap-1 text-xs font-medium ${trendColor}`}>
            <TrendIcon className="w-3.5 h-3.5" />
          </div>
        )}
      </div>
      <div className="mt-4">
        <p className="text-3xl font-bold text-slate-900">{value}</p>
        <p className="text-sm text-slate-500 mt-1">{title}</p>
        <p className={`text-xs mt-2 ${trend === 'up' ? 'text-emerald-600' : trend === 'down' ? 'text-emerald-600' : 'text-slate-400'}`}>
          {subtitle}
        </p>
      </div>
    </div>
  );
}

// 最近活动项
interface RecentActivityItemProps {
  pipeline: PipelineListItem;
  onClick: () => void;
}

function RecentActivityItem({ pipeline, onClick }: RecentActivityItemProps) {
  const statusConfig = {
    running: {
      icon: Play,
      color: 'text-blue-600',
      bg: 'bg-blue-50',
      label: '运行中',
      dot: 'bg-blue-500',
    },
    success: {
      icon: CheckCircle2,
      color: 'text-emerald-600',
      bg: 'bg-emerald-50',
      label: '成功',
      dot: 'bg-emerald-500',
    },
    failed: {
      icon: XCircle,
      color: 'text-red-600',
      bg: 'bg-red-50',
      label: '失败',
      dot: 'bg-red-500',
    },
    paused: {
      icon: AlertCircle,
      color: 'text-amber-600',
      bg: 'bg-amber-50',
      label: '暂停',
      dot: 'bg-amber-500',
    },
  };

  const config = statusConfig[pipeline.status] || statusConfig.running;
  const StatusIcon = config.icon;

  return (
    <div
      onClick={onClick}
      className="flex items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors cursor-pointer group"
    >
      <div className="flex items-center gap-4">
        <div className={`w-10 h-10 rounded-lg ${config.bg} flex items-center justify-center`}>
          <StatusIcon className={`w-5 h-5 ${config.color}`} />
        </div>
        <div>
          <p className="font-medium text-slate-900 group-hover:text-blue-600 transition-colors line-clamp-1">
            {pipeline.description}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-slate-500">#{pipeline.id}</span>
            <span className="text-xs text-slate-300">·</span>
            <span className="text-xs text-slate-500">
              {new Date(pipeline.created_at).toLocaleDateString('zh-CN')}
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {pipeline.current_stage && (
          <span className="hidden sm:inline-flex px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 text-xs font-medium">
            {pipeline.current_stage}
          </span>
        )}
        <ArrowRight className="w-4 h-4 text-slate-300 group-hover:text-blue-600 transition-colors" />
      </div>
    </div>
  );
}

// 系统状态项
interface SystemStatusItemProps {
  icon: React.ElementType;
  label: string;
  status: string;
  statusColor: 'emerald' | 'amber' | 'red';
}

function SystemStatusItem({ icon: Icon, label, status, statusColor }: SystemStatusItemProps) {
  const colorClasses = {
    emerald: 'text-emerald-600',
    amber: 'text-amber-600',
    red: 'text-red-600',
  };

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Icon className="w-4 h-4 text-slate-400" />
        <span className="text-sm text-slate-600">{label}</span>
      </div>
      <span className={`text-xs font-medium ${colorClasses[statusColor]}`}>{status}</span>
    </div>
  );
}

// 快捷链接
interface QuickLinkProps {
  icon: React.ElementType;
  label: string;
  description: string;
  onClick: () => void;
}

function QuickLink({ icon: Icon, label, description, onClick }: QuickLinkProps) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-slate-50 transition-all group text-left"
    >
      <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center group-hover:bg-blue-100 transition-colors">
        <Icon className="w-5 h-5 text-blue-600" />
      </div>
      <div className="flex-1">
        <p className="font-medium text-slate-900 group-hover:text-blue-600 transition-colors">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-blue-600 transition-colors" />
    </button>
  );
}
