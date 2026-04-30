/**
 * OmniFlowAI 浏览器注入脚本 - 核心工具模块
 * 包含 React DevTools 集成、DOM 工具函数、选择器工具
 */

(function () {
  'use strict';

  const CONFIG = window.OmniFlowAIConfig;

  // ============================================
  // React DevTools 集成 - 获取组件源码位置
  // ============================================
  const ReactSourceMapper = {
    isDevToolsAvailable() {
      return window.__REACT_DEVTOOLS_GLOBAL_HOOK__ ||
             document.querySelector('[data-reactroot]') ||
             !!document.querySelector('[data-react-checksum]');
    },

    getFiberNode(element) {
      const keys = Object.keys(element);
      const reactKey = keys.find(key =>
        key.startsWith('__reactFiber$') ||
        key.startsWith('__reactInternalInstance$') ||
        key.startsWith('_reactListening')
      );

      if (reactKey) {
        return element[reactKey];
      }
      return null;
    },

    getComponentNameFromFiber(fiber) {
      if (!fiber) return null;

      if (fiber.type && fiber.type.name) {
        return fiber.type.name;
      }

      if (fiber.type && fiber.type.displayName) {
        return fiber.type.displayName;
      }

      let current = fiber;
      while (current) {
        if (current.type) {
          if (current.type.name) return current.type.name;
          if (current.type.displayName) return current.type.displayName;
        }
        current = current.return || current._debugOwner;
      }

      return null;
    },

    getSourceLocationFromFiber(fiber) {
      if (!fiber) return null;

      if (fiber._debugSource) {
        return {
          fileName: fiber._debugSource.fileName,
          lineNumber: fiber._debugSource.lineNumber,
          columnNumber: fiber._debugSource.columnNumber,
        };
      }

      let current = fiber;
      while (current) {
        if (current._debugSource) {
          return {
            fileName: current._debugSource.fileName,
            lineNumber: current._debugSource.lineNumber,
            columnNumber: current._debugSource.columnNumber,
          };
        }
        current = current.return || current._debugOwner;
      }

      return null;
    },

    getComponentInfo(element) {
      const fiber = this.getFiberNode(element);

      if (!fiber) {
        return null;
      }

      const componentName = this.getComponentNameFromFiber(fiber);
      const sourceLocation = this.getSourceLocationFromFiber(fiber);

      return {
        componentName,
        sourceLocation,
        fiber: fiber,
      };
    },
  };

  // ============================================
  // DOM 工具函数
  // ============================================
  const DOM = {
    create: (tag, className, styles = {}) => {
      const el = document.createElement(tag);
      if (className) el.className = className;
      Object.assign(el.style, styles);
      return el;
    },

    getElementInfo: (el) => {
      const rect = el.getBoundingClientRect();

      let dataSource = el.getAttribute('data-source-id') ||
                       el.getAttribute('data-source') || '';
      let sourceElement = el;

      if (!dataSource) {
        const closestWithSource = el.closest('[data-source-id], [data-source]');
        if (closestWithSource) {
          dataSource = closestWithSource.getAttribute('data-source-id') ||
                       closestWithSource.getAttribute('data-source') || '';
          sourceElement = closestWithSource;
        }
      }

      const reactInfo = ReactSourceMapper.getComponentInfo(el) ||
                       ReactSourceMapper.getComponentInfo(sourceElement);

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

      const props = {};
      if (el.attributes) {
        for (let attr of el.attributes) {
          if (attr.name.startsWith('data-') ||
              ['class', 'id', 'style', 'src', 'href'].includes(attr.name)) {
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
        xpath: Utils.getXPath(el),
        selector: Utils.getUniqueSelector(el),
        props: props,
        componentName: componentName,
        sourceFile: finalSourceFile,
        sourceLine: finalSourceLine,
        sourceColumn: finalSourceColumn,
        dataSource: dataSource,
        dataComponent: el.getAttribute('data-component') || '',
        dataFile: el.getAttribute('data-file') || '',
        reactDebugInfo: reactInfo ? {
          hasFiber: !!reactInfo.fiber,
          componentName: reactInfo.componentName,
          sourceLocation: reactInfo.sourceLocation,
        } : null,
        rect: {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
        },
      };
    },

    getElementsInRect: (rect) => {
      const elements = [];
      const seen = new Set();

      const step = 20;
      for (let x = rect.left; x <= rect.right; x += step) {
        for (let y = rect.top; y <= rect.bottom; y += step) {
          const els = document.elementsFromPoint(x, y);
          els.forEach(el => {
            if (!Utils.isOmniElement(el) && !seen.has(el)) {
              seen.add(el);
              elements.push(el);
            }
          });
        }
      }

      return elements;
    },

    getSurroundingContext: (elementInfo) => {
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
    },
  };

  // ============================================
  // 工具函数
  // ============================================
  const Utils = {
    getXPath: (el) => {
      if (el.id) return `//*[@id="${el.id}"]`;
      const parts = [];
      while (el && el.nodeType === Node.ELEMENT_NODE) {
        let index = 1;
        let sibling = el.previousSibling;
        while (sibling) {
          if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName === el.tagName) {
            index++;
          }
          sibling = sibling.previousSibling;
        }
        const tagName = el.tagName.toLowerCase();
        const part = index > 1 ? `${tagName}[${index}]` : tagName;
        parts.unshift(part);
        el = el.parentNode;
      }
      return '/' + parts.join('/');
    },

    getUniqueSelector: (el) => {
      if (el.id) return `#${el.id}`;
      const path = [];
      while (el && el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.tagName.toLowerCase();
        if (el.className) {
          // 过滤并转义 class 名（CSS 选择器中的特殊字符需要转义）
          const classes = el.className.split(' ')
            .filter(c => c && !c.startsWith('omni-'))
            .slice(0, 3)
            .map(c => CSS.escape(c)); // 使用 CSS.escape 转义特殊字符
          if (classes.length) selector += '.' + classes.join('.');
        }
        path.unshift(selector);
        try {
          if (document.querySelectorAll(path.join(' > ')).length === 1) {
            return path.join(' > ');
          }
        } catch (e) {
          // 如果选择器无效，跳过当前层级继续向上
        }
        el = el.parentNode;
      }
      return path.join(' > ');
    },

    isOmniElement: (el) => {
      if (!el || !el.classList) return false;
      return el.classList.contains('omni-floating-icon') ||
             el.classList.contains('omni-exit-button') ||
             el.classList.contains('omni-highlight-box') ||
             el.classList.contains('omni-multi-highlight-box') ||
             el.classList.contains('omni-tooltip') ||
             el.classList.contains('omni-selection-box') ||
             el.classList.contains('omni-selection-rect') ||
             el.classList.contains('omni-floating-panel') ||
             el.classList.contains('omni-area-highlight') ||
             el.closest?.('.omni-edit-dialog') ||
             el.closest?.('.omni-progress-container') ||
             el.closest?.('.omni-completion-notification') ||
             el.closest?.('.omni-floating-panel') ||
             el.closest?.('.omni-exit-button');
    },

    escapeHtml: (html) => {
      const div = document.createElement('div');
      div.textContent = html;
      return div.innerHTML;
    },

    calculatePanelPosition: (referenceRect, panel) => {
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
    },
  };

  window.OmniFlowAICore = {
    ReactSourceMapper,
    DOM,
    Utils,
  };

})();
