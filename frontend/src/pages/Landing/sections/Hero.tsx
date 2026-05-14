import { useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  Zap,
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
        <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-blue-500/20 rounded-full blur-[150px] animate-pulse" />
        <div className="absolute bottom-0 right-1/4 w-[500px] h-[500px] bg-purple-500/20 rounded-full blur-[120px] animate-pulse" style={{ animationDelay: '1s' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-blue-500/10 rounded-full blur-[200px]" />
      </div>

      <div className="container-feishu relative z-10 -mt-16 lg:-mt-24">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* 左侧文案 */}
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 border border-white/20 backdrop-blur-sm">
              <Zap className="w-4 h-4 text-blue-400" />
              <span className="text-sm text-white/90">AI 驱动的开发全流程引擎</span>
            </div>

            <h1 className="text-5xl lg:text-7xl font-bold leading-[1.1] text-white">
              <span className="text-white">让 AI 重新定义</span>
              <br />
              <span className="text-blue-400">软件开发流程</span>
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
                开始使用
                <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </Link>
              <button className="group inline-flex items-center gap-2 px-6 py-4 text-white hover:text-white border border-white/20 hover:border-white/40 rounded-xl backdrop-blur-sm transition-all duration-300">
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center group-hover:bg-white/20 transition-colors">
                  <Play className="w-4 h-4 ml-0.5" />
                </div>
                观看产品演示
              </button>
            </div>
          </div>

          {/* 右侧视觉 - 产品界面预览 */}
          <div className="hidden lg:block relative">
            <div className="relative rounded-2xl overflow-hidden shadow-2xl shadow-blue-500/20 border border-white/10 bg-slate-800/50 backdrop-blur-sm">
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
                    <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center">
                      <Zap className="w-6 h-6 text-blue-400" />
                    </div>
                    <div>
                      <div className="text-white font-semibold">AI 正在生成代码...</div>
                      <div className="text-white/40 text-sm">预计剩余 3 分钟</div>
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
                      <div className="h-full w-3/4 rounded-full bg-gradient-to-r from-blue-500 to-purple-500" />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 浮动卡片 */}
            <div className="absolute -bottom-6 -left-6 p-4 bg-white rounded-xl shadow-xl border border-gray-200 animate-on-scroll">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-green-100 flex items-center justify-center">
                  <CheckCircle2 className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900">部署成功</p>
                  <p className="text-xs text-gray-500">耗时 2 分 34 秒</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 滚动提示 */}
      <button
        onClick={() => {
          window.scrollTo({ top: window.innerHeight, behavior: 'smooth' });
        }}
        className="absolute bottom-10 left-1/2 -translate-x-1/2 flex flex-col items-center gap-3 text-white/60 hover:text-blue-400 transition-all duration-300 group cursor-pointer z-20"
      >
        <span className="text-xs font-bold tracking-[0.2em] uppercase mb-1">
          向下滑动 探索更多
        </span>

        <div className="relative flex flex-col items-center">
          <div className="w-6 h-10 rounded-full border-2 border-white/40 flex justify-center pt-2 group-hover:border-blue-400 transition-colors">
            <div className="w-1 h-2 rounded-full bg-blue-400 animate-bounce" />
          </div>

          <div className="mt-2">
            <ChevronRight className="w-5 h-5 rotate-90 text-blue-400/80 animate-pulse" />
          </div>
        </div>

      </button>
    </section>
  );
}
