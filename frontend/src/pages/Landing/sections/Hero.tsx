import { useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  Zap,
  Sparkles,
  ArrowRight,
  Play,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react';

export function Hero() {
  const heroRef = useRef<HTMLDivElement>(null);

  return (
    <section
      ref={heroRef}
      className="relative min-h-screen flex items-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 overflow-hidden"
    >
      {/* 动态背景 */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-brand-primary/20 rounded-full blur-[150px] animate-pulse" />
        <div className="absolute bottom-0 right-1/4 w-[500px] h-[500px] bg-purple-500/20 rounded-full blur-[120px] animate-pulse" style={{ animationDelay: '1s' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-blue-500/10 rounded-full blur-[200px]" />
        {/* 网格背景 */}
        <div className="absolute inset-0 bg-[url('data:image/svg+xml,%3Csvg%20width%3D%2260%22%20height%3D%2260%22%20viewBox%3D%220%200%2060%2060%22%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%3E%3Cg%20fill%3D%22none%22%20fill-rule%3D%22evenodd%22%3E%3Cg%20fill%3D%22%23ffffff%22%20fill-opacity%3D%220.03%22%3E%3Cpath%20d%3D%22M36%2034v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6%2034v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6%204V0H4v4H0v2h4v4h2V6h4V4H6z%22/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')] opacity-50" />
      </div>

      {/* 将内容整体向上挪动，-mt-16 在小屏生效，lg:-mt-24 在大屏生效 */}
      <div className="container-feishu relative z-10 -mt-16 lg:-mt-24">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* 左侧文案 */}
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 border border-white/20 backdrop-blur-sm">
              <Sparkles className="w-4 h-4 text-yellow-400" />
              <span className="text-sm text-white/90">AI 驱动的开发全流程引擎</span>
            </div>

            {/* 将 leading-tight 改为 leading-[1.1] 增加紧凑感 */}
            <h1 className="text-5xl lg:text-7xl font-bold leading-[1.1]">
              <span className="bg-gradient-to-r from-blue-500 via-blue-400 to-blue-600 bg-clip-text text-transparent">
                让 AI 重新定义
              </span>
              <br />
              <span className="bg-gradient-to-r from-blue-500 to-blue-600 bg-clip-text text-transparent">
                软件开发流程
              </span>
            </h1>

            <p className="text-xl text-white/60 max-w-xl leading-relaxed">
              OmniFlowAI 是新一代企业级 AI 开发平台，从需求分析到生产部署，
              智能化编排每一个环节，让团队效率提升 3 倍以上。
            </p>

            <div className="flex flex-wrap items-center gap-4">
              <Link
                to="/console"
                className="group inline-flex items-center gap-2 px-8 py-4 bg-blue-500 text-white rounded-xl font-semibold text-lg hover:bg-blue-600 hover:shadow-lg hover:shadow-blue-500/25 hover:-translate-y-0.5 transition-all duration-300"
              >
                免费开始使用
                <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </Link>
              <button className="group inline-flex items-center gap-2 px-6 py-4 text-white/80 hover:text-white border border-white/20 hover:border-white/40 rounded-xl backdrop-blur-sm transition-all duration-300">
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center group-hover:bg-white/20 transition-colors">
                  <Play className="w-4 h-4 ml-0.5" />
                </div>
                观看产品演示
              </button>
            </div>
          </div>

          {/* 右侧视觉 - 产品界面预览 */}
          <div className="hidden lg:block relative">
            <div className="relative rounded-2xl overflow-hidden shadow-2xl shadow-brand-primary/20 border border-white/10 bg-slate-800/50 backdrop-blur-sm">
              {/* 模拟产品界面 */}
              <div className="aspect-[4/3] bg-gradient-to-br from-slate-800 to-slate-900 p-6">
                {/* 顶部栏 */}
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-red-500" />
                    <div className="w-3 h-3 rounded-full bg-yellow-500" />
                    <div className="w-3 h-3 rounded-full bg-green-500" />
                  </div>
                  <div className="px-3 py-1 rounded-full bg-white/5 text-xs text-white/40">
                    OmniFlowAI Console
                  </div>
                </div>
                {/* 内容区 */}
                <div className="space-y-4">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-brand-primary/20 flex items-center justify-center">
                      <Zap className="w-6 h-6 text-brand-primary" />
                    </div>
                    <div>
                      <div className="text-white font-semibold">AI 正在生成代码...</div>
                      <div className="text-white/40 text-sm">预计剩余 2 分钟</div>
                    </div>
                  </div>
                  {/* 代码预览 */}
                  <div className="rounded-lg bg-black/30 p-4 font-mono text-sm">
                    <div className="text-green-400">+ import {'{'} useState {'}'} from &apos;react&apos;;</div>
                    <div className="text-blue-400">+ export function Component() {'{'}</div>
                    <div className="text-white/70 pl-4">+ const [data, setData] = useState();</div>
                    <div className="text-white/70 pl-4">+ return &lt;div&gt;Hello AI&lt;/div&gt;;</div>
                    <div className="text-blue-400">+ {'}'}</div>
                  </div>
                  {/* 进度条 */}
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs text-white/40">
                      <span>生成进度</span>
                      <span>75%</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full w-3/4 rounded-full bg-gradient-to-r from-brand-primary to-purple-500" />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 浮动卡片 */}
            <div className="absolute -bottom-6 -left-6 p-4 bg-white rounded-xl shadow-xl border border-border-default animate-on-scroll">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-green-100 flex items-center justify-center">
                  <CheckCircle2 className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-text-primary">部署成功</p>
                  <p className="text-xs text-text-tertiary">耗时 2 分 34 秒</p>
                </div>
              </div>
            </div>

            <div className="absolute -top-4 -right-4 p-4 bg-white rounded-xl shadow-xl border border-border-default animate-on-scroll" style={{ transitionDelay: '200ms' }}>
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-yellow-500" />
                <span className="text-sm font-medium text-text-primary">AI 优化建议</span>
              </div>
              <p className="text-xs text-text-secondary mt-1">性能提升 40%</p>
            </div>
          </div>
        </div>
      </div>

      {/* 滚动提示 - 强化版 */}
      <button
        onClick={() => {
          // 点击自动滚动到下一屏
          window.scrollTo({ top: window.innerHeight, behavior: 'smooth' });
        }}
        className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-3 text-white/60 hover:text-blue-400 transition-all duration-300 group cursor-pointer z-20"
      >
        {/* 文字部分：加粗并增加字间距 */}
        <span className="text-xs font-bold tracking-[0.2em] uppercase mb-1">
          向下滑动 探索更多
        </span>

        <div className="relative flex flex-col items-center">
          {/* 鼠标图标：增加亮度 */}
          <div className="w-6 h-10 rounded-full border-2 border-white/40 flex justify-center pt-2 group-hover:border-blue-400 transition-colors">
            <div className="w-1 h-2 rounded-full bg-blue-400 animate-bounce" />
          </div>

          {/* 新增：动态下箭头，明确指向下方 */}
          <div className="mt-2">
            <ChevronRight className="w-5 h-5 rotate-90 text-blue-400/80 animate-pulse" />
          </div>
        </div>

        {/* 背景光晕：让提示区域在深色背景下更突出 */}
        <div className="absolute -inset-4 bg-blue-500/5 blur-xl rounded-full -z-10 opacity-0 group-hover:opacity-100 transition-opacity" />
      </button>
    </section>
  );
}
