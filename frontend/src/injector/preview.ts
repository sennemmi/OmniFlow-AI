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
    isBatch: false,
    successCount: 0,
    failedCount: 0,
  };
  private scrollHandler: (() => void) | null = null;

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
    console.log('[PreviewManager] 绑定事件监听');
    
    bus.on('ui:preview-controls:show', ({ filePath, originalContent, isBatch, successCount, failedCount }) => {
      console.log('[PreviewManager] 收到显示预览控制事件:', { filePath, originalContentLength: originalContent?.length, isBatch, successCount, failedCount });
      this.createPreviewControls(filePath, originalContent, isBatch, successCount, failedCount);
    });

    bus.on('ui:preview-controls:hide', () => {
      console.log('[PreviewManager] 收到隐藏预览控制事件');
      this.clearPreviewUI();
    });
    
    console.log('[PreviewManager] 事件监听绑定完成');
  }

  /**
   * 创建预览控制浮层
   */
  private createPreviewControls(
    filePath: string,
    originalContent: string,
    isBatch = false,
    successCount = 0,
    failedCount = 0
  ): void {
    console.log('[PreviewManager] 创建预览控制浮层:', { filePath, originalContentLength: originalContent?.length, isBatch });

    try {
      // 清除之前的预览 UI
      this.clearPreviewUI();

      // 保存状态
      this.state.filePath = filePath;
      this.state.originalContent = originalContent;
      this.state.isPreviewing = true;
      this.state.isBatch = isBatch;
      this.state.successCount = successCount;
      this.state.failedCount = failedCount;

      // 添加毛玻璃样式
      this.injectStyles();

      // 创建预览中提示条
      const banner = this.createBanner(filePath, originalContent, isBatch, successCount, failedCount);
      
      // 检查 document.body 是否存在
      if (!document.body) {
        console.error('[PreviewManager] document.body 不存在，无法添加预览横幅');
        bus.emit('ui:toast', { message: '预览界面创建失败：页面未加载完成', type: 'error' });
        return;
      }
      
      document.body.appendChild(banner);
      this.state.previewBanner = banner;

      // 绑定滚动事件，让横幅跟随页面
      this.bindScrollHandler();

      console.log('[PreviewManager] 预览横幅已添加到 DOM');
    } catch (error) {
      console.error('[PreviewManager] 创建预览控制浮层失败:', error);
      bus.emit('ui:toast', { message: '预览界面创建失败', type: 'error' });
    }
  }

  /**
   * 绑定滚动事件处理器
   */
  private bindScrollHandler(): void {
    // 移除旧的处理器
    if (this.scrollHandler) {
      window.removeEventListener('scroll', this.scrollHandler);
    }

    // 保存横幅的初始位置
    const banner = this.state.previewBanner;
    if (!banner) return;

    const initialTop = 16; // 固定距离顶部的距离

    // 创建新的滚动处理器
    this.scrollHandler = () => {
      if (banner && this.state.isPreviewing) {
        // 横幅保持固定在顶部，不随页面滚动
        banner.style.position = 'fixed';
        banner.style.top = `${initialTop}px`;
      }
    };

    window.addEventListener('scroll', this.scrollHandler, { passive: true });
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
    
    // 检查 document.head 是否存在
    if (!document.head) {
      console.error('[PreviewManager] document.head 不存在，无法添加样式');
      return;
    }
    
    document.head.appendChild(style);
  }

  /**
   * 创建预览横幅
   */
  private createBanner(
    filePath: string,
    originalContent: string,
    isBatch = false,
    successCount = 0,
    failedCount = 0
  ): HTMLElement {
    console.log('[PreviewManager] createBanner 开始:', { filePath, originalContentLength: originalContent?.length, isBatch, successCount, failedCount });
    
    const banner = document.createElement('div');
    banner.id = 'omni-preview-banner';
    console.log('[PreviewManager] banner 元素创建成功');
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

    // 批量修改显示不同的文案
    const title = isBatch ? '批量预览模式' : '预览模式';
    const subtitle = isBatch
      ? `${successCount} 个文件已更新，${failedCount > 0 ? `${failedCount} 个失败，` : ''}查看效果后确认或取消`
      : 'Vite 热更新已应用变更，查看效果后确认或取消';

    banner.innerHTML = `
      <div style="display: flex; align-items: center; gap: 16px;">
        <div style="width: 44px; height: 44px; background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(147, 51, 234, 0.2)); border-radius: 12px; display: flex; align-items: center; justify-content: center; border: 1px solid rgba(96, 165, 250, 0.3); animation: omni-pulse 2s infinite;">${eyeIcon}</div>
        <div>
          <div style="font-weight: 600; font-size: 15px; letter-spacing: -0.01em; color: #f8fafc;">${title}</div>
          <div style="font-size: 13px; color: #94a3b8; margin-top: 2px;">${subtitle}</div>
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
    console.log('[PreviewManager] 按钮元素查询:', { cancelBtn: !!cancelBtn, confirmBtn: !!confirmBtn });

    cancelBtn?.addEventListener('click', () => {
      console.log('[PreviewManager] 取消按钮点击');
      this.handleCancel(filePath, originalContent);
    });

    confirmBtn?.addEventListener('click', () => {
      console.log('[PreviewManager] 确认按钮点击');
      this.handleConfirm(filePath);
    });

    // ESC 取消
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        console.log('[PreviewManager] ESC 按下');
        this.handleCancel(filePath, originalContent);
      }
    };
    document.addEventListener('keydown', escHandler);
    this.state.escHandler = escHandler;

    console.log('[PreviewManager] createBanner 完成');
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

    if (this.scrollHandler) {
      window.removeEventListener('scroll', this.scrollHandler);
      this.scrollHandler = null;
    }

    this.state.previewBanner = null;
    this.state.escHandler = null;
  }

  /**
   * 重置状态
   */
  private resetState(): void {
    // 清理滚动事件处理器
    if (this.scrollHandler) {
      window.removeEventListener('scroll', this.scrollHandler);
      this.scrollHandler = null;
    }
    
    this.state = {
      isPreviewing: false,
      filePath: null,
      originalContent: null,
      modifiedContent: null,
      previewBanner: null,
      escHandler: null,
      isBatch: false,
      successCount: 0,
      failedCount: 0,
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
