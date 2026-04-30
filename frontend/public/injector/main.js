/**
 * OmniFlowAI 浏览器注入脚本 - 主入口模块
 * 整合所有子模块，提供统一的初始化入口
 */

(function () {
  'use strict';

  const CONFIG = window.OmniFlowAIConfig;
  const { UI } = window.OmniFlowAIUI;
  const { state, StateManager } = window.OmniFlowAIState;
  const { VisualFeedback } = window.OmniFlowAISelection;
  const Handlers = window.OmniFlowAIHandlers;
  const Pipeline = window.OmniFlowAIPipeline;

  // ============================================
  // 选择模式控制
  // ============================================
  function toggleSelectionMode() {
    if (state.isSelectionMode) {
      exitSelectionMode();
    } else {
      enterSelectionMode();
    }
  }

  let exitButton = null;

  function enterSelectionMode() {
    state.isSelectionMode = true;
    state.selectionMode = 'single';
    document.body.style.cursor = 'crosshair';

    // 设置事件处理器回调
    // 【修改】使用 quickModify 替代 handleModify，走轻量级修改流程
    Handlers.setCallbacks({
      onExitSelectionMode: exitSelectionMode,
      onHandleModify: (elementInfo, feedback) => {
        Pipeline.quickModify(elementInfo, feedback, () => {
          VisualFeedback.closeEditDialog();
          exitSelectionMode();
        });
      },
      onHandleAreaModify: (elements, feedback) => {
        Pipeline.quickAreaModify(elements, feedback, () => {
          VisualFeedback.closeEditDialog();
          exitSelectionMode();
        });
      },
    });

    // 绑定事件
    Handlers.bindEvents();

    // 【新增】显示退出按钮
    if (!exitButton) {
      exitButton = UI.createExitButton(() => {
        exitSelectionMode();
      });
      document.body.appendChild(exitButton);
    }

    UI.createToast('圈选模式已开启：单击选择单个元素，Shift+点击多选，右键/ESC/退出按钮取消');
  }

  function exitSelectionMode() {
    state.isSelectionMode = false;
    state.selectionMode = 'single';
    StateManager.resetSelectionState();

    document.body.style.cursor = '';

    // 解绑事件
    Handlers.unbindEvents();

    // 清除所有视觉反馈
    VisualFeedback.clearAll();

    // 【新增】移除退出按钮
    if (exitButton) {
      exitButton.remove();
      exitButton = null;
    }
  }

  // ============================================
  // 初始化
  // ============================================
  function init() {
    // 注入样式
    const style = document.createElement('style');
    style.textContent = `
      @keyframes omni-slide-in {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      @keyframes omni-slide-out {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 1; }
      }
      @keyframes omni-spin {
        to { transform: rotate(360deg); }
      }
      .omni-highlight-box {
        animation: omni-pulse 1.5s ease-in-out infinite;
      }
      @keyframes omni-pulse {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 0.9; }
      }
      .omni-floating-panel {
        animation: omni-fade-in 0.2s ease-out;
      }
      @keyframes omni-fade-in {
        from { opacity: 0; transform: translateY(-8px); }
        to { opacity: 1; transform: translateY(0); }
      }
    `;
    document.head.appendChild(style);

    // 创建浮动图标
    const icon = UI.createFloatingIcon(() => {
      toggleSelectionMode();
    });
    document.body.appendChild(icon);

    console.log('[OmniFlowAI] 注入脚本已加载，点击右下角图标开启圈选模式');
    console.log('[OmniFlowAI] React DevTools 可用:', window.OmniFlowAICore.ReactSourceMapper.isDevToolsAvailable());
  }

  // 等待 DOM 加载完成
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 导出全局 API
  window.OmniFlowAI = {
    toggle: toggleSelectionMode,
    isActive: () => state.isSelectionMode,
    version: '4.0.0',
    config: CONFIG,
    getElementInfo: (el) => window.OmniFlowAICore.DOM.getElementInfo(el),
    // 内部模块访问（调试用）
    _state: state,
    _StateManager: StateManager,
    _VisualFeedback: VisualFeedback,
    _Handlers: Handlers,
    _Pipeline: Pipeline,
  };

})();
