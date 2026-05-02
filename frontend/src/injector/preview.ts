/**
 * OmniFlowAI Injector - Vite HMR 预览模块
 * 处理 AI 修改预览和确认/取消逻辑
 */

import { bus } from './events';
import { api } from './api';
import type { PreviewState } from './types';

/**
 * 预览管理器
 */
class PreviewManager {
  private state: PreviewState = {
    isPreviewing: false,
    filePath: null,
    originalContent: null,
    modifiedContent: null,
    previewBanner: null,
    escHandler: null,
  };

  /**
   * 初始化预览模块
   */
  init(): void {
    this.bindEvents();
  }

  /**
   * 绑定事件监听
   */
  private bindEvents(): void {
    bus.on('ui:preview-controls:show', ({ filePath, originalContent }) => {
      this.createPreviewControls(filePath, originalContent);
    });

    bus.on('ui:preview-controls:hide', () => {
      this.clearPreviewUI();
    });
  }

  /**
   * 创建预览控制浮层
   */
  private createPreviewControls(filePath: string, originalContent: string): void {
    // 清除之前的预览 UI
    this.clearPreviewUI();

    // 保存状态
    this.state.filePath = filePath;
    this.state.originalContent = originalContent;
    this.state.isPreviewing = true;

    // 添加毛玻璃样式
    this.injectStyles();

    // 创建预览中提示条
    const banner = this.createBanner(filePath, originalContent);
    document.body.appendChild(banner);
    this.state.previewBanner = banner;
  }

  /**
   * 注入预览样式
   */
  private injectStyles(): void {
    const styleId = 'omni-preview-styles';
    if (document.getElementById(styleId)) return;

    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      @keyframes omni-slide-down {
        from { transform: translateY(-100%); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
      }
      @keyframes omni-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
        50% { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
      }
      .omni-preview-spinner {
        animation: omni-spin 1s linear infinite;
      }
      @keyframes omni-spin {
        to { transform: rotate(360deg); }
      }
    `;
    document.head.appendChild(style);
  }

  /**
   * 创建预览横幅
   */
  private createBanner(filePath: string, originalContent: string): HTMLElement {
    const banner = document.createElement('div');
    banner.id = 'omni-preview-banner';
    banner.style.cssText = `
      position: fixed;
      top: 16px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: white;
      padding: 16px 32px;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 32px;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      border-radius: 16px;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05);
      animation: omni-slide-down 0.4s cubic-bezier(0.16, 1, 0.3, 1);
      min-width: 560px;
    `;

    const eyeIcon = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #60a5fa;"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const closeIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
    const checkIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

    banner.innerHTML = `
      <div style="display: flex; align-items: center; gap: 16px;">
        <div style="width: 44px; height: 44px; background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(147, 51, 234, 0.2)); border-radius: 12px; display: flex; align-items: center; justify-content: center; border: 1px solid rgba(96, 165, 250, 0.3); animation: omni-pulse 2s infinite;">${eyeIcon}</div>
        <div>
          <div style="font-weight: 600; font-size: 15px; letter-spacing: -0.01em; color: #f8fafc;">预览模式</div>
          <div style="font-size: 13px; color: #94a3b8; margin-top: 2px;">Vite 热更新已应用变更，查看效果后确认或取消</div>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <button id="omni-preview-cancel-btn" style="padding: 10px 20px; background: rgba(255, 255, 255, 0.05); color: #e2e8f0; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; font-size: 13px; cursor: pointer; transition: all 0.2s ease; font-weight: 500; display: flex; align-items: center; gap: 8px; letter-spacing: 0.01em;">${closeIcon}<span>取消恢复</span></button>
        <button id="omni-preview-confirm-btn" style="padding: 10px 20px; background: linear-gradient(135deg, #059669, #10b981); color: white; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 8px; letter-spacing: 0.01em; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);">${checkIcon}<span>确认保持</span></button>
      </div>
    `;

    // 绑定事件
    const cancelBtn = banner.querySelector<HTMLButtonElement>('#omni-preview-cancel-btn');
    const confirmBtn = banner.querySelector<HTMLButtonElement>('#omni-preview-confirm-btn');

    cancelBtn?.addEventListener('click', () => {
      this.handleCancel(filePath, originalContent);
    });

    confirmBtn?.addEventListener('click', () => {
      this.handleConfirm(filePath);
    });

    // ESC 取消
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        this.handleCancel(filePath, originalContent);
      }
    };
    document.addEventListener('keydown', escHandler);
    this.state.escHandler = escHandler;

    return banner;
  }

  /**
   * 处理确认
   */
  private handleConfirm(filePath: string): void {
    this.clearPreviewUI();
    this.resetState();
    bus.emit('action:preview:confirm', { filePath });
  }

  /**
   * 处理取消
   */
  private async handleCancel(filePath: string, originalContent: string): Promise<void> {
    bus.emit('ui:progress:show', {});
    bus.emit('ui:progress:update', { status: '正在恢复原始文件...', percent: 50 });

    try {
      await api.writeFile(filePath, originalContent);

      this.clearPreviewUI();
      this.resetState();

      bus.emit('ui:progress:update', { status: '已恢复原始文件', percent: 100 });
      setTimeout(() => {
        bus.emit('ui:progress:hide', undefined);
        bus.emit('action:preview:cancel', { filePath, originalContent });
      }, 1000);
    } catch (error) {
      bus.emit('ui:progress:update', {
        status: `恢复失败: ${error instanceof Error ? error.message : '未知错误'}`,
        percent: 0,
      });
      bus.emit('ui:toast', {
        message: `恢复失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      setTimeout(() => bus.emit('ui:progress:hide', undefined), 3000);
    }
  }

  /**
   * 清除预览 UI
   */
  private clearPreviewUI(): void {
    if (this.state.previewBanner) {
      this.state.previewBanner.remove();
    }

    if (this.state.escHandler) {
      document.removeEventListener('keydown', this.state.escHandler);
    }

    this.state.previewBanner = null;
    this.state.escHandler = null;
  }

  /**
   * 重置状态
   */
  private resetState(): void {
    this.state = {
      isPreviewing: false,
      filePath: null,
      originalContent: null,
      modifiedContent: null,
      previewBanner: null,
      escHandler: null,
    };
  }

  /**
   * 开始预览（兼容旧 API）
   */
  async startPreview(): Promise<void> {
    // 这个方法现在由 Pipeline 模块调用
    // 实际逻辑已经迁移到 PipelineManager.handleQuickModify
    console.warn('[PreviewManager] startPreview is deprecated, use PipelineManager instead');
  }

  /**
   * 获取预览状态
   */
  getPreviewState(): PreviewState {
    return { ...this.state };
  }
}

// 导出单例
export const preview = new PreviewManager();
export const PreviewModule = preview;

export default preview;
