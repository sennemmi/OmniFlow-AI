/**
 * OmniFlowAI Injector - API 调用模块
 * 封装所有后端 API 调用
 */

import { config } from './config';
import { bus } from './events';
import type {
  PipelineResponse,
  FileContentResponse,
  ModifyResponse,
  BatchModifyResponse,
} from './types';

/**
 * API 错误类
 */
export class APIError extends Error {
  statusCode?: number;
  response?: Response;

  constructor(
    message: string,
    statusCode?: number,
    response?: Response
  ) {
    super(message);
    this.name = 'APIError';
    this.statusCode = statusCode;
    this.response = response;
  }
}

/**
 * API 客户端
 */
class APIClient {
  private baseUrl: string;

  constructor() {
    this.baseUrl = config.API_BASE_URL;
  }

  /**
   * 发送 HTTP 请求
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      });

      if (!response.ok) {
        throw new APIError(
          `API 错误: ${response.status}`,
          response.status,
          response
        );
      }

      return response.json() as Promise<T>;
    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        error instanceof Error ? error.message : '网络请求失败'
      );
    }
  }

  /**
   * 创建 Pipeline
   */
  async createPipeline(data: {
    requirement: string;
    elementContext: Record<string, unknown>;
    sourceContext: Record<string, unknown> | null;
    llmContext: Record<string, unknown>;
  }): Promise<PipelineResponse> {
    const response = await this.request<PipelineResponse>(
      config.API_ENDPOINT,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );

    if (response.success && response.data?.pipeline_id) {
      bus.emit('pipeline:created', { pipelineId: response.data.pipeline_id });
    }

    return response;
  }

  /**
   * 获取 Pipeline 状态
   */
  async getPipelineStatus(pipelineId: string): Promise<PipelineResponse> {
    return this.request<PipelineResponse>(
      `/api/v1/pipeline/${pipelineId}/status`
    );
  }

  /**
   * 获取文件内容
   */
  async getFileContent(filePath: string): Promise<FileContentResponse> {
    return this.request<FileContentResponse>(
      `/api/v1/code/file-content?path=${encodeURIComponent(filePath)}`
    );
  }

  /**
   * 写入文件内容
   */
  async writeFile(filePath: string, content: string): Promise<FileContentResponse> {
    return this.request<FileContentResponse>(`/api/v1/code/file-content`, {
      method: 'PUT',
      body: JSON.stringify({ path: filePath, content }),
    });
  }

  /**
   * 修改代码（AI 生成）
   */
  async modifyCode(payload: {
    source_context: {
      file: string;
      line: number;
      column: number;
    };
    element_context: {
      tag: string;
      id: string;
      class_name: string;
      outer_html: string;
      text: string;
      xpath: string;
      selector: string;
    };
    user_instruction: string;
    auto_apply: boolean;
  }): Promise<ModifyResponse> {
    return this.request<ModifyResponse>(`/api/v1/code/modify`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  /**
   * 批量修改代码
   */
  async modifyBatch(payload: {
    files: Array<{
      file: string;
      line: number;
      column: number;
      element_tag: string;
      element_id: string;
      element_class: string;
      element_html: string;
      element_text: string;
    }>;
    user_instruction: string;
    auto_apply: boolean;
  }): Promise<BatchModifyResponse> {
    return this.request<BatchModifyResponse>(`/api/v1/code/modify-batch`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
}

// 导出单例
export const api = new APIClient();
export const API = api;

// 导出便捷方法
export const createPipeline = (data: Parameters<APIClient['createPipeline']>[0]) =>
  api.createPipeline(data);
export const getPipelineStatus = (pipelineId: string) =>
  api.getPipelineStatus(pipelineId);
export const getFileContent = (filePath: string) => api.getFileContent(filePath);
export const writeFile = (filePath: string, content: string) =>
  api.writeFile(filePath, content);
export const modifyCode = (payload: Parameters<APIClient['modifyCode']>[0]) =>
  api.modifyCode(payload);
export const modifyBatch = (payload: Parameters<APIClient['modifyBatch']>[0]) =>
  api.modifyBatch(payload);

export default api;
