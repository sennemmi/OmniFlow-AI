/**
 * OmniFlowAI Injector - 圈选逻辑模块
 * 处理元素高亮、多选、视觉反馈
 */

import { dom } from './core';
import { appState, stateManager } from './state';
import { ui } from './ui';

/**
 * 几何计算工具
 */
class Geometry {
  /**
   * 计算多个元素的包围矩形
   */
  static getElementsBoundingRect(elements: HTMLElement[]): DOMRect | null {
    if (!elements || elements.length === 0) return null;

    let minLeft = Infinity,
      minTop = Infinity;
    let maxRight = -Infinity,
      maxBottom = -Infinity;

    elements.forEach((el) => {
      const rect = el.getBoundingClientRect();
      minLeft = Math.min(minLeft, rect.left);
      minTop = Math.min(minTop, rect.top);
      maxRight = Math.max(maxRight, rect.right);
      maxBottom = Math.max(maxBottom, rect.bottom);
    });

    return {
      left: minLeft,
      top: minTop,
      right: maxRight,
      bottom: maxBottom,
      width: maxRight - minLeft,
      height: maxBottom - minTop,
      x: minLeft,
      y: minTop,
      toJSON: () => ({}),
    } as DOMRect;
  }
}

/**
 * 视觉反馈管理器类
 */
class VisualFeedbackClass {
  private highlightedElements: HTMLElement[] = [];
  private multiSelectedElements: HTMLElement[] = [];

  /**
   * 高亮单个元素
   */
  highlightElement(el: HTMLElement): void {
    this.clearHighlight();
    this.highlightedElements = [el];
    const rect = el.getBoundingClientRect();
    const box = ui.createHighlightBox(rect);
    document.body.appendChild(box);
  }

  /**
   * 清除单元素高亮
   */
  clearHighlight(): void {
    const boxes = document.querySelectorAll('.omni-highlight-box');
    boxes.forEach((box) => box.remove());
    this.highlightedElements = [];
  }

  /**
   * 更新多选高亮
   */
  updateMultiSelection(elements: HTMLElement[]): void {
    this.clearMultiHighlight();
    this.multiSelectedElements = [...elements];

    elements.forEach((el, index) => {
      const rect = el.getBoundingClientRect();
      const box = ui.createMultiHighlightBox(rect, index + 1);
      document.body.appendChild(box);
    });
  }

  /**
   * 清除多选高亮
   */
  clearMultiHighlight(): void {
    const boxes = document.querySelectorAll('.omni-multi-highlight-box');
    boxes.forEach((box) => box.remove());
    this.multiSelectedElements = [];
  }

  /**
   * 更新所有高亮框位置（滚动时调用）
   */
  updateHighlightPositions(): void {
    // 更新单元素高亮
    if (this.highlightedElements.length > 0) {
      const boxes = document.querySelectorAll('.omni-highlight-box');
      this.highlightedElements.forEach((el, index) => {
        const box = boxes[index] as HTMLElement;
        if (box) {
          const rect = el.getBoundingClientRect();
          box.style.left = `${rect.left}px`;
          box.style.top = `${rect.top}px`;
          box.style.width = `${rect.width}px`;
          box.style.height = `${rect.height}px`;
        }
      });
    }

    // 更新多选高亮
    if (this.multiSelectedElements.length > 0) {
      const boxes = document.querySelectorAll('.omni-multi-highlight-box');
      this.multiSelectedElements.forEach((el, index) => {
        const box = boxes[index] as HTMLElement;
        if (box) {
          const rect = el.getBoundingClientRect();
          box.style.left = `${rect.left}px`;
          box.style.top = `${rect.top}px`;
          box.style.width = `${rect.width}px`;
          box.style.height = `${rect.height}px`;
        }
      });
    }
  }

  /**
   * 获取多选元素的包围矩形
   */
  getMultiSelectionRect(elements: HTMLElement[]): DOMRect | null {
    return Geometry.getElementsBoundingRect(elements);
  }

  /**
   * 清除所有视觉反馈
   */
  clearAll(): void {
    this.clearHighlight();
    this.clearMultiHighlight();
    stateManager.clearFloatingPanel();
    stateManager.closeEditDialog();
  }
}

/**
 * 面板管理器类
 */
