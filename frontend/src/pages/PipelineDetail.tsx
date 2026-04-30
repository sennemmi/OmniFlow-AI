import { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type NodeMouseHandler,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  ArrowLeft,
  RefreshCw,
  MoreHorizontal,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Play,
  Terminal,
  FileText,
  Palette,
  Code,
  Eye,
  GitBranch,
  Activity,
  ChevronDown,
  ChevronUp,
  Square,
} from 'lucide-react';
import { apiGet, apiPost } from '@utils/axios';
import { usePipelineStore } from '@stores/pipelineStore';
import { PipelineNode, ApproveDrawer, ThoughtLog } from '@components/Pipeline';
import { usePipelineFlow, statusConfig, STAGE_CONFIG } from '@hooks/usePipelineFlow';
import type { Pipeline, PipelineStage } from '@types';

// ============================================
// 流水线详情页 - React Flow 横向布局（集成作战室）
// ============================================

// 图标映射
const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  FileText,
  Palette,
  Code,
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  Play,
};

// 自定义节点类型 - 显式声明类型避免 TypeScript 报错
const nodeTypes: NodeTypes = {
  pipelineNode: PipelineNode as any,
};

export function PipelineDetail() {
  const { id: rawId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { openApproveDrawer, setSelectedPipeline } = usePipelineStore();
  const [showThoughtLog, setShowThoughtLog] = useState(true);
  const [isTerminating, setIsTerminating] = useState(false);

  // 验证并转换 Pipeline ID
  const pipelineId = rawId ? parseInt(rawId, 10) : NaN;
  const isValidId = !isNaN(pipelineId) && pipelineId > 0;

  // 获取流水线详情（动态轮询）
  const { data: response, isLoading, refetch } = useQuery<Pipeline>({
    queryKey: ['pipeline', pipelineId],
    queryFn: () => apiGet(`/pipeline/${pipelineId}/status`),
    enabled: isValidId,
    refetchInterval: (query) => {
      // 根据 pipeline 状态动态决定轮询间隔
      const data = query.state.data as Pipeline | undefined;
      if (data?.status === 'success' || data?.status === 'failed') {
        return false; // 停止轮询
      }
      return 2000; // 每 2 秒轮询
    },
    refetchIntervalInBackground: true,
    staleTime: 0,
    gcTime: 5 * 60 * 1000,
  });

  // 直接使用后端返回的数据
  const pipeline = response || null;

  // 终止 Pipeline
  const handleTerminate = useCallback(async () => {
    if (!pipeline || (pipeline.status !== 'running' && pipeline.status !== 'paused')) return;
    
    const confirmed = window.confirm('确定要终止当前 Pipeline 吗？此操作不可撤销。');
    if (!confirmed) return;

    setIsTerminating(true);
    try {
      await apiPost(`/pipeline/${pipelineId}/terminate`, {
        reason: '用户手动终止'
      });
      // 刷新状态
      refetch();
    } catch (error) {
      console.error('终止 Pipeline 失败:', error);
      alert('终止失败: ' + (error as Error).message);
    } finally {
      setIsTerminating(false);
    }
  }, [pipeline, pipelineId, refetch]);

  // 使用 usePipelineFlow Hook 管理流程图状态
  const {
    nodes: flowNodes,
    edges: flowEdges,
    currentStage,
    completedStages,
    progress,
    showApproveButton,
    isDone,
  } = usePipelineFlow(pipeline);

  // React Flow 状态
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // 同步 flowNodes/flowEdges 到 React Flow 状态
  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  // 更新 store 中的选中流水线
  useEffect(() => {
    if (pipeline) {
      setSelectedPipeline(pipeline);
    }
  }, [pipeline, setSelectedPipeline]);

  // 节点点击处理 - 修复抽屉唤起
  const handleNodeClick: NodeMouseHandler = useCallback(
    (event, node) => {
      if (!pipeline) return;

      const backendStage = node.data?.backendStage as any;
      const isClickable = node.data?.isClickable as boolean;

      // 修改这里：只要是 CODING 阶段且有 output_data，无论成功失败，强制允许点击查看！
      if (backendStage && backendStage.name === 'CODING' && backendStage.output_data) {
        openApproveDrawer(backendStage);
        return;
      }

      // 如果节点可点击（是当前阶段、pipeline 是 paused、有 output_data）
      if (isClickable && backendStage) {
        openApproveDrawer(backendStage);
      } else if (backendStage?.output_data) {
        // 只要有 output_data 就可以查看
        openApproveDrawer(backendStage);
      }
    },
    [pipeline, openApproveDrawer]
  );

  // 打开当前阶段的审批抽屉
  const handleOpenCurrentStageDrawer = useCallback(() => {
    if (!pipeline) return;
    
    const currentStage = pipeline.stages?.find(s => s.name === pipeline.current_stage);
    if (currentStage) {
      openApproveDrawer(currentStage);
    }
  }, [pipeline, openApproveDrawer]);

  // 状态信息
  const statusInfo = pipeline ? (statusConfig[pipeline.status] || statusConfig.running) : statusConfig.running;
  const StatusIcon = iconMap[statusInfo?.icon] || Clock;

  // 无效 ID 错误页面
  if (!isValidId) {
    return (
      <div className="h-full flex flex-col items-center justify-center">
        <AlertCircle className="w-12 h-12 text-status-error mb-4" />
        <p className="text-text-secondary">无效的流水线 ID</p>
        <button onClick={() => navigate('/console')} className="mt-4 btn-primary">
          返回控制台
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
      </div>
    );
  }

  if (!pipeline) {
    return (
      <div className="h-full flex flex-col items-center justify-center">
        <AlertCircle className="w-12 h-12 text-status-error mb-4" />
        <p className="text-text-secondary">流水线不存在或已被删除</p>
        <button onClick={() => navigate('/console')} className="mt-4 btn-primary">
          返回控制台
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 - 优化样式 */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-slate-200">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/console')}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-slate-900">Pipeline #{pipeline.id}</h1>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusInfo.bgClass || 'bg-slate-50'} ${statusInfo.class} ${statusInfo.borderClass || 'border-slate-200'}`}>
                <StatusIcon className="w-3.5 h-3.5" />
                {statusInfo.label}
              </span>
            </div>
            <ExpandableDescription description={pipeline.description} />
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* 审批按钮 - 当 paused 且可以审批时显示 - 固定宽度防止变形 */}
          {showApproveButton && (
            <button
              onClick={handleOpenCurrentStageDrawer}
              className="flex items-center justify-center gap-2 w-[140px] h-10 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm flex-shrink-0"
            >
              <Eye className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm font-medium truncate">查看并审批</span>
            </button>
          )}

          {/* 终止按钮 - 当 running 或 paused（审批中）时显示 */}
          {(pipeline?.status === 'running' || pipeline?.status === 'paused') && (
            <button
              onClick={handleTerminate}
              disabled={isTerminating}
              className="flex items-center justify-center gap-2 w-[100px] h-10 bg-red-50 text-red-600 rounded-lg hover:bg-red-100 transition-colors border border-red-200 flex-shrink-0 disabled:opacity-50"
            >
              {isTerminating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Square className="w-4 h-4 fill-current" />
              )}
              <span className="text-sm font-medium truncate">
                {isTerminating ? '终止中' : '终止'}
              </span>
            </button>
          )}

          {/* 终端开关 - 固定宽度 */}
          <button
            onClick={() => setShowThoughtLog(!showThoughtLog)}
            className={`flex items-center justify-center gap-2 w-[100px] h-10 rounded-lg transition-colors text-sm font-medium flex-shrink-0 ${
              showThoughtLog 
                ? 'text-blue-600 bg-blue-50' 
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
            }`}
            title="切换终端显示"
          >
            <Terminal className="w-4 h-4 flex-shrink-0" />
            <span className="truncate">{showThoughtLog ? '隐藏终端' : '显示终端'}</span>
          </button>

          {/* 操作按钮 - 固定正方形 */}
          <button
            onClick={() => refetch()}
            className="flex items-center justify-center w-10 h-10 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors flex-shrink-0"
            title="刷新"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            className="flex items-center justify-center w-10 h-10 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors flex-shrink-0"
            title="更多操作"
          >
            <MoreHorizontal className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* 左侧：流程图 */}
        <div className={`${showThoughtLog ? 'flex-[2]' : 'flex-1'} bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm transition-all duration-300`}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.5}
            maxZoom={1.5}
            defaultEdgeOptions={{
              type: 'smoothstep',
              style: { strokeWidth: 2 },
            }}
          >
            <Background color="#E2E8F0" gap={20} size={1} />
            <Controls className="!bg-white !border-slate-200 !shadow-md" />
            <MiniMap
              className="!bg-white !border-slate-200 !shadow-md"
              nodeColor={(node) => {
                const status = (node.data?.status as string) || 'pending';
                const colors: Record<string, string> = {
                  pending: '#94A3B8',
                  running: '#3B82F6',
                  paused: '#F59E0B',
                  completed: '#10B981',
                  success: '#10B981',
                  failed: '#EF4444',
                  approved: '#10B981',
                  rejected: '#EF4444',
                };
                return colors[status] || '#94A3B8';
              }}
              maskColor="rgba(148, 163, 184, 0.1)"
            />
          </ReactFlow>
        </div>

        {/* 右侧：Agent 终端 */}
        {showThoughtLog && (
          <div className="w-96 flex-shrink-0 min-h-0 h-full">
            <ThoughtLog
              pipelineId={String(pipelineId)}
              stageId={pipeline.current_stage || currentStage?.name || 'REQUIREMENT'}
              status={pipeline.status}
              isRunning={pipeline.status === 'running'}
            />
          </div>
        )}
      </div>

      {/* 底部信息栏 - 紧凑布局 */}
      <div className="mt-4 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
        <div className="flex items-center gap-6">
          {/* 当前阶段 */}
          <div className="flex items-center gap-3 min-w-[140px]">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
              <Play className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-slate-500">当前阶段</p>
              <p className="text-sm font-medium text-slate-900">
                {currentStage?.name ? STAGE_CONFIG[currentStage.name]?.label : '等待开始'}
              </p>
            </div>
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 进度 */}
          <div className="flex items-center gap-3 flex-1 max-w-[280px]">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
              <span className="text-xs font-bold text-blue-600">{progress}%</span>
            </div>
            <div className="flex-1">
              <p className="text-xs text-slate-500 mb-1">总体进度</p>
              <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-blue-500 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 创建时间 */}
          <div className="flex items-center gap-3 min-w-[160px]">
            <div className="w-9 h-9 rounded-lg bg-slate-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-slate-500" />
            </div>
            <div>
              <p className="text-xs text-slate-500">创建时间</p>
              <p className="text-sm font-medium text-slate-900">
                {pipeline.created_at 
                  ? new Date(pipeline.created_at).toLocaleString('zh-CN', { 
                      month: 'numeric', 
                      day: 'numeric', 
                      hour: '2-digit', 
                      minute: '2-digit' 
                    }) 
                  : '-'}
              </p>
            </div>
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 更新时间 */}
          <div className="flex items-center gap-3 min-w-[160px]">
            <div className="w-9 h-9 rounded-lg bg-slate-50 flex items-center justify-center">
              <RefreshCw className={`w-4 h-4 text-slate-500 ${pipeline.status === 'running' ? 'animate-spin' : ''}`} />
            </div>
            <div>
              <p className="text-xs text-slate-500">最后更新</p>
              <p className="text-sm font-medium text-slate-900">
                {pipeline.updated_at 
                  ? new Date(pipeline.updated_at).toLocaleString('zh-CN', { 
                      month: 'numeric', 
                      day: 'numeric', 
                      hour: '2-digit', 
                      minute: '2-digit' 
                    }) 
                  : '-'}
              </p>
            </div>
          </div>

          <div className="flex-1" />

          {/* 阶段完成数 */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-50 rounded-lg flex-shrink-0">
            <span className="text-xs text-slate-500">已完成</span>
            <span className="text-sm font-semibold text-slate-900">{completedStages}/{pipeline.stages?.length || 0}</span>
            <span className="text-xs text-slate-400">阶段</span>
          </div>
        </div>
      </div>

      {/* 阶段执行指标统计 */}
      <StageMetrics pipeline={pipeline} />

      {/* 审批抽屉 */}
      <ApproveDrawer />
    </div>
  );
}

