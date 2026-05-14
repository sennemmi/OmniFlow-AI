import { useCallback, useMemo, useState, useEffect } from 'react';
import { Position, type Node, type Edge } from '@xyflow/react';
import type { Pipeline, PipelineStage } from '@types';

// ============================================
// Pipeline Flow 状态管理和节点/边构建 Hook
// 【修复】统一前后端状态枚举，移除 success -> completed 的映射
// ============================================

import type { LucideIcon } from 'lucide-react';

// 状态显示配置类型
export interface StatusDisplayConfig {
  icon: LucideIcon | string;
  label: string;
  color: string;
  bg: string;
  dot: string;
}

// 状态配置 - 与后端 PipelineStatus 枚举保持一致
// 后端 PipelineStatus: running, paused, success, failed
// 后端 StageStatus: pending, running, success, failed
export const statusConfig: Record<string, {
  icon: string;
  class: string;
  label: string;
  bgClass?: string;
  borderClass?: string;
}> = {
  running: { 
    icon: 'Loader2', 
    class: 'text-blue-600', 
    label: '执行中',
    bgClass: 'bg-blue-50',
    borderClass: 'border-blue-200'
  },
  paused: { 
    icon: 'Clock', 
    class: 'text-amber-600', 
    label: '等待审批',
    bgClass: 'bg-amber-50',
    borderClass: 'border-amber-200'
  },
  success: { 
    icon: 'CheckCircle2', 
    class: 'text-emerald-600', 
    label: '成功',
    bgClass: 'bg-emerald-50',
    borderClass: 'border-emerald-200'
  },
  failed: { 
    icon: 'AlertCircle', 
    class: 'text-red-600', 
    label: '失败',
    bgClass: 'bg-red-50',
    borderClass: 'border-red-200'
  },
  // 【移除】completed 状态，直接使用 success
};

// 阶段配置 - 更新拓扑结构
export const STAGE_CONFIG: Record<string, { label: string; icon: string; description: string }> = {
  REQUIREMENT: { label: '需求分析', icon: 'FileText', description: 'AI 架构师分析需求' },
  DESIGN: { label: '技术设计', icon: 'Palette', description: 'AI 设计师制定方案' },
  CODER: { label: '自动编码', icon: 'Code', description: 'AI 程序员编写代码' },
  TESTER: { label: '分层测试', icon: 'CheckCircle2', description: 'AI 测试员执行分层测试' },
  DELIVERY: { label: '代码交付', icon: 'GitBranch', description: 'Git Commit & PR' },
};

// 新的拓扑顺序：REQUIREMENT -> DESIGN -> [CODER, TESTER] -> DELIVERY
export const STAGE_ORDER = ['REQUIREMENT', 'DESIGN', 'CODER', 'TESTER', 'DELIVERY'];

