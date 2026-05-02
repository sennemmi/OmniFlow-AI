/**
 * OmniFlowAI 浏览器注入脚本 - 圈选逻辑模块
 * 
 * 【简化版】只保留 Shift 多选支持
 * - 多选高亮
 * - 多选包围矩形计算
 * - 【新增】滚动时更新高亮框位置
 */

(function () {
  'use strict';

  const { UI } = window.OmniFlowAIUI;
  const { state } = window.OmniFlowAIState;

  // ============================================
  // 几何计算
  // ============================================
  const Geometry = {
    /**
     * 计算多个元素的包围矩形
     */
    getElementsBoundingRect(elements) {
      if (!elements || elements.length === 0) return null;

      let minLeft = Infinity, minTop = Infinity;
      let maxRight = -Infinity, maxBottom = -Infinity;

      elements.forEach(el => {
        const rect = el.getBoundingClientRect();
        minLeft = Math.min(minLeft, rect.left);
        minTop = Math.min(minTop, rect.top);
        maxRight = Math.max(maxRight, rect.right);
        maxBottom = Math.max(maxBottom, rect.bottom);
      });

      return {
        left: minLeft + window.scrollX,
        top: minTop + window.scrollY,
        right: maxRight + window.scrollX,
        bottom: maxBottom + window.scrollY,
        width: maxRight - minLeft,
        height: maxBottom - minTop,
      };
    },
  };

  // ============================================
  // 视觉反馈管理
  // ============================================
  const VisualFeedback = {
    /**
     * 【新增】存储当前高亮的元素，用于滚动时更新位置
     */
    _highlightedElements: [],
    _multiSelectedElements: [],

    /**
     * 高亮单个元素（悬停或选中）
     */
    highlightElement(el) {
      this.clearHighlight();
      this._highlightedElements = [el];
      const rect = el.getBoundingClientRect();
      const box = UI.createHighlightBox(rect);
      document.body.appendChild(box);
    },

    /**
     * 清除单元素高亮
     */
    clearHighlight() {
      const boxes = document.querySelectorAll('.omni-highlight-box');
      boxes.forEach(box => box.remove());
      this._highlightedElements = [];
    },

    /**
     * 更新多选高亮
     */
    updateMultiSelection(elements) {
      this.clearMultiHighlight();
      this._multiSelectedElements = [...elements];
      
      elements.forEach((el, index) => {
        const rect = el.getBoundingClientRect();
        const box = UI.createMultiHighlightBox(rect, index + 1);
        document.body.appendChild(box);
      });
    },

    /**
     * 清除多选高亮
     */
    clearMultiHighlight() {
      const boxes = document.querySelectorAll('.omni-multi-highlight-box');
      boxes.forEach(box => box.remove());
      this._multiSelectedElements = [];
    },

    /**
     * 【新增】更新所有高亮框的位置（滚动时调用）
     */
    updateHighlightPositions() {
      // 更新单元素高亮
      if (this._highlightedElements.length > 0) {
        const boxes = document.querySelectorAll('.omni-highlight-box');
        this._highlightedElements.forEach((el, index) => {
          if (boxes[index]) {
            const rect = el.getBoundingClientRect();
            boxes[index].style.left = `${rect.left}px`;
            boxes[index].style.top = `${rect.top}px`;
            boxes[index].style.width = `${rect.width}px`;
            boxes[index].style.height = `${rect.height}px`;
          }
        });
      }

      // 更新多选高亮
      if (this._multiSelectedElements.length > 0) {
        const boxes = document.querySelectorAll('.omni-multi-highlight-box');
        this._multiSelectedElements.forEach((el, index) => {
          if (boxes[index]) {
            const rect = el.getBoundingClientRect();
            boxes[index].style.left = `${rect.left}px`;
            boxes[index].style.top = `${rect.top}px`;
            boxes[index].style.width = `${rect.width}px`;
            boxes[index].style.height = `${rect.height}px`;
            
            // 更新 badge 位置
            const badge = boxes[index].querySelector('.omni-multi-highlight-badge');
            if (badge) {
              badge.style.left = '-10px';
              badge.style.top = '-10px';
            }
          }
        });
      }
    },

    /**
     * 获取多选元素的包围矩形
     */
    getMultiSelectionRect(elements) {
      return Geometry.getElementsBoundingRect(elements);
    },

    /**
     * 清除浮动面板
     */
    clearFloatingPanel() {
      if (state.floatingPanel) {
        state.floatingPanel.remove();
        state.floatingPanel = null;
      }
    },

    /**
     * 关闭编辑弹窗
     */
    closeEditDialog() {
      if (state.editDialog) {
        state.editDialog.remove();
        state.editDialog = null;
      }
    },

    /**
     * 清除所有视觉反馈
     */
    clearAll() {
      this.clearHighlight();
      this.clearMultiHighlight();
      this.clearFloatingPanel();
      this.closeEditDialog();
    },
  };

  // ============================================
  // 圈选面板管理
  // ============================================
  const PanelManager = {
    showAreaSelectionPanel(elements, rect, onCancel, onSubmit) {
      VisualFeedback.clearFloatingPanel();

      const panel = UI.createAreaSelectionPanel(elements, {
        left: rect.left - window.scrollX,
        top: rect.top - window.scrollY,
        width: rect.width,
        height: rect.height,
      }, onCancel, onSubmit);

      document.body.appendChild(panel);
      state.floatingPanel = panel;
    },

    showEditDialog(elementInfo, isAreaSelection, selectedElements, onCancel, onSubmit) {
      const dialog = UI.createEditDialog(elementInfo, isAreaSelection, selectedElements, onCancel, onSubmit);
      document.body.appendChild(dialog);
      state.editDialog = dialog;

      setTimeout(() => {
        const input = dialog.querySelector('#omni-edit-input');
        if (input) input.focus();
      }, 100);

      return dialog;
    },
  };

  // ============================================
  // 【新增】滚动监听
  // ============================================
  function handleScroll() {
    if (state.isSelectionMode) {
      VisualFeedback.updateHighlightPositions();
    }
  }

  // 使用 requestAnimationFrame 优化滚动性能
  let ticking = false;
  function optimizedScrollHandler() {
    if (!ticking) {
      window.requestAnimationFrame(() => {
        handleScroll();
        ticking = false;
      });
      ticking = true;
    }
  }

  // 绑定滚动事件
  window.addEventListener('scroll', optimizedScrollHandler, { passive: true });
  // 也监听窗口 resize
  window.addEventListener('resize', optimizedScrollHandler, { passive: true });

  window.OmniFlowAISelection = {
    Geometry,
    VisualFeedback,
    PanelManager,
  };

})();
