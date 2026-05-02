import { Loader2 } from 'lucide-react';
import type { PipelineListItem } from '@types';

interface StatusBadgeProps {
  status: PipelineListItem['status'];
}

const config = {
  running: { class: 'bg-brand-primary-light text-brand-primary', label: '执行中' },
  paused: { class: 'bg-status-warning/10 text-status-warning', label: '等待审批' },
  success: { class: 'bg-status-success/10 text-status-success', label: '成功' },
  failed: { class: 'bg-status-error/10 text-status-error', label: '失败' },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const { class: className, label } = config[status] || config.running;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-sm text-xs font-medium ${className}`}>
      {status === 'running' && <Loader2 className="w-3 h-3 mr-1 animate-spin" />}
      {label}
    </span>
  );
}
