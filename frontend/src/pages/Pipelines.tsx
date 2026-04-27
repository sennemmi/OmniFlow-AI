import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Plus,
  Search,
  GitBranch,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Calendar,
  ArrowUpRight,
  Layers,
  RefreshCw,
  ChevronDown,
  LayoutGrid,
  List,
  Trash2,
  Edit3,
  Pause,
} from 'lucide-react';
import { apiGet } from '@utils/axios';
import type { PipelineListItem, PipelineListResponse } from '@types';

// ============================================
// 流水线管理页面 - 企业级列表视图
// ============================================

type ViewMode = 'list' | 'grid';
type SortField = 'created_at' | 'status' | 'description';
type SortOrder = 'asc' | 'desc';

export function Pipelines() {
  const navigate = useNavigate();
  
  // 状态管理
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());

  // 获取流水线列表
  const { data: pipelinesData, isLoading, refetch } = useQuery<PipelineListResponse>({
    queryKey: ['pipelines'],
    queryFn: () => apiGet('/pipelines'),
  });

  const pipelines = pipelinesData?.pipelines || [];

  // 过滤和排序
  const filteredPipelines = useMemo(() => {
    let result = [...pipelines];

    // 搜索过滤
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.description?.toLowerCase().includes(query) ||
          String(p.id).toLowerCase().includes(query)
      );
    }

    // 状态过滤
    if (statusFilter !== 'all') {
      result = result.filter((p) => p.status === statusFilter);
    }

    // 排序
    result.sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case 'created_at':
          comparison = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case 'status':
          comparison = a.status.localeCompare(b.status);
          break;
        case 'description':
          comparison = (a.description || '').localeCompare(b.description || '');
          break;
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });

    return result;
  }, [pipelines, searchQuery, statusFilter, sortField, sortOrder]);

  // 统计数据
  const stats = useMemo(() => {
    const total = pipelines.length;
    const running = pipelines.filter((p) => p.status === 'running').length;
    const success = pipelines.filter((p) => p.status === 'success').length;
    const failed = pipelines.filter((p) => p.status === 'failed').length;
    const paused = pipelines.filter((p) => p.status === 'paused').length;
    return { total, running, success, failed, paused };
  }, [pipelines]);

  // 切换排序
  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  // 选择项处理
  const toggleSelection = (id: number) => {
    const newSelected = new Set(selectedItems);
    const idStr = String(id);
    if (newSelected.has(idStr)) {
      newSelected.delete(idStr);
    } else {
      newSelected.add(idStr);
    }
    setSelectedItems(newSelected);
  };

  const selectAll = () => {
    if (selectedItems.size === filteredPipelines.length) {
      setSelectedItems(new Set());
    } else {
      setSelectedItems(new Set(filteredPipelines.map((p) => String(p.id))));
    }
  };

  // 状态配置
  const statusConfig = {
    running: {
      icon: Play,
      label: '运行中',
      color: 'text-blue-600',
      bgColor: 'bg-blue-50',
      borderColor: 'border-blue-200',
      dotColor: 'bg-blue-500',
    },
    success: {
      icon: CheckCircle2,
      label: '成功',
      color: 'text-emerald-600',
      bgColor: 'bg-emerald-50',
      borderColor: 'border-emerald-200',
      dotColor: 'bg-emerald-500',
    },
    failed: {
      icon: XCircle,
      label: '失败',
      color: 'text-red-600',
      bgColor: 'bg-red-50',
      borderColor: 'border-red-200',
      dotColor: 'bg-red-500',
    },
    paused: {
      icon: Pause,
      label: '暂停',
      color: 'text-amber-600',
      bgColor: 'bg-amber-50',
      borderColor: 'border-amber-200',
      dotColor: 'bg-amber-500',
    },
    pending: {
      icon: Clock,
      label: '等待中',
      color: 'text-slate-600',
      bgColor: 'bg-slate-50',
      borderColor: 'border-slate-200',
      dotColor: 'bg-slate-400',
    },
  };

  return (
    <div className="h-full flex flex-col">
      {/* 页面头部 */}
      <div className="flex flex-col gap-6 pb-6 border-b border-slate-200">
        {/* 标题行 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">流水线管理</h1>
            <p className="text-slate-500 mt-1">管理和监控所有 AI 研发流水线</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => refetch()}
              className="p-2.5 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-all"
              title="刷新"
            >
              <RefreshCw className={`w-5 h-5 ${isLoading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={() => navigate('/console/pipelines/new')}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-all shadow-sm hover:shadow-md"
            >
              <Plus className="w-5 h-5" />
              创建流水线
            </button>
          </div>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-5 gap-4">
          <StatCard
            label="全部流水线"
            value={stats.total}
            icon={Layers}
            color="slate"
            isActive={statusFilter === 'all'}
            onClick={() => setStatusFilter('all')}
          />
          <StatCard
            label="运行中"
            value={stats.running}
            icon={Play}
            color="blue"
            isActive={statusFilter === 'running'}
            onClick={() => setStatusFilter('running')}
          />
          <StatCard
            label="成功"
            value={stats.success}
            icon={CheckCircle2}
            color="emerald"
            isActive={statusFilter === 'success'}
            onClick={() => setStatusFilter('success')}
          />
          <StatCard
            label="失败"
            value={stats.failed}
            icon={XCircle}
            color="red"
            isActive={statusFilter === 'failed'}
            onClick={() => setStatusFilter('failed')}
          />
          <StatCard
            label="暂停"
            value={stats.paused}
            icon={Pause}
            color="amber"
            isActive={statusFilter === 'paused'}
            onClick={() => setStatusFilter('paused')}
          />
        </div>
      </div>

      {/* 工具栏 */}
      <div className="flex items-center justify-between py-4">
        <div className="flex items-center gap-3">
          {/* 搜索框 */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索流水线..."
              className="pl-10 pr-4 py-2 w-64 bg-white border border-slate-200 rounded-lg text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
            />
          </div>

          {/* 批量操作 */}
          {selectedItems.size > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-lg">
              <span className="text-sm text-blue-700 font-medium">
                已选择 {selectedItems.size} 项
              </span>
              <button
                onClick={() => setSelectedItems(new Set())}
                className="text-blue-600 hover:text-blue-800"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* 视图切换 */}
          <div className="flex items-center bg-slate-100 rounded-lg p-1">
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 rounded-md transition-all ${
                viewMode === 'list'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
              title="列表视图"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 rounded-md transition-all ${
                viewMode === 'grid'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
              title="网格视图"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* 内容区域 */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <div className="flex items-center gap-3">
              <RefreshCw className="w-6 h-6 text-blue-600 animate-spin" />
              <span className="text-slate-500">加载中...</span>
            </div>
          </div>
        ) : filteredPipelines.length === 0 ? (
          <EmptyState onCreate={() => navigate('/console/pipelines/new')} />
        ) : viewMode === 'list' ? (
          <ListView
            pipelines={filteredPipelines}
            selectedItems={selectedItems}
            onToggleSelection={toggleSelection}
            onSelectAll={selectAll}
            onSort={toggleSort}
            sortField={sortField}
            sortOrder={sortOrder}
            statusConfig={statusConfig}
            onNavigate={navigate}
          />
        ) : (
          <GridView
            pipelines={filteredPipelines}
            statusConfig={statusConfig}
            onNavigate={navigate}
          />
        )}
      </div>
    </div>
  );
}

