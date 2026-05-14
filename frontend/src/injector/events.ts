/**
 * OmniFlowAI Injector - 类型安全的事件总线
 * 使用 mitt 风格的轻量级实现，支持 TypeScript 类型检查
 */

import type { OmniEvents, EventHandler } from './types';

/**
 * 类型安全的事件总线实现
 */
class EventBus {
  private handlers = new Map<keyof OmniEvents, EventHandler[]>();

  /**
   * 监听事件
   * @param event - 事件名称
   * @param handler - 事件处理器
   */
  on<K extends keyof OmniEvents>(
    event: K,
    handler: EventHandler<OmniEvents[K]>
  ): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, []);
    }
    this.handlers.get(event)!.push(handler as EventHandler);

    // 返回取消订阅函数
    return () => this.off(event, handler);
  }

  /**
   * 监听一次性事件
   * @param event - 事件名称
   * @param handler - 事件处理器
   */
  once<K extends keyof OmniEvents>(
    event: K,
    handler: EventHandler<OmniEvents[K]>
  ): void {
    const onceHandler = (data: OmniEvents[K]) => {
      this.off(event, onceHandler as EventHandler<OmniEvents[K]>);
      handler(data);
    };
    this.on(event, onceHandler as EventHandler<OmniEvents[K]>);
  }

  /**
   * 取消监听事件
   * @param event - 事件名称
   * @param handler - 要移除的事件处理器
   */
  off<K extends keyof OmniEvents>(
    event: K,
    handler: EventHandler<OmniEvents[K]>
  ): void {
    const handlers = this.handlers.get(event);
    if (handlers) {
      const index = handlers.indexOf(handler as EventHandler);
      if (index > -1) {
        handlers.splice(index, 1);
      }
    }
  }

  /**
   * 触发事件
   * @param event - 事件名称
   * @param data - 事件数据
   */
  emit<K extends keyof OmniEvents>(event: K, data: OmniEvents[K]): void {
    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(data);
        } catch (error) {
          console.error(`[EventBus] 事件处理器执行失败 (${String(event)}):`, error);
        }
      });
    }
  }

  /**
   * 获取事件监听器数量
   * @param event - 事件名称
   */
  listenerCount<K extends keyof OmniEvents>(event: K): number {
    return this.handlers.get(event)?.length || 0;
  }

  /**
   * 清除所有事件监听器
   */
  clear(): void {
    this.handlers.clear();
  }

  /**
   * 清除特定事件的所有监听器
   * @param event - 事件名称
   */
  clearEvent<K extends keyof OmniEvents>(event: K): void {
    this.handlers.delete(event);
  }
}

// 导出单例实例
export const bus = new EventBus();

// 导出便捷函数
export const on = bus.on.bind(bus);
export const once = bus.once.bind(bus);
export const off = bus.off.bind(bus);
export const emit = bus.emit.bind(bus);

// 导出事件名称枚举（避免魔术字符串）
export const Events = {
  // 模式切换
  MODE_SELECTION_TOGGLE: 'mode:selection:toggle' as const,
  MODE_SELECTION_ENTER: 'mode:selection:enter' as const,
  MODE_SELECTION_EXIT: 'mode:selection:exit' as const,

  // 元素交互
  ELEMENT_HOVER: 'element:hover' as const,
  ELEMENT_CLICK: 'element:click' as const,
  ELEMENT_SELECT_SINGLE: 'element:select:single' as const,
  ELEMENT_SELECT_MULTI: 'element:select:multi' as const,
  ELEMENT_DESELECT_ALL: 'element:deselect:all' as const,

  // 业务动作
  ACTION_MODIFY_SUBMIT: 'action:modify:submit' as const,
  ACTION_AREA_MODIFY_SUBMIT: 'action:area-modify:submit' as const,
  ACTION_PREVIEW_START: 'action:preview:start' as const,
  ACTION_PREVIEW_CONFIRM: 'action:preview:confirm' as const,
  ACTION_PREVIEW_CANCEL: 'action:preview:cancel' as const,

  // Pipeline
  PIPELINE_CREATED: 'pipeline:created' as const,
  PIPELINE_PROGRESS: 'pipeline:progress' as const,
  PIPELINE_COMPLETED: 'pipeline:completed' as const,
  PIPELINE_ERROR: 'pipeline:error' as const,

  // UI 状态
  UI_TOAST: 'ui:toast' as const,
  UI_PROGRESS_SHOW: 'ui:progress:show' as const,
  UI_PROGRESS_UPDATE: 'ui:progress:update' as const,
  UI_PROGRESS_HIDE: 'ui:progress:hide' as const,
  UI_DIALOG_SHOW: 'ui:dialog:show' as const,
  UI_DIALOG_CLOSE: 'ui:dialog:close' as const,
  UI_PANEL_SHOW: 'ui:panel:show' as const,
  UI_PANEL_CLOSE: 'ui:panel:close' as const,
  UI_NOTIFICATION_SHOW: 'ui:notification:show' as const,
  UI_PREVIEW_CONTROLS_SHOW: 'ui:preview-controls:show' as const,
  UI_PREVIEW_CONTROLS_HIDE: 'ui:preview-controls:hide' as const,

  // 系统
  SYSTEM_INIT: 'system:init' as const,
  SYSTEM_ERROR: 'system:error' as const,
};

export default bus;
