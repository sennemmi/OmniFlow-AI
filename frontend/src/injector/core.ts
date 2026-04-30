/**
 * OmniFlowAI Injector - 核心工具模块
 * 包含 React DevTools 集成、DOM 工具函数、选择器工具
 */

import type {
  ElementInfo,
  ReactDebugInfo,
  IDOMUtils,
  IUtils,
  IReactSourceMapper,
} from './types';

// ============================================
// React DevTools 集成
// ============================================
class ReactSourceMapperClass implements IReactSourceMapper {
  /**
   * 检查 React DevTools 是否可用
   */
  isDevToolsAvailable(): boolean {
    return !!(
      (window as Window & { __REACT_DEVTOOLS_GLOBAL_HOOK__?: unknown }).__REACT_DEVTOOLS_GLOBAL_HOOK__ ||
      document.querySelector('[data-reactroot]') ||
      document.querySelector('[data-react-checksum]')
    );
  }

  /**
   * 获取元素的 Fiber 节点
   */
  getFiberNode(element: HTMLElement): unknown | null {
    const keys = Object.keys(element);
    const reactKey = keys.find(
      (key) =>
        key.startsWith('__reactFiber$') ||
        key.startsWith('__reactInternalInstance$') ||
        key.startsWith('_reactListening')
    );

    if (reactKey) {
      return (element as HTMLElement & Record<string, unknown>)[reactKey];
    }
    return null;
  }

  /**
   * 从 Fiber 节点获取组件名称
   */
  getComponentNameFromFiber(fiber: unknown): string | null {
    if (!fiber) return null;

    const f = fiber as Record<string, unknown>;

    if (f.type && typeof f.type === 'object') {
      const type = f.type as { name?: string; displayName?: string };
      if (type.name) return type.name;
      if (type.displayName) return type.displayName;
    }

    let current: unknown = fiber;
    while (current) {
      const c = current as Record<string, unknown>;
      if (c.type && typeof c.type === 'object') {
        const type = c.type as { name?: string; displayName?: string };
        if (type.name) return type.name;
        if (type.displayName) return type.displayName;
      }
      current = c.return || c._debugOwner;
    }

    return null;
  }

  /**
   * 从 Fiber 节点获取源码位置
   */
  getSourceLocationFromFiber(fiber: unknown): { fileName: string; lineNumber: number; columnNumber: number } | null {
    if (!fiber) return null;

    const f = fiber as Record<string, unknown>;

    if (f._debugSource && typeof f._debugSource === 'object') {
      const source = f._debugSource as { fileName?: string; lineNumber?: number; columnNumber?: number };
      return {
        fileName: source.fileName || '',
        lineNumber: source.lineNumber || 0,
        columnNumber: source.columnNumber || 0,
      };
    }

    let current: unknown = fiber;
    while (current) {
      const c = current as Record<string, unknown>;
      if (c._debugSource && typeof c._debugSource === 'object') {
        const source = c._debugSource as { fileName?: string; lineNumber?: number; columnNumber?: number };
        return {
          fileName: source.fileName || '',
          lineNumber: source.lineNumber || 0,
          columnNumber: source.columnNumber || 0,
        };
      }
      current = c.return || c._debugOwner;
    }

    return null;
  }

  /**
   * 获取组件信息
   */
  getComponentInfo(element: HTMLElement): ReactDebugInfo | null {
    const fiber = this.getFiberNode(element);

    if (!fiber) {
      return null;
    }

    const componentName = this.getComponentNameFromFiber(fiber);
    const sourceLocation = this.getSourceLocationFromFiber(fiber);

    return {
      componentName: componentName || '',
      sourceLocation,
      hasFiber: true,
    };
  }
}

// ============================================
// DOM 工具函数
// ============================================
class DOMClass implements IDOMUtils {
  /**
   * 创建 DOM 元素
   */
  create(
    tag: string,
    className?: string,
    styles: Partial<CSSStyleDeclaration> = {}
  ): HTMLElement {
    const el = document.createElement(tag);
    if (className) el.className = className;
    Object.assign(el.style, styles);
    return el;
  }

