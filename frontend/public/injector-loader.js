/**
 * OmniFlowAI Injector - 加载器脚本
 * 用于加载打包后的 TypeScript 版本 Injector
 * 
 * 使用方法：
 * <script src="/injector-loader.js" data-api-url="http://localhost:8000"></script>
 */

(function () {
  'use strict';

  // 获取当前脚本的基础路径
  const BASE_PATH = (() => {
    const currentScript = document.currentScript as HTMLScriptElement | null;
    if (currentScript) {
      const src = currentScript.src;
      return src.substring(0, src.lastIndexOf('/') + 1);
    }
    return window.location.origin + '/';
  })();

  // 获取 API URL
  const API_URL = (() => {
    const currentScript = document.currentScript as HTMLScriptElement | null;
    return currentScript?.dataset.apiUrl || window.location.origin;
  })();

  // 加载 Injector 脚本
  function loadInjector() {
    const script = document.createElement('script');
    script.src = BASE_PATH + 'omni-injector.iife.js';
    script.dataset.apiUrl = API_URL;
    script.async = false;

    script.onload = () => {
      console.log('[OmniFlowAI] Injector 加载完成');
    };

    script.onerror = () => {
      console.error('[OmniFlowAI] Injector 加载失败');
    };

    document.head.appendChild(script);
  }

  // 页面加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadInjector);
  } else {
    loadInjector();
  }
})();
