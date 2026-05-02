/**
 * OmniFlowAI Injector - UI 组件模块
 * 所有 UI 组件通过事件驱动，不直接调用业务逻辑
 */

import { config } from './config';
import { dom, utils } from './core';
import { bus } from './events';
import { stateManager, appState } from './state';
import type { ElementInfo } from './types';

/**
 * UI 组件管理器
 */
class UIManager {
  private progressBar: HTMLElement | null = null;
  private exitButton: HTMLElement | null = null;

  /**
   * 初始化 UI 模块
   */
  init(): void {
    // 监听 UI 相关事件
    this.bindEvents();
  }

  /**
   * 绑定事件监听
   */
  private bindEvents(): void {
    // 监听 UI 事件
    bus.on('ui:toast', ({ message, type }) => {
      this.createToast(message, type);
    });

    bus.on('ui:progress:show', ({ pipelineId }) => {
      this.showProgress(pipelineId);
    });

    bus.on('ui:progress:update', ({ status, percent }) => {
      this.updateProgress(status, percent);
    });

    bus.on('ui:progress:hide', () => {
      this.hideProgress();
    });

    bus.on('ui:notification:show', ({ prUrl }) => {
      this.createCompletionNotification(prUrl);
    });

    bus.on('mode:selection:enter', () => {
      this.showExitButton();
    });

    bus.on('mode:selection:exit', () => {
      this.hideExitButton();
    });

    bus.on('ui:dialog:show', ({ elementInfo, isMulti }) => {
      this.showEditDialog(elementInfo, isMulti || false);
    });

    bus.on('ui:panel:show', ({ elements }) => {
      this.showMultiSelectionPanel(elements);
    });
  }

  /**
   * 创建浮动图标
   */
  createFloatingIcon(): HTMLElement {
    const icon = dom.create('div', 'omni-floating-icon', {
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      width: `${config.ICON_SIZE}px`,
      height: `${config.ICON_SIZE}px`,
      borderRadius: '50%',
      background: `linear-gradient(135deg, ${config.COLORS.primary}, #2860EE)`,
      boxShadow: '0 4px 16px rgba(51, 112, 255, 0.4)',
      cursor: 'pointer',
      zIndex: String(config.Z_INDEX),
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'transform 0.2s, box-shadow 0.2s',
    });

    icon.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M2 17L12 22L22 17" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M2 12L12 17L22 12" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;

    icon.addEventListener('mouseenter', () => {
      icon.style.transform = 'scale(1.1)';
      icon.style.boxShadow = '0 6px 20px rgba(51, 112, 255, 0.5)';
    });

    icon.addEventListener('mouseleave', () => {
      icon.style.transform = 'scale(1)';
      icon.style.boxShadow = '0 4px 16px rgba(51, 112, 255, 0.4)';
    });

    icon.addEventListener('click', () => {
      stateManager.toggleSelectionMode();
    });

    return icon;
  }

