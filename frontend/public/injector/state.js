/**
 * OmniFlowAI 浏览器注入脚本 - 状态管理模块
 * 
 * 【简化版】只保留 Shift 多选模式
 */

(function () {
  'use strict';

  // 全局状态
  const state = {
    isActive: false,
    isSelectionMode: false,
    selectedElement: null,
    selectedElements: [],
    hoverElement: null,
    currentPipelineId: null,
    isPolling: false,
    floatingPanel: null,
    editDialog: null,
  };

  // 状态操作方法
  const StateManager = {
    getState() {
      return state;
    },

    resetSelectionState() {
      state.selectedElement = null;
      state.selectedElements = [];
      state.hoverElement = null;
    },

    clearFloatingPanel() {
      if (state.floatingPanel) {
        state.floatingPanel.remove();
        state.floatingPanel = null;
      }
    },

    closeEditDialog() {
      if (state.editDialog) {
        state.editDialog.remove();
        state.editDialog = null;
      }
    },
  };

  window.OmniFlowAIState = {
    state,
    StateManager,
  };

})();
