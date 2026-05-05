import type { PipelineStage } from '@types';

type MetricKey = 'input_tokens' | 'output_tokens' | 'duration_ms' | 'retry_count';

const metricContainers = (stage: PipelineStage): Array<Record<string, unknown> | undefined> => {
  const outputData = stage.output_data as Record<string, unknown> | undefined;

  return [
    stage as unknown as Record<string, unknown>,
    outputData,
    outputData?.metrics as Record<string, unknown> | undefined,
    outputData?.agent_metrics as Record<string, unknown> | undefined,
    outputData?.coder_output as Record<string, unknown> | undefined,
    outputData?.testing_result as Record<string, unknown> | undefined,
    outputData?.coding_output as Record<string, unknown> | undefined,
  ];
};

const toMetricNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

export const getStageMetric = (stage: PipelineStage, key: MetricKey): number => {
  let fallback = 0;

  for (const source of metricContainers(stage)) {
    const value = toMetricNumber(source?.[key]);
    if (value === undefined) continue;
    if (value > 0) return value;
    fallback = value;
  }

  return fallback;
};

export const getStageReasoning = (stage: PipelineStage): string | undefined => {
  for (const source of metricContainers(stage)) {
    const reasoning = source?.reasoning;
    if (typeof reasoning === 'string' && reasoning.trim()) {
      return reasoning;
    }
  }
  return undefined;
};

export const getStageMetrics = (stage: PipelineStage) => {
  let inputTokens = getStageMetric(stage, 'input_tokens');
  let outputTokens = getStageMetric(stage, 'output_tokens');

  if (inputTokens <= 0 && stage.input_data) {
    inputTokens = Math.max(1, Math.floor(JSON.stringify(stage.input_data).length * 0.3));
  }
  if (outputTokens <= 0 && stage.output_data) {
    outputTokens = Math.max(1, Math.floor(JSON.stringify(stage.output_data).length * 0.3));
  }

  return {
    inputTokens,
    outputTokens,
    totalTokens: inputTokens + outputTokens,
    durationMs: getStageMetric(stage, 'duration_ms'),
    retryCount: getStageMetric(stage, 'retry_count'),
    reasoning: getStageReasoning(stage),
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
