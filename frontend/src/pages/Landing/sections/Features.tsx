import { useState, useEffect } from 'react';
import {
  Sparkles,
  MousePointer2,
  Workflow,
  Shield,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react';
import { coreFeatures, TrendingUp } from '../data';

export function Features() {
  const [activeTab, setActiveTab] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveTab((prev) => (prev + 1) % coreFeatures.length);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="py-24">
      <div className="container-feishu">
        <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
            <Sparkles className="w-4 h-4" />
            主要功能
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
            AI 重新定义研发流程
          </h2>
          <p className="text-text-secondary text-lg">
            从需求到部署，每一个环节都有 AI 的智能加持，让研发效率实现质的飞跃
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* 左侧标签 */}
          <div className="space-y-4">
            {coreFeatures.map((feature, index) => {
              const Icon = feature.icon;
              const isActive = activeTab === index;
              return (
                <button
                  key={feature.id}
                  onClick={() => setActiveTab(index)}
                  className={`w-full text-left p-6 rounded-2xl border-2 transition-all duration-300 ${
                    isActive
                      ? 'border-brand-primary bg-brand-primary/5 shadow-lg shadow-brand-primary/10'
                      : 'border-border-default hover:border-brand-primary/30 hover:bg-bg-primary'
                  }`}
                >
                  <div className="flex items-start gap-4">
                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${feature.color} flex items-center justify-center flex-shrink-0`}>
                      <Icon className="w-6 h-6 text-white" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="text-lg font-semibold text-text-primary">{feature.title}</h3>
                        {isActive && <ChevronRight className="w-5 h-5 text-brand-primary" />}
                      </div>
                      <p className="text-text-secondary text-sm mb-3">{feature.description}</p>
                      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-xs font-medium">
                        <TrendingUp className="w-3 h-3" />
                        {feature.stats.label}: {feature.stats.value}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* 右侧展示 */}
          <div className="relative animate-on-scroll">
            <div className="aspect-square rounded-3xl bg-gradient-to-br from-slate-900 to-slate-800 p-8 shadow-2xl">
              {activeTab === 0 && (
                <div className="h-full flex flex-col">
                  <div className="flex items-center gap-3 mb-6">
                    <Sparkles className="w-8 h-8 text-purple-400" />
                    <span className="text-white font-semibold text-xl">AI 代码生成</span>
                  </div>
                  <div className="flex-1 rounded-xl bg-black/40 p-4 font-mono text-sm overflow-hidden">
                    <div className="text-purple-400">// AI 正在分析需求...</div>
                    <div className="text-green-400 mt-2">✓ 理解业务逻辑</div>
                    <div className="text-green-400">✓ 设计数据模型</div>
                    <div className="text-green-400">✓ 生成 API 接口</div>
                    <div className="text-blue-400 mt-4">→ 生成 React 组件</div>
                    <div className="text-white/70 mt-2 pl-4">export const UserProfile = () ={'>'} {'{'}</div>
                    <div className="text-white/70 pl-8">// AI 生成的代码...</div>
                  </div>
                </div>
              )}
              {activeTab === 1 && (
                <div className="h-full flex flex-col">
                  <div className="flex items-center gap-3 mb-6">
                    <MousePointer2 className="w-8 h-8 text-blue-400" />
                    <span className="text-white font-semibold text-xl">可视化圈选</span>
                  </div>
                  <div className="flex-1 rounded-xl bg-black/40 p-4 relative overflow-hidden">
                    <div className="absolute inset-4 border-2 border-dashed border-blue-400/50 rounded-lg" />
                    <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
                      <MousePointer2 className="w-12 h-12 text-blue-400 mx-auto mb-2" />
                      <p className="text-white/60 text-sm">点击任意元素进行修改</p>
                    </div>
                  </div>
                </div>
              )}
              {activeTab === 2 && (
                <div className="h-full flex flex-col">
                  <div className="flex items-center gap-3 mb-6">
                    <Workflow className="w-8 h-8 text-emerald-400" />
                    <span className="text-white font-semibold text-xl">智能流水线</span>
                  </div>
                  <div className="flex-1 flex items-center justify-center gap-4">
                    {['设计', '开发', '测试', '部署'].map((step, i) => (
                      <div key={step} className="text-center">
                        <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-2 ${
                          i < 3 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-white/10 text-white/40'
                        }`}>
                          <CheckCircle2 className="w-8 h-8" />
                        </div>
                        <span className="text-white/60 text-sm">{step}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {activeTab === 3 && (
                <div className="h-full flex flex-col">
                  <div className="flex items-center gap-3 mb-6">
                    <Shield className="w-8 h-8 text-orange-400" />
                    <span className="text-white font-semibold text-xl">安全合规</span>
                  </div>
                  <div className="flex-1 space-y-3">
                    {['代码安全扫描', '依赖漏洞检测', '合规性检查', '权限审计'].map((item, i) => (
                      <div key={item} className="flex items-center gap-3 p-3 rounded-lg bg-white/5">
                        <CheckCircle2 className={`w-5 h-5 ${i < 3 ? 'text-green-400' : 'text-orange-400'}`} />
                        <span className="text-white/80">{item}</span>
                        <span className="ml-auto text-xs text-white/40">已通过</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}