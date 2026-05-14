import { memo } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import {
  Code,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Clock,
  FileText,
  Palette,
  GitBranch,
  Hand,
} from 'lucide-react';
import type { PipelineNodeData } from '@types';

// ============================================
// 流水线自定义节点 - React Flow（优化版）
// ============================================

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  FileText: FileText,
  Palette: Palette,
  Code: Code,
  CheckCircle2: CheckCircle2,
  GitBranch: GitBranch,
  default: Code,
};

// 【修复】统一前后端状态枚举
// 后端 PipelineStatus: running, paused, success, failed
// 后端 StageStatus: pending, running, success, failed
const statusConfig: Record<
  string,
  { icon: React.ComponentType<{ className?: string }>; className: string; label: string; indicatorClass: string }
> = {
  pending: { 
    icon: Clock, 
    className: 'text-text-tertiary bg-bg-tertiary', 
    label: '待执行',
    indicatorClass: 'pending'
  },
  running: { 
    icon: Loader2, 
    className: 'text-brand-primary bg-brand-primary-light', 
    label: '执行中',
    indicatorClass: 'running'
  },
  // 【修复】直接使用 success 状态，与后端保持一致
  success: {
    icon: CheckCircle2,
    className: 'text-status-success bg-status-success/10',
    label: '已完成',
    indicatorClass: 'success'
  },
  failed: { 
    icon: AlertCircle, 
    className: 'text-status-error bg-status-error/10', 
    label: '失败',
    indicatorClass: 'failed'
  },
  paused: {
    icon: Hand,
    className: 'text-status-warning bg-status-warning/10',
    label: '待审批',
    indicatorClass: 'pending'
  },
};

type PipelineFlowNode = Node<PipelineNodeData, 'pipelineNode'>;

function PipelineNodeComponent({ data, selected }: NodeProps<PipelineFlowNode>) {
  const { label, icon, status, description, onClick, isPendingApproval } = data;

  const IconComponent = iconMap[icon] || iconMap.default;
  const statusConfig_item = statusConfig[status] || statusConfig.pending;
  const StatusIcon = statusConfig_item.icon;
  const isRunning = status === 'running';

  // 根据状态确定节点样式
  const getNodeStyles = () => {
    if (isPendingApproval) {
      // 等待审批：橙色高亮边框
      return 'border-status-warning ring-2 ring-status-warning/30';
    }
    if (isRunning) {
      // 执行中：发光效果
      return 'node-running-glow';
    }
    if (status === 'pending') {
      // 未执行：降低透明度
      return 'border-border-card opacity-50';
    }
    return 'border-border-card hover:border-brand-primary/30';
  };

  return (
    <div
      className={`relative min-w-[160px] max-w-[200px] p-3 rounded-xl border bg-bg-primary shadow-feishu-card transition-all duration-250 cursor-pointer ${getNodeStyles()} ${
        selected ? 'ring-2 ring-brand-primary/20 shadow-feishu' : ''
      }`}
      onClick={onClick}
    >
      {/* 输入连接点 */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-3 !h-3 !bg-brand-primary !border-2 !border-bg-primary"
      />

      {/* 节点内容 */}
      <div className="flex items-start gap-2">
        {/* 图标 */}
        <div className={`w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0 ${
          isPendingApproval ? 'bg-status-warning/10' : 'bg-brand-primary-light'
        } ${isRunning ? 'node-icon-running' : ''}`}>
          <IconComponent className={`w-4 h-4 ${isPendingApproval ? 'text-status-warning' : 'text-brand-primary'}`} />
        </div>

        {/* 信息 */}
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-text-primary truncate">{label}</h4>
          {description && (
            <p className="text-xs text-text-tertiary mt-0.5 line-clamp-1">{description}</p>
          )}
        </div>
      </div>

      {/* 状态标签 */}
      <div className="mt-2 flex items-center justify-between">
        <span
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-xs font-medium ${statusConfig_item.className}`}
        >
          <StatusIcon className={`w-3 h-3 ${isRunning ? 'animate-spin' : ''}`} />
          {statusConfig_item.label}
        </span>

        {/* 待审批标签 */}
        {isPendingApproval && (
          <span className="text-xs font-medium text-status-warning flex items-center gap-1">
            <Hand className="w-3 h-3" />
            待审批
          </span>
        )}
      </div>

      {/* 状态指示器 - 右下角小圆点 */}
      <div className={`node-status-indicator ${statusConfig_item.indicatorClass}`} />

      {/* 执行中进度条 */}
      {isRunning && <div className="node-progress-bar" />}

      {/* 输出连接点 */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-3 !h-3 !bg-brand-primary !border-2 !border-bg-primary"
      />
    </div>
  );
}

export const PipelineNode = memo(PipelineNodeComponent);
