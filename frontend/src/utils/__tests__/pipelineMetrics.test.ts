import { describe, expect, it } from 'vitest';
import { formatMetricDuration, getStageMetrics } from '../pipelineMetrics';
import type { PipelineStage } from '@types';

const baseStage: PipelineStage = {
  id: 1,
  name: 'CODING',
  status: 'success',
};

describe('pipelineMetrics', () => {
  it('prefers persisted stage metrics when present', () => {
    const metrics = getStageMetrics({
      ...baseStage,
      input_tokens: 12,
      output_tokens: 34,
      duration_ms: 5600,
      retry_count: 1,
      output_data: {
        input_tokens: 99,
        output_tokens: 99,
        duration_ms: 9900,
      },
    });

    expect(metrics).toMatchObject({
      inputTokens: 12,
      outputTokens: 34,
      totalTokens: 46,
      durationMs: 5600,
      retryCount: 1,
    });
  });

  it('falls back to output_data metrics for legacy stages', () => {
    const metrics = getStageMetrics({
      ...baseStage,
      input_tokens: 0,
      output_tokens: 0,
      duration_ms: 0,
      output_data: {
        input_tokens: 120,
        output_tokens: 80,
        duration_ms: 45000,
        retry_count: 2,
        reasoning: 'checked contracts',
      },
    });

    expect(metrics).toMatchObject({
      inputTokens: 120,
      outputTokens: 80,
      totalTokens: 200,
      durationMs: 45000,
      retryCount: 2,
      reasoning: 'checked contracts',
    });
  });

  it('formats durations for dashboard cards', () => {
    expect(formatMetricDuration(0)).toBe('-');
    expect(formatMetricDuration(950)).toBe('950ms');
    expect(formatMetricDuration(65000)).toBe('1m 5s');
  });

  it('estimates tokens from stage payloads when usage is unavailable', () => {
    const metrics = getStageMetrics({
      ...baseStage,
      name: 'DESIGN',
      input_data: { prompt: 'design this feature' },
      output_data: { technical_design: 'a'.repeat(100) },
    });

    expect(metrics.inputTokens).toBeGreaterThan(0);
    expect(metrics.outputTokens).toBeGreaterThan(0);
  });
});
