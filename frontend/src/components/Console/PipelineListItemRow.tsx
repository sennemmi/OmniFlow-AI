import { GitBranch } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import type { PipelineListItem } from '@types';

interface PipelineListItemRowProps {
  pipeline: PipelineListItem;
  onClick: () => void;
}

export function PipelineListItemRow({ pipeline, onClick }: PipelineListItemRowProps) {
  return (
    <div
      onClick={onClick}
      className="flex items-center justify-between p-3 hover:bg-bg-secondary/50 transition-colors cursor-pointer group border-b border-border-default last:border-b-0"
    >
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-bg-tertiary flex items-center justify-center">
          <GitBranch className="w-4 h-4 text-text-tertiary" />
        </div>
        <div>
          <h3 className="text-sm font-medium text-text-primary group-hover:text-brand-primary transition-colors">
            #{pipeline.id}
          </h3>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <p className="text-xs text-text-tertiary truncate max-w-[200px]">
          {pipeline.description}
        </p>
        <span className="text-xs text-text-tertiary w-24 text-right">
          {new Date(pipeline.created_at).toLocaleDateString('zh-CN')}
        </span>
        <StatusBadge status={pipeline.status} />
      </div>
    </div>
  );
}
