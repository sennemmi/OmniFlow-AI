import { useState, useCallback, useRef, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';

const MIN_SPIN_DURATION = 1200;

interface RefreshButtonProps {
  onRefresh: () => void | Promise<void>;
}

export function RefreshButton({ onRefresh }: RefreshButtonProps) {
  const [spinning, setSpinning] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const handleClick = useCallback(async () => {
    if (spinning) return;
    setSpinning(true);

    onRefresh();

    timerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        setSpinning(false);
      }
      timerRef.current = null;
    }, MIN_SPIN_DURATION);
  }, [onRefresh, spinning]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <button
      onClick={handleClick}
      disabled={spinning}
      className="flex items-center justify-center w-10 h-10 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors flex-shrink-0 disabled:opacity-50"
      title="刷新"
    >
      <RefreshCw className={`w-5 h-5 ${spinning ? 'animate-spin' : ''}`} />
    </button>
  );
}
