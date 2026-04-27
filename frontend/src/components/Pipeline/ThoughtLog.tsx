import { useEffect, useRef, useState } from 'react';
import { Terminal, Cpu, Search, FileCode, AlertTriangle, CheckCircle, Sparkles, Pause, Brain } from 'lucide-react';

// ============================================
// Agent 终端 - SSE 实时日志流组件（浅色主题）
// ============================================

interface LogEntry {
  id: string;
  timestamp: Date;
  type: 'info' | 'thinking' | 'action' | 'warning' | 'success' | 'error' | 'paused' | 'thought';
  message: string;
  details?: string;
  isThought?: boolean;
}

interface ThoughtLogProps {
  pipelineId: string;
  stageId?: string;
  status?: string;
  isRunning?: boolean;
}

// SSE 日志级别映射到 UI 类型
function levelToType(level: string): LogEntry['type'] {
  const map: Record<string, LogEntry['type']> = {
    debug: 'info',
    info: 'info',
    warning: 'warning',
    error: 'error',
    success: 'success',
    thought: 'thought',
  };
  return map[level] ?? 'info';
}

// 阶段名称映射到显示文本
function stageToLabel(stage: string): string {
  const map: Record<string, string> = {
    REQUIREMENT: '需求分析',
    DESIGN: '技术设计',
    CODING: '代码生成',
    UNIT_TESTING: '单元测试',
    CODE_REVIEW: '代码审查',
    DELIVERY: '代码交付',
  };
  return map[stage] ?? stage;
}

const typeIcons = {
  info: Terminal,
  thinking: Cpu,
  action: FileCode,
  warning: AlertTriangle,
  success: CheckCircle,
  error: AlertTriangle,
  paused: Pause,
  thought: Brain,
};

const typeColors = {
  info: 'text-slate-600',
  thinking: 'text-blue-600',
  action: 'text-amber-600',
  warning: 'text-amber-600',
  success: 'text-emerald-600',
  error: 'text-red-600',
  paused: 'text-blue-600',
  thought: 'text-purple-600',
};

const typeBgColors = {
  info: 'bg-slate-50',
  thinking: 'bg-blue-50',
  action: 'bg-amber-50',
  warning: 'bg-amber-50',
  success: 'bg-emerald-50',
  error: 'bg-red-50',
  paused: 'bg-blue-50',
  thought: 'bg-purple-50',
};

const typeBorderColors = {
  info: 'border-slate-200',
  thinking: 'border-blue-200',
  action: 'border-amber-200',
  warning: 'border-amber-200',
  success: 'border-emerald-200',
  error: 'border-red-200',
  paused: 'border-blue-200',
  thought: 'border-purple-200',
};

// 打字机效果组件
function TypewriterText({ text, speed = 30 }: { text: string; speed?: number }) {
  const [displayText, setDisplayText] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    if (currentIndex < text.length) {
      const timeout = setTimeout(() => {
        setDisplayText((prev) => prev + text[currentIndex]);
        setCurrentIndex((prev) => prev + 1);
      }, speed);
      return () => clearTimeout(timeout);
    }
  }, [currentIndex, text, speed]);

  return <span>{displayText}</span>;
}