  /**
   * 获取元素信息
   */
  getElementInfo(el: HTMLElement): ElementInfo {
    const rect = el.getBoundingClientRect();

    let dataSource =
      el.getAttribute('data-source-id') || el.getAttribute('data-source') || '';
    let sourceElement: HTMLElement = el;

    if (!dataSource) {
      const closestWithSource = el.closest<HTMLElement>('[data-source-id], [data-source]');
      if (closestWithSource) {
        dataSource =
          closestWithSource.getAttribute('data-source-id') ||
          closestWithSource.getAttribute('data-source') ||
          '';
        sourceElement = closestWithSource;
      }
    }

    const reactInfo = reactSourceMapper.getComponentInfo(el) ||
                     reactSourceMapper.getComponentInfo(sourceElement);

    let sourceFile = '';
    let sourceLine = 0;
    let sourceColumn = 0;

    if (dataSource) {
      const parts = dataSource.split(':');
      if (parts.length >= 2) {
        if (parts[0].length === 1 && parts[1].startsWith('\\')) {
          sourceFile = parts[0] + ':' + parts[1];
          sourceLine = parseInt(parts[2]) || 0;
          sourceColumn = parseInt(parts[3]) || 0;
        } else {
          sourceFile = parts[0];
          sourceLine = parseInt(parts[1]) || 0;
          sourceColumn = parseInt(parts[2]) || 0;
        }
      }
    }

    let finalSourceFile = sourceFile;
    let finalSourceLine = sourceLine;
    let finalSourceColumn = sourceColumn;
    let componentName = '';

    if (reactInfo) {
      if (reactInfo.componentName) {
        componentName = reactInfo.componentName;
      }
      if (reactInfo.sourceLocation) {
        finalSourceFile = reactInfo.sourceLocation.fileName || sourceFile;
        finalSourceLine = reactInfo.sourceLocation.lineNumber || sourceLine;
        finalSourceColumn = reactInfo.sourceLocation.columnNumber || sourceColumn;
      }
    }

    const props: Record<string, string> = {};
    if (el.attributes) {
      for (const attr of el.attributes) {
        if (
          attr.name.startsWith('data-') ||
          ['class', 'id', 'style', 'src', 'href'].includes(attr.name)
        ) {
          props[attr.name] = attr.value;
        }
      }
    }

    return {
      tag: el.tagName.toLowerCase(),
      id: el.id,
      class: el.className,
      text: el.textContent?.slice(0, 200) || '',
      outerHTML: el.outerHTML?.slice(0, 2000) || '',
      xpath: utils.getXPath(el),
      selector: utils.getUniqueSelector(el),
      props,
      componentName,
      sourceFile: finalSourceFile,
      sourceLine: finalSourceLine,
      sourceColumn: finalSourceColumn,
      dataSource,
      dataComponent: el.getAttribute('data-component') || '',
      dataFile: el.getAttribute('data-file') || '',
      reactDebugInfo: reactInfo
        ? {
            hasFiber: reactInfo.hasFiber,
            componentName: reactInfo.componentName,
            sourceLocation: reactInfo.sourceLocation,
          }
        : null,
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
    };
  }

  /**
   * 获取矩形区域内的所有元素
   */
  getElementsInRect(rect: DOMRect): HTMLElement[] {
    const elements: HTMLElement[] = [];
    const seen = new Set<HTMLElement>();

    const step = 20;
    for (let x = rect.left; x <= rect.right; x += step) {
      for (let y = rect.top; y <= rect.bottom; y += step) {
        const els = document.elementsFromPoint(x, y);
        els.forEach((el) => {
          if (el instanceof HTMLElement && !utils.isOmniElement(el) && !seen.has(el)) {
            seen.add(el);
            elements.push(el);
          }
        });
      }
    }

    return elements;
  }

  /**
   * 获取元素周围上下文
   */
  getSurroundingContext(elementInfo: ElementInfo): Record<string, unknown> {
    return {
      file: elementInfo.sourceFile,
      line: elementInfo.sourceLine,
      column: elementInfo.sourceColumn,
      component: elementInfo.componentName,
      selected_html: elementInfo.outerHTML.slice(0, 500),
      element_type: elementInfo.tag,
      element_id: elementInfo.id,
      element_class: elementInfo.class,
      has_precise_source: !!(elementInfo.sourceFile && elementInfo.sourceLine > 0),
    };
  }
}

