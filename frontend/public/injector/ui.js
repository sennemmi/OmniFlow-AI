/**
 * OmniFlowAI 浏览器注入脚本 - UI 组件模块
 */

(function () {
  'use strict';

  const CONFIG = window.OmniFlowAIConfig;
  const { DOM, Utils } = window.OmniFlowAICore;

  const UI = {
    createFloatingIcon(onClick) {
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

      icon.addEventListener('click', onClick);

      return icon;
    },

    /**
     * 【新增】创建退出圈选模式按钮
     */
    createExitButton(onClick) {
      const button = DOM.create('div', 'omni-exit-button', {
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
        zIndex: CONFIG.Z_INDEX + 100,
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

      button.addEventListener('click', onClick);

      return button;
    },

    /**
     * 【Inspector 模式】创建高亮框 - Figma 同款镂空效果
     */
    createHighlightBox(rect) {
      const box = DOM.create('div', 'omni-highlight-box', {
        position: 'fixed',
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        border: `2px solid #6366f1`,
        borderRadius: '3px',
        pointerEvents: 'none',
        zIndex: CONFIG.Z_INDEX - 1,
        transition: 'all 60ms ease',
        boxShadow: '0 0 0 2px rgba(99, 102, 241, 0.3), 0 0 0 9999px rgba(0, 0, 0, 0.15)',
      });
      return box;
    },

    /**
     * 【新增】多选高亮框 - 带序号标记
     */
    createMultiHighlightBox(rect, index) {
      const container = DOM.create('div', 'omni-multi-highlight-box', {
        position: 'fixed',
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        border: `2px solid #00B42A`,
        borderRadius: '3px',
        pointerEvents: 'none',
        zIndex: CONFIG.Z_INDEX - 1,
        boxShadow: '0 0 0 2px rgba(0, 180, 66, 0.3)',
      });

      // 添加序号标记
      const badge = DOM.create('div', 'omni-multi-highlight-badge', {
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
        zIndex: CONFIG.Z_INDEX,
      });
      badge.textContent = index;
      container.appendChild(badge);

      return container;
    },

    /**
     * 【已移除】画圈圈选矩形 - 不再使用
     * 保留注释作为历史记录
     */
    // createSelectionRect(rect) { ... }

    /**
     * 【已移除】区域高亮 - 不再使用
     * 保留注释作为历史记录
     */
    // createAreaHighlight(rect) { ... }

    createFloatingPanel(referenceRect, content) {
      const panel = DOM.create('div', 'omni-floating-panel', {
        position: 'fixed',
        minWidth: '280px',
        maxWidth: '400px',
        background: '#fff',
        borderRadius: '12px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        zIndex: CONFIG.Z_INDEX + 1,
        overflow: 'hidden',
        animation: 'omni-slide-in 0.2s ease-out',
      });

      const position = Utils.calculatePanelPosition(referenceRect, panel);
      panel.style.left = `${position.x}px`;
      panel.style.top = `${position.y}px`;

      panel.innerHTML = content;
      return panel;
    },

    createTooltip(el) {
      const info = DOM.getElementInfo(el);
      const rect = el.getBoundingClientRect();

      const hasPreciseSource = info.sourceFile && info.sourceLine > 0;
      const hasComponentName = info.componentName;

      let sourceInfoHtml = '';
      let componentInfoHtml = '';

      if (hasComponentName) {
        componentInfoHtml = `
          <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 8px;">
            <span style="background: #3370FF; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;">
              ${info.componentName}
            </span>
            ${hasPreciseSource ? '<span style="color: #00B42A; font-size: 11px;">✅ 已映射</span>' : ''}
          </div>
        `;
      }

      if (hasPreciseSource) {
        const displayPath = info.sourceFile.includes('src/')
          ? info.sourceFile.substring(info.sourceFile.indexOf('src/'))
          : info.sourceFile;
        sourceInfoHtml = `
          <div style="color: #00B42A; font-size: 11px; font-family: monospace; margin-top: 4px;">
            📍 ${displayPath}:${info.sourceLine}
          </div>
        `;
      } else if (info.dataSource) {
        sourceInfoHtml = `<div style="color: #FF7D00; font-size: 11px;">📄 ${info.dataSource}</div>`;
      } else {
        sourceInfoHtml = `
          <div style="color: #646A73; font-size: 11px; margin-top: 4px;">
            ❓ 无源码映射
          </div>
        `;
      }

      const content = `
        <div style="padding: 12px 16px;">
          ${componentInfoHtml}
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
            <span style="font-weight: 600; color: #1F2329;">${info.tag}</span>
            ${info.id ? `<span style="color: #646A73;">#${info.id}</span>` : ''}
          </div>
          <div style="color: #8F959E; font-size: 12px; margin-bottom: 8px;">
            ${info.class.slice(0, 50)}${info.class.length > 50 ? '...' : ''}
          </div>
          ${sourceInfoHtml}
          <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #E8E9EB; font-size: 11px; color: #8F959E;">
            💡 拖拽可圈选多个元素
          </div>
        </div>
      `;

      return this.createFloatingPanel(rect, content);
    },

    createAreaSelectionPanel(elements, rect, onCancel, onSubmit) {
      const hasPreciseSource = elements.some(el => {
        const info = DOM.getElementInfo(el);
        return info.sourceFile && info.sourceLine > 0;
      });

      const content = `
        <div style="padding: 16px 20px; border-bottom: 1px solid #E8E9EB;">
          <h4 style="margin: 0; font-size: 16px; font-weight: 600; color: #1F2329;">
            已圈选 ${elements.length} 个元素
          </h4>
          <p style="margin: 4px 0 0; font-size: 12px; color: #646A73;">
            ${hasPreciseSource ? '✅ 包含可定位源码的元素' : '⚠️ 部分元素可能无法精确定位'}
          </p>
        </div>
        <div style="padding: 12px 20px; max-height: 200px; overflow-y: auto;">
          ${elements.slice(0, 5).map(el => {
            const info = DOM.getElementInfo(el);
            const sourceHint = info.sourceFile && info.sourceLine > 0
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
                <div style="color: #8F959E; margin-top: 2px; margin-left: 22px;">
                  ${info.class.slice(0, 40)}${info.class.length > 40 ? '...' : ''}
                </div>
              </div>
            `;
          }).join('')}
          ${elements.length > 5 ? `<div style="padding: 8px 0; text-align: center; color: #8F959E; font-size: 12px;">...还有 ${elements.length - 5} 个元素</div>` : ''}
        </div>
        <div style="padding: 12px 20px; border-top: 1px solid #E8E9EB; display: flex; gap: 8px;">
          <button id="omni-area-cancel" style="
            flex: 1;
            padding: 8px 12px;
            border: 1px solid #DEE0E3;
            background: #fff;
            color: #646A73;
            fontSize: 13px;
            cursor: pointer;
            border-radius: 6px;
          ">取消</button>
          <button id="omni-area-submit" style="
            flex: 1;
            padding: 8px 12px;
            border: none;
            background: #3370FF;
            color: #fff;
            fontSize: 13px;
            cursor: pointer;
            border-radius: 6px;
            font-weight: 500;
          ">批量修改</button>
        </div>
      `;

      const panel = this.createFloatingPanel(rect, content);

      const cancelBtn = panel.querySelector('#omni-area-cancel');
      const submitBtn = panel.querySelector('#omni-area-submit');

      cancelBtn.addEventListener('click', onCancel);
      submitBtn.addEventListener('click', onSubmit);

      // 【新增】回车键进入更改
      const handleKeyDown = (e) => {
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

      return panel;
    },

    createEditDialog(elementInfo, isAreaSelection = false, selectedElements = [], onCancel, onSubmit) {
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
      const hasComponentName = elementInfo.componentName;

      const title = isAreaSelection
        ? `批量修改 ${selectedElements.length} 个元素`
        : `修改元素`;

      const elementDesc = isAreaSelection
        ? `已选择 ${selectedElements.length} 个元素，将统一应用修改`
        : `${elementInfo.tag}${elementInfo.id ? `#${elementInfo.id}` : ''}`;

      let sourceDisplayHtml = '';
      if (hasComponentName) {
        sourceDisplayHtml += `<span style="background: #3370FF; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 8px;">${elementInfo.componentName}</span>`;
      }
      if (hasPreciseSource) {
        const displayPath = elementInfo.sourceFile.includes('src/')
          ? elementInfo.sourceFile.substring(elementInfo.sourceFile.indexOf('src/'))
          : elementInfo.sourceFile;
        sourceDisplayHtml += `<span style="color: #00B42A; font-family: monospace; font-size: 12px;">📍 ${displayPath}:${elementInfo.sourceLine}</span>`;
      }

      dialog.innerHTML = `
        <div style="padding: 20px 24px; border-bottom: 1px solid #E8E9EB;">
          <h3 style="margin: 0; font-size: 18px; font-weight: 600; color: #1F2329;">${title}</h3>
          <p style="margin: 8px 0 0; font-size: 13px; color: #646A73;">
            ${elementDesc}
          </p>
          ${sourceDisplayHtml ? `<div style="margin-top: 8px;">${sourceDisplayHtml}</div>` : ''}
          ${hasPreciseSource ? `
          <div style="margin-top: 8px; padding: 8px 12px; background: #F0FFF5; border-radius: 6px; border: 1px solid #00B42A;">
            <span style="font-size: 12px; color: #00B42A;">✅ 已精确定位到源码位置，AI 将直接修改此文件</span>
          </div>
          ` : `
          <div style="margin-top: 8px; padding: 8px 12px; background: #FFF7F0; border-radius: 6px; border: 1px solid #FF7D00;">
            <span style="font-size: 12px; color: #FF7D00;">⚠️ 未精确定位源码，AI 将尝试猜测对应代码</span>
          </div>
          `}
        </div>
        <div style="padding: 20px 24px; overflow-y: auto; flex: 1;">
          <label style="display: block; margin-bottom: 8px; font-size: 14px; font-weight: 500; color: #1F2329;">
            你想如何修改${isAreaSelection ? '这些元素' : '此元素'}？
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
            <div style="font-size: 12px; color: #646A73; margin-bottom: 4px;">源码定位信息：</div>
            <div style="font-size: 11px; color: #1F2329; font-family: monospace; overflow: hidden; line-height: 1.6;">
              <div>File: ${elementInfo.sourceFile || 'unknown'}</div>
              <div>Line: ${elementInfo.sourceLine || 'unknown'}, Column: ${elementInfo.sourceColumn || 'unknown'}</div>
              <div>Component: ${elementInfo.componentName || 'unknown'}</div>
              <div>Selector: ${elementInfo.selector}</div>
            </div>
          </div>

          ${!isAreaSelection ? `
          <div style="margin-top: 12px; padding: 12px; background: #F5F6F7; border-radius: 8px;">
            <div style="font-size: 12px; color: #646A73; margin-bottom: 4px;">当前 HTML：</div>
            <div style="font-size: 11px; color: #1F2329; font-family: monospace; white-space: pre-wrap; max-height: 80px; overflow: auto; background: #fff; padding: 8px; border-radius: 4px;">
              ${Utils.escapeHtml(elementInfo.outerHTML.slice(0, 300))}${elementInfo.outerHTML.length > 300 ? '...' : ''}
            </div>
          </div>
          ` : ''}
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

      const input = dialog.querySelector('#omni-edit-input');
      const cancelBtn = dialog.querySelector('#omni-edit-cancel');
      const submitBtn = dialog.querySelector('#omni-edit-submit');

      cancelBtn.addEventListener('click', () => {
        onCancel();
        overlay.remove();
      });

      submitBtn.addEventListener('click', () => {
        const feedback = input.value.trim();
        if (!feedback) {
          input.style.borderColor = '#F53F3F';
          return;
        }
        onSubmit(feedback);
        overlay.remove();
      });

      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
          overlay.remove();
        }
      });

      return overlay;
    },

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

    updateProgressBar(container, status, percent) {
      const statusEl = container.querySelector('.omni-progress-status');
      const percentEl = container.querySelector('.omni-progress-percent');
      const barEl = container.querySelector('.omni-progress-bar');
      const spinnerEl = container.querySelector('.omni-progress-spinner');

      if (statusEl) statusEl.textContent = status;
      if (percentEl) percentEl.textContent = `${percent}%`;
      if (barEl) barEl.style.width = `${percent}%`;

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

    removeProgressBar(container) {
      container.style.animation = 'omni-slide-out 0.3s ease-in';
      setTimeout(() => container.remove(), 300);
    },

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
              background: #F0FFF5;
              display: flex;
              align-items: center;
              justify-content: center;
              flex-shrink: 0;
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
                  text-decoration: none;
                  border-radius: 6px;
                  font-size: 13px;
                  font-weight: 500;
                ">查看 PR</a>
                <button onclick="this.closest('.omni-completion-notification').remove()" style="
                  padding: 6px 12px;
                  background: transparent;
                  border: 1px solid #DEE0E3;
                  color: #646A73;
                  border-radius: 6px;
                  font-size: 13px;
                  cursor: pointer;
                ">关闭</button>
              </div>
            </div>
          </div>
        </div>
      `;

      document.body.appendChild(notification);

      setTimeout(() => {
        if (notification.parentNode) {
          notification.style.animation = 'omni-slide-out 0.3s ease-in';
          setTimeout(() => notification.remove(), 300);
        }
      }, 10000);
    },

    createToast(message, type = 'info') {
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

      return toast;
    },
  };

  window.OmniFlowAIUI = { UI };

})();
