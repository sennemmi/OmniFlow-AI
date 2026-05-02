/**
 * OmniFlowAI Injector - 主入口模块
 * 类型安全、事件驱动的浏览器注入脚本
 */

import './styles.css';
import { config } from './config';
import { bus } from './events';
import { ui } from './ui';
import { stateManager, appState } from './state';
import { interaction } from './interaction';
import { pipeline } from './pipeline';
import { preview } from './preview';
import { dom, utils, reactSourceMapper } from './core';

/**
 * OmniFlowAI Injector 主类
 */
class OmniFlowInjector {
  private initialized = false;
  private version = '4.1.0';

  /**
   * 初始化 Injector
   */
  init(): void {
    if (this.initialized) {
      console.log('[OmniFlowAI] Injector 已初始化');
      return;
    }

    console.log(`[OmniFlowAI] Injector v${this.version} 初始化中...`);

    // 初始化各个模块
    this.initializeModules();

    // 绑定全局事件流
    this.bindGlobalEvents();

    // 注入全局样式
    this.injectGlobalStyles();

    // 创建浮动图标
    this.createFloatingIcon();

    // 标记为已初始化
    this.initialized = true;

    // 触发系统初始化事件
    bus.emit('system:init', undefined);

    console.log('[OmniFlowAI] Injector 初始化完成，点击右下角图标开启圈选模式');
    console.log('[OmniFlowAI] React DevTools 可用:', reactSourceMapper.isDevToolsAvailable());

    // 导出全局 API（向后兼容）
    this.exposeGlobalAPI();
  }

  /**
   * 初始化所有模块
   */
  private initializeModules(): void {
    ui.init();
    interaction.init();
    pipeline.init();
    preview.init();
  }

  /**
   * 绑定全局事件流
   */
  private bindGlobalEvents(): void {
    // 串联全局逻辑：点击元素后显示弹窗
    bus.on('element:click', ({ isShift }) => {
      if (!isShift) {
        // 单选模式下，高亮元素并准备显示对话框
        // 实际显示逻辑在 interaction.ts 中处理
      }
    });

    // 全局退出信号
    bus.on('mode:selection:exit', () => {
      document.body.style.cursor = '';
      // 各个模块会自动通过监听此事件来清理自己
    });

    // 系统错误处理
    bus.on('system:error', ({ error }) => {
      console.error('[OmniFlowAI] 系统错误:', error);
      ui.createToast(`系统错误: ${error.message}`, 'error');
    });
  }

  /**
   * 注入全局样式
   */
  private injectGlobalStyles(): void {
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
      @keyframes omni-fade-in {
        from { opacity: 0; transform: translateY(-8px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes omni-pulse {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 0.9; }
      }
      .omni-highlight-box {
        animation: omni-pulse 1.5s ease-in-out infinite;
      }
      .omni-floating-panel {
        animation: omni-fade-in 0.2s ease-out;
      }
      .omni-progress-spinner {
        animation: omni-spin 1s linear infinite;
      }
    `;
    document.head.appendChild(style);
  }

  /**
   * 创建浮动图标
   */
  private createFloatingIcon(): void {
    const icon = ui.createFloatingIcon();
    document.body.appendChild(icon);
  }

  /**
   * 导出全局 API（向后兼容）
   */
  private exposeGlobalAPI(): void {
    (window as Window & { OmniFlowAI?: Record<string, unknown> }).OmniFlowAI = {
      // 公共 API
      toggle: () => stateManager.toggleSelectionMode(),
      enter: () => stateManager.enterSelectionMode(),
      exit: () => stateManager.exitSelectionMode(),
      isActive: () => appState.isSelectionMode,
      version: this.version,
      config: config as unknown as Record<string, unknown>,

      // 工具方法
      getElementInfo: (el: HTMLElement) => dom.getElementInfo(el),

      // 事件总线（高级用法）
      events: {
        on: bus.on.bind(bus),
        off: bus.off.bind(bus),
        emit: bus.emit.bind(bus),
      },

      // 内部模块访问（调试用）
      _internals: {
        state: appState,
        stateManager,
        ui,
        interaction,
        pipeline,
        preview,
        dom,
        utils,
        bus,
      },
    };
  }
}

// 创建并导出单例
const injector = new OmniFlowInjector();

/**
   * 自动初始化
   */
function bootstrap(): void {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => injector.init());
  } else {
    injector.init();
  }
}

// 启动
bootstrap();

// 导出模块（用于测试和高级用法）
export { injector as default, injector as OmniFlowInjector };
export { config } from './config';
export { bus, Events } from './events';
export { ui, UI } from './ui';
export { stateManager, StateManager, appState } from './state';
export { api, API } from './api';
export { interaction, InteractionModule } from './interaction';
export { pipeline, PipelineModule } from './pipeline';
export { preview, PreviewModule } from './preview';
export { dom, DOM, utils, Utils, reactSourceMapper, ReactSourceMapper } from './core';
export { visualFeedback, VisualFeedback, panelManager, PanelManager } from './selection';
export type * from './types';
