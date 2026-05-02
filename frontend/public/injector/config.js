/**
 * OmniFlowAI 浏览器注入脚本 - 配置模块
 */

(function () {
  'use strict';

  const getApiBaseUrl = () => {
    if (window.parent !== window && window.parent.__OMNIFLOW_API_URL__) {
      return window.parent.__OMNIFLOW_API_URL__;
    }
    const currentScript = document.currentScript;
    if (currentScript && currentScript.dataset.apiUrl) {
      return currentScript.dataset.apiUrl;
    }
    return window.location.origin;
  };

  window.OmniFlowAIConfig = {
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
      selection: 'rgba(51, 112, 255, 0.15)',
      selectionBorder: '#3370FF',
    },
  };

})();
