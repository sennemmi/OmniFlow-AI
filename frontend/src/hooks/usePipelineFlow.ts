import { useCallback, useMemo, useState, useEffect } from 'react';
import { Position, type Node, type Edge } from '@xyflow/react';
import type { Pipeline, PipelineStage } from '@types';

// ============================================
// Pipeline Flow 状态管理和节点/边构建 Hook
// ============================================

// 状态配置 - 与后端 PipelineStatus 枚举保持一致
export const statusConfig: Record<string, { icon: string; class: string; label: string }> = {
  running: { icon: 'Loader2', class: 'text-brand-primary animate-spin', label: '执行中' },
  paused: { icon: 'Clock', class: 'text-brand-primary', label: '等待审批' },
  success: { icon: 'CheckCircle2', class: 'text-status-success', label: '成功' },
  failed: { icon: 'AlertCircle', class: 'text-status-error', label: '失败' },
};

// 阶段配置 - 更新拓扑结构
export const STAGE_CONFIG: Record<string, { label: string; icon: string; description: string }> = {
  REQUIREMENT: { label: '需求分析', icon: 'FileText', description: 'AI 架构师分析需求' },
  DESIGN: { label: '技术设计', icon: 'Palette', description: 'AI 设计师制定方案' },
  CODER: { label: '自动编码', icon: 'Code', description: 'AI 程序员编写代码' },
  TESTER: { label: '单元测试', icon: 'CheckCircle2', description: 'AI 测试员生成测试' },
  DELIVERY: { label: '代码交付', icon: 'GitBranch', description: 'Git Commit & PR' },
};

// 新的拓扑顺序：REQUIREMENT -> DESIGN -> [CODER, TESTER] -> DELIVERY
export const STAGE_ORDER = ['REQUIREMENT', 'DESIGN', 'CODER', 'TESTER', 'DELIVERY'];

// 阶段映射：后端阶段名 -> 前端显示名
export const stageMapping: Record<string, string> = {
  'REQUIREMENT': 'REQUIREMENT',
  'DESIGN': 'DESIGN',
  'CODING': 'CODER',
  'CODE_REVIEW': 'CODER',
  'DELIVERY': 'DELIVERY',
};

// 布局配置：REQUIREMENT -> DESIGN -> [CODER, TESTER] -> DELIVERY
export const getLayouts = (nodeWidth: number, horizontalGap: number, verticalGap: number) => ({
  REQUIREMENT: { x: 0, y: 0 },
  DESIGN: { x: nodeWidth + horizontalGap, y: 0 },
  CODER: { x: (nodeWidth + horizontalGap) * 2, y: -verticalGap / 2 },
  TESTER: { x: (nodeWidth + horizontalGap) * 2, y: verticalGap / 2 },
  DELIVERY: { x: (nodeWidth + horizontalGap) * 3, y: 0 },
});

// 获取阶段状态 - 修复状态映射
export function getStageStatus(
  stageName: string,
  backendStages: PipelineStage[],
  currentStage: string | null,
  pipelineStatus: string
): string {
  // 优先以后端实际 stage 记录为准
  const backendStage = backendStages.find(s => s.name === stageName);
  
  if (backendStage) {
    // 当前阶段 + pipeline paused = 等待审批
    if (stageName === currentStage && pipelineStatus === 'paused') {
      return 'paused';
    }
    // 当前阶段 + pipeline running = 运行中
    if (stageName === currentStage && pipelineStatus === 'running') {
      return 'running';
    }
    return backendStage.status;
  }
  
  // 后端无记录时根据 current_stage 推断
  const currentIndex = STAGE_ORDER.indexOf(currentStage || '');
  const thisIndex = STAGE_ORDER.indexOf(stageName);
  
  if (currentIndex === -1) return 'pending';
  
  if (thisIndex < currentIndex) return 'success';       // 已完成的阶段
  if (thisIndex === currentIndex) {                     // 当前阶段
    if (pipelineStatus === 'paused') return 'paused';
    if (pipelineStatus === 'running') return 'running';
    return 'running';
  }
  return 'pending';                                     // 未来阶段
}

