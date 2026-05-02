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
  
  // Actions
  setSelectedPipeline: (pipeline: Pipeline | null) => void;
  setSelectedStage: (stage: PipelineStage | null) => void;
  openApproveDrawer: (stage: PipelineStage) => void;
  closeApproveDrawer: () => void;
  
  // 更新流水线状态（用于轮询更新）
  updatePipelineStatus: (pipelineId: number, updates: Partial<Pipeline>) => void;
  updateStageStatus: (pipelineId: number, stageId: number, updates: Partial<PipelineStage>) => void;
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  selectedPipeline: null,
  selectedStage: null,
  isApproveDrawerOpen: false,
  
  setSelectedPipeline: (pipeline) => set({ selectedPipeline: pipeline }),
  
  setSelectedStage: (stage) => set({ selectedStage: stage }),
  
  openApproveDrawer: (stage) => set({
    selectedStage: stage,
    isApproveDrawerOpen: true,
  }),
  
  closeApproveDrawer: () => set({
    selectedStage: null,
    isApproveDrawerOpen: false,
  }),
  
  updatePipelineStatus: (pipelineId, updates) => {
    const { selectedPipeline } = get();
    if (selectedPipeline?.id === pipelineId) {
      set({
        selectedPipeline: { ...selectedPipeline, ...updates },
      });
    }
  },
  
  updateStageStatus: (pipelineId, stageId, updates) => {
    const { selectedPipeline } = get();
    if (selectedPipeline?.id === pipelineId) {
      const updatedStages = selectedPipeline.stages.map((stage) =>
        stage.id === stageId ? { ...stage, ...updates } : stage
      );
      set({
        selectedPipeline: { ...selectedPipeline, stages: updatedStages },
      });
    }
  },
}));
