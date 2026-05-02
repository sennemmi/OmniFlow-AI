/**
 * OmniFlowAI 浏览器注入脚本 - 加载器
 * 按顺序加载各个模块
 */

(function () {
  'use strict';

  const BASE_PATH = (() => {
    const currentScript = document.currentScript;
    if (currentScript) {
      const src = currentScript.src;
      return src.substring(0, src.lastIndexOf('/') + 1);
    }
    return window.location.origin + '/';
  })();

  const MODULES = [
    'injector/config.js',
    'injector/core.js',
    'injector/api.js',
    'injector/ui.js',
    'injector/state.js',
    'injector/selection.js',
    'injector/handlers.js',
    'injector/searchReplace.js', // 搜索替换引擎（必须在 preview.js 和 pipeline.js 之前加载）
    'injector/preview.js',       // 预览模块（依赖 searchReplace.js）
    'injector/pipeline.js',      // 依赖 searchReplace.js
    'injector/main.js',
  ];

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      // 添加时间戳防止缓存
      script.src = url + '?v=' + Date.now();
      script.async = false;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`Failed to load ${url}`));
      document.head.appendChild(script);
    });
  }

  async function init() {
    try {
      for (const module of MODULES) {
        await loadScript(BASE_PATH + module);
      }
      console.log('[OmniFlowAI] 所有模块加载完成');
    } catch (error) {
      console.error('[OmniFlowAI] 模块加载失败:', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();