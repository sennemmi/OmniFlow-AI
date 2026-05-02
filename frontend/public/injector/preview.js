/**
 * OmniFlowAI 浏览器注入脚本 - Vite HMR 预览模块
 *
 * 功能：
 * - 直接修改文件（Vite HMR 自动刷新显示效果）
 * - 显示预览提示和控制按钮
 * - 确认后保持变更
 * - 取消后从缓存恢复原始文件
 */

(function () {
  'use strict';

  const getUI = () => {
    const omniUI = window.OmniFlowAIUI;
    return omniUI ? omniUI.UI : null;
  };
  const getConfig = () => window.OmniFlowAIConfig;

  // 预览状态
  let previewState = {
    isPreviewing: false,
    filePath: null,           // 文件路径
    originalContent: null,    // 原始文件内容（用于回滚）
    modifiedContent: null,    // 修改后的内容
  };

  // ============================================
  // 预览 UI
  // ============================================

  /**
   * 创建预览控制浮层 - 企业级毛玻璃设计
   */
  function createPreviewControls(onConfirm, onCancel) {
    // 添加毛玻璃样式
    const styleId = 'omni-preview-styles';
    if (!document.getElementById(styleId)) {
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
      `;
      document.head.appendChild(style);
    }

    // 预览中提示条 - 毛玻璃效果
    const banner = document.createElement('div');
    banner.id = 'omni-preview-banner';
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

    // SVG 图标
    const eyeIcon = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #60a5fa;">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>`;

    const closeIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
    </svg>`;

    const checkIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>`;

    banner.innerHTML = `
      <div style="display: flex; align-items: center; gap: 16px;">
        <div style="
          width: 44px;
          height: 44px;
          background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(147, 51, 234, 0.2));
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid rgba(96, 165, 250, 0.3);
          animation: omni-pulse 2s infinite;
        ">${eyeIcon}</div>
        <div>
          <div style="font-weight: 600; font-size: 15px; letter-spacing: -0.01em; color: #f8fafc;">预览模式</div>
          <div style="font-size: 13px; color: #94a3b8; margin-top: 2px;">Vite 热更新已应用变更，查看效果后确认或取消</div>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <button id="omni-preview-cancel-btn" style="
          padding: 10px 20px;
          background: rgba(255, 255, 255, 0.05);
          color: #e2e8f0;
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 10px;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s ease;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
          letter-spacing: 0.01em;
        " onmouseover="this.style.background='rgba(255, 255, 255, 0.1)'; this.style.borderColor='rgba(255, 255, 255, 0.2)';" 
           onmouseout="this.style.background='rgba(255, 255, 255, 0.05)'; this.style.borderColor='rgba(255, 255, 255, 0.1)';">
          ${closeIcon}
          <span>取消恢复</span>
        </button>
        <button id="omni-preview-confirm-btn" style="
          padding: 10px 20px;
          background: linear-gradient(135deg, #059669, #10b981);
          color: white;
          border: none;
          border-radius: 10px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          gap: 8px;
          letter-spacing: 0.01em;
          box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);
        " onmouseover="this.style.transform='translateY(-1px)'; this.style.boxShadow='0 6px 20px rgba(16, 185, 129, 0.4)';" 
           onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 14px rgba(16, 185, 129, 0.3)';">
          ${checkIcon}
          <span>确认保持</span>
        </button>
      </div>
    `;

    // 绑定事件
    banner.querySelector('#omni-preview-cancel-btn').addEventListener('click', onCancel);
    banner.querySelector('#omni-preview-confirm-btn').addEventListener('click', onConfirm);

    // ESC 取消
    const escHandler = (e) => {
      if (e.key === 'Escape') {
        onCancel();
      }
    };
    document.addEventListener('keydown', escHandler);
    previewState.escHandler = escHandler;

    document.body.appendChild(banner);
    previewState.previewBanner = banner;

    return banner;
  }

  /**
   * 清除预览 UI
   */
  function clearPreviewUI() {
    // 移除预览浮层
    if (previewState.previewBanner) {
      previewState.previewBanner.remove();
    }

    // 移除 ESC 监听
    if (previewState.escHandler) {
      document.removeEventListener('keydown', previewState.escHandler);
    }

    previewState.previewBanner = null;
    previewState.escHandler = null;
  }

  // ============================================
  // 文件操作
  // ============================================

  /**
   * 写入文件内容（通过后端 API）
   */
  async function writeFile(filePath, content) {
    const CONFIG = getConfig();

    const response = await fetch(`${CONFIG.API_BASE_URL}/api/v1/code/file-content`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: filePath,
        content: content,
      }),
    });

    if (!response.ok) {
      throw new Error('写入文件失败');
    }

    const result = await response.json();
    if (!result.success) {
      throw new Error(result.error || '写入文件失败');
    }

    return result.data;
  }

  // ============================================
  // 主预览函数
  // ============================================

  /**
   * 开始效果预览（Vite HMR 方案）
   * @param {Object} elementInfo - 元素信息
   * @param {string} instruction - 用户修改指令
   * @param {Function} onConfirm - 确认回调
   * @param {Function} onCancel - 取消回调
   */
  async function startPreview(elementInfo, instruction, onComplete) {
    const UI = getUI();
    const CONFIG = getConfig();

    if (!UI || !CONFIG) {
      console.error('[OmniFlowAI] UI 或 CONFIG 模块未加载');
      throw new Error('依赖模块未加载');
    }

    // 清除之前的预览
    clearPreviewUI();

    const progressBar = UI.createProgressBar('pending');

    try {
      const filePath = elementInfo.sourceFile;

      // 步骤1: 获取原始文件内容并缓存
      UI.updateProgressBar(progressBar, '正在读取文件内容...', 20);

      const contentResponse = await fetch(
        `${CONFIG.API_BASE_URL}/api/v1/code/file-content?path=${encodeURIComponent(filePath)}`,
        { method: 'GET' }
      );

      if (!contentResponse.ok) {
        throw new Error('无法读取文件内容');
      }

      const contentResult = await contentResponse.json();
      if (!contentResult.success) {
        throw new Error(contentResult.error || '读取文件失败');
      }

      const originalContent = contentResult.data.content;

      // 保存状态
      previewState.filePath = filePath;
      previewState.originalContent = originalContent;
      previewState.isPreviewing = true;

      // 步骤2: 调用 AI 生成修改后的代码
      UI.updateProgressBar(progressBar, '🤖 AI 正在生成代码...', 50);

      const payload = {
        source_context: {
          file: filePath,
          line: elementInfo.sourceLine,
          column: elementInfo.sourceColumn,
        },
        element_context: {
          tag: elementInfo.tag,
          id: elementInfo.id,
          class_name: elementInfo.class,
          outer_html: elementInfo.outerHTML,
          text: elementInfo.text,
          xpath: elementInfo.xpath,
          selector: elementInfo.selector,
        },
        user_instruction: instruction,
        auto_apply: false,
      };

      const response = await fetch(`${CONFIG.API_BASE_URL}/api/v1/code/modify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'AI 生成失败');
      }

      UI.updateProgressBar(progressBar, '正在应用变更...', 80);

      const data = result.data;
      const modifiedContent = data.new_content;

      // 保存修改后的内容
      previewState.modifiedContent = modifiedContent;

      // 步骤3: 直接写入修改后的文件（触发 Vite HMR）
      await writeFile(filePath, modifiedContent);

      UI.removeProgressBar(progressBar);

      // 步骤4: 显示预览控制浮层
      createPreviewControls(
        // 确认 - 保持变更，清除缓存
        async () => {
          clearPreviewUI();
          previewState = { isPreviewing: false };
          UI.createToast('修改已确认保持', 'success');
          if (onComplete) onComplete(true);
        },
        // 取消 - 恢复原始文件
        async () => {
          const restoreProgressBar = UI.createProgressBar('pending');

          try {
            UI.updateProgressBar(restoreProgressBar, '正在恢复原始文件...', 50);

            // 写回原始内容
            await writeFile(filePath, originalContent);

            clearPreviewUI();
            previewState = { isPreviewing: false };

            UI.updateProgressBar(restoreProgressBar, '已恢复原始文件', 100);
            UI.createToast('已取消修改，恢复原始文件', 'info');
            setTimeout(() => {
              UI.removeProgressBar(restoreProgressBar);
              if (onComplete) onComplete(false);
            }, 1000);
          } catch (error) {
            console.error('恢复文件失败:', error);
            UI.updateProgressBar(restoreProgressBar, `恢复失败: ${error.message}`, 0);
            UI.createToast(`恢复失败: ${error.message}`, 'error');
            setTimeout(() => UI.removeProgressBar(restoreProgressBar), 3000);
            if (onComplete) onComplete(false);
          }
        }
      );

      UI.createToast('预览模式已开启 - Vite 热更新已应用变更', 'info');

    } catch (error) {
      console.error('预览失败:', error);
      clearPreviewUI();
      previewState = { isPreviewing: false };
      UI.updateProgressBar(progressBar, `错误: ${error.message}`, 0);
      UI.createToast(`预览失败: ${error.message}`, 'error');
      setTimeout(() => UI.removeProgressBar(progressBar), 3000);
      if (onComplete) onComplete(false);
    }
  }

  // ============================================
  // 导出 API
  // ============================================

  window.OmniFlowAIPreview = {
    startPreview,
    clearPreviewUI,
    getPreviewState: () => previewState,
  };

})();
