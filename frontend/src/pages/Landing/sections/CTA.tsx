import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';

export function CTA() {
  return (
    <section className="py-24">
      <div className="container-feishu">
        <div className="relative rounded-3xl overflow-hidden bg-gradient-to-br from-brand-primary via-brand-primary to-purple-600 p-12 lg:p-20 text-center animate-on-scroll">
          {/* 背景装饰 */}
          <div className="absolute inset-0 overflow-hidden">
            <div className="absolute top-0 left-1/4 w-96 h-96 bg-white/10 rounded-full blur-[100px]" />
            <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-purple-500/20 rounded-full blur-[80px]" />
          </div>

          <div className="relative z-10 max-w-3xl mx-auto">
            <h2 className="text-4xl lg:text-5xl font-bold text-white mb-6">
              准备好提升研发效率了吗？
            </h2>
            <p className="text-white/80 text-xl mb-10">
              立即开始使用 OmniFlowAI，体验 AI 驱动的研发全流程自动化
              <br />
              免费版永久免费，无需信用卡
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4">
              <Link
                to="/console"
                className="inline-flex items-center gap-2 px-10 py-5 bg-white text-brand-primary rounded-xl font-semibold text-lg hover:bg-white/90 hover:shadow-xl transition-all duration-300"
              >
                免费开始使用
                <ArrowRight className="w-5 h-5" />
              </Link>
              <Link
                to="/docs"
                className="inline-flex items-center gap-2 px-10 py-5 border-2 border-white/30 text-white rounded-xl font-semibold text-lg hover:bg-white/10 transition-all duration-300"
              >
                查看文档
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