// 统计卡片组件
interface StatCardProps {
  label: string;
  value: number;
  icon: React.ElementType;
  color: 'slate' | 'blue' | 'emerald' | 'red' | 'amber';
  isActive: boolean;
  onClick: () => void;
}

function StatCard({ label, value, icon: Icon, color, isActive, onClick }: StatCardProps) {
  const colorClasses = {
    slate: {
      bg: isActive ? 'bg-slate-900' : 'bg-white',
      border: isActive ? 'border-slate-900' : 'border-slate-200',
      text: isActive ? 'text-white' : 'text-slate-900',
      subtext: isActive ? 'text-slate-300' : 'text-slate-500',
      icon: isActive ? 'text-slate-300' : 'text-slate-400',
    },
    blue: {
      bg: isActive ? 'bg-blue-600' : 'bg-white',
      border: isActive ? 'border-blue-600' : 'border-slate-200',
      text: isActive ? 'text-white' : 'text-slate-900',
      subtext: isActive ? 'text-blue-100' : 'text-slate-500',
      icon: isActive ? 'text-blue-200' : 'text-blue-500',
    },
    emerald: {
      bg: isActive ? 'bg-emerald-600' : 'bg-white',
      border: isActive ? 'border-emerald-600' : 'border-slate-200',
      text: isActive ? 'text-white' : 'text-slate-900',
      subtext: isActive ? 'text-emerald-100' : 'text-slate-500',
      icon: isActive ? 'text-emerald-200' : 'text-emerald-500',
    },
    red: {
      bg: isActive ? 'bg-red-600' : 'bg-white',
      border: isActive ? 'border-red-600' : 'border-slate-200',
      text: isActive ? 'text-white' : 'text-slate-900',
      subtext: isActive ? 'text-red-100' : 'text-slate-500',
      icon: isActive ? 'text-red-200' : 'text-red-500',
    },
    amber: {
      bg: isActive ? 'bg-amber-500' : 'bg-white',
      border: isActive ? 'border-amber-500' : 'border-slate-200',
      text: isActive ? 'text-white' : 'text-slate-900',
      subtext: isActive ? 'text-amber-100' : 'text-slate-500',
      icon: isActive ? 'text-amber-200' : 'text-amber-500',
    },
  };

  const classes = colorClasses[color];

  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-4 p-4 rounded-xl border-2 transition-all hover:shadow-md ${classes.bg} ${classes.border}`}
    >
      <div className={`p-3 rounded-lg bg-white/10`}>
        <Icon className={`w-6 h-6 ${classes.icon}`} />
      </div>
      <div className="text-left">
        <p className={`text-2xl font-bold ${classes.text}`}>{value}</p>
        <p className={`text-sm ${classes.subtext}`}>{label}</p>
      </div>
    </button>
  );
}

// 列表视图
interface ListViewProps {
  pipelines: PipelineListItem[];
  selectedItems: Set<string>;
  onToggleSelection: (id: number) => void;
  onSelectAll: () => void;
  onSort: (field: SortField) => void;
  sortField: SortField;
  sortOrder: SortOrder;
  statusConfig: Record<string, any>;
  onNavigate: (path: string) => void;
}

function ListView({
  pipelines,
  selectedItems,
  onToggleSelection,
  onSelectAll,
  onSort,
  sortField,
  sortOrder,
  statusConfig,
  onNavigate,
}: ListViewProps) {
  const allSelected = selectedItems.size === pipelines.length && pipelines.length > 0;

  const SortHeader = ({
    field,
    children,
    className = '',
  }: {
    field: SortField;
    children: React.ReactNode;
    className?: string;
  }) => (
    <button
      onClick={() => onSort(field)}
      className={`flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700 uppercase tracking-wider ${className}`}
    >
      {children}
      {sortField === field && (
        <ChevronDown
          className={`w-3 h-3 transition-transform ${sortOrder === 'asc' ? 'rotate-180' : ''}`}
        />
      )}
    </button>
  );

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
      {/* 表头 */}
      <div className="flex items-center gap-4 px-6 py-3 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center w-8">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={onSelectAll}
            className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
        </div>
        <div className="flex-1">
          <SortHeader field="description">流水线信息</SortHeader>
        </div>
        <div className="w-28">
          <SortHeader field="status">状态</SortHeader>
        </div>
        <div className="w-32 text-xs font-medium text-slate-500 uppercase tracking-wider">当前阶段</div>
        <div className="w-36">
          <SortHeader field="created_at">创建时间</SortHeader>
        </div>
        <div className="w-28 text-xs font-medium text-slate-500 uppercase tracking-wider text-right">
          操作
        </div>
      </div>

      {/* 列表项 */}
      <div className="divide-y divide-slate-100">
        {pipelines.map((pipeline) => {
          const config = statusConfig[pipeline.status] || statusConfig.pending;
          const isSelected = selectedItems.has(String(pipeline.id));

          return (
            <div
              key={pipeline.id}
              onClick={() => onNavigate(`/console/pipelines/${pipeline.id}`)}
              className={`flex items-center gap-4 px-6 py-4 hover:bg-slate-50 transition-colors cursor-pointer group ${
                isSelected ? 'bg-blue-50/50' : ''
              }`}
            >
              <div 
                className="flex items-center w-8"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggleSelection(pipeline.id as unknown as number)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
              </div>

              {/* 流水线信息 - 加大显示区域 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center flex-shrink-0">
                    <GitBranch className="w-5 h-5 text-white" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-slate-900 text-base truncate group-hover:text-blue-600 transition-colors">
                      {pipeline.description}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-slate-400 font-mono">#{pipeline.id}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* 状态 */}
              <div className="w-28">
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium ${config.bgColor} ${config.color} border ${config.borderColor}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${config.dotColor} ${pipeline.status === 'running' ? 'animate-pulse' : ''}`} />
                  {config.label}
                </span>
              </div>

              {/* 当前阶段 */}
              <div className="w-32">
                {pipeline.current_stage ? (
                  <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-slate-100 text-slate-600 text-xs font-medium">
                    {pipeline.current_stage}
                  </span>
                ) : (
                  <span className="text-sm text-slate-400">-</span>
                )}
              </div>

              {/* 创建时间 */}
              <div className="w-36 text-sm text-slate-500">
                <div className="flex flex-col">
                  <span>{new Date(pipeline.created_at).toLocaleDateString('zh-CN')}</span>
                  <span className="text-xs text-slate-400">
                    {new Date(pipeline.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </div>

              {/* 操作 - 更大的按钮 */}
              <div className="w-28 flex items-center justify-end gap-2">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onNavigate(`/console/pipelines/${pipeline.id}`);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-all text-sm font-medium"
                >
                  查看
                  <ArrowUpRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 网格视图
interface GridViewProps {
  pipelines: PipelineListItem[];
  statusConfig: Record<string, any>;
  onNavigate: (path: string) => void;
}

function GridView({ pipelines, statusConfig, onNavigate }: GridViewProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {pipelines.map((pipeline) => {
        const config = statusConfig[pipeline.status] || statusConfig.pending;

        return (
          <div
            key={pipeline.id}
            onClick={() => onNavigate(`/console/pipelines/${pipeline.id}`)}
            className="group bg-white border border-slate-200 rounded-xl p-5 hover:shadow-lg hover:border-blue-300 transition-all cursor-pointer"
          >
            {/* 头部 */}
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
                  <GitBranch className="w-6 h-6 text-white" />
                </div>
                <div>
                  <p className="font-semibold text-slate-900 line-clamp-1">{pipeline.description}</p>
                  <p className="text-xs text-slate-500">#{pipeline.id}</p>
                </div>
              </div>
              <span
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${config.bgColor} ${config.color} border ${config.borderColor}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${config.dotColor} ${pipeline.status === 'running' ? 'animate-pulse' : ''}`} />
                {config.label}
              </span>
            </div>

            {/* 信息 */}
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">当前阶段</span>
                <span className="text-slate-700 font-medium">
                  {pipeline.current_stage || '-'}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">创建时间</span>
                <span className="text-slate-700">
                  {new Date(pipeline.created_at).toLocaleDateString('zh-CN')}
                </span>
              </div>
            </div>

            {/* 底部操作 */}
            <div className="mt-4 pt-4 border-t border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Calendar className="w-4 h-4 text-slate-400" />
                <span className="text-xs text-slate-500">
                  {new Date(pipeline.created_at).toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button className="p-2 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-all">
                  <Edit3 className="w-4 h-4" />
                </button>
                <button className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// 空状态
function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-96">
      <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center mb-6">
        <GitBranch className="w-12 h-12 text-blue-500" />
      </div>
      <h3 className="text-xl font-semibold text-slate-900 mb-2">暂无流水线</h3>
      <p className="text-slate-500 mb-6 text-center max-w-md">
        开始创建您的第一个 AI 研发流水线，让 AI 自动完成架构设计、代码生成和部署
      </p>
      <button
        onClick={onCreate}
        className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition-all shadow-lg shadow-blue-600/20"
      >
        <Plus className="w-5 h-5" />
        创建流水线
      </button>
    </div>
  );
}
