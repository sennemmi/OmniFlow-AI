/**
 * OmniFlowAI 浏览器注入脚本 - 所见即所得闭环版本
 * 实现页面元素圈选、修改需求收集、Pipeline 创建和状态监听
 */

(function () {
  'use strict';

  // ============================================
  // 配置
  // ============================================
  // 动态获取 API 基础地址：优先使用父窗口配置，降级到当前 origin
  const getApiBaseUrl = () => {
    // 尝试从父窗口获取配置（iframe 场景）
    if (window.parent !== window && window.parent.__OMNIFLOW_API_URL__) {
      return window.parent.__OMNIFLOW_API_URL__;
    }
    // 从当前脚本标签的 data-api-url 属性获取
    const currentScript = document.currentScript;
    if (currentScript && currentScript.dataset.apiUrl) {
      return currentScript.dataset.apiUrl;
    }
    // 降级：使用当前页面的 origin（适用于同域或通过代理访问）
    return window.location.origin;
  };

  const CONFIG = {
    API_BASE_URL: getApiBaseUrl(),
    API_ENDPOINT: '/api/v1/pipeline/create',
    POLL_INTERVAL: 3000,
    ICON_SIZE: 48,
    Z_INDEX: 999999,
    COLORS: {
      primary: '#3370FF',
      highlight: 'rgba(51, 112, 255, 0.3)',
      border: '#3370FF',
      overlay: 'rgba(0, 0, 0, 0.5)',
      success: '#00B42A',
      warning: '#FF7D00',
      error: '#F53F3F',
    },
  };

  // ============================================
  // 状态管理
  // ============================================
  const state = {
    isActive: false,
    isSelectionMode: false,
    selectedElement: null,
    hoverElement: null,
    currentPipelineId: null,
    isPolling: false,
    originalStyles: new Map(),
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

      // 获取源码位置信息（支持多种属性名）
      // vite-plugin-component-debugger 使用 data-source-id
      // 格式: filepath:line:column
      let dataSource = el.getAttribute('data-source-id') ||
                       el.getAttribute('data-source') || '';
      let sourceElement = el;

      // 如果当前元素没有源码信息，尝试向上查找
      if (!dataSource) {
        const closestWithSource = el.closest('[data-source-id], [data-source]');
        if (closestWithSource) {
          dataSource = closestWithSource.getAttribute('data-source-id') ||
                       closestWithSource.getAttribute('data-source') || '';
          sourceElement = closestWithSource;
        }
      }

      // 解析源码位置信息：格式为 "filepath:line:column"
      let sourceFile = '';
      let sourceLine = 0;
      let sourceColumn = 0;

      if (dataSource) {
        const parts = dataSource.split(':');
        if (parts.length >= 2) {
          // 处理 Windows 路径（如 D:\project\file.tsx:10:5）
          if (parts[0].length === 1 && parts[1].startsWith('\\')) {
            // Windows 绝对路径：D:\path\to\file.tsx:10:5
            sourceFile = parts[0] + ':' + parts[1];
            sourceLine = parseInt(parts[2]) || 0;
            sourceColumn = parseInt(parts[3]) || 0;
          } else {
            // Unix 路径或相对路径：src/file.tsx:10:5
            sourceFile = parts[0];
            sourceLine = parseInt(parts[1]) || 0;
            sourceColumn = parseInt(parts[2]) || 0;
          }
        }
      }

      return {
        tag: el.tagName.toLowerCase(),
        id: el.id,
        class: el.className,
        text: el.textContent?.slice(0, 200) || '',
        outerHTML: el.outerHTML?.slice(0, 2000) || '',
        xpath: getXPath(el),
        selector: getUniqueSelector(el),
        dataSource: dataSource,
        dataComponent: el.getAttribute('data-component') || '',
        dataFile: el.getAttribute('data-file') || '',
        // 新增：精确的源码位置信息
        sourceFile: sourceFile,
        sourceLine: sourceLine,
        sourceColumn: sourceColumn,
        rect: {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
        },
      };
    },
  };

  // 获取 XPath
  function getXPath(el) {
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
  }

  // 获取唯一选择器
  function getUniqueSelector(el) {
    if (el.id) return `#${el.id}`;
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
      let selector = el.tagName.toLowerCase();
      if (el.className) {
        const classes = el.className.split(' ').filter(c => c && !c.startsWith('omni-')).slice(0, 3);
        if (classes.length) selector += '.' + classes.join('.');
      }
      path.unshift(selector);
      if (document.querySelectorAll(path.join(' > ')).length === 1) {
        return path.join(' > ');
      }
      el = el.parentNode;
    }
    return path.join(' > ');
  }

  // ============================================
  // API 调用
  // ============================================
  const API = {
    // 创建 Pipeline
    async createPipeline(data) {
      const response = await fetch(`${CONFIG.API_BASE_URL}${CONFIG.API_ENDPOINT}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        throw new Error(`API 错误: ${response.status}`);
      }

      return response.json();
    },

    // 获取 Pipeline 状态
    async getPipelineStatus(pipelineId) {
      const response = await fetch(`${CONFIG.API_BASE_URL}/api/v1/pipeline/${pipelineId}/status`);
      if (!response.ok) {
        throw new Error(`获取状态失败: ${response.status}`);
      }
      return response.json();
    },
  };

  // ============================================
  // UI 组件
  // ============================================
  const UI = {
    // 悬浮图标
    createFloatingIcon() {
      const icon = DOM.create('div', 'omni-floating-icon', {
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        width: `${CONFIG.ICON_SIZE}px`,
        height: `${CONFIG.ICON_SIZE}px`,
        borderRadius: '50%',
        background: `linear-gradient(135deg, ${CONFIG.COLORS.primary}, #2860EE)`,
        boxShadow: '0 4px 16px rgba(51, 112, 255, 0.4)',
        cursor: 'pointer',
        zIndex: CONFIG.Z_INDEX,
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
        toggleSelectionMode();
      });

      return icon;
    },

    // 高亮框
    createHighlightBox(rect) {
      const box = DOM.create('div', 'omni-highlight-box', {
        position: 'fixed',
        left: `${rect.left + window.scrollX}px`,
        top: `${rect.top + window.scrollY}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        border: `2px solid ${CONFIG.COLORS.border}`,
        background: CONFIG.COLORS.highlight,
        borderRadius: '4px',
        pointerEvents: 'none',
        zIndex: CONFIG.Z_INDEX - 1,
        transition: 'all 0.1s ease-out',
      });
      return box;
    },

    // 信息提示框
    createTooltip(el) {
      const info = DOM.getElementInfo(el);
      const tooltip = DOM.create('div', 'omni-tooltip', {
        position: 'fixed',
        bottom: '80px',
        right: '24px',
        padding: '12px 16px',
        background: 'rgba(26, 28, 33, 0.95)',
        borderRadius: '8px',
        color: '#fff',
        fontSize: '12px',
        fontFamily: 'monospace',
        maxWidth: '320px',
        zIndex: CONFIG.Z_INDEX,
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      });

      // 判断是否成功获取到精确的源码位置
      const hasPreciseSource = info.sourceFile && info.sourceLine > 0;
      const hasLegacySource = info.dataSource || info.dataFile;

      let sourceInfoHtml = '';
      let sourceStatusHtml = '';

      if (hasPreciseSource) {
        // 显示精确的源码位置
        const displayPath = info.sourceFile.includes('src/')
          ? info.sourceFile.substring(info.sourceFile.indexOf('src/'))
          : info.sourceFile;
        sourceInfoHtml = `<div style="color: #00B42A; font-size: 11px;">📍 ${displayPath}:${info.sourceLine}</div>`;
        sourceStatusHtml = '<div style="color: #00B42A; font-size: 11px; margin-top: 4px;">✅ 已精确定位源码</div>';
      } else if (hasLegacySource) {
        // 显示旧的 source 信息
        sourceInfoHtml = `<div style="color: #FF7D00; font-size: 11px;">📄 ${info.dataSource || info.dataFile}</div>`;
        sourceStatusHtml = '<div style="color: #FF7D00; font-size: 11px; margin-top: 4px;">⚠️ 未精确定位（生产构建模式）</div>';
      } else {
        // 生产构建无源码信息时的提示
        sourceStatusHtml = `
          <div style="color: #646A73; font-size: 11px; margin-top: 4px;">
            ❓ 无源码信息（生产构建）<br/>
            <span style="font-size: 10px;">提示：在开发模式下使用可精确定位</span>
          </div>
        `;
      }

      tooltip.innerHTML = `
        <div style="margin-bottom: 4px; color: #3370FF; font-weight: bold;">${info.tag}${info.id ? `#${info.id}` : ''}</div>
        <div style="color: #8F959E; margin-bottom: 4px;">${info.class.slice(0, 50)}${info.class.length > 50 ? '...' : ''}</div>
        ${sourceInfoHtml}
        ${sourceStatusHtml}
      `;

      return tooltip;
    },

    // 修改对话框
    createEditDialog(elementInfo) {
      const overlay = DOM.create('div', 'omni-edit-overlay', {
        position: 'fixed',
        inset: '0',
        background: CONFIG.COLORS.overlay,
        zIndex: CONFIG.Z_INDEX + 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      });

      const dialog = DOM.create('div', 'omni-edit-dialog', {
        width: '520px',
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
      const hasLegacySource = elementInfo.dataSource || elementInfo.dataFile;

      // 构建源码位置显示
      let sourceDisplayHtml = '';
      if (hasPreciseSource) {
        const displayPath = elementInfo.sourceFile.includes('src/')
          ? elementInfo.sourceFile.substring(elementInfo.sourceFile.indexOf('src/'))
          : elementInfo.sourceFile;
        sourceDisplayHtml = `<span style="color: #00B42A; margin-left: 8px;">📍 ${displayPath}:${elementInfo.sourceLine}</span>`;
      } else if (hasLegacySource) {
        sourceDisplayHtml = `<span style="color: #FF7D00; margin-left: 8px;">📄 ${elementInfo.dataSource || elementInfo.dataFile}</span>`;
      }

      dialog.innerHTML = `
        <div style="padding: 20px 24px; border-bottom: 1px solid #E8E9EB;">
          <h3 style="margin: 0; font-size: 18px; font-weight: 600; color: #1F2329;">修改元素</h3>
          <p style="margin: 8px 0 0; font-size: 13px; color: #646A73;">
            ${elementInfo.tag}${elementInfo.id ? `#${elementInfo.id}` : ''}
            ${sourceDisplayHtml}
          </p>
          ${hasPreciseSource ? `
          <div style="margin-top: 8px; padding: 8px 12px; background: #F0FFF5; border-radius: 6px; border: 1px solid #00B42A;">
            <span style="font-size: 12px; color: #00B42A;">✅ 已精确定位到源码位置，AI 将直接修改此文件</span>
          </div>
          ` : hasLegacySource ? `
          <div style="margin-top: 8px; padding: 8px 12px; background: #FFF7F0; border-radius: 6px; border: 1px solid #FF7D00;">
            <span style="font-size: 12px; color: #FF7D00;">⚠️ 未精确定位源码，AI 将尝试猜测对应代码</span>
          </div>
          ` : ''}
        </div>
        <div style="padding: 20px 24px; overflow-y: auto; flex: 1;">
          <label style="display: block; margin-bottom: 8px; font-size: 14px; font-weight: 500; color: #1F2329;">
            你想如何修改此元素？
          </label>
          <textarea
            id="omni-edit-input"
            placeholder="例如：将按钮颜色改为红色，增加点击动画效果..."
            style="
              width: 100%;
              height: 100px;
              padding: 12px;
              border: 1px solid #DEE0E3;
              border-radius: 8px;
              fontSize: 14px;
              resize: vertical;
              box-sizing: border-box;
            "
          ></textarea>

          <div style="margin-top: 12px; padding: 12px; background: #F5F6F7; border-radius: 8px;">
            <div style="font-size: 12px; color: #646A73; margin-bottom: 4px;">元素上下文信息：</div>
            <div style="font-size: 11px; color: #1F2329; font-family: monospace; overflow: hidden;">
              <div>XPath: ${elementInfo.xpath}</div>
              ${hasPreciseSource ? `
                <div style="color: #00B42A;">📍 Source: ${elementInfo.sourceFile}:${elementInfo.sourceLine}:${elementInfo.sourceColumn}</div>
              ` : elementInfo.dataSource ? `
                <div>Source: ${elementInfo.dataSource}</div>
              ` : ''}
              ${elementInfo.dataComponent ? `<div>Component: ${elementInfo.dataComponent}</div>` : ''}
            </div>
          </div>
          
          <div style="margin-top: 12px; padding: 12px; background: #F5F6F7; border-radius: 8px;">
            <div style="font-size: 12px; color: #646A73; margin-bottom: 4px;">当前内容预览：</div>
            <div style="font-size: 13px; color: #1F2329; font-family: monospace; white-space: pre-wrap; max-height: 80px; overflow: auto;">
              ${elementInfo.text.slice(0, 200)}${elementInfo.text.length > 200 ? '...' : ''}
            </div>
          </div>
        </div>
        <div style="padding: 16px 24px; border-top: 1px solid #E8E9EB; display: flex; justify-content: flex-end; gap: 12px;">
          <button id="omni-edit-cancel" style="
            padding: 8px 16px;
            border: none;
            background: transparent;
            color: #646A73;
            fontSize: 14px;
            cursor: pointer;
            border-radius: 6px;
          ">取消</button>
          <button id="omni-edit-submit" style="
            padding: 8px 16px;
            border: none;
            background: #3370FF;
            color: #fff;
            fontSize: 14px;
            cursor: pointer;
            border-radius: 6px;
            font-weight: 500;
          ">提交给 AI</button>
        </div>
      `;

      overlay.appendChild(dialog);

      // 事件绑定
      const input = dialog.querySelector('#omni-edit-input');
      const cancelBtn = dialog.querySelector('#omni-edit-cancel');
      const submitBtn = dialog.querySelector('#omni-edit-submit');

      cancelBtn.addEventListener('click', () => {
        overlay.remove();
        exitSelectionMode();
      });

      submitBtn.addEventListener('click', () => {
        const feedback = input.value.trim();
        if (!feedback) {
          input.style.borderColor = '#F53F3F';
          return;
        }

        handleModify(elementInfo, feedback);
        overlay.remove();
      });

      // 点击遮罩关闭
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
          overlay.remove();
        }
      });

      return overlay;
    },

    // 创建进度条
    createProgressBar(pipelineId) {
      const container = DOM.create('div', 'omni-progress-container', {
        position: 'fixed',
        bottom: '80px',
        right: '24px',
        width: '320px',
        background: '#fff',
        borderRadius: '12px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        zIndex: CONFIG.Z_INDEX + 10,
        overflow: 'hidden',
        animation: 'omni-slide-in 0.3s ease-out',
      });

      container.innerHTML = `
        <div style="padding: 16px 20px; border-bottom: 1px solid #E8E9EB;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="omni-progress-spinner" style="
              width: 16px;
              height: 16px;
              border: 2px solid #E8E9EB;
              border-top-color: #3370FF;
              border-radius: 50%;
              animation: omni-spin 1s linear infinite;
            "></div>
            <span style="font-size: 14px; font-weight: 500; color: #1F2329;">AI 正在为您生成变更...</span>
          </div>
          <div style="margin-top: 8px; font-size: 12px; color: #646A73;">
            Pipeline: <span style="font-family: monospace; color: #3370FF;">${pipelineId.slice(0, 8)}...</span>
          </div>
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
      return container;
    },

    // 更新进度条
    updateProgressBar(container, status, percent) {
      const statusEl = container.querySelector('.omni-progress-status');
      const percentEl = container.querySelector('.omni-progress-percent');
      const barEl = container.querySelector('.omni-progress-bar');
      const spinnerEl = container.querySelector('.omni-progress-spinner');

      if (statusEl) statusEl.textContent = status;
      if (percentEl) percentEl.textContent = `${percent}%`;
      if (barEl) barEl.style.width = `${percent}%`;

      // 完成状态
      if (percent >= 100) {
        if (spinnerEl) {
          spinnerEl.style.border = 'none';
          spinnerEl.style.background = '#00B42A';
          spinnerEl.innerHTML = '✓';
          spinnerEl.style.color = '#fff';
          spinnerEl.style.display = 'flex';
          spinnerEl.style.alignItems = 'center';
          spinnerEl.style.justifyContent = 'center';
          spinnerEl.style.fontSize = '10px';
        }
      }
    },

    // 移除进度条
    removeProgressBar(container) {
      container.style.animation = 'omni-slide-out 0.3s ease-in';
      setTimeout(() => container.remove(), 300);
    },

    // 创建完成通知
    createCompletionNotification(prUrl) {
      const notification = DOM.create('div', 'omni-completion-notification', {
        position: 'fixed',
        top: '24px',
        right: '24px',
        width: '380px',
        background: '#fff',
        borderRadius: '12px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        zIndex: CONFIG.Z_INDEX + 20,
        overflow: 'hidden',
        animation: 'omni-slide-in 0.3s ease-out',
        border: '1px solid #00B42A',
      });

      notification.innerHTML = `
        <div style="padding: 20px;">
          <div style="display: flex; align-items: flex-start; gap: 12px;">
            <div style="
              width: 40px;
              height: 40px;
              border-radius: 50%;
              background: '#00B42A10',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            ">
              <span style="font-size: 20px;">✨</span>
            </div>
            <div style="flex: 1;">
              <h4 style="margin: 0 0 8px; font-size: 16px; font-weight: 600; color: #1F2329;">AI 已完成修改！</h4>
              <p style="margin: 0 0 12px; font-size: 13px; color: #646A73; line-height: 1.5;">
                代码已自动同步并 Push 到了 GitHub PR。<br>
                请查看本地预览页面的热更新效果！
              </p>
              <div style="display: flex; gap: 8px;">
                <a href="${prUrl}" target="_blank" style="
                  padding: 6px 12px;
                  background: #3370FF;
                  color: #fff;
                  textDecoration: none;
                  borderRadius: 6px;
                  fontSize: 13px;
                  fontWeight: 500;
                ">查看 PR</a>
                <button onclick="this.closest('.omni-completion-notification').remove()" style="
                  padding: 6px 12px;
                  background: transparent;
                  border: 1px solid #DEE0E3;
                  color: #646A73;
                  borderRadius: 6px;
                  fontSize: 13px;
                  cursor: pointer;
                ">关闭</button>
              </div>
            </div>
          </div>
        </div>
      `;

      document.body.appendChild(notification);

      // 5秒后自动移除
      setTimeout(() => {
        if (notification.parentNode) {
          notification.style.animation = 'omni-slide-out 0.3s ease-in';
          setTimeout(() => notification.remove(), 300);
        }
      }, 10000);
    },
  };

  // ============================================
  // 核心功能
  // ============================================

  // 处理修改提交
  async function handleModify(elementInfo, feedback) {
    const progressBar = UI.createProgressBar('pending');

    try {
      // 构建请求体 - 适配后端 API
      const requirement = `修复: ${elementInfo.tag}${elementInfo.id ? `#${elementInfo.id}` : ''}\n\n${feedback}`;

      // 构建 sourceContext（如果有精确的源码位置信息）
      let sourceContext = null;
      if (elementInfo.sourceFile && elementInfo.sourceLine > 0) {
        sourceContext = {
          file: elementInfo.sourceFile,
          line: elementInfo.sourceLine,
          column: elementInfo.sourceColumn,
          // 转换为相对路径（如果可能）
          relativePath: elementInfo.sourceFile.includes('src/')
            ? elementInfo.sourceFile.substring(elementInfo.sourceFile.indexOf('src/'))
            : elementInfo.sourceFile,
        };
      }

      const payload = {
        requirement: requirement,
        elementContext: {
          tag: elementInfo.tag,
          id: elementInfo.id,
          class: elementInfo.class,
          xpath: elementInfo.xpath,
          selector: elementInfo.selector,
          outerHTML: elementInfo.outerHTML,
          text: elementInfo.text,
          dataSource: elementInfo.dataSource,
          dataComponent: elementInfo.dataComponent,
          dataFile: elementInfo.dataFile,
          rect: elementInfo.rect,
        },
        // 新增：精确的源码位置上下文
        sourceContext: sourceContext,
      };

      // 发送请求
      const response = await API.createPipeline(payload);
      
      // 后端返回的是 pipeline_id 不是 id
      const pipelineId = response.success && response.data?.pipeline_id;
      if (pipelineId) {
        state.currentPipelineId = pipelineId;
        UI.updateProgressBar(progressBar, 'Pipeline 已创建，开始执行...', 10);
        
        // 开始轮询状态
        startPolling(progressBar, pipelineId);
      } else {
        throw new Error(response.error || '创建 Pipeline 失败');
      }
    } catch (error) {
      console.error('提交失败:', error);
      UI.updateProgressBar(progressBar, `错误: ${error.message}`, 0);
      showToast(`提交失败: ${error.message}`, 'error');
      setTimeout(() => UI.removeProgressBar(progressBar), 3000);
    }

    exitSelectionMode();
  }

  // 轮询 Pipeline 状态
  function startPolling(progressBar, pipelineId) {
    state.isPolling = true;
    
    const poll = async () => {
      if (!state.isPolling) return;

      try {
        const response = await API.getPipelineStatus(pipelineId);
        
        if (response.success) {
          const { status, current_stage_index, stages } = response.data;
          const totalStages = stages?.length || 4;
          const progress = Math.min((current_stage_index / totalStages) * 100, 95);
          
          // 更新进度条
          const stageNames = ['架构设计', '代码生成', '测试验证', '部署发布'];
          const currentStage = stageNames[current_stage_index] || '执行中';
          
          UI.updateProgressBar(progressBar, `${currentStage}...`, Math.round(progress));

          // 检查是否完成（后端实际返回是 'success'）
          if (status === 'success') {
            state.isPolling = false;
            UI.updateProgressBar(progressBar, '完成！', 100);

            // 尝试从返回的 delivery 对象中拿真实的 pr_url
            const prUrl = response.data.delivery?.pr_url || '#';

            setTimeout(() => {
              UI.removeProgressBar(progressBar);
              UI.createCompletionNotification(prUrl);
            }, 1500);
            return;
          }

          // 检查是否失败
          if (status === 'failed') {
            state.isPolling = false;
            UI.updateProgressBar(progressBar, '执行失败', 0);
            showToast('Pipeline 执行失败', 'error');
            setTimeout(() => UI.removeProgressBar(progressBar), 3000);
            return;
          }

          // 继续轮询
          setTimeout(poll, CONFIG.POLL_INTERVAL);
        }
      } catch (error) {
        console.error('轮询失败:', error);
        setTimeout(poll, CONFIG.POLL_INTERVAL);
      }
    };

    poll();
  }

  // 切换圈选模式
  function toggleSelectionMode() {
    if (state.isSelectionMode) {
      exitSelectionMode();
    } else {
      enterSelectionMode();
    }
  }

  // 进入圈选模式
  function enterSelectionMode() {
    state.isSelectionMode = true;
    document.body.style.cursor = 'crosshair';

    document.addEventListener('mouseover', handleMouseOver, true);
    document.addEventListener('mouseout', handleMouseOut, true);
    document.addEventListener('click', handleClick, true);
    document.addEventListener('keydown', handleKeyDown);

    showToast('圈选模式已开启，悬停查看元素，点击锁定');
  }

  // 退出圈选模式
  function exitSelectionMode() {
    state.isSelectionMode = false;
    state.selectedElement = null;
    state.hoverElement = null;
    document.body.style.cursor = '';

    document.removeEventListener('mouseover', handleMouseOver, true);
    document.removeEventListener('mouseout', handleMouseOut, true);
    document.removeEventListener('click', handleClick, true);
    document.removeEventListener('keydown', handleKeyDown);

    clearHighlight();
    clearTooltip();
  }

  // 鼠标悬停处理
  function handleMouseOver(e) {
    if (!state.isSelectionMode || state.selectedElement) return;
    e.stopPropagation();

    const el = e.target;
    if (isOmniElement(el)) return;

    state.hoverElement = el;
    highlightElement(el);
    showTooltip(el);
  }

  // 鼠标移出处理
  function handleMouseOut(e) {
    if (!state.isSelectionMode || state.selectedElement) return;
    e.stopPropagation();

    clearHighlight();
    clearTooltip();
    state.hoverElement = null;
  }

  // 点击处理
  function handleClick(e) {
    if (!state.isSelectionMode) return;
    e.preventDefault();
    e.stopPropagation();

    const el = e.target;
    if (isOmniElement(el)) return;

    state.selectedElement = el;
    const elementInfo = DOM.getElementInfo(el);

    const dialog = UI.createEditDialog(elementInfo);
    document.body.appendChild(dialog);

    setTimeout(() => {
      const input = dialog.querySelector('#omni-edit-input');
      if (input) input.focus();
    }, 100);
  }

  // 键盘处理
  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      exitSelectionMode();
    }
  }

  // 检查是否是 Omni 元素
  function isOmniElement(el) {
    return el.classList?.contains('omni-floating-icon') ||
           el.classList?.contains('omni-highlight-box') ||
           el.classList?.contains('omni-tooltip') ||
           el.closest?.('.omni-edit-dialog') ||
           el.closest?.('.omni-progress-container') ||
           el.closest?.('.omni-completion-notification');
  }

  // 高亮元素
  function highlightElement(el) {
    clearHighlight();
    const rect = el.getBoundingClientRect();
    const box = UI.createHighlightBox(rect);
    box.className = 'omni-highlight-box';
    document.body.appendChild(box);
  }

  // 清除高亮
  function clearHighlight() {
    const boxes = document.querySelectorAll('.omni-highlight-box');
    boxes.forEach(box => box.remove());
  }

  // 显示提示
  function showTooltip(el) {
    clearTooltip();
    const tooltip = UI.createTooltip(el);
    tooltip.className = 'omni-tooltip';
    document.body.appendChild(tooltip);
  }

  // 清除提示
  function clearTooltip() {
    const tooltips = document.querySelectorAll('.omni-tooltip');
    tooltips.forEach(t => t.remove());
  }

  // 显示 Toast
  function showToast(message, type = 'info') {
    const colors = {
      info: '#1A1C21',
      success: '#00B42A',
      error: '#F53F3F',
      warning: '#FF7D00',
    };

    const toast = DOM.create('div', 'omni-toast', {
      position: 'fixed',
      bottom: '80px',
      right: '24px',
      padding: '12px 20px',
      background: colors[type] || colors.info,
      color: '#fff',
      borderRadius: '8px',
      fontSize: '14px',
      zIndex: CONFIG.Z_INDEX + 2,
      boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      animation: 'omni-slide-in 0.3s ease-out',
    });

    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'omni-slide-out 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // ============================================
  // 初始化
  // ============================================
  function init() {
    // 添加动画样式
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
      .omni-highlight-box {
        animation: omni-pulse 1.5s ease-in-out infinite;
      }
      @keyframes omni-pulse {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 0.9; }
      }
    `;
    document.head.appendChild(style);

    // 创建悬浮图标
    const icon = UI.createFloatingIcon();
    document.body.appendChild(icon);

    console.log('[OmniFlowAI] 注入脚本已加载，点击右下角图标开启圈选模式');
  }

  // 等待 DOM 加载完成
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 暴露全局 API
  window.OmniFlowAI = {
    toggle: toggleSelectionMode,
    isActive: () => state.isSelectionMode,
    version: '2.0.0',
    config: CONFIG,
  };
})();
