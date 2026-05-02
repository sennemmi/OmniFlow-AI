/**
 * OmniFlowAI 浏览器注入脚本 - 事件处理器模块
 * 
 * 【简化版】只保留 Shift 多选模式，移除画圈圈选
 * - 单击 = 选中单个元素
 * - Shift + 点击 = 多选/取消多选
 * - 半透明蒙层 + 镂空高亮
 */

(function () {
  'use strict';

  const { DOM, Utils } = window.OmniFlowAICore;
  const { UI } = window.OmniFlowAIUI;
  const { state } = window.OmniFlowAIState;
  const { VisualFeedback, PanelManager } = window.OmniFlowAISelection;

  // 外部传入的回调
  let callbacks = {
    onExitSelectionMode: null,
    onHandleModify: null,
    onHandleAreaModify: null,
  };

  function setCallbacks(cbs) {
    callbacks = { ...callbacks, ...cbs };
  }

  // ============================================
  // 核心选择逻辑
  // ============================================

  /**
   * 禁用页面原有的选择功能
   */
  function disableNativeSelection() {
    // 禁用文本选择
    document.body.style.userSelect = 'none';
    document.body.style.webkitUserSelect = 'none';
    document.body.style.mozUserSelect = 'none';
    document.body.style.msUserSelect = 'none';

    // 禁用拖拽
    document.body.style.pointerEvents = 'auto';

    // 为所有可能的选择元素添加禁用标记
    const selectableElements = document.querySelectorAll('[data-selectable], [data-multi-select], .selectable, [role="checkbox"], input[type="checkbox"]');
    selectableElements.forEach(el => {
      el.dataset.omniNativeDisabled = 'true';
      el.style.pointerEvents = 'none';
    });
  }

  /**
   * 恢复页面原有的选择功能
   */
  function enableNativeSelection() {
    // 恢复文本选择
    document.body.style.userSelect = '';
    document.body.style.webkitUserSelect = '';
    document.body.style.mozUserSelect = '';
    document.body.style.msUserSelect = '';

    // 恢复被禁用的元素
    const disabledElements = document.querySelectorAll('[data-omni-native-disabled]');
    disabledElements.forEach(el => {
      el.style.pointerEvents = '';
      delete el.dataset.omniNativeDisabled;
    });
  }

  /**
   * 点击拦截 - 在 capture 阶段阻止原始业务逻辑
   */
  function handleInspectClick(e) {
    if (!state.isSelectionMode) return;
    if (state.editDialog) return;

    const el = e.target;
    if (Utils.isOmniElement(el)) return;

    // 阻止原始点击事件（包括页面原有的批量选择）
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    // Shift 多选逻辑
    if (e.shiftKey) {
      toggleElementSelection(el);
    } else {
      selectSingleElement(el);
    }
  }

  /**
   * 选中单个元素
   */
  function selectSingleElement(el) {
    // 如果点击的是已选中元素，则取消选中
    if (state.selectedElement === el && state.selectedElements.length === 0) {
      deselectAll();
      UI.createToast('已取消选中');
      return;
    }

    // 清除之前的选择
    deselectAll();

    // 设置新选择
    state.selectedElement = el;
    VisualFeedback.highlightElement(el);
    
    // 显示编辑弹窗
    const elementInfo = DOM.getElementInfo(el);
    PanelManager.showEditDialog(
      elementInfo,
      false,
      [],
      // 取消
      () => deselectAll(),
      // 提交
      (feedback) => {
        if (callbacks.onHandleModify) {
          callbacks.onHandleModify(elementInfo, feedback);
        }
      }
    );
  }

  /**
   * Shift 多选 - 切换元素选择状态
   */
  function toggleElementSelection(el) {
    // 如果当前有单选，先转为多选模式
    if (state.selectedElement) {
      const singleEl = state.selectedElement;
      deselectAll();
      state.selectedElements = [singleEl];
      VisualFeedback.updateMultiSelection(state.selectedElements);
    }

    const index = state.selectedElements.indexOf(el);
    
    if (index > -1) {
      // 已选中，移除
      state.selectedElements.splice(index, 1);
      UI.createToast(`已移除，当前选中 ${state.selectedElements.length} 个元素`);
    } else {
      // 未选中，添加
      state.selectedElements.push(el);
      UI.createToast(`已添加，当前选中 ${state.selectedElements.length} 个元素`);
    }

    // 更新视觉反馈
    VisualFeedback.updateMultiSelection(state.selectedElements);

    // 如果有多选元素，显示批量操作面板
    if (state.selectedElements.length > 0) {
      showMultiSelectionPanel();
    } else {
      VisualFeedback.clearFloatingPanel();
    }
  }

  /**
   * 显示多选操作面板
   */
  function showMultiSelectionPanel() {
    const rect = VisualFeedback.getMultiSelectionRect(state.selectedElements);
    
    PanelManager.showAreaSelectionPanel(
      state.selectedElements,
      rect,
      // 取消
      () => {
        deselectAll();
        UI.createToast('已取消选择');
      },
      // 提交
      () => {
        const elementInfo = DOM.getElementInfo(state.selectedElements[0]);
        PanelManager.showEditDialog(
          elementInfo,
          true,
          state.selectedElements,
          // 取消
          () => deselectAll(),
          // 提交
          (feedback) => {
            if (callbacks.onHandleAreaModify) {
              callbacks.onHandleAreaModify(state.selectedElements, feedback);
            }
          }
        );
        VisualFeedback.clearFloatingPanel();
      }
    );
  }

  /**
   * 取消所有选择
   */
  function deselectAll() {
    state.selectedElement = null;
    state.selectedElements = [];
    VisualFeedback.clearHighlight();
    VisualFeedback.clearMultiHighlight();
    VisualFeedback.clearFloatingPanel();
    VisualFeedback.closeEditDialog();
  }

  // ============================================
  // 鼠标事件处理器
  // ============================================

  function handleMouseOver(e) {
    if (!state.isSelectionMode) return;
    if (state.editDialog) return;
    if (state.selectedElement) return;

    const el = e.target;
    if (Utils.isOmniElement(el)) return;

    state.hoverElement = el;
    VisualFeedback.highlightElement(el);
  }

  function handleMouseOut(e) {
    if (!state.isSelectionMode) return;
    if (state.editDialog) return;
    if (state.selectedElement) return;

    VisualFeedback.clearHighlight();
    state.hoverElement = null;
  }

  /**
   * 阻止拖拽选择
   */
  function handleMouseDown(e) {
    if (!state.isSelectionMode) return;

    const el = e.target;
    if (Utils.isOmniElement(el)) return;

    // 阻止拖拽选择
    e.preventDefault();
    e.stopPropagation();
  }

  /**
   * 阻止文本选择
   */
  function handleSelectStart(e) {
    if (!state.isSelectionMode) return;

    const el = e.target;
    if (Utils.isOmniElement(el)) return;

    e.preventDefault();
  }

  // ============================================
  // 键盘事件处理器
  // ============================================
  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      if (state.editDialog) {
        deselectAll();
      } else if (state.selectedElements.length > 0 || state.selectedElement) {
        deselectAll();
        UI.createToast('已取消选择');
      } else {
        if (callbacks.onExitSelectionMode) {
          callbacks.onExitSelectionMode();
        }
        UI.createToast('已退出圈选模式');
      }
    }
  }

  // ============================================
  // 右键菜单处理器
  // ============================================
  function handleContextMenu(e) {
    if (!state.isSelectionMode) return;

    e.preventDefault();

    if (state.editDialog || state.selectedElement || state.selectedElements.length > 0) {
      deselectAll();
      UI.createToast('已取消选择');
    } else {
      if (callbacks.onExitSelectionMode) {
        callbacks.onExitSelectionMode();
      }
      UI.createToast('已退出圈选模式');
    }
  }

  // ============================================
  // 事件绑定/解绑
  // ============================================
  function bindEvents() {
    // 禁用页面原有的选择功能
    disableNativeSelection();

    // 点击拦截（capture 阶段）
    document.addEventListener('click', handleInspectClick, true);

    // 阻止拖拽选择
    document.addEventListener('mousedown', handleMouseDown, true);

    // 阻止文本选择
    document.addEventListener('selectstart', handleSelectStart, true);

    // 悬停效果
    document.addEventListener('mouseover', handleMouseOver, true);
    document.addEventListener('mouseout', handleMouseOut, true);

    // 键盘事件
    document.addEventListener('keydown', handleKeyDown);

    // 右键菜单
    document.addEventListener('contextmenu', handleContextMenu, true);
  }

  function unbindEvents() {
    // 恢复页面原有的选择功能
    enableNativeSelection();

    document.removeEventListener('click', handleInspectClick, true);
    document.removeEventListener('mousedown', handleMouseDown, true);
    document.removeEventListener('selectstart', handleSelectStart, true);
    document.removeEventListener('mouseover', handleMouseOver, true);
    document.removeEventListener('mouseout', handleMouseOut, true);
    document.removeEventListener('keydown', handleKeyDown);
    document.removeEventListener('contextmenu', handleContextMenu, true);
  }

  window.OmniFlowAIHandlers = {
    bindEvents,
    unbindEvents,
    setCallbacks,
    handleInspectClick,
    handleMouseOver,
    handleMouseOut,
    handleKeyDown,
    handleContextMenu,
  };

})();
