import { useState, useCallback } from 'react';
import { Edit3, Play, X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { apiPost } from '@utils/axios';
import { useUIStore } from '@stores/uiStore';
import { UserDecisionPanel } from './UserDecisionPanel';

// ============================================
// 测试用例编辑器 - 允许人工修改 AI 生成的测试代码
// ============================================

interface TestCaseEditorProps {
  pipelineId: number;
  filePath: string;
  initialContent: string;
  language?: string;
  onSave?: (newContent: string) => void;
  onTestRun?: (success: boolean, result: any) => void;
}

interface OverrideTestResult {
  test_run_success: boolean;
  message?: string;
  logs?: string;
  summary?: string;
  failed_tests?: string[];
  layers?: Array<{ layer: string; passed: boolean; summary: string }>;
}

export function TestCaseEditor({
  pipelineId,
  filePath,
  initialContent,
  language = 'python',
  onSave,
  onTestRun
}: TestCaseEditorProps) {
  const [content, setContent] = useState(initialContent);
  const [isEditing, setIsEditing] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [lastResult, setLastResult] = useState<{
    success: boolean;
    message: string;
    layers?: Array<{ layer: string; passed: boolean; summary: string }>;
  } | null>(null);
  const { addToast } = useUIStore();

  // 开始编辑
  const handleStartEdit = useCallback(() => {
    setIsEditing(true);
    setLastResult(null);
  }, []);

  // 取消编辑
  const handleCancelEdit = useCallback(() => {
    setContent(initialContent);
    setIsEditing(false);
    setLastResult(null);
  }, [initialContent]);

  // 保存修改并重跑测试
  const handleSaveAndRun = useCallback(async () => {
    if (!content.trim()) {
      addToast({ type: 'warning', message: '测试代码不能为空' });
      return;
    }

    setIsRunning(true);
    setLastResult(null);

    try {
      const response = await apiPost<OverrideTestResult>(`/pipeline/${pipelineId}/override-test`, {
        file_path: filePath,
        content: content
      });

      const testRunSuccess = response.test_run_success;
      const message = response.message || '测试执行完成';
      const layers = response.layers;

      setLastResult({
        success: testRunSuccess,
        message,
        layers
      });

      addToast({
        type: testRunSuccess ? 'success' : 'warning',
        message: testRunSuccess ? '测试全部通过！' : message
      });

      onSave?.(content);
      onTestRun?.(testRunSuccess, response);
    } catch (error) {
      addToast({
        type: 'error',
        message: `保存失败: ${error instanceof Error ? error.message : '请重试'}`
      });
    } finally {
      setIsRunning(false);
    }
  }, [pipelineId, filePath, content, addToast, onSave, onTestRun]);

  // 获取语言对应的 Monaco Editor 语言标识
  const getMonacoLanguage = (lang: string) => {
    const langMap: Record<string, string> = {
      'python': 'python',
      'py': 'python',
      'javascript': 'javascript',
      'js': 'javascript',
      'typescript': 'typescript',
      'ts': 'typescript',
      'java': 'java',
      'go': 'go',
      'rust': 'rust',
    };
    return langMap[lang.toLowerCase()] || 'python';
  };

  return (
    <div className="space-y-3">
      {/* 编辑器头部 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Edit3 className="w-4 h-4 text-brand-primary" />
          <span className="text-sm font-medium text-text-primary">测试用例编辑器</span>
          <span className="text-xs text-text-tertiary">({filePath})</span>
        </div>

        <div className="flex items-center gap-2">
          {!isEditing ? (
            <button
              onClick={handleStartEdit}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-primary bg-brand-primary-light rounded-lg hover:bg-brand-primary/20 transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5" />
              编辑测试
            </button>
          ) : (
            <>
              <button
                onClick={handleCancelEdit}
                disabled={isRunning}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary bg-bg-tertiary rounded-lg hover:text-text-primary transition-colors disabled:opacity-50"
              >
                <X className="w-3.5 h-3.5" />
                取消
              </button>
              <button
                onClick={handleSaveAndRun}
                disabled={isRunning}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-brand-primary rounded-lg hover:bg-brand-primary-hover transition-colors disabled:opacity-50"
              >
                {isRunning ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" />运行中...</>
                ) : (
                  <><Play className="w-3.5 h-3.5" />保存并重跑</>
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 代码编辑区 */}
      <div className="relative">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          disabled={!isEditing || isRunning}
          spellCheck={false}
          className={`w-full h-64 px-4 py-3 font-mono text-sm rounded-lg border resize-none focus:outline-none transition-all ${
            isEditing
              ? 'bg-bg-primary border-brand-primary focus:ring-2 focus:ring-brand-primary/20 text-text-primary'
              : 'bg-bg-secondary border-border-default text-text-secondary cursor-default'
          } disabled:opacity-60`}
          style={{
            fontFamily: '"JetBrains Mono", "Fira Code", "Consolas", monospace',
            lineHeight: '1.6',
            tabSize: 4,
          }}
        />

        {/* 语言标识 */}
        <span className="absolute top-2 right-2 px-2 py-0.5 text-xs text-text-tertiary bg-bg-tertiary rounded">
          {getMonacoLanguage(language)}
        </span>
      </div>

      {/* 编辑提示 */}
      {isEditing && (
        <div className="p-3 bg-brand-primary-light rounded-lg text-xs text-brand-primary">
          <div className="flex items-start gap-2">
            <Edit3 className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">编辑模式</p>
              <p className="text-text-secondary mt-0.5">
                您可以修改测试代码（如调整断言的预期值），然后点击"保存并重跑"验证修改。
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 测试结果 */}
      {lastResult && (
        <div className={`p-4 rounded-lg border ${
          lastResult.success
            ? 'bg-status-success/10 border-status-success/30'
            : 'bg-status-warning/10 border-status-warning/30'
        }`}>
          <div className="flex items-start gap-3">
            {lastResult.success ? (
              <CheckCircle2 className="w-5 h-5 text-status-success flex-shrink-0 mt-0.5" />
            ) : (
              <AlertCircle className="w-5 h-5 text-status-warning flex-shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h4 className={`text-sm font-medium ${
                lastResult.success ? 'text-status-success' : 'text-status-warning'
              }`}>
                {lastResult.success ? '✅ 测试通过' : '⚠️ 测试未通过'}
              </h4>
              <p className="text-xs text-text-secondary mt-1">{lastResult.message}</p>

              {/* 分层测试结果 */}
              {lastResult.layers && lastResult.layers.length > 0 && (
                <div className="mt-3 space-y-1">
                  {lastResult.layers.map((layer, idx) => (
                    <div
                      key={idx}
                      className={`flex items-center gap-2 text-xs px-2 py-1 rounded ${
                        layer.passed
                          ? 'bg-status-success/10 text-status-success'
                          : 'bg-status-error/10 text-status-error'
                      }`}
                    >
                      {layer.passed ? (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      ) : (
                        <AlertCircle className="w-3.5 h-3.5" />
                      )}
                      <span className="font-medium">{layer.layer}:</span>
                      <span>{layer.summary}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 【新增】测试失败时显示用户决策选项 */}
      {lastResult && !lastResult.success && (
        <UserDecisionPanel
          pipelineId={pipelineId}
          title="用户修改的测试未通过"
          message="您修改的测试用例未能通过测试，您可以选择以下操作："
          suggestion="建议检查测试逻辑是否正确，或选择其他操作"
        />
      )}
    </div>
  );
}
