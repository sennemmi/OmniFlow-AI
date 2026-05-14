import type { PipelineStage } from '@types';

// ============================================
// 阶段指标工具函数
// 【修复】后端已将指标保存为 stage 列字段，直接读取即可
// ============================================

export const getStageMetrics = (stage: PipelineStage) => {
  const od = stage.output_data as Record<string, number | string | undefined> | undefined;
  const id = stage.input_data as Record<string, unknown> | undefined;

  // 优先读取持久化的 stage 列字段，为 0 时回退到 output_data（兼容旧阶段记录）
  let inputTokens = (stage.input_tokens as number) ?? 0;
  let outputTokens = (stage.output_tokens as number) ?? 0;
  let durationMs = (stage.duration_ms as number) ?? 0;
  let retryCount = (stage.retry_count as number) ?? 0;
  let reasoning = stage.reasoning as string | undefined;

  if (inputTokens <= 0 && od?.input_tokens != null) {
    inputTokens = od.input_tokens as number;
  }
  if (outputTokens <= 0 && od?.output_tokens != null) {
    outputTokens = od.output_tokens as number;
  }
  if (durationMs <= 0 && od?.duration_ms != null) {
    durationMs = od.duration_ms as number;
  }
  if (retryCount <= 0 && od?.retry_count != null) {
    retryCount = od.retry_count as number;
  }
  if (!reasoning && od?.reasoning != null) {
    reasoning = od.reasoning as string;
  }

  // 如果仍然没有 Token 数据，根据 payload 大小估算（约 3-4 字符/token）
  if (inputTokens <= 0 && id) {
    inputTokens = Math.max(1, Math.round(JSON.stringify(id).length * 0.3));
  }
  if (outputTokens <= 0 && od) {
    outputTokens = Math.max(1, Math.round(JSON.stringify(od).length * 0.3));
  }

  return {
    inputTokens,
    outputTokens,
    totalTokens: inputTokens + outputTokens,
    durationMs,
    retryCount,
    reasoning,
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
