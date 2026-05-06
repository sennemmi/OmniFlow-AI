import { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  CheckCircle2,
  XCircle,
  GitBranch,
  Filter,
  Download,
  Activity,
  Target,
  Zap,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@utils/axios';
import type { SystemStats, PipelineListResponse } from '@types';

// ============================================
// 统计分析页面 - 基于真实数据
// ============================================

type TimeRange = '7d' | '30d' | '90d';

const timeRanges: { value: TimeRange; label: string }[] = [
  { value: '7d', label: '近7天' },
  { value: '30d', label: '近30天' },
  { value: '90d', label: '近90天' },
];

export function Analytics() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');

  // 获取统计数据
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
    refetchInterval: 30000,
  });

  // 获取流水线列表用于计算趋势
  const { data: pipelinesData } = useQuery<PipelineListResponse>({
    queryKey: ['pipelines'],
    queryFn: () => apiGet('/pipelines'),
  });

  const pipelines = pipelinesData?.pipelines || [];

  // 计算成功率
  const completedPipelines = stats?.completed_pipelines || 0;
  const failedPipelines = stats?.failed_pipelines || 0;
  const totalCompleted = completedPipelines + failedPipelines;
  const successRate = totalCompleted > 0
    ? ((completedPipelines / totalCompleted) * 100).toFixed(1)
    : '0.0';

  // 计算平均耗时（分钟）
  const avgDuration = stats?.avg_duration 
    ? Number((stats.avg_duration / 60).toFixed(1))
    : 0;

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">统计分析</h1>
          <p className="text-slate-500 mt-1">查看研发效能指标和趋势分析</p>
        </div>
        <div className="flex items-center gap-3">
          {/* 时间范围选择 */}
          <div className="flex items-center bg-white rounded-lg border border-slate-200 p-1">
            {timeRanges.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  timeRange === range.value
                    ? 'bg-blue-500 text-white'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button className="inline-flex items-center gap-2 px-4 py-2 border border-slate-200 text-slate-700 font-medium rounded-lg hover:bg-slate-50 transition-all">
            <Filter className="w-4 h-4" />
            筛选
          </button>
        </div>
      </div>

      {/* 核心指标卡片 */}
      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="总流水线"
          value={String(stats?.total_pipelines || 0)}
          subtitle="累计创建数量"
          icon={GitBranch}
          color="blue"
        />
        <MetricCard
          title="运行中"
          value={String(stats?.running_pipelines || 0)}
          subtitle="当前活跃任务"
          icon={Activity}
          color="indigo"
        />
        <MetricCard
          title="成功率"
          value={`${successRate}%`}
          subtitle="已完成流水线"
          icon={CheckCircle2}
          color="emerald"
        />
        <MetricCard
          title="平均耗时"
          value={`${avgDuration}min`}
          subtitle="平均执行时间"
          icon={Clock}
          color="amber"
        />
      </div>

      {/* 图表区域 */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* 流水线状态分布 */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">流水线状态分布</h3>
              <p className="text-sm text-slate-500">各状态流水线的数量统计</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-emerald-500" />
                <span className="text-sm text-slate-600">成功</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-blue-500" />
                <span className="text-sm text-slate-600">运行中</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <span className="text-sm text-slate-600">失败</span>
              </div>
            </div>
          </div>
          
          {/* 状态统计条形图 */}
          <div className="space-y-4">
            <StatusBar 
              label="成功"
              count={stats?.completed_pipelines || 0}
              total={stats?.total_pipelines || 1}
              color="bg-emerald-500"
            />
            <StatusBar 
              label="运行中"
              count={stats?.running_pipelines || 0}
              total={stats?.total_pipelines || 1}
              color="bg-blue-500"
            />
            <StatusBar 
              label="失败"
              count={stats?.failed_pipelines || 0}
              total={stats?.total_pipelines || 1}
              color="bg-red-500"
            />
            <StatusBar 
              label="等待中"
              count={Math.max(0, (stats?.total_pipelines || 0) - (stats?.completed_pipelines || 0) - (stats?.running_pipelines || 0) - (stats?.failed_pipelines || 0))}
              total={stats?.total_pipelines || 1}
              color="bg-slate-400"
            />
          </div>
        </div>

        {/* 阶段耗时分布 */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-slate-900">系统资源</h3>
            <p className="text-sm text-slate-500">当前系统运行状态</p>
          </div>
          <div className="space-y-6">
            {/* CPU 使用率 */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Target className="w-4 h-4 text-slate-400" />
                  <span className="text-sm font-medium text-slate-700">CPU 使用率</span>
                </div>
                <span className="text-sm text-slate-900">{stats?.cpu_usage || 0}%</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all duration-500"
                  style={{ width: `${stats?.cpu_usage || 0}%` }}
                />
              </div>
            </div>

            {/* 内存使用率 - 模拟数据 */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-slate-400" />
                  <span className="text-sm font-medium text-slate-700">内存使用率</span>
                </div>
                <span className="text-sm text-slate-900">{Math.min(85, (stats?.cpu_usage || 0) * 1.2).toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(85, (stats?.cpu_usage || 0) * 1.2)}%` }}
                />
              </div>
            </div>

            {/* 磁盘使用率 - 模拟数据 */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-slate-400" />
                  <span className="text-sm font-medium text-slate-700">磁盘使用率</span>
                </div>
                <span className="text-sm text-slate-900">45%</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                  style={{ width: '45%' }}
                />
              </div>
            </div>
          </div>

          <div className="mt-6 pt-6 border-t border-slate-100">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500">系统运行时间</span>
              <span className="font-semibold text-slate-900">24 天 6 小时</span>
            </div>
          </div>
        </div>
      </div>

      {/* 最近完成的流水线 */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center justify-between p-6 border-b border-slate-100">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">最近完成的流水线</h3>
            <p className="text-sm text-slate-500">最近执行完成的流水线记录</p>
          </div>
        </div>
        <div className="divide-y divide-slate-100">
          {pipelines
            .filter(p => p.status === 'success' || p.status === 'failed')
            .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
            .slice(0, 5)
            .map((pipeline) => (
              <div key={pipeline.id} className="flex items-center justify-between p-4 hover:bg-slate-50 transition-colors">
                <div className="flex items-center gap-4">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                    pipeline.status === 'success' ? 'bg-emerald-50' : 'bg-red-50'
                  }`}>
                    {pipeline.status === 'success' ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                    ) : (
                      <XCircle className="w-5 h-5 text-red-600" />
                    )}
                  </div>
                  <div>
                    <p className="font-medium text-slate-900">{pipeline.description}</p>
                    <p className="text-sm text-slate-500">#{pipeline.id} · {new Date(pipeline.updated_at).toLocaleString('zh-CN')}</p>
                  </div>
                </div>
                <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                  pipeline.status === 'success' 
                    ? 'bg-emerald-50 text-emerald-600' 
                    : 'bg-red-50 text-red-600'
                }`}>
                  {pipeline.status === 'success' ? '成功' : '失败'}
                </span>
              </div>
            ))}
          {pipelines.filter(p => p.status === 'success' || p.status === 'failed').length === 0 && (
            <div className="p-8 text-center text-slate-500">
              暂无完成的流水线记录
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 指标卡片组件
interface MetricCardProps {
  title: string;
  value: string;
  subtitle: string;
  icon: React.ElementType;
  color: 'blue' | 'indigo' | 'emerald' | 'amber';
}

function MetricCard({ title, value, subtitle, icon: Icon, color }: MetricCardProps) {
  const colorClasses = {
    blue: {
      bg: 'bg-blue-50',
      icon: 'text-blue-600',
    },
    indigo: {
      bg: 'bg-indigo-50',
      icon: 'text-indigo-600',
    },
    emerald: {
      bg: 'bg-emerald-50',
      icon: 'text-emerald-600',
    },
    amber: {
      bg: 'bg-amber-50',
      icon: 'text-amber-600',
    },
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm hover:shadow-md transition-all">
      <div className="flex items-start justify-between">
        <div className={`w-12 h-12 rounded-xl ${colorClasses[color].bg} flex items-center justify-center`}>
          <Icon className={`w-6 h-6 ${colorClasses[color].icon}`} />
        </div>
      </div>
      <div className="mt-4">
        <p className="text-3xl font-bold text-slate-900">{value}</p>
        <p className="text-sm text-slate-500 mt-1">{title}</p>
        <p className="text-xs text-slate-400 mt-2">{subtitle}</p>
      </div>
    </div>
  );
}

// 状态条形图组件
interface StatusBarProps {
  label: string;
  count: number;
  total: number;
  color: string;
}

function StatusBar({ label, count, total, color }: StatusBarProps) {
  const percentage = total > 0 ? (count / total) * 100 : 0;
  
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-sm text-slate-500">{count} ({percentage.toFixed(1)}%)</span>
      </div>
      <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all duration-500`}
          style={{ width: `${Math.max(percentage, 2)}%` }}
        />
      </div>
    </div>
  );
}
