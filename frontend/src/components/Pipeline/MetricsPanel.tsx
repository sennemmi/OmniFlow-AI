import { Clock, ArrowRight, ArrowLeft, DollarSign, RefreshCw, Brain } from 'lucide-react';

// ============================================
// 可观测性面板 - 指标展示组件
// ============================================

interface PipelineStage {
  id: number;
  name: string;
  status: string;
  input_tokens?: number;
  output_tokens?: number;
  duration_ms?: number;
  retry_count?: number;
  reasoning?: string;
}

interface MetricsPanelProps {
  stage: PipelineStage;
}

// 计算成本（基于 GPT-4 价格估算）
function calculateCost(inputTokens: number, outputTokens: number): string {
  // GPT-4 价格：输入 $0.03/1K tokens，输出 $0.06/1K tokens
  const inputCost = (inputTokens / 1000) * 0.03;
  const outputCost = (outputTokens / 1000) * 0.06;
  const totalCost = inputCost + outputCost;
  return `$${totalCost.toFixed(4)}`;
}

// 格式化耗时
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

// 指标卡片组件
interface MetricCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
  subtitle?: string;
}

function MetricCard({ title, value, icon, color, subtitle }: MetricCardProps) {
  return (
    <div className="bg-bg-secondary rounded-lg p-4 border border-border-primary hover:border-brand-primary/50 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-text-secondary text-sm">{title}</span>
        <div className={color}>{icon}</div>
      </div>
      <div className="text-2xl font-semibold text-text-primary">{value}</div>
      {subtitle && <div className="text-xs text-text-tertiary mt-1">{subtitle}</div>}
    </div>
  );
}

// 推理过程展示组件
function ReasoningPanel({ reasoning }: { reasoning?: string }) {
  if (!reasoning) return null;

  return (
    <div className="mt-4 bg-bg-secondary rounded-lg p-4 border border-border-primary">
      <div className="flex items-center gap-2 mb-3">
        <Brain className="w-4 h-4 text-brand-primary" />
        <span className="text-sm font-medium text-text-primary">AI 推理过程</span>
      </div>
      <div className="bg-bg-tertiary rounded p-3 max-h-40 overflow-y-auto">
        <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono">
          {reasoning}
        </pre>
      </div>
    </div>
  );
}

export function MetricsPanel({ stage }: MetricsPanelProps) {
  const inputTokens = stage.input_tokens || 0;
  const outputTokens = stage.output_tokens || 0;
  const durationMs = stage.duration_ms || 0;
  const retryCount = stage.retry_count || 0;

  return (
    <div className="space-y-4">
      {/* 指标卡片网格 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="执行耗时"
          value={formatDuration(durationMs)}
          icon={<Clock className="w-5 h-5" />}
          color="text-blue-500"
          subtitle={durationMs > 0 ? `约 ${(durationMs / 1000).toFixed(1)} 秒` : '未开始'}
        />
        <MetricCard
          title="输入 Token"
          value={inputTokens.toLocaleString()}
          icon={<ArrowRight className="w-5 h-5" />}
          color="text-green-500"
          subtitle="Prompt 长度"
        />
        <MetricCard
          title="输出 Token"
          value={outputTokens.toLocaleString()}
          icon={<ArrowLeft className="w-5 h-5" />}
          color="text-purple-500"
          subtitle="生成内容"
        />
        <MetricCard
          title="成本预估"
          value={calculateCost(inputTokens, outputTokens)}
          icon={<DollarSign className="w-5 h-5" />}
          color="text-orange-500"
          subtitle="基于 GPT-4 价格"
        />
      </div>

      {/* 额外指标行 */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <MetricCard
          title="重试次数"
          value={retryCount}
          icon={<RefreshCw className="w-5 h-5" />}
          color={retryCount > 0 ? 'text-yellow-500' : 'text-gray-400'}
          subtitle={retryCount > 0 ? '发生过重试' : '一次通过'}
        />
        <MetricCard
          title="总 Token 数"
          value={(inputTokens + outputTokens).toLocaleString()}
          icon={<div className="w-5 h-5 flex items-center justify-center text-xs font-bold">Σ</div>}
          color="text-cyan-500"
          subtitle="输入 + 输出"
        />
        <MetricCard
          title="阶段状态"
          value={stage.status}
          icon={<div className="w-5 h-5 flex items-center justify-center text-xs">●</div>}
          color={
            stage.status === 'success' ? 'text-green-500' :
            stage.status === 'failed' ? 'text-red-500' :
            stage.status === 'running' ? 'text-blue-500' :
            'text-gray-400'
          }
          subtitle={stage.name}
        />
      </div>

      {/* 推理过程 */}
      <ReasoningPanel reasoning={stage.reasoning} />
    </div>
  );
}

export default MetricsPanel;
