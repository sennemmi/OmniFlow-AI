/**
 * OmniFlowAI Injector - 交互处理模块
 * 处理用户交互事件，通过事件总线解耦
 */

import { dom, utils } from './core';
import { bus } from './events';
import { appState, stateManager } from './state';
import { ui } from './ui';
import { visualFeedback, panelManager } from './selection';

/**
 * 交互处理器
 * 只负责监听原生事件并转换为内部事件，不处理业务逻辑
 */
class InteractionHandler {
  private isBound = false;

  /**
   * 初始化交互模块
   */
  init(): void {
    this.bindInternalEvents();
  }

  /**
   * 绑定内部事件监听
   */
  private bindInternalEvents(): void {
    // 监听模式切换事件来绑定/解绑原生事件
    bus.on('mode:selection:enter', () => {
      this.bindNativeEvents();
    });

    bus.on('mode:selection:exit', () => {
      this.unbindNativeEvents();
    });

    // 监听元素选择事件
    bus.on('element:click', ({ element, isShift }) => {
      this.handleElementClick(element, isShift);
    });

    bus.on('element:deselect:all', () => {
      this.deselectAll();
    });
  }

  /**
   * 绑定原生 DOM 事件
   */
  private bindNativeEvents(): void {
    if (this.isBound) return;

    // 禁用页面原有选择功能
    this.disableNativeSelection();

    // 点击拦截（capture 阶段）
    document.addEventListener('click', this.handleInspectClick, true);

    // 阻止拖拽选择
    document.addEventListener('mousedown', this.handleMouseDown, true);

    // 阻止文本选择
    document.addEventListener('selectstart', this.handleSelectStart, true);

    // 悬停效果
    document.addEventListener('mouseover', this.handleMouseOver, true);
    document.addEventListener('mouseout', this.handleMouseOut, true);

    // 键盘事件
    document.addEventListener('keydown', this.handleKeyDown);

    // 右键菜单
    document.addEventListener('contextmenu', this.handleContextMenu, true);

    this.isBound = true;
  }

  /**
   * 解绑原生 DOM 事件
   */
  private unbindNativeEvents(): void {
    if (!this.isBound) return;

    // 恢复页面原有选择功能
    this.enableNativeSelection();

    document.removeEventListener('click', this.handleInspectClick, true);
    document.removeEventListener('mousedown', this.handleMouseDown, true);
    document.removeEventListener('selectstart', this.handleSelectStart, true);
    document.removeEventListener('mouseover', this.handleMouseOver, true);
    document.removeEventListener('mouseout', this.handleMouseOut, true);
    document.removeEventListener('keydown', this.handleKeyDown);
    document.removeEventListener('contextmenu', this.handleContextMenu, true);

    this.isBound = false;
  }

  /**
   * 禁用页面原有的选择功能
   */
  private disableNativeSelection(): void {
    document.body.style.userSelect = 'none';
    document.body.style.webkitUserSelect = 'none';

    const selectableElements = document.querySelectorAll(
      '[data-selectable], [data-multi-select], .selectable, [role="checkbox"], input[type="checkbox"]'
    );
    selectableElements.forEach((el) => {
      (el as HTMLElement).dataset.omniNativeDisabled = 'true';
      (el as HTMLElement).style.pointerEvents = 'none';
    });
  }

  /**
   * 恢复页面原有的选择功能
   */
  private enableNativeSelection(): void {
    document.body.style.userSelect = '';
    document.body.style.webkitUserSelect = '';

    const disabledElements = document.querySelectorAll('[data-omni-native-disabled]');
    disabledElements.forEach((el) => {
      (el as HTMLElement).style.pointerEvents = '';
      delete (el as HTMLElement).dataset.omniNativeDisabled;
    });
  }

  /**
   * 点击拦截处理器
   */
  private handleInspectClick = (e: MouseEvent): void => {
    if (!appState.isSelectionMode) return;
    if (appState.editDialog) return;

    const el = e.target as HTMLElement;
    if (utils.isOmniElement(el)) return;

    // 阻止原始点击事件
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    // 发出元素点击事件，不直接处理业务逻辑
    bus.emit('element:click', {
      element: el,
      isShift: e.shiftKey,
    });
  };

  /**
   * 处理元素点击（内部事件处理器）
   */
  private handleElementClick(element: HTMLElement, isShift: boolean): void {
    if (isShift) {
      this.toggleElementSelection(element);
    } else {
      this.selectSingleElement(element);
    }
  }