class PanelManagerClass {
  /**
   * 显示多选操作面板
   */
  showAreaSelectionPanel(
    elements: HTMLElement[],
    onCancel: () => void,
    onSubmit: () => void
  ): void {
    stateManager.clearFloatingPanel();

    const rect = Geometry.getElementsBoundingRect(elements);
    if (!rect) return;

    const hasPreciseSource = elements.some((el) => {
      const info = dom.getElementInfo(el);
      return info.sourceFile && info.sourceLine > 0;
    });

    const content = `
      <div style="padding: 16px 20px; border-bottom: 1px solid #E8E9EB;">
        <h4 style="margin: 0; font-size: 16px; font-weight: 600; color: #1F2329;">已圈选 ${elements.length} 个元素</h4>
        <p style="margin: 4px 0 0; font-size: 12px; color: #646A73;">
          ${hasPreciseSource ? '✅ 包含可定位源码的元素' : '⚠️ 部分元素可能无法精确定位'}
        </p>
      </div>
      <div style="padding: 12px 20px; max-height: 200px; overflow-y: auto;">
        ${elements
          .slice(0, 5)
          .map((el) => {
            const info = dom.getElementInfo(el);
            const sourceHint =
              info.sourceFile && info.sourceLine > 0
                ? `<span style="color: #00B42A;">📍</span>`
                : `<span style="color: #8F959E;">📄</span>`;
            const componentBadge = info.componentName
              ? `<span style="background: #3370FF20; color: #3370FF; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-left: 6px;">${info.componentName}</span>`
              : '';
            return `
              <div style="padding: 8px 0; border-bottom: 1px solid #F0F1F2; font-size: 12px;">
                <div style="display: flex; align-items: center; gap: 6px;">
                  ${sourceHint}
                  <span style="font-weight: 500;">${info.tag}</span>
                  ${info.id ? `<span style="color: #646A73;">#${info.id}</span>` : ''}
                  ${componentBadge}
                </div>
              </div>
            `;
          })
          .join('')}
        ${
          elements.length > 5
            ? `<div style="padding: 8px 0; text-align: center; color: #8F959E; font-size: 12px;">...还有 ${elements.length - 5} 个元素</div>`
            : ''
        }
      </div>
      <div style="padding: 12px 20px; border-top: 1px solid #E8E9EB; display: flex; gap: 8px;">
        <button id="omni-area-cancel" style="flex: 1; padding: 8px 12px; border: 1px solid #DEE0E3; background: #fff; color: #646A73; font-size: 13px; cursor: pointer; border-radius: 6px;">取消</button>
        <button id="omni-area-submit" style="flex: 1; padding: 8px 12px; border: none; background: #3370FF; color: #fff; font-size: 13px; cursor: pointer; border-radius: 6px; font-weight: 500;">批量修改</button>
      </div>
    `;

    const panel = ui.createFloatingPanel(rect, content);

    const cancelBtn = panel.querySelector<HTMLButtonElement>('#omni-area-cancel');
    const submitBtn = panel.querySelector<HTMLButtonElement>('#omni-area-submit');

    cancelBtn?.addEventListener('click', onCancel);
    submitBtn?.addEventListener('click', onSubmit);

    // 键盘快捷键
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onSubmit();
        document.removeEventListener('keydown', handleKeyDown);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
        document.removeEventListener('keydown', handleKeyDown);
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    // 面板关闭时清理事件监听
    const originalRemove = panel.remove.bind(panel);
    panel.remove = () => {
      document.removeEventListener('keydown', handleKeyDown);
      originalRemove();
    };

    document.body.appendChild(panel);
    appState.floatingPanel = panel;
  }
}

// 导出实例
export const visualFeedback = new VisualFeedbackClass();
export const panelManager = new PanelManagerClass();

// 导出便捷访问
export const VisualFeedback = visualFeedback;
export const PanelManager = panelManager;

// 滚动监听优化
let ticking = false;
function optimizedScrollHandler() {
  if (!ticking) {
    window.requestAnimationFrame(() => {
      if (appState.isSelectionMode) {
        visualFeedback.updateHighlightPositions();
      }
      ticking = false;
    });
    ticking = true;
  }
}

// 绑定滚动事件
window.addEventListener('scroll', optimizedScrollHandler, { passive: true });
window.addEventListener('resize', optimizedScrollHandler, { passive: true });
