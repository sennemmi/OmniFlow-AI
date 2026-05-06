import { useEffect, useRef, useState } from 'react';
import { GitPullRequest, Clock, CheckCircle2, Globe, TrendingUp } from 'lucide-react';

interface StatItemProps {
  icon: React.ReactNode;
  value: string;
  label: string;
  suffix?: string;
  delay?: number;
}

function StatItem({ icon, value, label, suffix = '', delay = 0 }: StatItemProps) {
  const [count, setCount] = useState(0);
  const [isVisible, setIsVisible] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
        }
      },
      { threshold: 0.3 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible) return;

    const numericValue = parseInt(value.replace(/[^0-9]/g, ''));
    const duration = 2000;
    const steps = 60;
    const increment = numericValue / steps;
    let current = 0;

    const timer = setTimeout(() => {
      const interval = setInterval(() => {
        current += increment;
        if (current >= numericValue) {
          setCount(numericValue);
          clearInterval(interval);
        } else {
          setCount(Math.floor(current));
        }
      }, duration / steps);

      return () => clearInterval(interval);
    }, delay);

    return () => clearTimeout(timer);
  }, [isVisible, value, delay]);

  const displayValue = value.replace(/[0-9]+/, count.toString());

  return (
    <div
      ref={ref}
      className={`group relative overflow-hidden rounded-2xl bg-white p-8 shadow-lg transition-all duration-500 hover:-translate-y-2 hover:shadow-2xl ${
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'
      }`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {/* Icon */}
      <div className="relative mb-6 inline-flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 text-white shadow-lg transition-transform duration-500 group-hover:scale-110">
        {icon}
      </div>

      {/* Value */}
      <div className="relative">
        <div className="flex items-baseline gap-1">
          <span className="text-4xl font-bold text-blue-600 tracking-tight">
            {displayValue}
          </span>
          {suffix && (
            <span className="text-2xl font-semibold text-blue-600">{suffix}</span>
          )}
        </div>
        <p className="mt-2 text-sm font-medium text-gray-500">{label}</p>
      </div>

      {/* Decorative line */}
      <div className="absolute bottom-0 left-0 h-1 w-0 bg-gradient-to-r from-blue-500 to-blue-600 transition-all duration-500 group-hover:w-full" />
    </div>
  );
}

export function Stats() {
  const stats = [
    {
      icon: <GitPullRequest className="h-6 w-6" />,
      value: '10000',
      label: '流水线执行',
      suffix: '+',
    },
    {
      icon: <Clock className="h-6 w-6" />,
      value: '3.5',
      label: '平均构建时间',
      suffix: 'min',
    },
    {
      icon: <CheckCircle2 className="h-6 w-6" />,
      value: '99',
      label: '部署成功率',
      suffix: '%',
    },
    {
      icon: <Globe className="h-6 w-6" />,
      value: '30',
      label: '覆盖国家',
      suffix: '+',
    },
  ];

  return (
    <section className="relative overflow-hidden bg-gradient-to-b from-gray-50 to-white py-24">
      {/* Background decorations */}
      <div className="absolute left-0 top-0 -translate-x-1/2 -translate-y-1/2 h-96 w-96 rounded-full bg-blue-100/50 blur-3xl" />
      <div className="absolute right-0 bottom-0 translate-x-1/2 translate-y-1/2 h-96 w-96 rounded-full bg-purple-100/50 blur-3xl" />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mx-auto max-w-3xl text-center mb-16">
          <div className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-4 py-2 text-sm font-medium text-blue-600 mb-6">
            <TrendingUp className="h-4 w-4" />
            数据见证实力
          </div>
          <h2 className="text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl mb-6">
            用数据说话
          </h2>
          <p className="text-lg text-gray-600 leading-relaxed">
            我们的平台已经帮助数千家企业实现数字化转型，
            <br className="hidden sm:block" />
            显著提升研发效率，降低运营成本
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat, index) => (
            <StatItem
              key={stat.label}
              icon={stat.icon}
              value={stat.value}
              label={stat.label}
              suffix={stat.suffix}
              delay={index * 100}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