// 可展开的描述组件
interface ExpandableDescriptionProps {
  description: string;
  maxLength?: number;
}

function ExpandableDescription({ description, maxLength = 60 }: ExpandableDescriptionProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!description) return null;

  const shouldTruncate = description.length > maxLength;
  const displayText = shouldTruncate && !isExpanded
    ? description.slice(0, maxLength) + '...'
    : description;

  return (
    <div className="flex items-start gap-1 mt-0.5">
      <p className={`text-sm text-slate-500 ${shouldTruncate ? 'cursor-pointer' : ''}`} onClick={() => shouldTruncate && setIsExpanded(!isExpanded)}>
        {displayText}
      </p>
      {shouldTruncate && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex-shrink-0 p-0.5 text-slate-400 hover:text-slate-600 transition-colors"
          title={isExpanded ? '收起' : '展开'}
        >
          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      )}
    </div>
  );
}

// 阶段执行指标组件
interface StageMetricsProps {
  pipeline: Pipeline;
}

function StageMetrics({ pipeline }: StageMetricsProps) {
  // 阶段配置
  const stageConfig: Record<string, { label: string; icon: React.ElementType; color: string; bgColor: string }> = {
    REQUIREMENT: { 
      label: '需求分析', 
      icon: FileText, 
      color: 'text-blue-600', 
      bgColor: 'bg-blue-50' 
    },
    DESIGN: { 
      label: '技术设计', 
      icon: Palette, 
      color: 'text-purple-600', 
      bgColor: 'bg-purple-50' 
    },
    CODING: { 
      label: '代码生成', 
      icon: Code, 
      color: 'text-emerald-600', 
      bgColor: 'bg-emerald-50' 
    },
    UNIT_TESTING: { 
      label: '单元测试', 
      icon: CheckCircle2, 
      color: 'text-cyan-600', 
      bgColor: 'bg-cyan-50' 
    },
    CODE_REVIEW: { 
      label: '代码审查', 
      icon: CheckCircle2, 
      color: 'text-amber-600', 
      bgColor: 'bg-amber-50' 
    },
    DELIVERY: { 
      label: '代码交付', 
      icon: GitBranch, 
      color: 'text-indigo-600', 
      bgColor: 'bg-indigo-50' 
    },
  };

  // 计算阶段统计数据
  const getStageStats = (stage: PipelineStage) => {
    // ★ 直接从 stage 对象读取 duration_ms，不再依赖 created_at/completed_at 计算
    let durationText = '-';
    let durationSeconds = 0;

    // 优先使用后端返回的 duration_ms
    if (stage.duration_ms && stage.duration_ms > 0) {
      durationSeconds = Math.floor(stage.duration_ms / 1000);
      if (durationSeconds > 3600) {
        durationText = `${Math.floor(durationSeconds / 3600)}h ${Math.floor((durationSeconds % 3600) / 60)}m`;
      } else if (durationSeconds > 60) {
        durationText = `${Math.floor(durationSeconds / 60)}m ${durationSeconds % 60}s`;
      } else {
        durationText = `${durationSeconds}s`;
      }
    } else if (stage.created_at && stage.completed_at) {
      // 兼容旧数据：使用 created_at 和 completed_at 计算
      const diffMs = new Date(stage.completed_at).getTime() - new Date(stage.created_at).getTime();
      durationSeconds = Math.floor(diffMs / 1000);
      if (durationSeconds > 3600) {
        durationText = `${Math.floor(durationSeconds / 3600)}h ${Math.floor((durationSeconds % 3600) / 60)}m`;
      } else if (durationSeconds > 60) {
        durationText = `${Math.floor(durationSeconds / 60)}m ${durationSeconds % 60}s`;
      } else {
        durationText = `${durationSeconds}s`;
      }
    } else if (stage.created_at && stage.status === 'running') {
      // 正在运行的阶段，计算从开始到现在的时间
      const diffMs = Date.now() - new Date(stage.created_at).getTime();
      durationSeconds = Math.floor(diffMs / 1000);
      if (durationSeconds > 3600) {
        durationText = `${Math.floor(durationSeconds / 3600)}h ${Math.floor((durationSeconds % 3600) / 60)}m`;
      } else if (durationSeconds > 60) {
        durationText = `${Math.floor(durationSeconds / 60)}m ${durationSeconds % 60}s`;
      } else {
        durationText = `${durationSeconds}s`;
      }
    }

    // ★ 直接从 stage 对象读取 Token 用量，不再从 output_data 中提取
    const tokens = (stage.input_tokens || 0) + (stage.output_tokens || 0);

    // 从 output_data 中估算代码行数
    let lines = 0;
    const outputData = stage.output_data as Record<string, any> | undefined;
    if (outputData?.multi_agent_output?.files) {
      const files = outputData.multi_agent_output.files as Array<{ content?: string }>;
      lines = files.reduce((acc, file) => {
        if (file.content) {
          return acc + file.content.split('\n').length;
        }
        return acc;
      }, 0);
    }

    return {
      duration: durationText,
      durationSeconds,
      tokens: tokens > 0 ? tokens : undefined,
      lines: lines || undefined,
      status: stage.status,
    };
  };

  const statusColors: Record<string, { bg: string; text: string; border: string; label: string }> = {
    success: { 
      bg: 'bg-emerald-50', 
      text: 'text-emerald-600', 
      border: 'border-emerald-200',
      label: '成功'
    },
    running: { 
      bg: 'bg-blue-50', 
      text: 'text-blue-600', 
      border: 'border-blue-200',
      label: '执行中'
    },
    failed: { 
      bg: 'bg-red-50', 
      text: 'text-red-600', 
      border: 'border-red-200',
      label: '失败'
    },
    pending: { 
      bg: 'bg-slate-50', 
      text: 'text-slate-400', 
      border: 'border-slate-200',
      label: '等待中'
    },
  };

  return (
    <div className="mt-4 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
          <Activity className="w-4 h-4 text-slate-500" />
          阶段执行指标
        </h3>
        <span className="text-xs text-slate-500">
          共 {pipeline.stages?.length || 0} 个阶段
        </span>
      </div>
      
      <div className="grid grid-cols-5 gap-3">
        {pipeline.stages?.map((stage) => {
          const config = stageConfig[stage.name] || stageConfig['REQUIREMENT'];
          const Icon = config.icon;
          const stats = getStageStats(stage);
          const statusStyle = statusColors[stage.status] || statusColors.pending;
          
          return (
            <div 
              key={stage.id} 
              className={`relative p-3 rounded-lg border transition-all ${
                stage.status === 'success' 
                  ? 'bg-slate-50 border-slate-200' 
                  : stage.status === 'running'
                  ? 'bg-blue-50/50 border-blue-200 ring-1 ring-blue-100'
                  : stage.status === 'failed'
                  ? 'bg-red-50/50 border-red-200'
                  : 'bg-slate-50/50 border-slate-200'
              }`}
            >
              {/* 阶段头部 */}
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-7 h-7 rounded-md ${config.bgColor} flex items-center justify-center`}>
                  <Icon className={`w-3.5 h-3.5 ${config.color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-700 truncate">{config.label}</p>
                </div>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${statusStyle.bg} ${statusStyle.text} ${statusStyle.border}`}>
                  {statusStyle.label}
                </span>
              </div>
              
              {/* 指标数据 */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">耗时</span>
                  <span className={`text-xs font-medium ${
                    stage.status === 'pending' ? 'text-slate-400' : 'text-slate-700'
                  }`}>
                    {stats.duration}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">Token</span>
                  <span className={`text-xs font-medium ${
                    stage.status === 'pending' ? 'text-slate-400' : 'text-slate-700'
                  }`}>
                    {stage.status === 'pending' ? '-' : (stats.tokens ? stats.tokens.toLocaleString() : '-')}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">代码</span>
                  <span className={`text-xs font-medium ${
                    stage.status === 'pending' ? 'text-slate-400' : 'text-slate-700'
                  }`}>
                    {stage.status === 'pending' ? '-' : (stats.lines ? `${stats.lines} 行` : '-')}
                  </span>
                </div>
              </div>
              
              {/* 执行中动画指示器 */}
              {stage.status === 'running' && (
                <div className="absolute top-2 right-2">
                  <span className="flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      
      {/* 汇总统计 */}
      <div className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-6">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">总耗时</span>
          <span className="text-sm font-semibold text-slate-900">
            {(() => {
              // ★ 从 stage.duration_ms 累加，不再使用 s.duration
              const totalMs = pipeline.stages?.reduce((acc, s) => acc + (s.duration_ms || 0), 0) || 0;
              const totalSeconds = Math.floor(totalMs / 1000);
              if (totalSeconds > 3600) {
                return `${Math.floor(totalSeconds / 3600)}h ${Math.floor((totalSeconds % 3600) / 60)}m`;
              } else if (totalSeconds > 60) {
                return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
              }
              return `${totalSeconds}s`;
            })()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">总 Token</span>
          <span className="text-sm font-semibold text-slate-900">
            {(pipeline.stages?.reduce((acc, s) => {
              // ★ 直接从 stage 对象累加 Token，不再从 output_data 中提取
              const tokens = (s.input_tokens || 0) + (s.output_tokens || 0);
              return acc + (s.status !== 'pending' ? tokens : 0);
            }, 0) || 0).toLocaleString()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">成功率</span>
          <span className="text-sm font-semibold text-emerald-600">
            {(() => {
              const completed = pipeline.stages?.filter(s => s.status === 'success').length || 0;
              const total = pipeline.stages?.length || 1;
              return `${Math.round((completed / total) * 100)}%`;
            })()}
          </span>
        </div>
      </div>
    </div>
  );
}