  /**
   * 选中单个元素
   */
  private selectSingleElement(el: HTMLElement): void {
    // 如果点击的是已选中元素，则取消选中
    if (appState.selectedElement === el && appState.selectedElements.length === 0) {
      this.deselectAll();
      ui.createToast('已取消选中', 'info');
      return;
    }

    // 清除之前的选择
    this.deselectAll();

    // 设置新选择
    stateManager.selectSingle(el);
    visualFeedback.highlightElement(el);

    // 获取元素信息并显示编辑对话框
    const elementInfo = dom.getElementInfo(el);
    bus.emit('ui:dialog:show', { element: el, elementInfo, isMulti: false });
  }

  /**
   * Shift 多选 - 切换元素选择状态
   */
  private toggleElementSelection(el: HTMLElement): void {
    // 如果当前有单选，先转为多选模式
    if (appState.selectedElement) {
      const singleEl = appState.selectedElement;
      this.deselectAll();
      appState.selectedElements = [singleEl];
      visualFeedback.updateMultiSelection(appState.selectedElements);
    }

    const index = appState.selectedElements.indexOf(el);

    if (index > -1) {
      // 已选中，移除
      appState.selectedElements.splice(index, 1);
      ui.createToast(`已移除，当前选中 ${appState.selectedElements.length} 个元素`, 'info');
    } else {
      // 未选中，添加
      appState.selectedElements.push(el);
      ui.createToast(`已添加，当前选中 ${appState.selectedElements.length} 个元素`, 'info');
    }

    // 更新视觉反馈
    visualFeedback.updateMultiSelection(appState.selectedElements);

    // 如果有多选元素，显示批量操作面板
    if (appState.selectedElements.length > 0) {
      this.showMultiSelectionPanel();
    } else {
      stateManager.clearFloatingPanel();
    }
  }

  /**
   * 显示多选操作面板
   */
  private showMultiSelectionPanel(): void {
    panelManager.showAreaSelectionPanel(
      appState.selectedElements,
      // 取消
      () => {
        this.deselectAll();
        ui.createToast('已取消选择', 'info');
      },
      // 提交
      () => {
        const firstElement = appState.selectedElements[0];
        const elementInfo = dom.getElementInfo(firstElement);
        bus.emit('ui:dialog:show', {
          element: firstElement,
          elementInfo,
          isMulti: true,
        });
        stateManager.clearFloatingPanel();
      }
    );
  }

  /**
   * 取消所有选择
   */
  private deselectAll(): void {
    stateManager.resetSelectionState();
    visualFeedback.clearAll();
  }

  /**
   * 鼠标悬停处理器
   */
  private handleMouseOver = (e: MouseEvent): void => {
    if (!appState.isSelectionMode) return;
    if (appState.editDialog) return;
    if (appState.selectedElement) return;

    const el = e.target as HTMLElement;
    if (utils.isOmniElement(el)) return;

    appState.hoverElement = el;
    visualFeedback.highlightElement(el);
  };

  /**
   * 鼠标移出处理器
   */
  private handleMouseOut = (): void => {
    if (!appState.isSelectionMode) return;
    if (appState.editDialog) return;
    if (appState.selectedElement) return;

    visualFeedback.clearHighlight();
    appState.hoverElement = null;
  };

  /**
   * 鼠标按下处理器
   */
  private handleMouseDown = (e: MouseEvent): void => {
    if (!appState.isSelectionMode) return;

    const el = e.target as HTMLElement;
    if (utils.isOmniElement(el)) return;

    e.preventDefault();
    e.stopPropagation();
  };

  /**
   * 选择开始处理器
   */
  private handleSelectStart = (e: Event): void => {
    if (!appState.isSelectionMode) return;

    const el = e.target as HTMLElement;
    if (utils.isOmniElement(el)) return;

    e.preventDefault();
  };

  /**
   * 键盘事件处理器
   */
  private handleKeyDown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') {
      if (appState.editDialog) {
        this.deselectAll();
      } else if (appState.selectedElements.length > 0 || appState.selectedElement) {
        this.deselectAll();
        ui.createToast('已取消选择', 'info');
      } else {
        stateManager.exitSelectionMode();
        ui.createToast('已退出圈选模式', 'info');
      }
    }
  };

  /**
   * 右键菜单处理器
   */
  private handleContextMenu = (event: MouseEvent): void => {
    if (!appState.isSelectionMode) return;

    event.preventDefault();

    if (appState.editDialog || appState.selectedElement || appState.selectedElements.length > 0) {
      this.deselectAll();
      ui.createToast('已取消选择', 'info');
    } else {
      stateManager.exitSelectionMode();
      ui.createToast('已退出圈选模式', 'info');
    }
  };
}

// 导出单例
export const interaction = new InteractionHandler();
export const InteractionModule = interaction;

export default interaction;
