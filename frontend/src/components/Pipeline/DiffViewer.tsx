import { useState, useEffect, useRef, useMemo } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
import { FileCode, ChevronDown, ChevronUp, Copy, Check, Loader2 } from 'lucide-react';

// ============================================
// 代码 Diff 对比组件 - Monaco Editor 版本
// ============================================

interface DiffViewerProps {
  oldCode: string;
  newCode: string;
  oldFileName?: string;
  newFileName?: string;
  language?: string;
  splitView?: boolean;
}

export function DiffViewer({
  oldCode,
  newCode,
  oldFileName = '原始代码',
  newFileName = '生成代码',
  language = 'python',
  splitView = true,
}: DiffViewerProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [viewMode, setViewMode] = useState<'split' | 'unified'>(splitView ? 'split' : 'unified');
  const [theme, setTheme] = useState<'vs' | 'vs-dark'>('vs');
  const [copied, setCopied] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const editorRef = useRef<editor.IStandaloneDiffEditor | null>(null);
  const mountedRef = useRef(true);

  // 用于强制 DiffEditor 干净重建的 key
  const editorKey = useMemo(
    () => `${language}-${oldCode.length}-${newCode.length}-${viewMode}-${Date.now()}`,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, oldCode.length, newCode.length, viewMode]
  );

  // 检测系统主题
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    setTheme(mediaQuery.matches ? 'vs-dark' : 'vs');

    const handleChange = (e: MediaQueryListEvent) => {
      setTheme(e.matches ? 'vs-dark' : 'vs');
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // 组件卸载时先释放编辑器再释放模型，避免 TextModel got disposed before DiffEditorWidget 报错
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (editorRef.current) {
        const ed = editorRef.current;
        editorRef.current = null;
        // 先保存模型引用再释放编辑器
        const originalModel = ed.getModel()?.original;
        const modifiedModel = ed.getModel()?.modified;
        ed.dispose();
        originalModel?.dispose();
        modifiedModel?.dispose();
      }
    };
  }, []);

  const handleCopy = () => {
    navigator.clipboard.writeText(newCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const stats = {
    added: newCode.split('\n').length - oldCode.split('\n').length,
    removed: 0,
    modified: Math.min(oldCode.split('\n').length, newCode.split('\n').length),
  };

  return (
    <div className="rounded-xl border border-border-default overflow-hidden bg-bg-primary">
      {/* 头部工具栏 */}
      <div className="flex items-center justify-between px-4 py-3 bg-bg-secondary border-b border-border-default">
        <div className="flex items-center gap-3">
          <FileCode className="w-5 h-5 text-brand-primary" />
          <div>
            <h4 className="text-sm font-medium text-text-primary">代码变更对比</h4>
            <p className="text-xs text-text-tertiary">
              {language.toUpperCase()} · {stats.modified} 行修改 ·
              <span className="text-status-success ml-1">+{stats.added > 0 ? stats.added : 0}</span>
              <span className="text-status-error ml-1">{stats.added < 0 ? stats.added : ''}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* 视图模式切换 */}
          <div className="flex items-center bg-bg-primary rounded-lg p-0.5 border border-border-default">
            <button
              onClick={() => setViewMode('split')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                viewMode === 'split'
                  ? 'bg-brand-primary text-text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              分栏
            </button>
            <button
              onClick={() => setViewMode('unified')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                viewMode === 'unified'
                  ? 'bg-brand-primary text-text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              合并
            </button>
          </div>

          {/* 主题切换 */}
          <button
            onClick={() => setTheme(theme === 'vs' ? 'vs-dark' : 'vs')}
            className="p-2 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
          >
            {theme === 'vs' ? '[深色]' : '[浅色]'}
          </button>

          {/* 复制按钮 */}
          <button
            onClick={handleCopy}
            className="p-2 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
            title="复制新代码"
          >
            {copied ? <Check className="w-4 h-4 text-status-success" /> : <Copy className="w-4 h-4" />}
          </button>

          {/* 展开/折叠 */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-2 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors"
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Diff 内容 */}
      {isExpanded && (
        <div className="relative" style={{ height: '360px' }}>
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-bg-primary z-10">
              <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
            </div>
          )}
          <DiffEditor
            key={editorKey}
            height="360px"
            language={language}
            original={oldCode}
            modified={newCode}
            theme={theme}
            beforeMount={(monaco) => {
              // 禁用 Monaco 自带的模型自动释放，由我们手动管理生命周期
              monaco.editor.getModels().forEach((model) => model.dispose());
            }}
            onMount={(editor) => {
              editorRef.current = editor;
              if (mountedRef.current) {
                setIsLoading(false);
              }
            }}
            options={{
              readOnly: true,
              renderSideBySide: viewMode === 'split',
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
              lineNumbers: 'on',
              wordWrap: 'on',
              originalEditable: false,
            }}
            loading={
              <div className="flex items-center justify-center h-full">
                <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
              </div>
            }
          />
        </div>
      )}

      {/* 底部信息 */}
      {isExpanded && (
        <div className="flex items-center justify-between px-4 py-2 bg-bg-secondary border-t border-border-default text-xs">
          <div className="flex items-center gap-4">
            <span className="text-text-secondary">
              原始: <span className="text-text-primary font-medium">{oldFileName}</span>
              <span className="ml-1 text-text-tertiary">({oldCode.split('\n').length} 行)</span>
            </span>
            <span className="text-text-secondary">
              生成: <span className="text-text-primary font-medium">{newFileName}</span>
              <span className="ml-1 text-text-tertiary">({newCode.split('\n').length} 行)</span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-status-success">
              <span className="w-2 h-2 rounded-full bg-status-success" />
              新增
            </span>
            <span className="inline-flex items-center gap-1 text-status-error">
              <span className="w-2 h-2 rounded-full bg-status-error" />
              删除
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
