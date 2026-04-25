import { useEffect, useRef, useState } from 'react';
import { Terminal, Cpu, Search, FileCode, AlertTriangle, CheckCircle, Sparkles, Pause, Info, Brain } from 'lucide-react';

// ============================================
// Agent 终端 - SSE 实时日志流组件
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
  info: 'text-text-secondary',
  thinking: 'text-brand-primary',
  action: 'text-status-warning',
  warning: 'text-status-warning',
  success: 'text-status-success',
  error: 'text-status-error',
  paused: 'text-brand-primary',
  thought: 'text-purple-400',
};

const typeBgColors = {
  info: 'bg-bg-tertiary',
  thinking: 'bg-brand-primary/10',
  action: 'bg-status-warning/10',
  warning: 'bg-status-warning/10',
  success: 'bg-status-success/10',
  error: 'bg-status-error/10',
  paused: 'bg-brand-primary/20',
  thought: 'bg-purple-500/10',
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
          <span className="w-2 h-2 rounded-full bg-brand-primary animate-pulse" />
          <span className="text-xs text-text-tertiary">等待审批</span>
        </span>
      );
    }
    if (isRunning && connectionStatus === 'connected') {
      return (
        <span className="flex items-center gap-1.5 ml-2">
          <span className="w-2 h-2 rounded-full bg-status-success animate-pulse" />
          <span className="text-xs text-text-tertiary">实时接收中</span>
        </span>
      );
    }
    if (connectionStatus === 'connecting') {
      return (
        <span className="flex items-center gap-1.5 ml-2">
          <span className="w-2 h-2 rounded-full bg-status-warning animate-pulse" />
          <span className="text-xs text-text-tertiary">连接中...</span>
        </span>
      );
    }
    return null;
  };

  return (
    <div className="bg-hero-dark-1 rounded-xl border border-border-default/20 overflow-hidden">
      {/* 终端头部 */}
      <div className="flex items-center justify-between px-4 py-3 bg-black/30 border-b border-border-default/20">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-brand-primary" />
          <span className="text-sm font-medium text-text-white">Agent 终端</span>
          {getStatusDisplay()}
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-status-error/80" />
          <div className="w-3 h-3 rounded-full bg-status-warning/80" />
          <div className="w-3 h-3 rounded-full bg-status-success/80" />
        </div>
      </div>

      {/* 日志内容区 */}
      <div
        ref={scrollRef}
        className="h-64 overflow-y-auto p-4 font-mono text-sm space-y-2 scrollbar-hide"
      >
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-text-tertiary">
            {connectionStatus === 'connecting' ? (
              <>
                <Sparkles className="w-4 h-4 mr-2 animate-pulse" />
                正在连接日志流...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4 mr-2 animate-pulse" />
                等待 Agent 启动...
              </>
            )}
          </div>
        ) : (
          logs.map((log, index) => {
            const Icon = typeIcons[log.type];
            const isLast = index === logs.length - 1;

            return (
              <div
                key={log.id}
                className={`flex items-start gap-3 p-2.5 rounded-lg transition-all duration-300 ${
                  typeBgColors[log.type]
                } ${isLast ? 'animate-in fade-in slide-in-from-left-2' : ''} ${
                  log.type === 'paused' ? 'border border-brand-primary/30' : ''
                }`}
              >
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${typeColors[log.type]}`} />
                <div className="flex-1 min-w-0">
                  <div className={`font-medium ${typeColors[log.type]}`}>
                    {isLast && isTyping && log.type !== 'paused' ? (
                      <TypewriterText text={log.message} />
                    ) : (
                      log.message
                    )}
                    {isLast && isRunning && log.type !== 'paused' && (
                      <span className="inline-block w-2 h-4 ml-1 bg-brand-primary animate-pulse" />
                    )}
                  </div>
                  {log.details && (
                    <div className={`text-xs mt-1 truncate ${
                      log.type === 'paused' ? 'text-brand-primary font-medium' : 'text-text-tertiary'
                    }`}>
                      {log.details}
                    </div>
                  )}
                </div>
                <span className="text-xs text-text-tertiary flex-shrink-0">
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

      {/* 底部状态栏 */}
      <div className="flex items-center justify-between px-4 py-2 bg-black/20 border-t border-border-default/20 text-xs">
        <div className="flex items-center gap-4">
          <span className="text-text-tertiary">
            日志: <span className="text-text-white">{logs.length}</span>
          </span>
          <span className="text-text-tertiary">
            阶段: <span className="text-brand-primary">{stageId ? stageToLabel(stageId) : '初始化'}</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Search className="w-3 h-3 text-text-tertiary" />
          <span className="text-text-tertiary">实时观测</span>
        </div>
      </div>
    </div>
  );
}