// ============================================
// 通用工具函数
// ============================================
class UtilsClass implements IUtils {
  /**
   * 获取元素的 XPath
   */
  getXPath(el: HTMLElement): string {
    if (el.id) return `//*[@id="${el.id}"]`;
    const parts: string[] = [];
    let current: HTMLElement | null = el;

    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let index = 1;
      let sibling: ChildNode | null = current.previousSibling;
      while (sibling) {
        if (
          sibling.nodeType === Node.ELEMENT_NODE &&
          (sibling as HTMLElement).tagName === current.tagName
        ) {
          index++;
        }
        sibling = sibling.previousSibling;
      }
      const tagName = current.tagName.toLowerCase();
      const part = index > 1 ? `${tagName}[${index}]` : tagName;
      parts.unshift(part);
      current = current.parentNode as HTMLElement | null;
    }

    return '/' + parts.join('/');
  }

  /**
   * 获取元素的唯一选择器
   */
  getUniqueSelector(el: HTMLElement): string {
    if (el.id) return `#${el.id}`;
    const path: string[] = [];
    let current: HTMLElement | null = el;

    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let selector = current.tagName.toLowerCase();
      if (current.className) {
        const classes = current.className
          .split(' ')
          .filter((c) => c && !c.startsWith('omni-'))
          .slice(0, 3)
          .map((c) => CSS.escape(c));
        if (classes.length) selector += '.' + classes.join('.');
      }
      path.unshift(selector);
      try {
        if (document.querySelectorAll(path.join(' > ')).length === 1) {
          return path.join(' > ');
        }
      } catch {
        // 如果选择器无效，跳过当前层级继续向上
      }
      current = current.parentNode as HTMLElement | null;
    }

    return path.join(' > ');
  }

  /**
   * 检查元素是否是 Omni 内部元素
   */
  isOmniElement(el: HTMLElement | EventTarget | null): boolean {
    if (!el || !(el instanceof HTMLElement) || !el.classList) return false;

    const omniClasses = [
      'omni-floating-icon',
      'omni-exit-button',
      'omni-highlight-box',
      'omni-multi-highlight-box',
      'omni-tooltip',
      'omni-selection-box',
      'omni-selection-rect',
      'omni-floating-panel',
      'omni-area-highlight',
    ];

    if (omniClasses.some((cls) => el.classList.contains(cls))) {
      return true;
    }

    const omniParents = [
      '.omni-edit-dialog',
      '.omni-progress-container',
      '.omni-completion-notification',
      '.omni-floating-panel',
      '.omni-exit-button',
    ];

    return omniParents.some((selector) => !!el.closest(selector));
  }

  /**
   * 转义 HTML 特殊字符
   */
  escapeHtml(html: string): string {
    const div = document.createElement('div');
    div.textContent = html;
    return div.innerHTML;
  }

  /**
   * 计算面板位置
   */
  calculatePanelPosition(
    referenceRect: DOMRect,
    _panel: HTMLElement
  ): { x: number; y: number } {
    const padding = 8;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let x = referenceRect.left;
    let y = referenceRect.bottom + padding;

    const panelWidth = 320;
    const panelHeight = 200;

    if (x + panelWidth > viewportWidth - padding) {
      x = referenceRect.right - panelWidth;
    }

    if (x < padding) {
      x = padding;
    }

    if (y + panelHeight > viewportHeight - padding) {
      y = referenceRect.top - panelHeight - padding;
    }

    if (y < padding) {
      y = referenceRect.bottom + padding;
    }

    return { x, y };
  }
}

// 导出单例实例
export const reactSourceMapper = new ReactSourceMapperClass();
export const dom = new DOMClass();
export const utils = new UtilsClass();

// 兼容旧命名
export const DOM = dom;
export const Utils = utils;
export const ReactSourceMapper = reactSourceMapper;
