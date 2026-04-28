// ============================================
// OmniFlowAI 类型定义
// ============================================

// ---------- 全局 Window 扩展 ----------
declare global {
  interface Window {
    __OMNIFLOW_API_URL__?: string;
    OmniFlowAI?: {
      toggle: () => void;
      isActive: () => boolean;
      version: string;
      config: Record<string, unknown>;
    };
  }
}

// ---------- API 响应类型 ----------
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
  request_id: string;
}

// ---------- 流水线类型 ----------
// 与后端 PipelineStatus 枚举保持一致: running, paused, success, failed
export type PipelineStatus = 'running' | 'paused' | 'success' | 'failed';

// 阶段状态: pending, running, success, failed
export type StageStatus = 'pending' | 'running' | 'success' | 'failed';

// 交付物信息（与后端 PipelineDeliveryInfo 对齐）
export interface PipelineDeliveryInfo {
  git_branch?: string;
  commit_hash?: string;
  pr_url?: string;
  pr_created: boolean;
  summary: string;
  files_changed: Record<string, unknown>;
  diff_summary?: string;
}

// 阶段信息（与后端 PipelineStageInfo 对齐）
// 注意：icon, description, technical_design, duration 是前端扩展字段
export interface PipelineStage {
  id: number;
  name: string;
  status: StageStatus;
  icon?: string; // 前端扩展：图标名称
  description?: string; // 前端扩展：阶段描述
  technical_design?: string; // 前端扩展：从 output_data 提取的技术设计
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  created_at?: string;
  completed_at?: string;
  duration?: number; // 前端扩展：阶段耗时（秒）

  // 可观测性指标（与后端 PipelineStageRead 对齐）
  input_tokens?: number;
  output_tokens?: number;
  duration_ms?: number;
  retry_count?: number;
  reasoning?: string;
}

// Pipeline 列表项（与后端 PipelineListItem 对齐）
export interface PipelineListItem {
  id: number;
  description: string;
  status: PipelineStatus;
  current_stage: string | null;
  created_at: string;
}

// Pipeline 详情（与后端 PipelineStatusResponse 对齐）
export interface Pipeline {
  id: number;
  description: string;
  status: PipelineStatus;
  stages: PipelineStage[];
  current_stage: string | null;
  current_stage_index: number;
  created_at: string;
  updated_at: string;
  delivery?: PipelineDeliveryInfo;
}

// Pipeline 列表响应（与后端 PipelineListResponse 对齐）
export interface PipelineListResponse {
  total: number;
  pipelines: PipelineListItem[];
}

// 创建 Pipeline 请求（与后端 PipelineCreateRequest 对齐）
export interface CreatePipelineRequest {
  requirement: string;
  elementContext?: Record<string, unknown>;
}

// 创建 Pipeline 响应（与后端 PipelineCreateResponse 对齐）
export interface CreatePipelineResponse {
  pipeline_id: number;
  status: PipelineStatus;
  current_stage: string | null;
  created_at: string;
}

// ---------- 系统统计类型 ----------
export interface SystemStats {
  cpu_usage: number;
  memory_usage: number;
  total_pipelines: number;
  running_pipelines: number;
  completed_pipelines: number;
  failed_pipelines: number;
  avg_duration: number;
}

// ---------- 审批类型 ----------
// 审批请求（与后端 PipelineApproveRequest 对齐）
export interface ApproveRequest {
  notes?: string;
  feedback?: string;
}

// 审批响应（与后端 PipelineApproveResponse 对齐）
export interface ApproveResponse {
  pipeline_id: number;
  action: string;
  previous_stage: string | null;
  next_stage: string | null;
  notes?: string;
}

// 驳回请求（与后端 PipelineRejectRequest 对齐）
export interface RejectRequest {
  reason: string;
  suggested_changes?: string;
}

// 驳回响应（与后端 PipelineRejectResponse 对齐）
export interface RejectResponse {
  pipeline_id: number;
  action: string;
  current_stage: string | null;
  reason: string;
  retry_count: number;
}

// ---------- React Flow 节点类型 ----------
export interface PipelineNodeData {
  label: string;
  icon: string;
  status: PipelineStatus;
  description?: string;
  stageId: string;
  onClick?: () => void;
}

// ---------- 导航类型 ----------
export interface NavItem {
  id: string;
  label: string;
  icon: string;
  path: string;
}

// ---------- Feature 展示类型 ----------
export interface FeatureItem {
  id: string;
  title: string;
  description: string;
  icon: string;
  image?: string;
}
