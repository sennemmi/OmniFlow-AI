import { useState } from 'react';
import { Code2, FilePlus, FileEdit, FileMinus, GitCommit } from 'lucide-react';
import { DiffViewer } from './DiffViewer';
import { getLanguageFromPath } from '@utils/formatters';
import { extractAllCodeChanges, type CodeChange } from '@utils/pipelineHelpers';

// ============================================
// 代码生成阶段面板 - 展示 CoderAgent 输出
// 【修复】统一调用 pipelineHelpers，消除重复提取逻辑
// ============================================

interface CodingPanelProps {
  outputData?: Record<string, unknown>;
}

export function CodingPanel({ outputData }: CodingPanelProps) {
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);

  // 【修复】直接复用 pipelineHelpers 中的提取函数
  const codeChanges: CodeChange[] = extractAllCodeChanges(outputData);

  // 【修复】从多种可能的字段路径提取摘要
  const summary = (() => {
    if (!outputData) return undefined;
    // 优先从 coder_output.summary 提取
    const coderOutput = outputData.coder_output as Record<string, unknown> | undefined;
    return (coderOutput?.summary as string) || (outputData.summary as string) || undefined;
  })();

  // 统计变更
  const stats = {
    added: codeChanges.filter(c => c.changeType === 'add').length,
    modified: codeChanges.filter(c => c.changeType === 'modify').length,
    deleted: codeChanges.filter(c => c.changeType === 'delete').length,
  };

  const currentChange = codeChanges[selectedFileIndex];

  if (codeChanges.length === 0) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无代码变更数据
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 变更摘要 */}
      {summary && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <GitCommit className="w-4 h-4 text-brand-primary" />
            变更摘要
          </h4>
          <div className="p-3 bg-bg-secondary rounded-lg border border-border-default">
            <p className="text-sm text-text-secondary">
              {summary}
            </p>
          </div>
        </div>
      )}

      {/* 变更统计 */}
      <div className="flex items-center gap-4 p-3 bg-bg-secondary rounded-lg">
        <div className="flex items-center gap-2">
          <FilePlus className="w-4 h-4 text-status-success" />
          <span className="text-sm text-text-secondary">
            新增 <span className="font-medium text-status-success">{stats.added}</span> 个文件
          </span>
        </div>
        <div className="w-px h-4 bg-border-default" />
        <div className="flex items-center gap-2">
          <FileEdit className="w-4 h-4 text-status-warning" />
          <span className="text-sm text-text-secondary">
            修改 <span className="font-medium text-status-warning">{stats.modified}</span> 个文件
          </span>
        </div>
        <div className="w-px h-4 bg-border-default" />
        <div className="flex items-center gap-2">
          <FileMinus className="w-4 h-4 text-status-error" />
          <span className="text-sm text-text-secondary">
            删除 <span className="font-medium text-status-error">{stats.deleted}</span> 个文件
          </span>
        </div>
        <div className="flex-1" />
        <div className="text-sm text-text-tertiary">
          共 {codeChanges.length} 个文件
        </div>
      </div>

      {/* 文件选择 Tab */}
      {codeChanges.length > 1 && (
        <div className="flex gap-1 overflow-x-auto pb-1">
          {codeChanges.map((change, i) => (
            <button
              key={change.fileName}
              onClick={() => setSelectedFileIndex(i)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono whitespace-nowrap transition-colors
                ${i === selectedFileIndex
                  ? 'bg-brand-primary text-white'
                  : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'
                }`}
            >
              {change.changeType === 'add' && <span className="text-status-success font-bold">+</span>}
              {change.changeType === 'modify' && <span className="text-status-warning">~</span>}
              {change.changeType === 'delete' && <span className="text-status-error font-bold">-</span>}
              {change.fileName.split('/').pop()}
            </button>
          ))}
        </div>
      )}

      {/* Diff 查看器 */}
      {currentChange && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-3 py-2 bg-bg-secondary rounded-lg">
            <Code2 className="w-4 h-4 text-brand-primary" />
            <code className="text-xs text-text-secondary flex-1 truncate">
              {currentChange.fileName}
            </code>
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${
              currentChange.changeType === 'add'
                ? 'bg-status-success/10 text-status-success'
                : currentChange.changeType === 'delete'
                ? 'bg-status-error/10 text-status-error'
                : 'bg-status-warning/10 text-status-warning'
            }`}>
              {currentChange.changeType === 'add' ? '新增' : currentChange.changeType === 'delete' ? '删除' : '修改'}
            </span>
          </div>
          <DiffViewer
            oldCode={currentChange.oldCode}
            newCode={currentChange.newCode}
            oldFileName={currentChange.changeType === 'add' ? '/dev/null' : currentChange.fileName}
            newFileName={currentChange.changeType === 'delete' ? '/dev/null' : currentChange.fileName}
            language={getLanguageFromPath(currentChange.fileName)}
            splitView={true}
          />
        </div>
      )}
    </div>
  );
}
