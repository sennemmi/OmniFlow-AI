import { http, HttpResponse } from 'msw';
import type { Pipeline, PipelineStage } from '@types';

// Mock 数据
const mockPipelines: Pipeline[] = [
  {
    id: 1,
    description: '实现用户登录功能',
    status: 'PAUSED',
    current_stage: 'REQUIREMENT',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:05:00Z',
    stages: [
      {
        id: 1,
        name: 'REQUIREMENT',
        status: 'SUCCESS',
        input_data: { requirement: '实现用户登录功能' },
        output_data: { feature_description: '用户登录功能' },
        created_at: '2024-01-15T10:00:00Z',
        completed_at: '2024-01-15T10:05:00Z',
      },
    ],
  },
];

const mockStages: PipelineStage[] = [
  {
    id: 1,
    name: 'REQUIREMENT',
    status: 'SUCCESS',
    input_data: { requirement: '实现用户登录功能' },
    output_data: { feature_description: '用户登录功能' },
    created_at: '2024-01-15T10:00:00Z',
    completed_at: '2024-01-15T10:05:00Z',
  },
  {
    id: 2,
    name: 'DESIGN',
    status: 'PENDING',
    input_data: {},
    output_data: {},
    created_at: '2024-01-15T10:05:00Z',
  },
];

export const handlers = [
  // 获取 Pipeline 列表
  http.get('/api/v1/pipeline', () => {
    return HttpResponse.json({
      success: true,
      data: mockPipelines,
    });
  }),

  // 获取单个 Pipeline 状态
  http.get('/api/v1/pipeline/:id/status', ({ params }) => {
    const pipeline = mockPipelines.find(p => p.id === Number(params.id));
    if (!pipeline) {
      return HttpResponse.json(
        { success: false, error: 'Pipeline not found' },
        { status: 404 }
      );
    }
    return HttpResponse.json({
      success: true,
      data: pipeline,
    });
  }),

  // 创建 Pipeline
  http.post('/api/v1/pipeline', async ({ request }) => {
    const body = await request.json() as { description: string };
    const newPipeline: Pipeline = {
      id: mockPipelines.length + 1,
      description: body.description,
      status: 'RUNNING',
      current_stage: 'REQUIREMENT',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      stages: [],
    };
    mockPipelines.push(newPipeline);
    return HttpResponse.json({
      success: true,
      data: newPipeline,
    }, { status: 201 });
  }),

  // 审批 Pipeline
  http.post('/api/v1/pipeline/:id/approve', ({ params }) => {
    const pipeline = mockPipelines.find(p => p.id === Number(params.id));
    if (!pipeline) {
      return HttpResponse.json(
        { success: false, error: 'Pipeline not found' },
        { status: 404 }
      );
    }
    pipeline.status = 'RUNNING';
    pipeline.updated_at = new Date().toISOString();
    return HttpResponse.json({
      success: true,
      data: {
        pipeline_id: pipeline.id,
        previous_stage: pipeline.current_stage,
        next_stage: 'DESIGN',
        status: 'RUNNING',
      },
    });
  }),

  // 驳回 Pipeline
  http.post('/api/v1/pipeline/:id/reject', async ({ request, params }) => {
    const body = await request.json() as { reason: string };
    const pipeline = mockPipelines.find(p => p.id === Number(params.id));
    if (!pipeline) {
      return HttpResponse.json(
        { success: false, error: 'Pipeline not found' },
        { status: 404 }
      );
    }
    pipeline.status = 'RUNNING';
    pipeline.updated_at = new Date().toISOString();
    return HttpResponse.json({
      success: true,
      data: {
        pipeline_id: pipeline.id,
        current_stage: pipeline.current_stage,
        status: 'RUNNING',
        feedback: { reason: body.reason },
      },
    });
  }),

  // SSE 日志流
  http.get('/api/v1/pipeline/:id/logs', () => {
    // SSE 流在测试中返回空即可
    return new HttpResponse(null, { status: 200 });
  }),
];
