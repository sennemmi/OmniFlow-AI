/**
 * OmniFlowAI Injector - 配置模块
 */

import type { Config } from './types';

/**
 * 获取 API 基础 URL
 */
const getApiBaseUrl = (): string => {
  // 从父窗口获取（iframe 场景）
  if (window.parent !== window) {
    const parentUrl = (window.parent as Window & { __OMNIFLOW_API_URL__?: string }).__OMNIFLOW_API_URL__;
    if (parentUrl) return parentUrl;
  }

  // 从当前脚本标签获取
  const currentScript = document.currentScript as HTMLScriptElement | null;
  if (currentScript?.dataset.apiUrl) {
    return currentScript.dataset.apiUrl;
  }

  // 默认使用当前域名
  return window.location.origin;
};

/**
 * 全局配置对象
 */
export const config: Config = {
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

/**
 * 更新配置
 * @param partial - 部分配置对象
 */
export function updateConfig(partial: Partial<Config>): void {
  Object.assign(config, partial);
}

/**
 * 获取完整配置
 */
export function getConfig(): Config {
  return config;
}

export default config;