export function ThoughtLog({ pipelineId, stageId, status, isRunning: initialIsRunning = true }: ThoughtLogProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [hasPaused, setHasPaused] = useState(false);
  const [isRunning, setIsRunning] = useState(initialIsRunning);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // SSE 连接
  useEffect(() => {
    if (!pipelineId) return;

    // 清理之前的连接
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setConnectionStatus('connecting');
    setIsRunning(initialIsRunning);

    // 创建 SSE 连接
    const url = `/api/v1/pipeline/${pipelineId}/logs`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionStatus('connected');
    };

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as { ts: string; level: string; msg: string; stage: string; is_thought?: boolean };

        const entry: LogEntry = {
          id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
          timestamp: new Date(),
          type: levelToType(data.level),
          message: data.msg,
          details: stageToLabel(data.stage),
          isThought: data.is_thought,
        };

        setLogs((prev) => {
          // 最多保留 200 条日志
          const newLogs = [...prev, entry];
          return newLogs.length > 200 ? newLogs.slice(-200) : newLogs;
        });

        // 触发打字机效果
        setIsTyping(true);
        setTimeout(() => setIsTyping(false), 300);
      } catch (e) {
        console.error('Failed to parse SSE message:', e);
      }
    };

    // 监听 done 事件
    es.addEventListener('done', () => {
      es.close();
      setIsRunning(false);
      setConnectionStatus('disconnected');
    });

    es.onerror = () => {
      // SSE 断线时回退到显示最后状态，不崩溃
      setConnectionStatus('disconnected');
      es.close();
    };

    // 清理函数
    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [pipelineId, initialIsRunning]);

  // 当状态变为 paused 时，添加暂停提示
  useEffect(() => {
    if (status === 'paused' && !hasPaused) {
      setHasPaused(true);
      setLogs((currentLogs) => [
        ...currentLogs,
        {
          id: 'paused-' + Date.now(),
          timestamp: new Date(),
          type: 'paused',
          message: '【系统提示】分析已完成',
          details: '流水线已暂停，等待人类主驾驶审批。请点击左侧高亮的节点查看详细方案！',
        },
      ]);
    }
  }, [status, hasPaused]);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  // 根据状态显示不同的头部状态
  const getStatusDisplay = () => {
    if (status === 'paused') {
      return (
        <span className="flex items-center gap-1.5 ml-2">
          <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-xs text-slate-500">等待审批</span>
        </span>
      );
    }
    if (isRunning && connectionStatus === 'connected') {
      return (
        <span className="flex items-center gap-1.5 ml-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs text-slate-500">实时接收中</span>
        </span>
      );
    }
    if (connectionStatus === 'connecting') {
      return (
        <span className="flex items-center gap-1.5 ml-2">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          <span className="text-xs text-slate-500">连接中...</span>
        </span>
      );
    }
    return null;
  };

  return (
    <div className="h-full flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
      {/* 终端头部 - 浅色主题 */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
            <Terminal className="w-4 h-4 text-blue-600" />
          </div>
          <div>
            <span className="text-sm font-semibold text-slate-900">Agent 终端</span>
            {getStatusDisplay()}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-400" />
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
        </div>
      </div>

      {/* 日志内容区 - 浅色背景 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 font-mono text-sm space-y-2 scrollbar-hide bg-slate-50/50"
      >
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center mb-3">
              <Sparkles className="w-6 h-6 text-slate-400" />
            </div>
            <p className="text-sm">
              {connectionStatus === 'connecting' ? '正在连接日志流...' : '等待 Agent 启动...'}
            </p>
          </div>
        ) : (
          logs.map((log, index) => {
            const Icon = typeIcons[log.type];
            const isLast = index === logs.length - 1;

            return (
              <div
                key={log.id}
                className={`flex items-start gap-3 p-3 rounded-lg border transition-all duration-300 ${
                  typeBgColors[log.type]
                } ${typeBorderColors[log.type]} ${
                  isLast ? 'ring-1 ring-blue-200 shadow-sm' : ''
                }`}
              >
                <div className={`w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 ${typeBgColors[log.type]}`}>
                  <Icon className={`w-3.5 h-3.5 ${typeColors[log.type]}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className={`text-sm ${typeColors[log.type]}`}>
                    {isLast && isTyping && log.type !== 'paused' ? (
                      <TypewriterText text={log.message} />
                    ) : (
                      log.message
                    )}
                    {isLast && isRunning && log.type !== 'paused' && (
                      <span className="inline-block w-1.5 h-4 ml-1 bg-blue-500 animate-pulse rounded-sm" />
                    )}
                  </div>
                  {log.details && (
                    <div className={`text-xs mt-1 ${
                      log.type === 'paused' ? 'text-blue-600 font-medium' : 'text-slate-500'
                    }`}>
                      {log.details}
                    </div>
                  )}
                </div>
                <span className="text-xs text-slate-400 flex-shrink-0 font-mono">
                  {log.timestamp.toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* 底部状态栏 - 浅色 */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-white border-t border-slate-200 text-xs">
        <div className="flex items-center gap-4">
          <span className="text-slate-500">
            日志: <span className="text-slate-900 font-medium">{logs.length}</span>
          </span>
          <span className="text-slate-500">
            阶段: <span className="text-blue-600 font-medium">{stageId ? stageToLabel(stageId) : '初始化'}</span>
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Search className="w-3 h-3 text-slate-400" />
          <span className="text-slate-500">实时观测</span>
        </div>
      </div>
    </div>
  );
}
