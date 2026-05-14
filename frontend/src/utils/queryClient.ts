import { QueryClient } from '@tanstack/react-query';

// ============================================
// TanStack Query 客户端配置
// ============================================

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 3秒轮询配置
      refetchInterval: false,
      refetchOnWindowFocus: true,
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      staleTime: 5000,
      gcTime: 10 * 60 * 1000, // 10分钟
    },
    mutations: {
      retry: 1,
    },
  },
});

// Pipeline 专用轮询配置 —— 激进轮询 + 立即刷新
export const pipelinePollingOptions = {
  refetchInterval: 2000,           // 每 2 秒轮询一次
  refetchIntervalInBackground: true, // 后台也轮询
  staleTime: 0,                    // 始终视为过期，强制 refetch
  gcTime: 5 * 60 * 1000,
};

// 已完成的 pipeline 不再轮询
export const pipelineDoneOptions = {
  refetchInterval: false as const,
  staleTime: Infinity,
};