// 构建 React Flow 节点和边 - 支持分叉拓扑结构
export function buildFlowElements(
  backendStages: PipelineStage[],
  currentStage: string | null,
  pipelineStatus: string,
  animationState: 'normal' | 'fast' | 'rollback'
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const nodeWidth = 180;
  const nodeHeight = 80;
  const horizontalGap = 60;
  const verticalGap = 100;

  const layouts = getLayouts(nodeWidth, horizontalGap, verticalGap);

  STAGE_ORDER.forEach((stageName) => {
    const pos = layouts[stageName as keyof typeof layouts];
    const config = STAGE_CONFIG[stageName];
    const status = getStageStatus(stageName, backendStages, currentStage, pipelineStatus);

    // 查找后端对应的 stage 数据
    const backendStage = backendStages.find(s => stageMapping[s.name] === stageName);

    // 判断是否是当前阶段
    const isCurrentStage = stageMapping[currentStage || ''] === stageName;

    // 节点样式 - 根据状态设置
    let nodeClassName = '';
    if (isCurrentStage && pipelineStatus === 'paused') {
      // 等待审批：静态橙色高亮边框 + 待审批标签
      nodeClassName = 'ring-2 ring-status-warning ring-offset-2';
    } else if (isCurrentStage && pipelineStatus === 'running') {
      // 执行中：蓝色呼吸灯
      nodeClassName = 'ring-2 ring-brand-primary ring-offset-2 animate-pulse';
    } else if (status === 'pending') {
      // 未执行：降低透明度
      nodeClassName = 'opacity-50';
    } else if (animationState === 'rollback' && status === 'rejected') {
      nodeClassName = 'animate-pulse';
    }

    nodes.push({
      id: stageName,
      type: 'pipelineNode',
      position: pos,
      data: {
        label: config.label,
        icon: config.icon,
        status: status,
        description: backendStage?.description || config.description,
        stageId: stageName,
        isClickable: isCurrentStage && pipelineStatus === 'paused',
        backendStage: backendStage,
        isPendingApproval: isCurrentStage && pipelineStatus === 'paused',
      },
      sourcePosition: stageName === 'DESIGN' ? Position.Right : Position.Right,
      targetPosition: stageName === 'DELIVERY' ? Position.Left : Position.Left,
      className: nodeClassName,
    });
  });

  // 创建边 - 分叉拓扑
  const edgeConfigs = [
    { source: 'REQUIREMENT', target: 'DESIGN' },
    { source: 'DESIGN', target: 'CODER' },
    { source: 'DESIGN', target: 'TESTER' },
    { source: 'CODER', target: 'DELIVERY' },
    { source: 'TESTER', target: 'DELIVERY' },
  ];

  edgeConfigs.forEach(({ source, target }) => {
    const sourceStatus = getStageStatus(source, backendStages, currentStage, pipelineStatus);
    const isRunning = sourceStatus === 'running' || 
      (stageMapping[currentStage || ''] === source && pipelineStatus === 'running');

    const edgeClass = animationState === 'fast'
      ? 'fast-flow'
      : animationState === 'rollback'
      ? 'rollback-flow'
      : isRunning ? 'running' : '';

    edges.push({
      id: `edge-${source}-${target}`,
      source,
      target,
      type: 'smoothstep',
      animated: isRunning || animationState !== 'normal',
      className: edgeClass,
      style: {
        stroke: animationState === 'rollback'
          ? '#F53F3F'
          : isRunning || animationState === 'fast'
          ? '#3370FF'
          : '#DEE0E3',
        strokeWidth: isRunning ? 3 : 2,
      },
    });
  });

  return { nodes, edges };
}

// Hook 返回类型
export interface UsePipelineFlowReturn {
  nodes: Node[];
  edges: Edge[];
  animationState: 'normal' | 'fast' | 'rollback';
  setAnimationState: (state: 'normal' | 'fast' | 'rollback') => void;
  handleApproveAnimation: () => void;
  handleRejectAnimation: () => void;
  currentStage: PipelineStage | undefined;
  completedStages: number;
  progress: number;
  showApproveButton: boolean;
  isDone: boolean;
}

export function usePipelineFlow(pipeline: Pipeline | null): UsePipelineFlowReturn {
  const [animationState, setAnimationState] = useState<'normal' | 'fast' | 'rollback'>('normal');

  // 构建流程图节点和边
  const { nodes, edges } = useMemo(() => {
    if (!pipeline) {
      return { nodes: [], edges: [] };
    }
    return buildFlowElements(
      pipeline.stages,
      pipeline.current_stage,
      pipeline.status,
      animationState
    );
  }, [pipeline, animationState]);

  // 获取当前阶段
  const currentStage = useMemo(() => {
    if (!pipeline) return undefined;
    return pipeline.stages?.find(s => s.name === pipeline.current_stage)
      ?? pipeline.stages?.find(s => s.status === 'running')
      ?? pipeline.stages?.[0];
  }, [pipeline]);

  // 计算进度
  const totalStages = 3;
  const completedStages = useMemo(() => {
    return pipeline?.stages?.filter(s => s.status === 'success').length || 0;
  }, [pipeline]);
  const progress = useMemo(() => {
    return Math.round((completedStages / totalStages) * 100);
  }, [completedStages]);

  // 是否显示审批按钮
  const showApproveButton = useMemo(() => {
    return pipeline?.status === 'paused';
  }, [pipeline]);

  // 判断是否已完成
  const isDone = useMemo(() => {
    return pipeline?.status === 'success' || pipeline?.status === 'failed';
  }, [pipeline]);

  // 监听批准事件 - 流光加速动画
  useEffect(() => {
    const handleApprove = () => {
      setAnimationState('fast');
      setTimeout(() => setAnimationState('normal'), 3000);
    };
    document.addEventListener('pipeline:approve', handleApprove);
    return () => document.removeEventListener('pipeline:approve', handleApprove);
  }, []);

  // 监听拒绝事件 - 回退动画
  useEffect(() => {
    const handleReject = () => {
      setAnimationState('rollback');
      setTimeout(() => setAnimationState('normal'), 3000);
    };
    document.addEventListener('pipeline:reject', handleReject);
    return () => document.removeEventListener('pipeline:reject', handleReject);
  }, []);

  // 手动触发批准动画
  const handleApproveAnimation = useCallback(() => {
    setAnimationState('fast');
    setTimeout(() => setAnimationState('normal'), 3000);
  }, []);

  // 手动触发拒绝动画
  const handleRejectAnimation = useCallback(() => {
    setAnimationState('rollback');
    setTimeout(() => setAnimationState('normal'), 3000);
  }, []);

  return {
    nodes,
    edges,
    animationState,
    setAnimationState,
    handleApproveAnimation,
    handleRejectAnimation,
    currentStage,
    completedStages,
    progress,
    showApproveButton,
    isDone,
  };
}
