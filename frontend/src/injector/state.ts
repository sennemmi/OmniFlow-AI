/**
 * OmniFlowAI Injector - 状态管理模块
 * 使用事件驱动的响应式状态管理
 */

import { bus } from './events';
import type { AppState } from './types';

/**
 * 全局状态对象
 */
const state: AppState = {
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

/**
 * 状态管理器
 */
class StateManager {
  /**
   * 获取当前状态
   */
  getState(): Readonly<AppState> {
    return Object.freeze({ ...state });
  }

  /**
   * 获取特定状态值
   */
  get<K extends keyof AppState>(key: K): AppState[K] {
    return state[key];
  }

  /**
   * 设置状态值
   */
  set<K extends keyof AppState>(key: K, value: AppState[K]): void {
    const oldValue = state[key];
    state[key] = value;

    // 触发状态变化事件
    bus.emit(`state:${key}:changed` as keyof import('./types').OmniEvents, {
      key,
      oldValue,
      newValue: value,
    } as never);
  }

  /**
   * 批量设置状态
   */
  setMultiple(updates: Partial<AppState>): void {
    Object.entries(updates).forEach(([key, value]) => {
      this.set(key as keyof AppState, value as AppState[keyof AppState]);
    });
  }

  /**
   * 重置选择状态
   */
  resetSelectionState(): void {
    state.selectedElement = null;
    state.selectedElements = [];
    state.hoverElement = null;

    bus.emit('element:deselect:all', undefined);
  }

  /**
   * 清除浮动面板
   */
  clearFloatingPanel(): void {
    if (state.floatingPanel) {
      state.floatingPanel.remove();
      state.floatingPanel = null;
    }
  }

  /**
   * 关闭编辑对话框
   */
  closeEditDialog(): void {
    if (state.editDialog) {
      state.editDialog.remove();
      state.editDialog = null;
    }
    bus.emit('ui:dialog:close', undefined);
  }

  /**
   * 进入选择模式
   */
  enterSelectionMode(): void {
    state.isSelectionMode = true;
    document.body.style.cursor = 'crosshair';
    bus.emit('mode:selection:enter', undefined);
  }

  /**
   * 退出选择模式
   */
  exitSelectionMode(): void {
    state.isSelectionMode = false;
    document.body.style.cursor = '';
    this.resetSelectionState();
    this.clearFloatingPanel();
    this.closeEditDialog();
    bus.emit('mode:selection:exit', undefined);
  }

  /**
   * 切换选择模式
   */
  toggleSelectionMode(): void {
    if (state.isSelectionMode) {
      this.exitSelectionMode();
    } else {
      this.enterSelectionMode();
    }
  }

  /**
   * 选择单个元素
   */
  selectSingle(element: HTMLElement): void {
    state.selectedElement = element;
    state.selectedElements = [];
  }

  /**
   * 切换多选元素
   */
  toggleMultiSelect(element: HTMLElement): void {
    const index = state.selectedElements.indexOf(element);
    if (index > -1) {
      state.selectedElements.splice(index, 1);
    } else {
      state.selectedElements.push(element);
    }
  }

  /**
   * 清除所有状态
   */
  clearAll(): void {
    this.exitSelectionMode();
    state.isActive = false;
    state.currentPipelineId = null;
    state.isPolling = false;
  }
}

// 导出单例
export const stateManager = new StateManager();
export const appState = state;

// 导出便捷访问
export const getState = () => stateManager.getState();
export const get = <K extends keyof AppState>(key: K) => stateManager.get(key);

// 兼容旧命名
export { stateManager as StateManager, state };
export default stateManager;
