import { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal, Cpu, Search, FileCode, AlertTriangle, CheckCircle, Pause, Brain, RefreshCw, Activity, Server, Gauge } from 'lucide-react';

// ============================================
// Agent Terminal - SSE Real-time Log Stream Component
// Professional light theme terminal design
// Enhanced with system metrics and error details
// ============================================

interface LogEntry {
  id: string;
  timestamp: Date;
  type: 'info' | 'thinking' | 'action' | 'warning' | 'success' | 'error' | 'paused' | 'thought' | 'system' | 'metrics';
  message: string;
  details?: string;
  isThought?: boolean;
  source?: string;
  extra?: Record<string, any>;
}

interface ThoughtLogProps {
  pipelineId: string;
  stageId?: string;
  status?: string;
  isRunning?: boolean;
}

// SSE log level mapping to UI type
function levelToType(level: string): LogEntry['type'] {
  const map: Record<string, LogEntry['type']> = {
    debug: 'info',
    info: 'info',
    warning: 'warning',
    error: 'error',
    success: 'success',
    thought: 'thought',
    system: 'system',
    metrics: 'metrics',
  };
  return map[level] ?? 'info';
}

// Stage name mapping to display text
function stageToLabel(stage: string): string {
  const map: Record<string, string> = {
    REQUIREMENT: 'Requirement Analysis',
    DESIGN: 'Technical Design',
    CODING: 'Code Generation',
    CODER: 'Code Generation',
    UNIT_TESTING: 'Layered Testing',
    TESTER: 'Layered Testing',
    CODE_REVIEW: 'Code Review',
    DELIVERY: 'Code Delivery',
    SYSTEM: 'System',
    METRICS: 'Metrics',
    ERROR: 'Error',
    STACK_TRACE: 'Stack Trace',
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
  system: Server,
  metrics: Gauge,
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
  system: 'text-cyan-600',
  metrics: 'text-orange-600',
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
  system: 'bg-cyan-50',
  metrics: 'bg-orange-50',
};

const typeLabels = {
  info: 'INFO',
  thinking: 'THINK',
  action: 'ACTION',
  warning: 'WARN',
  success: 'SUCCESS',
  error: 'ERROR',
  paused: 'PAUSED',
  thought: 'THOUGHT',
  system: 'SYSTEM',
  metrics: 'METRICS',
};

// Source colors
const sourceColors: Record<string, string> = {
  backend: 'border-l-blue-500',
  system: 'border-l-cyan-500',
  frontend: 'border-l-purple-500',
};

// Reconnect configuration
const RECONNECT_CONFIG = {
  initialDelay: 1000,
  maxDelay: 30000,
  maxAttempts: 10,
  backoffMultiplier: 2,
};

export function ThoughtLog({ pipelineId, stageId, status, isRunning: initialIsRunning = true }: ThoughtLogProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isRunning, setIsRunning] = useState(initialIsRunning);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'reconnecting'>('connecting');
  const [showSystemLogs, setShowSystemLogs] = useState(true);
  const [showMetrics, setShowMetrics] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const hasPausedRef = useRef(false);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_CONFIG.initialDelay);
  const reconnectAttemptRef = useRef(0);

  // Clear reconnect timeout
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // Establish SSE connection
  const connectSSE = useCallback(() => {
    if (!pipelineId) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    if (status === 'success' || status === 'failed') {
      setConnectionStatus('disconnected');
      setIsRunning(false);
      return;
    }

    setConnectionStatus(reconnectAttemptRef.current > 0 ? 'reconnecting' : 'connecting');

    const url = `/api/v1/pipeline/${pipelineId}/logs`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionStatus('connected');
      reconnectAttemptRef.current = 0;
      reconnectDelayRef.current = RECONNECT_CONFIG.initialDelay;
    };

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as { 
          ts: string; 
          level: string; 
          msg: string; 
          stage: string; 
          is_thought?: boolean;
          source?: string;
          [key: string]: any;
        };

        const entry: LogEntry = {
          id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
          timestamp: new Date(),
          type: levelToType(data.level),
          message: data.msg,
          details: stageToLabel(data.stage),
          isThought: data.is_thought,
          source: data.source || 'backend',
          extra: Object.fromEntries(
            Object.entries(data).filter(([k]) => !['ts', 'level', 'msg', 'stage', 'is_thought', 'source'].includes(k))
          ),
        };

        setLogs((prev) => {
          const newLogs = [...prev, entry];
          return newLogs.length > 500 ? newLogs.slice(-500) : newLogs;
        });

        setIsTyping(true);
        setTimeout(() => setIsTyping(false), 300);
      } catch (e) {
        console.error('Failed to parse SSE message:', e);
      }
    };

    es.addEventListener('done', () => {
      es.close();
      setIsRunning(false);
      setConnectionStatus('disconnected');
      clearReconnectTimeout();
    });

    es.onerror = () => {
      es.close();

      if (status === 'success' || status === 'failed') {
        setConnectionStatus('disconnected');
        return;
      }

      if (reconnectAttemptRef.current >= RECONNECT_CONFIG.maxAttempts) {
        setConnectionStatus('disconnected');
        console.error(`[ThoughtLog] SSE reconnect failed, max attempts reached (${RECONNECT_CONFIG.maxAttempts})`);
        return;
      }

      reconnectAttemptRef.current += 1;
      const currentAttempt = reconnectAttemptRef.current;
      setConnectionStatus('reconnecting');

      const delay = Math.min(
        reconnectDelayRef.current * Math.pow(RECONNECT_CONFIG.backoffMultiplier, currentAttempt - 1),
        RECONNECT_CONFIG.maxDelay
      );

      console.log(`[ThoughtLog] SSE disconnected, reconnecting in ${delay}ms (attempt ${currentAttempt})...`);

      reconnectTimeoutRef.current = setTimeout(() => {
        connectSSE();
      }, delay);
    };
  }, [pipelineId, status, clearReconnectTimeout]);

  // SSE connection management
  useEffect(() => {
    connectSSE();

    return () => {
      clearReconnectTimeout();
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [pipelineId, initialIsRunning, connectSSE, clearReconnectTimeout]);

  // Manual reconnect
  const handleManualReconnect = useCallback(() => {
    reconnectAttemptRef.current = 0;
    reconnectDelayRef.current = RECONNECT_CONFIG.initialDelay;
    connectSSE();
  }, [connectSSE]);

  // Handle paused state
  useEffect(() => {
    if (status === 'paused' && !hasPausedRef.current) {
      hasPausedRef.current = true;
      setLogs((currentLogs) => [
        ...currentLogs,
        {
          id: 'paused-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9),
          timestamp: new Date(),
          type: 'paused',
          message: 'Analysis complete - awaiting approval',
          details: 'Pipeline paused. Review the highlighted nodes for detailed proposals.',
          source: 'system',
        },
      ]);
    } else if (status === 'running' && hasPausedRef.current) {
      hasPausedRef.current = false;
    }
  }, [status]);

  // Auto scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  // Get connection status display
  const getConnectionStatus = () => {
    switch (connectionStatus) {
      case 'connected':
        return { text: 'LIVE', color: 'text-emerald-600', bg: 'bg-emerald-500', animate: true };
      case 'connecting':
        return { text: 'CONNECTING', color: 'text-amber-600', bg: 'bg-amber-500', animate: true };
      case 'reconnecting':
        return { text: `RECONNECTING ${reconnectAttemptRef.current}/${RECONNECT_CONFIG.maxAttempts}`, color: 'text-amber-600', bg: 'bg-amber-500', animate: true };
      default:
        return { text: 'OFFLINE', color: 'text-slate-400', bg: 'bg-slate-400', animate: false };
    }
  };

  const connStatus = getConnectionStatus();

  // Filter logs based on settings
  const filteredLogs = logs.filter(log => {
    if (log.type === 'system' && !showSystemLogs) return false;
    if (log.type === 'metrics' && !showMetrics) return false;
    return true;
  });

  // Format extra data for display
  const formatExtra = (extra?: Record<string, any>): string => {
    if (!extra) return '';
    const entries = Object.entries(extra).slice(0, 3);
    return entries.map(([k, v]) => `${k}=${v}`).join(' | ');
  };

  return (
    <div className="h-[600px] flex flex-col bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm">
      {/* Terminal Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-slate-500" />
            <span className="text-sm font-medium text-slate-800">Agent Terminal</span>
          </div>
          <div className="h-4 w-px bg-slate-300" />
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${connStatus.bg} ${connStatus.animate ? 'animate-pulse' : ''}`} />
            <span className={`text-xs font-mono ${connStatus.color}`}>{connStatus.text}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Filter toggles */}
          <div className="flex items-center gap-2 mr-2">
            <button
              onClick={() => setShowSystemLogs(!showSystemLogs)}
              className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
                showSystemLogs ? 'bg-cyan-100 text-cyan-700' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              <Server className="w-3 h-3" />
              <span className="font-mono">SYSTEM</span>
            </button>
            <button
              onClick={() => setShowMetrics(!showMetrics)}
              className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
                showMetrics ? 'bg-orange-100 text-orange-700' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              <Gauge className="w-3 h-3" />
              <span className="font-mono">METRICS</span>
            </button>
          </div>
          {connectionStatus === 'disconnected' && status !== 'success' && status !== 'failed' && (status === 'running' || status === 'paused') && (
            <button
              onClick={handleManualReconnect}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors"
              title="Reconnect log stream"
            >
              <RefreshCw className="w-3 h-3" />
              <span className="font-mono">RECONNECT</span>
            </button>
          )}
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-amber-400" />
            <div className="w-3 h-3 rounded-full bg-emerald-400" />
          </div>
        </div>
      </div>

      {/* Terminal Content */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-0 font-mono text-sm bg-white min-h-0 scrollbar-hide"
      >
        {filteredLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400">
            <Activity className="w-8 h-8 mb-3 opacity-50" />
            <p className="text-sm font-mono">
              {connectionStatus === 'connecting' ? 'Connecting to log stream...' :
               connectionStatus === 'reconnecting' ? `Reconnecting (${reconnectAttemptRef.current}/${RECONNECT_CONFIG.maxAttempts})...` :
               'Waiting for Agent to start...'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filteredLogs.map((log, index) => {
              const Icon = typeIcons[log.type];
              const isLast = index === filteredLogs.length - 1;
              const timeStr = log.timestamp.toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              });
              const sourceBorder = sourceColors[log.source || 'backend'] || 'border-l-slate-300';

              return (
                <div
                  key={log.id}
                  className={`flex items-start gap-3 px-4 py-2 hover:bg-slate-50 transition-colors border-l-2 ${sourceBorder} ${
                    isLast ? 'bg-blue-50/50' : ''
                  } ${log.type === 'error' ? 'bg-red-50/50' : ''}`}
                >
                  <span className="text-xs text-slate-400 flex-shrink-0 font-mono mt-0.5 w-16">
                    {timeStr}
                  </span>
                  <div className="flex items-center gap-2 flex-shrink-0 w-24">
                    <Icon className={`w-3.5 h-3.5 ${typeColors[log.type]}`} />
                    <span className={`text-xs font-mono font-semibold ${typeColors[log.type]}`}>
                      {typeLabels[log.type]}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className={`text-sm ${typeColors[log.type]} ${log.type === 'error' ? 'font-semibold' : ''}`}>
                      {log.message}
                      {isLast && isRunning && log.type !== 'paused' && (
                        <span className="inline-block w-2 h-4 ml-1 bg-blue-500 animate-pulse" />
                      )}
                    </span>
                    {log.details && log.details !== stageToLabel(log.details) && (
                      <span className="text-xs text-slate-400 ml-2">
                        [{log.details}]
                      </span>
                    )}
                    {log.extra && Object.keys(log.extra).length > 0 && (
                      <span className="text-xs text-slate-400 ml-2">
                        ({formatExtra(log.extra)})
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Terminal Footer */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-50 border-t border-slate-200 text-xs flex-shrink-0">
        <div className="flex items-center gap-6">
          <span className="text-slate-500 font-mono">
            LOGS: <span className="text-slate-700">{logs.length}</span>
            {logs.length !== filteredLogs.length && (
              <span className="text-slate-400"> ({filteredLogs.length} shown)</span>
            )}
          </span>
          <span className="text-slate-500 font-mono">
            STAGE: <span className="text-blue-600">{stageId ? stageToLabel(stageId).toUpperCase() : 'INIT'}</span>
          </span>
          <span className="text-slate-500 font-mono">
            STATUS: <span className={isRunning ? 'text-emerald-600' : 'text-slate-500'}>{isRunning ? 'RUNNING' : 'IDLE'}</span>
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-400">
          <Search className="w-3 h-3" />
          <span className="font-mono">LIVE STREAM</span>
        </div>
      </div>
    </div>
  );
}
