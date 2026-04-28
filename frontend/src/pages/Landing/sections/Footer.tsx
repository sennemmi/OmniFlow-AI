import { Link } from 'react-router-dom';
import { Zap } from 'lucide-react';

export function Footer() {
  return (
    <footer className="bg-slate-900 text-white py-20">
      <div className="container-feishu">
        <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-12 mb-16">
          {/* 品牌 */}
          <div className="lg:col-span-2">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-brand-primary flex items-center justify-center">
                <Zap className="w-6 h-6 text-white" />
              </div>
              <span className="text-xl font-bold">OmniFlowAI</span>
            </div>
            <p className="text-white/60 max-w-sm mb-6 leading-relaxed">
              AI 驱动的研发全流程引擎，让企业研发效率提升 3 倍以上。
              从需求到部署，智能化编排每一个环节。
            </p>
            <div className="flex items-center gap-4">
              {['GitHub', 'Twitter', 'Discord'].map((social) => (
                <a
                  key={social}
                  href="#"
                  className="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors"
                >
                  <span className="text-xs">{social[0]}</span>
                </a>
              ))}
            </div>
          </div>

          {/* 产品 */}
          <div>
            <h4 className="font-semibold mb-6">产品</h4>
            <ul className="space-y-4 text-white/60">
              <li><Link to="/console" className="hover:text-white transition-colors">控制台</Link></li>
              <li><Link to="/console/workspace" className="hover:text-white transition-colors">工作区</Link></li>
              <li><Link to="/pricing" className="hover:text-white transition-colors">定价</Link></li>
              <li><Link to="/changelog" className="hover:text-white transition-colors">更新日志</Link></li>
            </ul>
          </div>

          {/* 资源 */}
          <div>
            <h4 className="font-semibold mb-6">资源</h4>
            <ul className="space-y-4 text-white/60">
              <li><Link to="/docs" className="hover:text-white transition-colors">文档</Link></li>
              <li><Link to="/api" className="hover:text-white transition-colors">API 参考</Link></li>
              <li><Link to="/templates" className="hover:text-white transition-colors">模板</Link></li>
              <li><Link to="/blog" className="hover:text-white transition-colors">博客</Link></li>
            </ul>
          </div>

          {/* 支持 */}
          <div>
            <h4 className="font-semibold mb-6">支持</h4>
            <ul className="space-y-4 text-white/60">
              <li><Link to="/help" className="hover:text-white transition-colors">帮助中心</Link></li>
              <li><Link to="/contact" className="hover:text-white transition-colors">联系我们</Link></li>
              <li><Link to="/status" className="hover:text-white transition-colors">系统状态</Link></li>
              <li><Link to="/security" className="hover:text-white transition-colors">安全</Link></li>
            </ul>
          </div>
        </div>

        <div className="pt-8 border-t border-white/10 flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-white/40">
          <p>© 2024 OmniFlowAI. All rights reserved.</p>
          <div className="flex items-center gap-8">
            <Link to="/privacy" className="hover:text-white transition-colors">隐私政策</Link>
            <Link to="/terms" className="hover:text-white transition-colors">服务条款</Link>
            <Link to="/cookies" className="hover:text-white transition-colors">Cookie 设置</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
