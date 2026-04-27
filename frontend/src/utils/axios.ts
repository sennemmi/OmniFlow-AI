import axios from 'axios';
import type { AxiosError, AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@types';

// ============================================
// Axios 实例配置 - 适配后端 {success, data, error, request_id} 格式
// ============================================

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 可添加认证 token
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    // 生成请求 ID（如果没有）
    if (!config.headers['X-Request-ID']) {
      config.headers['X-Request-ID'] = generateRequestId();
    }
    
    return config;
  },
  (error: AxiosError) => {
    return Promise.reject(error);
  }
);

// 响应拦截器 - 统一处理 {success, data, error, request_id} 格式
apiClient.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<unknown>>) => {
    const { data } = response;

    // 检查后端返回的成功状态
    if (!data.success) {
      // 业务逻辑错误
      const error = new Error(data.error || '请求失败');
      (error as Error & { requestId?: string }).requestId = data.request_id;
      return Promise.reject(error);
    }

    // ★ 直接返回业务数据，而不是放入 data 字段
    return data.data as any;
  },
  (error: AxiosError<ApiResponse<unknown>>) => {
    // HTTP 错误处理
    if (error.response?.data) {
      const apiError = error.response.data;
      const customError = new Error(apiError.error || '服务器错误');
      (customError as Error & { requestId?: string; status?: number }).requestId = apiError.request_id;
      (customError as Error & { requestId?: string; status?: number }).status = error.response.status;
      return Promise.reject(customError);
    }

    // 网络错误
    if (error.request) {
      return Promise.reject(new Error('网络错误，请检查连接'));
    }

    return Promise.reject(error);
  }
);

// 生成请求 ID
function generateRequestId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// 包装响应类型 - 拦截器已返回业务数据，直接使用
export async function apiGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return apiClient.get<any, T>(url, { params });
}

export async function apiPost<T>(url: string, data?: Record<string, unknown>): Promise<T> {
  return apiClient.post<any, T>(url, data);
}

export async function apiPut<T>(url: string, data?: Record<string, unknown>): Promise<T> {
  return apiClient.put<any, T>(url, data);
}

export async function apiDelete<T>(url: string): Promise<T> {
  return apiClient.delete<any, T>(url);
}

export default apiClient;
