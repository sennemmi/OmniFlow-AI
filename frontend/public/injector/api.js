/**
 * OmniFlowAI 浏览器注入脚本 - API 调用模块
 */

(function () {
  'use strict';

  const CONFIG = window.OmniFlowAIConfig;

  const API = {
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

    async getPipelineStatus(pipelineId) {
      const response = await fetch(`${CONFIG.API_BASE_URL}/api/v1/pipeline/${pipelineId}/status`);
      if (!response.ok) {
        throw new Error(`获取状态失败: ${response.status}`);
      }
      return response.json();
    },
  };

  window.OmniFlowAIAPI = { API };

})();
