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
} from 'lucide-react';
import { apiGet } from '@utils/axios';
import { usePipelineStore } from '@stores/pipelineStore';
import { PipelineNode, ApproveDrawer, ThoughtLog } from '@components/Pipeline';
import { usePipelineFlow, statusConfig, STAGE_CONFIG } from '@hooks/usePipelineFlow';
import type { Pipeline } from '@types';

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

// 自定义节点类型
const nodeTypes = {
  pipelineNode: PipelineNode,
};

export function PipelineDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { openApproveDrawer, setSelectedPipeline } = usePipelineStore();
  const [showThoughtLog, setShowThoughtLog] = useState(true);

  // 获取流水线详情（动态轮询）
  const { data: response, isLoading, refetch } = useQuery<Pipeline>({
    queryKey: ['pipeline', id],
    queryFn: () => apiGet(`/pipeline/${id}/status`),
    enabled: !!id,
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
      {/* 头部 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/console')}
            className="p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="text-xl font-bold text-text-primary">Pipeline #{pipeline.id}</h1>
            <p className="text-sm text-text-secondary">{pipeline.description}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* 状态 */}
          <div className="flex items-center gap-2 px-4 py-2 bg-bg-primary rounded-xl border border-border-default">
            <StatusIcon className={`w-4 h-4 ${statusInfo.class}`} />
            <span className="text-sm font-medium text-text-primary">{statusInfo.label}</span>
          </div>

          {/* 审批按钮 - 当 paused 且可以审批时显示 */}
          {showApproveButton && (
            <button
              onClick={handleOpenCurrentStageDrawer}
              className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-xl hover:bg-brand-primary-hover transition-colors animate-pulse"
            >
              <Eye className="w-4 h-4" />
              <span className="text-sm font-medium">查看方案并审批</span>
            </button>
          )}

          {/* 终端开关 */}
          <button
            onClick={() => setShowThoughtLog(!showThoughtLog)}
            className={`p-2 rounded-md transition-colors ${
              showThoughtLog 
                ? 'text-brand-primary bg-brand-primary-light' 
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary'
            }`}
            title="切换终端显示"
          >
            <Terminal className="w-5 h-5" />
          </button>

          {/* 操作按钮 */}
          <button
            onClick={() => refetch()}
            className="p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
            title="刷新"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            className="p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
            title="更多操作"
          >
            <MoreHorizontal className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex gap-6 min-h-0">
        {/* 左侧：流程图 */}
        <div className="flex-1 bg-bg-primary rounded-xl border border-border-default overflow-hidden">
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
            <Background color="#DEE0E3" gap={20} size={1} />
            <Controls className="!bg-bg-primary !border-border-default !shadow-feishu-card" />
            <MiniMap
              className="!bg-bg-primary !border-border-default !shadow-feishu-card"
              nodeColor={(node) => {
                const status = (node.data?.status as string) || 'pending';
                const colors: Record<string, string> = {
                  pending: '#8F959E',
                  running: '#3370FF',
                  paused: '#FF7D00',
                  completed: '#00B42A',
                  success: '#00B42A',
                  failed: '#F53F3F',
                  approved: '#00B42A',
                  rejected: '#F53F3F',
                };
                return colors[status] || '#8F959E';
              }}
              maskColor="rgba(31, 35, 41, 0.1)"
            />
          </ReactFlow>
        </div>

        {/* 右侧：Agent 终端 */}
        {showThoughtLog && (
          <div className="w-80 flex-shrink-0">
            <ThoughtLog
              pipelineId={String(pipeline.id)}
              stageId={pipeline.current_stage || currentStage?.name || 'REQUIREMENT'}
              status={pipeline.status}
              isRunning={pipeline.status === 'running'}
            />
          </div>
        )}
      </div>

      {/* 底部信息栏 */}
      <div className="mt-6 grid md:grid-cols-4 gap-4">
        {/* 当前阶段 */}
        <div className="card-flat p-4">
          <p className="text-xs text-text-tertiary uppercase tracking-wider mb-2">当前阶段</p>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-primary-light flex items-center justify-center">
              <Play className="w-5 h-5 text-brand-primary" />
            </div>
            <div>
              <p className="font-medium text-text-primary">
                {currentStage?.name ? STAGE_CONFIG[currentStage.name]?.label : '等待开始'}
              </p>
              <p className="text-xs text-text-tertiary">
                {completedStages} / 3 阶段完成
              </p>
            </div>
          </div>
        </div>

        {/* 进度 */}
        <div className="card-flat p-4">
          <p className="text-xs text-text-tertiary uppercase tracking-wider mb-2">总体进度</p>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-primary-light flex items-center justify-center">
              <span className="text-sm font-bold text-brand-primary">{progress}%</span>
            </div>
            <div className="flex-1">
              <div className="h-2 bg-bg-tertiary rounded-full overflow-hidden">
                <div 
                  className="h-full bg-brand-primary rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-xs text-text-tertiary mt-1">
                {completedStages} 个阶段已完成
              </p>
            </div>
          </div>
        </div>

        {/* 创建时间 */}
        <div className="card-flat p-4">
          <p className="text-xs text-text-tertiary uppercase tracking-wider mb-2">创建时间</p>
          <p className="font-medium text-text-primary">
            {pipeline.created_at ? new Date(pipeline.created_at).toLocaleString('zh-CN') : '-'}
          </p>
          <p className="text-xs text-text-tertiary mt-1">
            由 system 创建
          </p>
        </div>

        {/* 更新时间 */}
        <div className="card-flat p-4">
          <p className="text-xs text-text-tertiary uppercase tracking-wider mb-2">最后更新</p>
          <p className="font-medium text-text-primary">
            {pipeline.updated_at ? new Date(pipeline.updated_at).toLocaleString('zh-CN') : '-'}
          </p>
          <p className="text-xs text-text-tertiary mt-1">
            {pipeline.status === 'running' ? '正在执行中...' : '已同步'}
          </p>
        </div>
      </div>

      {/* 审批抽屉 */}
      <ApproveDrawer />
    </div>
  );
}
