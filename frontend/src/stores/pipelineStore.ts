import { create } from 'zustand';
import type { Pipeline, PipelineStage } from '@types';

// ============================================
// Pipeline 状态管理 (Zustand)
// ============================================

interface PipelineState {
  // 当前选中的流水线
  selectedPipeline: Pipeline | null;

  // 选中的阶段（用于审批抽屉）
  selectedStage: PipelineStage | null;

  // 审批抽屉状态
  isApproveDrawerOpen: boolean;

  // 点击的节点来源（用于 CODE_REVIEW 阶段区分 CODER/TESTER）
  selectedNodeSource: 'CODER' | 'TESTER' | null;

  // Actions
  setSelectedPipeline: (pipeline: Pipeline | null) => void;
  setSelectedStage: (stage: PipelineStage | null) => void;
  openApproveDrawer: (stage: PipelineStage, nodeSource?: 'CODER' | 'TESTER') => void;
  closeApproveDrawer: () => void;

}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  selectedPipeline: null,
  selectedStage: null,
  isApproveDrawerOpen: false,
  selectedNodeSource: null,

  setSelectedPipeline: (pipeline) => set({ selectedPipeline: pipeline }),

  setSelectedStage: (stage) => set({ selectedStage: stage }),

  openApproveDrawer: (stage, nodeSource) => set({
    selectedStage: stage,
    isApproveDrawerOpen: true,
    selectedNodeSource: nodeSource || null,
  }),

  closeApproveDrawer: () => set({
    selectedStage: null,
    isApproveDrawerOpen: false,
    selectedNodeSource: null,
  }),
}));
