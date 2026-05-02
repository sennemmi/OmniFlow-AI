import { AlertCircle, CheckCircle2 } from 'lucide-react';
import type { PipelineListItem } from '@types';

interface PendingApprovalCardProps {
  pipeline: PipelineListItem;
  onClick: () => void;
}

export function PendingApprovalCard({ pipeline, onClick }: PendingApprovalCardProps) {
  return (
    <div
      onClick={onClick}
      className="relative flex items-center gap-4 p-4 bg-bg-primary rounded-xl border-l-4 border-status-warning shadow-feishu-card hover:shadow-feishu-hover transition-all cursor-pointer group"
    >
      {/* 呼吸闪烁指示灯 */}
      <div className="absolute top-4 right-4">
        <span className="relative flex h-3 w-3">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-warning opacity-75"></span>
          <span className="relative inline-flex rounded-full h-3 w-3 bg-status-warning"></span>
        </span>
      </div>

      <div className="w-12 h-12 rounded-xl bg-status-warning/10 flex items-center justify-center">
        <AlertCircle className="w-6 h-6 text-status-warning" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text-primary group-hover:text-brand-primary transition-colors">
            Pipeline #{pipeline.id}
          </h3>
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-status-warning/10 text-status-warning">
            待审批
          </span>
        </div>
        <p className="text-xs text-text-tertiary mt-1 truncate">{pipeline.description}</p>
        <p className="text-xs text-text-tertiary mt-0.5">
          {new Date(pipeline.created_at).toLocaleString('zh-CN')}
        </p>
      </div>

      <div className="flex items-center gap-2 text-status-warning">
        <span className="text-sm font-medium">点击审查</span>
        <CheckCircle2 className="w-4 h-4" />
      </div>
    </div>
  );
}
