import { useEffect, useState } from 'react';
import { X, GitBranch as Github, ExternalLink, Sparkles, CheckCircle2, Copy, Check } from 'lucide-react';
import type { Pipeline } from '@types';

// ============================================
// Pipeline 完成弹窗组件
// ============================================

interface CompletionModalData {
  pipeline: Pipeline;
  prUrl: string;
  previewUrl?: string;
}

export function PipelineCompletionModal() {
  const [modalData, setModalData] = useState<CompletionModalData | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleCompleted = (e: CustomEvent<CompletionModalData>) => {
      setModalData(e.detail);
    };

    document.addEventListener('pipeline:completed', handleCompleted as EventListener);
    return () => {
      document.removeEventListener('pipeline:completed', handleCompleted as EventListener);
    };
  }, []);

  if (!modalData) return null;

  const { pipeline, prUrl, previewUrl } = modalData;

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleClose = () => {
    setModalData(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 遮罩层 */}
      <div
        className="absolute inset-0 bg-text-primary/50 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* 弹窗 */}
      <div className="relative w-full max-w-lg bg-bg-primary rounded-2xl shadow-feishu-hover overflow-hidden animate-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="relative bg-gradient-cta p-6 text-center">
          <button
            onClick={handleClose}
            className="absolute top-4 right-4 p-2 rounded-lg text-text-white/70 hover:text-text-white hover:bg-text-white/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>

          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-text-white/20 flex items-center justify-center">
            <Sparkles className="w-8 h-8 text-text-white" />
          </div>

          <h2 className="text-2xl font-bold text-text-white mb-2">
            ✨ AI 已完成修改！
          </h2>
          <p className="text-text-white/80">
            Pipeline #{pipeline.id} 所有阶段已执行完成
          </p>
        </div>

        {/* 内容 */}
        <div className="p-6 space-y-6">
          {/* 成功信息 */}
          <div className="flex items-start gap-4 p-4 bg-status-success/10 rounded-xl border border-status-success/20">
            <CheckCircle2 className="w-6 h-6 text-status-success flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-text-primary mb-1">代码已自动同步</h3>
              <p className="text-sm text-text-secondary">
                代码已自动 Push 到了 GitHub PR，请查看本地预览页面的热更新效果！
              </p>
            </div>
          </div>

          {/* 链接列表 */}
          <div className="space-y-3">
            {/* GitHub PR */}
            <div className="flex items-center justify-between p-4 bg-bg-secondary rounded-xl">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-gray-900 flex items-center justify-center">
                  <Github className="w-5 h-5 text-white" />
                </div>
                <div>
                  <p className="font-medium text-text-primary">查看 GitHub PR</p>
                  <p className="text-xs text-text-tertiary font-mono truncate max-w-[200px]">
                    {prUrl}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleCopy(prUrl)}
                  className="p-2 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
                  title="复制链接"
                >
                  {copied ? <Check className="w-4 h-4 text-status-success" /> : <Copy className="w-4 h-4" />}
                </button>
                <a
                  href={prUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-2 rounded-lg text-brand-primary hover:bg-brand-primary-light transition-colors"
                  title="在新窗口打开"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            </div>

            {/* 预览页面 */}
            {previewUrl ? (
              <div className="flex items-center justify-between p-4 bg-bg-secondary rounded-xl">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-brand-primary flex items-center justify-center">
                    <ExternalLink className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <p className="font-medium text-text-primary">本地预览页面</p>
                    <p className="text-xs text-text-tertiary font-mono truncate max-w-[200px]">
                      {previewUrl}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleCopy(previewUrl)}
                    className="p-2 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
                    title="复制链接"
                  >
                    {copied ? <Check className="w-4 h-4 text-status-success" /> : <Copy className="w-4 h-4" />}
                  </button>
                  <a
                    href={previewUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 rounded-lg text-brand-primary hover:bg-brand-primary-light transition-colors"
                    title="在新窗口打开"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </a>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between p-4 bg-bg-secondary rounded-xl opacity-60">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-brand-primary/50 flex items-center justify-center">
                    <ExternalLink className="w-5 h-5 text-white/70" />
                  </div>
                  <div>
                    <p className="font-medium text-text-primary">本地预览页面</p>
                    <p className="text-xs text-text-tertiary">预览环境暂未配置</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 统计信息 */}
          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-border-default">
            <div className="text-center">
              <p className="text-2xl font-bold text-brand-primary">{pipeline.stages.length}</p>
              <p className="text-xs text-text-tertiary">执行阶段</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-status-success">
                {Math.max(0, Math.round((new Date(pipeline.updated_at).getTime() - new Date(pipeline.created_at).getTime()) / 60000))}m
              </p>
              <p className="text-xs text-text-tertiary">执行耗时</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-text-primary">100%</p>
              <p className="text-xs text-text-tertiary">成功率</p>
            </div>
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 bg-bg-secondary border-t border-border-default">
          <button
            onClick={handleClose}
            className="px-5 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
          >
            稍后查看
          </button>
          <a
            href={prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary"
          >
            <Github className="w-4 h-4 mr-2" />
            查看 PR
          </a>
        </div>
      </div>
    </div>
  );
}