  /**
   * 显示退出按钮
   */
  private showExitButton(): void {
    if (this.exitButton) return;

    const button = dom.create('div', 'omni-exit-button', {
      position: 'fixed',
      top: '24px',
      right: '24px',
      padding: '8px 16px',
      background: '#F53F3F',
      color: '#fff',
      borderRadius: '6px',
      fontSize: '14px',
      fontWeight: '500',
      cursor: 'pointer',
      zIndex: String(config.Z_INDEX + 100),
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      boxShadow: '0 4px 12px rgba(245, 63, 63, 0.4)',
      transition: 'transform 0.2s, box-shadow 0.2s',
    });

    button.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M18 6L6 18M6 6l12 12"/>
      </svg>
      <span>退出圈选</span>
    `;

    button.addEventListener('mouseenter', () => {
      button.style.transform = 'scale(1.05)';
      button.style.boxShadow = '0 6px 16px rgba(245, 63, 63, 0.5)';
    });

    button.addEventListener('mouseleave', () => {
      button.style.transform = 'scale(1)';
      button.style.boxShadow = '0 4px 12px rgba(245, 63, 63, 0.4)';
    });

    button.addEventListener('click', () => {
      stateManager.exitSelectionMode();
    });

    document.body.appendChild(button);
    this.exitButton = button;
  }

  /**
   * 隐藏退出按钮
   */
  private hideExitButton(): void {
    if (this.exitButton) {
      this.exitButton.remove();
      this.exitButton = null;
    }
  }

  /**
   * 创建高亮框
   */
  createHighlightBox(rect: DOMRect): HTMLElement {
    return dom.create('div', 'omni-highlight-box', {
      position: 'fixed',
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
      border: '2px solid #6366f1',
      borderRadius: '3px',
      pointerEvents: 'none',
      zIndex: String(config.Z_INDEX - 1),
      transition: 'all 60ms ease',
      boxShadow: '0 0 0 2px rgba(99, 102, 241, 0.3), 0 0 0 9999px rgba(0, 0, 0, 0.15)',
    });
  }

  /**
   * 创建多选高亮框
   */
  createMultiHighlightBox(rect: DOMRect, index: number): HTMLElement {
    const container = dom.create('div', 'omni-multi-highlight-box', {
      position: 'fixed',
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
      border: '2px solid #00B42A',
      borderRadius: '3px',
      pointerEvents: 'none',
      zIndex: String(config.Z_INDEX - 1),
      boxShadow: '0 0 0 2px rgba(0, 180, 66, 0.3)',
    });

    const badge = dom.create('div', 'omni-multi-highlight-badge', {
      position: 'absolute',
      top: '-10px',
      left: '-10px',
      width: '20px',
      height: '20px',
      background: '#00B42A',
      color: '#fff',
      borderRadius: '50%',
      fontSize: '11px',
      fontWeight: '600',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: String(config.Z_INDEX),
    });
    badge.textContent = String(index);
    container.appendChild(badge);

    return container;
  }

  /**
   * 创建浮动面板
   */
  createFloatingPanel(referenceRect: DOMRect, content: string): HTMLElement {
    const panel = dom.create('div', 'omni-floating-panel', {
      position: 'fixed',
      minWidth: '280px',
      maxWidth: '400px',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      zIndex: String(config.Z_INDEX + 1),
      overflow: 'hidden',
    });

    const position = utils.calculatePanelPosition(referenceRect, panel);
    panel.style.left = `${position.x}px`;
    panel.style.top = `${position.y}px`;
    panel.innerHTML = content;

    return panel;
  }

  /**
   * 显示编辑对话框
   */
  showEditDialog(elementInfo: ElementInfo, isAreaSelection: boolean): void {
    const overlay = dom.create('div', 'omni-edit-overlay', {
      position: 'fixed',
      inset: '0',
      background: config.COLORS.overlay,
      zIndex: String(config.Z_INDEX + 1),
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    });

    const dialog = dom.create('div', 'omni-edit-dialog', {
      width: '560px',
      maxWidth: '90vw',
      maxHeight: '90vh',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    });

    const hasPreciseSource = elementInfo.sourceFile && elementInfo.sourceLine > 0;
    const title = isAreaSelection
      ? `批量修改 ${appState.selectedElements.length} 个元素`
      : '修改元素';

    dialog.innerHTML = `
      <div style="padding: 20px 24px; border-bottom: 1px solid #E8E9EB;">
        <h3 style="margin: 0; font-size: 18px; font-weight: 600; color: #1F2329;">${title}</h3>
        <p style="margin: 8px 0 0; font-size: 13px; color: #646A73;">
          ${elementInfo.tag}${elementInfo.id ? `#${elementInfo.id}` : ''}
        </p>
        ${hasPreciseSource ? `
        <div style="margin-top: 8px; padding: 8px 12px; background: #F0FFF5; border-radius: 6px; border: 1px solid #00B42A;">
          <span style="font-size: 12px; color: #00B42A;">✅ 已精确定位到源码位置</span>
        </div>
        ` : ''}
      </div>
      <div style="padding: 20px 24px; overflow-y: auto; flex: 1;">
        <label style="display: block; margin-bottom: 8px; font-size: 14px; font-weight: 500; color: #1F2329;">
          你想如何修改${isAreaSelection ? '这些元素' : '此元素'}？
        </label>
        <textarea id="omni-edit-input" placeholder="例如：将按钮颜色改为红色，增加点击动画效果..."
          style="width: 100%; height: 100px; padding: 12px; border: 1px solid #DEE0E3; border-radius: 8px; font-size: 14px; resize: vertical; box-sizing: border-box;"></textarea>
      </div>
      <div style="padding: 16px 24px; border-top: 1px solid #E8E9EB; display: flex; justify-content: flex-end; gap: 12px;">
        <button id="omni-edit-cancel" style="padding: 8px 16px; border: none; background: transparent; color: #646A73; font-size: 14px; cursor: pointer; border-radius: 6px;">取消</button>
        <button id="omni-edit-submit" style="padding: 8px 16px; border: none; background: #3370FF; color: #fff; font-size: 14px; cursor: pointer; border-radius: 6px; font-weight: 500;">提交给 AI</button>
      </div>
    `;

    overlay.appendChild(dialog);

    const input = dialog.querySelector<HTMLTextAreaElement>('#omni-edit-input');
    const cancelBtn = dialog.querySelector<HTMLButtonElement>('#omni-edit-cancel');
    const submitBtn = dialog.querySelector<HTMLButtonElement>('#omni-edit-submit');

    cancelBtn?.addEventListener('click', () => {
      stateManager.resetSelectionState();
      overlay.remove();
    });

    submitBtn?.addEventListener('click', () => {
      const feedback = input?.value.trim();
      if (!feedback) {
        if (input) input.style.borderColor = '#F53F3F';
        return;
      }

      if (isAreaSelection) {
        bus.emit('action:area-modify:submit', {
          elements: appState.selectedElements,
          feedback,
        });
      } else {
        bus.emit('action:modify:submit', { elementInfo, feedback });
      }
      overlay.remove();
    });

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        stateManager.resetSelectionState();
        overlay.remove();
      }
    });

    document.body.appendChild(overlay);
    appState.editDialog = overlay;

    setTimeout(() => input?.focus(), 100);
  }

  /**
   * 显示多选面板
   */
  showMultiSelectionPanel(elements: HTMLElement[]): void {
    // 简化实现，触发事件让 Selection 模块处理
    bus.emit('element:select:multi', { elements });
  }

  /**
   * 显示进度条
   */
  private showProgress(pipelineId?: string): void {
    if (this.progressBar) return;

    const container = dom.create('div', 'omni-progress-container', {
      position: 'fixed',
      bottom: '80px',
      right: '24px',
      width: '320px',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      zIndex: String(config.Z_INDEX + 10),
      overflow: 'hidden',
    });

    container.innerHTML = `
      <div style="padding: 16px 20px; border-bottom: 1px solid #E8E9EB;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div class="omni-progress-spinner" style="width: 16px; height: 16px; border: 2px solid #E8E9EB; border-top-color: #3370FF; border-radius: 50%;"></div>
          <span style="font-size: 14px; font-weight: 500; color: #1F2329;">AI 正在为您生成变更...</span>
        </div>
        ${pipelineId ? `<div style="margin-top: 8px; font-size: 12px; color: #646A73;">Pipeline: <span style="font-family: monospace; color: #3370FF;">${pipelineId.slice(0, 8)}...</span></div>` : ''}
      </div>
      <div style="padding: 12px 20px; background: #F5F6F7;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <span class="omni-progress-status" style="font-size: 12px; color: #646A73;">初始化...</span>
          <span class="omni-progress-percent" style="font-size: 12px; font-weight: 500; color: #3370FF;">0%</span>
        </div>
        <div style="width: 100%; height: 4px; background: #E8E9EB; border-radius: 2px; overflow: hidden;">
          <div class="omni-progress-bar" style="width: 0%; height: 100%; background: linear-gradient(90deg, #3370FF, #00B42A); border-radius: 2px; transition: width 0.5s ease;"></div>
        </div>
      </div>
    `;

    document.body.appendChild(container);
    this.progressBar = container;
  }

  /**
   * 更新进度条
   */
  private updateProgress(status: string, percent: number): void {
    if (!this.progressBar) return;

    const statusEl = this.progressBar.querySelector('.omni-progress-status');
    const percentEl = this.progressBar.querySelector('.omni-progress-percent');
    const barEl = this.progressBar.querySelector('.omni-progress-bar');
    const spinnerEl = this.progressBar.querySelector('.omni-progress-spinner');

    if (statusEl) statusEl.textContent = status;
    if (percentEl) percentEl.textContent = `${percent}%`;
    if (barEl) (barEl as HTMLElement).style.width = `${percent}%`;

    if (percent >= 100 && spinnerEl) {
      (spinnerEl as HTMLElement).style.border = 'none';
      (spinnerEl as HTMLElement).style.background = '#00B42A';
      spinnerEl.innerHTML = '✓';
      (spinnerEl as HTMLElement).style.color = '#fff';
      (spinnerEl as HTMLElement).style.display = 'flex';
      (spinnerEl as HTMLElement).style.alignItems = 'center';
      (spinnerEl as HTMLElement).style.justifyContent = 'center';
      (spinnerEl as HTMLElement).style.fontSize = '10px';
    }
  }

  /**
   * 隐藏进度条
   */
  private hideProgress(): void {
    if (this.progressBar) {
      this.progressBar.style.animation = 'omni-slide-out 0.3s ease-in';
      setTimeout(() => {
        this.progressBar?.remove();
        this.progressBar = null;
      }, 300);
    }
  }

  /**
   * 创建 Toast 提示
   */
  createToast(message: string, type: 'info' | 'success' | 'error' | 'warning' = 'info'): void {
    const colors = {
      info: '#1A1C21',
      success: '#00B42A',
      error: '#F53F3F',
      warning: '#FF7D00',
    };

    const toast = dom.create('div', 'omni-toast', {
      position: 'fixed',
      bottom: '80px',
      right: '24px',
      padding: '12px 20px',
      background: colors[type],
      color: '#fff',
      borderRadius: '8px',
      fontSize: '14px',
      zIndex: String(config.Z_INDEX + 2),
      boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
    });

    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'omni-slide-out 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  /**
   * 创建完成通知
   */
  createCompletionNotification(prUrl: string): void {
    const notification = dom.create('div', 'omni-completion-notification', {
      position: 'fixed',
      top: '24px',
      right: '24px',
      width: '380px',
      background: '#fff',
      borderRadius: '12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      zIndex: String(config.Z_INDEX + 20),
      overflow: 'hidden',
      border: '1px solid #00B42A',
    });

    notification.innerHTML = `
      <div style="padding: 20px;">
        <div style="display: flex; align-items: flex-start; gap: 12px;">
          <div style="width: 40px; height: 40px; border-radius: 50%; background: #F0FFF5; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
            <span style="font-size: 20px;">✨</span>
          </div>
          <div style="flex: 1;">
            <h4 style="margin: 0 0 8px; font-size: 16px; font-weight: 600; color: #1F2329;">AI 已完成修改！</h4>
            <p style="margin: 0 0 12px; font-size: 13px; color: #646A73; line-height: 1.5;">
              代码已自动同步并 Push 到了 GitHub PR。
            </p>
            <div style="display: flex; gap: 8px;">
              <a href="${prUrl}" target="_blank" style="padding: 6px 12px; background: #3370FF; color: #fff; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 500;">查看 PR</a>
              <button class="omni-close-notification" style="padding: 6px 12px; background: transparent; border: 1px solid #DEE0E3; color: #646A73; border-radius: 6px; font-size: 13px; cursor: pointer;">关闭</button>
            </div>
          </div>
        </div>
      </div>
    `;

    const closeBtn = notification.querySelector('.omni-close-notification');
    closeBtn?.addEventListener('click', () => notification.remove());

    document.body.appendChild(notification);

    setTimeout(() => {
      if (notification.parentNode) {
        notification.style.animation = 'omni-slide-out 0.3s ease-in';
        setTimeout(() => notification.remove(), 300);
      }
    }, 10000);
  }
}

// 导出单例
export const ui = new UIManager();
export const UI = ui;

export default ui;
