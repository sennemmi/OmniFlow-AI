import type { PipelineStage } from '@types';

// ============================================
// 阶段指标工具函数
// 【修复】后端已将指标保存为 stage 列字段，直接读取即可
// ============================================

export const getStageMetrics = (stage: PipelineStage) => {
  const inputTokens = stage.input_tokens ?? 0;
  const outputTokens = stage.output_tokens ?? 0;

  return {
    inputTokens,
    outputTokens,
    totalTokens: inputTokens + outputTokens,
    durationMs: stage.duration_ms ?? 0,
    retryCount: stage.retry_count ?? 0,
    reasoning: stage.reasoning,
  };
};

export const formatMetricDuration = (ms: number): string => {
  if (!ms || ms < 0) return '-';
  if (ms < 1000) return `${ms}ms`;

  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds >= 3600) {
    return `${Math.floor(totalSeconds / 3600)}h ${Math.floor((totalSeconds % 3600) / 60)}m`;
  }
  if (totalSeconds >= 60) {
    return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
  }
  return `${totalSeconds}s`;
};
