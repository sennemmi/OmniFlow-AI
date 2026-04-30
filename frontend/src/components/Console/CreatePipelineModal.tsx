import { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, LayoutGrid, List, Command, Loader2 } from 'lucide-react';
import { apiPost } from '@utils/axios';
import { useUIStore } from '@stores/uiStore';
import { TemplateGrid, type Template } from './TemplateGrid';
import type { CreatePipelineResponse } from '@types';

interface CreatePipelineModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTemplate?: Template | null;
}

export function CreatePipelineModal({ isOpen, onClose, initialTemplate }: CreatePipelineModalProps) {
  const [name, setName] = useState(initialTemplate?.title || '');
  const [description, setDescription] = useState(initialTemplate?.description || '');
  const [prompt, setPrompt] = useState(initialTemplate?.prompt || '');
  const [activeTab, setActiveTab] = useState<'template' | 'custom'>(initialTemplate ? 'custom' : 'template');
  const { addToast } = useUIStore();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // 当 initialTemplate 变化时更新表单
  const prevTemplateRef = useRef(initialTemplate);
  useEffect(() => {
    if (initialTemplate && initialTemplate !== prevTemplateRef.current) {
      prevTemplateRef.current = initialTemplate;
      setName(initialTemplate.title);
      setDescription(initialTemplate.description);
      setPrompt(initialTemplate.prompt);
      setActiveTab('custom');
    }
  }, [initialTemplate]);

  const createMutation = useMutation({
    mutationFn: (data: { requirement: string; elementContext?: Record<string, unknown> }) =>
      apiPost<CreatePipelineResponse>('/pipeline/create', data),
    onSuccess: (response) => {
      console.log('[CreatePipeline] 创建成功，响应:', response);
      addToast({ type: 'success', message: '流水线创建成功' });
      queryClient.invalidateQueries({ queryKey: ['pipelines'] });
      onClose();
      // 后端返回的 ID 字段名为 pipeline_id
      const pipelineId = response?.pipeline_id;
      if (pipelineId) {
        navigate(`/console/pipelines/${pipelineId}`);
      } else {
        console.error('[CreatePipeline] 响应中未找到 pipeline_id:', response);
        addToast({ type: 'error', message: '未能获取到流水线 ID' });
      }
    },
    onError: (error) => {
      console.error('[CreatePipeline] 创建失败:', error);
      addToast({ type: 'error', message: `创建失败: ${error.message || '请重试'}` });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;
    // 适配后端 API：requirement 对应 prompt，name 和 description 合并到 requirement
    const requirement = `${name}\n\n${description || ''}\n\n需求详情：${prompt}`;
    createMutation.mutate({
      requirement,
      elementContext: undefined
    });
  };

  // Cmd+Enter 快捷提交
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        if (name.trim() && prompt.trim()) {
          const requirement = `${name}\n\n${description || ''}\n\n需求详情：${prompt}`;
          createMutation.mutate({ requirement });
        }
      }
    },
    [name, description, prompt, createMutation]
  );

  // 选择模板
  const handleSelectTemplate = (template: Template) => {
    setName(template.title);
    setDescription(template.description);
    setPrompt(template.prompt);
    setActiveTab('custom');
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-text-primary/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-bg-primary rounded-2xl shadow-feishu-hover overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-default">
          <h2 className="text-xl font-semibold text-text-primary">创建新流水线</h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-secondary transition-colors"
          >
            <span className="sr-only">关闭</span>
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 标签切换 */}
        <div className="flex items-center gap-1 px-6 pt-4">
          <button
            onClick={() => setActiveTab('template')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'template'
                ? 'bg-brand-primary-light text-brand-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
            }`}
          >
            <LayoutGrid className="w-4 h-4" />
            选择模板
          </button>
          <button
            onClick={() => setActiveTab('custom')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'custom'
                ? 'bg-brand-primary-light text-brand-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
            }`}
          >
            <List className="w-4 h-4" />
            自定义需求
          </button>
        </div>

        {/* 内容区 */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
          {activeTab === 'template' ? (
            <TemplateGrid onSelectTemplate={handleSelectTemplate} />
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4 max-w-lg">
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">名称</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="输入流水线名称"
                  className="input-feishu"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">描述</label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="输入流水线描述（可选）"
                  className="input-feishu"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  需求描述
                  <span className="text-status-error ml-1">*</span>
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="描述您想要实现的功能，AI 将自动设计技术方案并生成代码..."
                  className="input-feishu h-40 resize-none"
                />
                <p className="text-xs text-text-tertiary mt-2 flex items-center gap-1">
                  <Command className="w-3 h-3" />
                  + Enter 快速创建
                </p>
              </div>
            </form>
          )}
        </div>

        {/* 底部按钮 */}
        {activeTab === 'custom' && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-default bg-bg-secondary">
            <button type="button" onClick={onClose} className="btn-ghost">
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!name.trim() || !prompt.trim() || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  创建中...
                </>
              ) : (
                '创建流水线'
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