// 阶段映射：后端阶段名 -> 前端显示名
export const stageMapping: Record<string, string> = {
  'REQUIREMENT': 'REQUIREMENT',
  'DESIGN': 'DESIGN',
  'CODING': 'CODER',
  'UNIT_TESTING': 'TESTER',  // 新增：分层测试阶段映射到 TESTER 节点
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

// 【修复】简化阶段状态获取 - 直接使用后端返回的 stage 状态
export function getStageStatus(
  stageName: string, // 前端节点名称 (REQUIREMENT, DESIGN, CODER, TESTER, DELIVERY)
  backendStages: PipelineStage[],
  currentStage: string | null,
  pipelineStatus: string
): string {
  // 建立后端阶段名到前端节点名的映射
  const backendToFrontendMap: Record<string, string> = {
    'REQUIREMENT': 'REQUIREMENT',
    'DESIGN': 'DESIGN',
    'CODING': 'CODER',
    'UNIT_TESTING': 'TESTER',
    'CODE_REVIEW': 'CODER',
    'DELIVERY': 'DELIVERY'
  };

  // 找到此前端节点对应的后端 Stage 记录
  const backendStage = backendStages.slice().reverse().find(
    s => backendToFrontendMap[s.name] === stageName
  );

  // 如果后端有记录，直接返回其状态
  if (backendStage) {
    return backendStage.status;
  }

  // 没有记录时，根据当前阶段推断
  const mappedCurrentStage = currentStage ? backendToFrontendMap[currentStage] : null;
  const currentIndex = STAGE_ORDER.indexOf(mappedCurrentStage || '');
  const thisIndex = STAGE_ORDER.indexOf(stageName);

  if (currentIndex === -1) return 'pending';
  if (thisIndex < currentIndex) return 'success';
  return 'pending';
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
  const horizontalGap = 60;
  const verticalGap = 100;

  const layouts = getLayouts(nodeWidth, horizontalGap, verticalGap);

  STAGE_ORDER.forEach((stageName) => {
    const pos = layouts[stageName as keyof typeof layouts];
    const config = STAGE_CONFIG[stageName];
    const status = getStageStatus(stageName, backendStages, currentStage, pipelineStatus);

    // 查找后端对应的 stage 数据 - 区分 CODING 和 CODE_REVIEW
    let backendStage: PipelineStage | undefined;
    if (stageName === 'CODER') {
      // CODER 节点：优先显示 CODING 阶段数据，如果没有则显示 CODE_REVIEW
      backendStage = backendStages.slice().reverse().find(s => s.name === 'CODING') 
                  || backendStages.slice().reverse().find(s => s.name === 'CODE_REVIEW');
    } else if (stageName === 'TESTER') {
      // TESTER 节点：只显示 UNIT_TESTING 阶段数据
      backendStage = backendStages.slice().reverse().find(s => s.name === 'UNIT_TESTING');
    } else {
      backendStage = backendStages.slice().reverse().find(s => stageMapping[s.name] === stageName);
    }

    // 判断是否是当前阶段
    const isCurrentStage = stageMapping[currentStage || ''] === stageName;

    // 【新流程】CODING 阶段需要审批，TESTER 只展示测试结果，不审批
    const isCodingStage = currentStage === 'CODING';
    const isCodeReviewStage = currentStage === 'CODE_REVIEW';
    const isCoder = stageName === 'CODER';
    const isTester = stageName === 'TESTER';
    // CODER 节点在 CODING 或 CODE_REVIEW 阶段都显示为可审批
    const isPendingApproval = (isCodingStage && isCoder) || (isCodeReviewStage && isCoder);

    // 节点样式 - 根据状态设置
    let nodeClassName = '';
    if ((isCurrentStage && pipelineStatus === 'paused') || isPendingApproval) {
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

    // 修复：只要有 output_data 就可以点击查看（包括 CODING 自动编码阶段）
    const hasOutputData = !!backendStage?.output_data;
    // 【修改】TESTER 节点在测试失败且需要用户决策时也显示待审批提示
    const testingResult = backendStage?.output_data?.testing_result;
    const requiresUserDecision = testingResult?.requires_user_decision || testingResult?.warning;
    const isPending = (isCurrentStage && pipelineStatus === 'paused' && !isTester) || isPendingApproval ||
                      (isTester && requiresUserDecision); // TESTER 节点需要用户决策时也显示待审批

    // 【新增】为 TESTER 节点构建详细的测试状态描述
    let nodeDescription = backendStage?.description || config.description;
    if (stageName === 'TESTER' && backendStage?.output_data) {
      const testingResult = backendStage.output_data.testing_result || {};
      const testRunSuccess = backendStage.output_data.test_run_success;
      const contractCheck = backendStage.output_data.contract_check;
      const layers = backendStage.output_data.layers || [];

      // 构建测试状态描述
      const parts: string[] = [];

      // 契约检查状态
      if (contractCheck) {
        parts.push(contractCheck.passed ? '✓ 契约检查通过' : '✗ 契约检查失败');
      }

      // 分层测试状态
      if (layers.length > 0) {
        const passedLayers = layers.filter((l: any) => l.passed).length;
        parts.push(`${passedLayers}/${layers.length} 层测试通过`);
      }

      // 修复状态
      if (testRunSuccess === false) {
        parts.push('修复失败');
      } else if (testRunSuccess === true && layers.some((l: any) => !l.passed)) {
        parts.push('✓ 修复成功');
      }

      if (parts.length > 0) {
        nodeDescription = parts.join(' | ');
      }
    }

    nodes.push({
      id: stageName,
      type: 'pipelineNode',
      position: pos,
      data: {
        label: config.label,
        icon: config.icon,
        status: status,
        description: nodeDescription,
        stageId: stageName,
        isClickable: isPending || hasOutputData, // 修复：待审批或有数据都可点击
        backendStage: backendStage,
        isPendingApproval: isPending,
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
    const targetStatus = getStageStatus(target, backendStages, currentStage, pipelineStatus);

    // 【修复】边的流动状态判断：
    // 1. 源阶段正在执行
    // 2. 源阶段是当前正在执行的阶段的输入阶段（即数据流向当前阶段）
    // 3. 目标阶段正在执行（表示数据正在流入该阶段）
    const mappedCurrentStage = currentStage ? stageMapping[currentStage] : null;
    const isSourceRunning = sourceStatus === 'running';
    const isTargetRunning = targetStatus === 'running';
    const isCurrentStageInput = mappedCurrentStage === target && pipelineStatus === 'running';
    const isRunning = isSourceRunning || isTargetRunning || isCurrentStageInput;

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

  // 计算进度 - 使用固定总阶段数（STAGE_ORDER 长度）
  const { completedStages, progress } = useMemo(() => {
    // 固定总阶段数为 5 (即 STAGE_ORDER 的长度)
    const total = STAGE_ORDER.length;

    if (!pipeline || !pipeline.stages) {
      return { totalStages: total, completedStages: 0, progress: 0 };
    }

    // 计算已经真正完成（Success）的【唯一】阶段数量
    // 使用 Set 是为了防止同一个阶段因为驳回重跑产生多条成功记录导致进度超过 100%
    const finishedStageNames = new Set(
      pipeline.stages
        .filter(
          // 【修复】直接使用 success 状态
          s => s.status === 'success'
        )
        .map(s => {
          // 将后端阶段名映射到前端节点名，统一统计
          if (s.name === 'CODING' || s.name === 'CODE_REVIEW') return 'CODER';
          if (s.name === 'UNIT_TESTING') return 'TESTER';
          return s.name;
        })
    );

    const completed = finishedStageNames.size;

    // 计算百分比，最高 100%
    const percent = Math.min(Math.round((completed / total) * 100), 100);

    return {
      totalStages: total,
      completedStages: completed,
      progress: percent
    };
  }, [pipeline]);

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
