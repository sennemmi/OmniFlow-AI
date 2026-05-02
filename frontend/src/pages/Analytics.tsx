import { useState } from 'react';
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  Clock,
  CheckCircle2,
  XCircle,
  GitBranch,
  Users,
  Calendar,
  Filter,
  Download,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Target,
  Zap,
  MoreHorizontal,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@utils/axios';
import type { SystemStats } from '@types';

// ============================================
// 统计分析页面 - 企业级数据可视化
// ============================================

type TimeRange = '7d' | '30d' | '90d' | '1y';

const timeRanges: { value: TimeRange; label: string }[] = [
  { value: '7d', label: '近7天' },
  { value: '30d', label: '近30天' },
  { value: '90d', label: '近90天' },
  { value: '1y', label: '近1年' },
];

export function Analytics() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');

  // 获取统计数据
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
    refetchInterval: 30000,
  });

  // 模拟趋势数据
  const trendData = {
    pipelines: { value: 128, change: 12.5, up: true },
    successRate: { value: 98.5, change: 2.1, up: true },
    avgDuration: { value: 4.2, change: -8.3, up: false },
    deployments: { value: 45, change: 15.2, up: true },
  };

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">统计分析</h1>
          <p className="text-text-secondary mt-1">查看研发效能指标和趋势分析</p>
        </div>
        <div className="flex items-center gap-3">
          {/* 时间范围选择 */}
          <div className="flex items-center bg-bg-primary rounded-lg border border-border-default p-1">
            {timeRanges.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  timeRange === range.value
                    ? 'bg-brand-primary text-white'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button className="btn-secondary">
            <Filter className="w-4 h-4 mr-2" />
            筛选
          </button>
          <button className="btn-secondary">
            <Download className="w-4 h-4 mr-2" />
            导出
          </button>
        </div>
      </div>

      {/* 核心指标卡片 */}
      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="流水线执行"
          value={String(stats?.total_pipelines || trendData.pipelines.value)}
          change={trendData.pipelines.change}
          up={trendData.pipelines.up}
          icon={GitBranch}
          trend={[40, 55, 45, 60, 70, 65, 80, 75, 85, 90]}
        />
        <MetricCard
          title="成功率"
          value={`${trendData.successRate.value}%`}
          change={trendData.successRate.change}
          up={trendData.successRate.up}
          icon={CheckCircle2}
          trend={[95, 96, 95, 97, 96, 98, 97, 98, 99, 98.5]}
        />
        <MetricCard
          title="平均耗时"
          value={`${stats?.avg_duration || trendData.avgDuration.value}min`}
          change={trendData.avgDuration.change}
          up={trendData.avgDuration.up}
          icon={Clock}
          trend={[6, 5.8, 5.5, 5.2, 5, 4.8, 4.5, 4.3, 4.2, 4.2]}
        />
        <MetricCard
          title="部署次数"
          value={String(trendData.deployments.value)}
          change={trendData.deployments.change}
          up={trendData.deployments.up}
          icon={Zap}
          trend={[20, 25, 22, 28, 30, 32, 35, 38, 42, 45]}
        />
      </div>

      {/* 图表区域 */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* 流水线趋势图 */}
        <div className="lg:col-span-2 bg-bg-primary rounded-xl border border-border-default shadow-feishu-card p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold text-text-primary">流水线执行趋势</h3>
              <p className="text-sm text-text-secondary">每日流水线执行数量和状态分布</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-status-success" />
                <span className="text-sm text-text-secondary">成功</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-status-error" />
                <span className="text-sm text-text-secondary">失败</span>
              </div>
            </div>
          </div>
          <div className="h-64 flex items-end justify-between gap-2">
            {[
              { success: 45, failed: 5 },
              { success: 52, failed: 3 },
              { success: 48, failed: 7 },
              { success: 60, failed: 2 },
              { success: 55, failed: 4 },
              { success: 68, failed: 3 },
              { success: 72, failed: 2 },
              { success: 65, failed: 5 },
              { success: 78, failed: 1 },
              { success: 82, failed: 2 },
              { success: 75, failed: 3 },
              { success: 88, failed: 2 },
            ].map((day, index) => {
              const total = day.success + day.failed;
              const successHeight = (day.success / total) * 100;
              const failedHeight = (day.failed / total) * 100;
              return (
                <div key={index} className="flex-1 flex flex-col justify-end gap-1 group cursor-pointer">
                  <div className="relative w-full">
                    <div
                      className="w-full bg-status-success rounded-t-md transition-all group-hover:opacity-80"
                      style={{ height: `${successHeight * 2}px` }}
                    />
                    <div
                      className="w-full bg-status-error rounded-b-md transition-all group-hover:opacity-80"
                      style={{ height: `${failedHeight * 2}px` }}
                    />
                  </div>
                  <span className="text-xs text-text-tertiary text-center">
                    {index + 1}日
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* 阶段耗时分布 */}
        <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card p-6">
          <div className="mb-6">
            <h3 className="text-lg font-semibold text-text-primary">阶段耗时分布</h3>
            <p className="text-sm text-text-secondary">各阶段平均耗时占比</p>
          </div>
          <div className="space-y-4">
            {[
              { name: '架构设计', duration: 15, color: 'bg-blue-500', icon: Target },
              { name: '代码生成', duration: 35, color: 'bg-purple-500', icon: Zap },
              { name: '测试验证', duration: 30, color: 'bg-green-500', icon: CheckCircle2 },
              { name: '部署发布', duration: 20, color: 'bg-orange-500', icon: Rocket },
            ].map((stage) => {
              const Icon = stage.icon;
              return (
                <div key={stage.name} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Icon className="w-4 h-4 text-text-tertiary" />
                      <span className="text-sm font-medium text-text-primary">{stage.name}</span>
                    </div>
                    <span className="text-sm text-text-secondary">{stage.duration}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-bg-tertiary overflow-hidden">
                    <div
                      className={`h-full rounded-full ${stage.color} transition-all duration-500`}
                      style={{ width: `${stage.duration}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-6 pt-6 border-t border-border-default">
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">平均总耗时</span>
              <span className="font-semibold text-text-primary">4.2 分钟</span>
            </div>
          </div>
        </div>
      </div>

      {/* 详细数据表格 */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* 热门项目 */}
        <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card">
          <div className="flex items-center justify-between p-6 border-b border-border-default">
            <div>
              <h3 className="text-lg font-semibold text-text-primary">热门项目</h3>
              <p className="text-sm text-text-secondary">执行次数最多的项目</p>
            </div>
            <button className="text-brand-primary text-sm font-medium hover:underline">
              查看全部
            </button>
          </div>
          <div className="divide-y divide-border-default">
            {[
              { name: '前端主项目', pipelines: 156, success: 98.1, trend: 'up' },
              { name: '后端 API 服务', pipelines: 142, success: 97.9, trend: 'up' },
              { name: '移动端应用', pipelines: 89, success: 96.5, trend: 'down' },
              { name: '数据平台', pipelines: 67, success: 99.2, trend: 'up' },
              { name: '管理后台', pipelines: 54, success: 95.8, trend: 'stable' },
            ].map((project, index) => (
              <div key={index} className="flex items-center justify-between p-4 hover:bg-bg-secondary transition-colors">
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 rounded-lg bg-brand-primary/10 flex items-center justify-center text-brand-primary font-semibold text-sm">
                    {index + 1}
                  </div>
                  <div>
                    <p className="font-medium text-text-primary">{project.name}</p>
                    <p className="text-sm text-text-secondary">{project.pipelines} 次执行</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <p className="font-medium text-text-primary">{project.success}%</p>
                    <p className="text-xs text-text-secondary">成功率</p>
                  </div>
                  {project.trend === 'up' && <TrendingUp className="w-5 h-5 text-status-success" />}
                  {project.trend === 'down' && <TrendingDown className="w-5 h-5 text-status-error" />}
                  {project.trend === 'stable' && <Activity className="w-5 h-5 text-text-tertiary" />}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 最近活动 */}
        <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card">
          <div className="flex items-center justify-between p-6 border-b border-border-default">
            <div>
              <h3 className="text-lg font-semibold text-text-primary">最近活动</h3>
              <p className="text-sm text-text-secondary">系统最新动态</p>
            </div>
            <button className="text-brand-primary text-sm font-medium hover:underline">
              查看全部
            </button>
          </div>
          <div className="divide-y divide-border-default">
            {[
              { type: 'success', message: '流水线 #1289 执行成功', time: '2 分钟前', project: '前端主项目' },
              { type: 'deploy', message: '生产环境部署完成', time: '15 分钟前', project: '后端 API 服务' },
              { type: 'approval', message: '新的审批请求', time: '1 小时前', project: '移动端应用' },
              { type: 'error', message: '流水线 #1285 执行失败', time: '2 小时前', project: '数据平台' },
              { type: 'success', message: '流水线 #1284 执行成功', time: '3 小时前', project: '管理后台' },
            ].map((activity, index) => (
              <div key={index} className="flex items-start gap-4 p-4 hover:bg-bg-secondary transition-colors">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                  activity.type === 'success' ? 'bg-status-success/10' :
                  activity.type === 'error' ? 'bg-status-error/10' :
                  activity.type === 'deploy' ? 'bg-brand-primary/10' :
                  'bg-status-warning/10'
                }`}>
                  {activity.type === 'success' && <CheckCircle2 className="w-5 h-5 text-status-success" />}
                  {activity.type === 'error' && <XCircle className="w-5 h-5 text-status-error" />}
                  {activity.type === 'deploy' && <Zap className="w-5 h-5 text-brand-primary" />}
                  {activity.type === 'approval' && <Users className="w-5 h-5 text-status-warning" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-text-primary">{activity.message}</p>
                  <p className="text-sm text-text-secondary">{activity.project}</p>
                </div>
                <span className="text-xs text-text-tertiary flex-shrink-0">{activity.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 团队效能 */}
      <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-semibold text-text-primary">团队效能</h3>
            <p className="text-sm text-text-secondary">团队成员贡献统计</p>
          </div>
          <button className="btn-secondary">
            <Users className="w-4 h-4 mr-2" />
            管理团队
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">成员</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">流水线</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">成功率</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">平均耗时</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">最近活动</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-text-secondary">趋势</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-default">
              {[
                { name: '张三', role: '前端工程师', pipelines: 45, success: 98.5, duration: '3.2min', lastActive: '10 分钟前', trend: 'up' },
                { name: '李四', role: '后端工程师', pipelines: 38, success: 97.2, duration: '4.1min', lastActive: '30 分钟前', trend: 'up' },
                { name: '王五', role: '全栈工程师', pipelines: 52, success: 96.8, duration: '3.8min', lastActive: '1 小时前', trend: 'stable' },
                { name: '赵六', role: 'DevOps', pipelines: 67, success: 99.1, duration: '2.9min', lastActive: '5 分钟前', trend: 'up' },
                { name: '钱七', role: '测试工程师', pipelines: 28, success: 95.5, duration: '5.2min', lastActive: '2 小时前', trend: 'down' },
              ].map((member, index) => (
                <tr key={index} className="hover:bg-bg-secondary transition-colors">
                  <td className="py-4 px-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-brand-primary/10 flex items-center justify-center">
                        <span className="text-brand-primary font-semibold">{member.name[0]}</span>
                      </div>
                      <div>
                        <p className="font-medium text-text-primary">{member.name}</p>
                        <p className="text-sm text-text-secondary">{member.role}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-4 px-4">
                    <span className="font-medium text-text-primary">{member.pipelines}</span>
                  </td>
                  <td className="py-4 px-4">
                    <span className={`font-medium ${member.success >= 98 ? 'text-status-success' : member.success >= 95 ? 'text-text-primary' : 'text-status-warning'}`}>
                      {member.success}%
                    </span>
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-text-primary">{member.duration}</span>
                  </td>
                  <td className="py-4 px-4">
                    <span className="text-text-secondary">{member.lastActive}</span>
                  </td>
                  <td className="py-4 px-4">
                    {member.trend === 'up' && (
                      <span className="inline-flex items-center gap-1 text-status-success text-sm">
                        <ArrowUpRight className="w-4 h-4" />
                        上升
                      </span>
                    )}
                    {member.trend === 'down' && (
                      <span className="inline-flex items-center gap-1 text-status-error text-sm">
                        <ArrowDownRight className="w-4 h-4" />
                        下降
                      </span>
                    )}
                    {member.trend === 'stable' && (
                      <span className="inline-flex items-center gap-1 text-text-secondary text-sm">
                        <Activity className="w-4 h-4" />
                        稳定
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// 指标卡片组件
interface MetricCardProps {
  title: string;
  value: string;
  change: number;
  up: boolean;
  icon: React.ElementType;
  trend: number[];
}

function MetricCard({ title, value, change, up, icon: Icon, trend }: MetricCardProps) {
  const min = Math.min(...trend);
  const max = Math.max(...trend);
  const range = max - min || 1;

  return (
    <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="w-12 h-12 rounded-xl bg-brand-primary/10 flex items-center justify-center">
          <Icon className="w-6 h-6 text-brand-primary" />
        </div>
        <div className={`flex items-center gap-1 text-sm font-medium ${up ? 'text-status-success' : 'text-status-error'}`}>
          {up ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          {Math.abs(change)}%
        </div>
      </div>
      <h3 className="text-2xl font-bold text-text-primary mb-1">{value}</h3>
      <p className="text-text-secondary text-sm mb-4">{title}</p>
      {/* 迷你趋势图 */}
      <div className="h-10 flex items-end gap-1">
        {trend.map((value, index) => {
          const height = ((value - min) / range) * 100;
          return (
            <div
              key={index}
              className="flex-1 bg-brand-primary/20 rounded-sm"
              style={{ height: `${Math.max(height, 10)}%` }}
            />
          );
        })}
      </div>
    </div>
  );
}

// 辅助组件
function Rocket(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
      <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
      <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
    </svg>
  );
}
