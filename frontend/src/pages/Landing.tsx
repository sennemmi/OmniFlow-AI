import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Zap,
  Workflow,
  Shield,
  Rocket,
  ChevronRight,
  Play,
  BarChart3,
  Clock,
  CheckCircle2,
  ArrowRight,
} from 'lucide-react';
import { Navbar } from '@components/Layout';
import { apiGet } from '@utils/axios';

// ============================================
// OmniFlowAI 官网首页 - 飞书级 Hero 设计
// ============================================

// 特性数据
const features = [
  {
    id: 'automation',
    title: '智能流水线编排',
    description: 'AI 驱动的研发流程自动化，从需求分析到代码部署，全流程智能化管理。支持自定义阶段、条件分支和并行执行。',
    icon: Workflow,
    image: '/assets/feature-automation.png',
    stats: [
      { label: '效率提升', value: '3x' },
      { label: '人工干预', value: '-70%' },
    ],
  },
  {
    id: 'security',
    title: '企业级安全管控',
    description: '内置代码审计、合规检查和权限管理，确保每一次发布都符合企业安全标准。支持多级审批流程。',
    icon: Shield,
    image: '/assets/feature-security.png',
    stats: [
      { label: '安全漏洞', value: '-90%' },
      { label: '合规通过率', value: '99.9%' },
    ],
  },
  {
    id: 'speed',
    title: '极速交付体验',
    description: '并行执行、智能缓存和增量构建，将构建时间缩短至分钟级。支持多云部署和一键回滚。',
    icon: Rocket,
    image: '/assets/feature-speed.png',
    stats: [
      { label: '构建速度', value: '5min' },
      { label: '部署频率', value: '10x' },
    ],
  },
];

// 统计数据
const stats = [
  { label: '流水线执行次数', value: '1M+', suffix: '' },
  { label: '平均构建时间', value: '3.5', suffix: 'min' },
  { label: '部署成功率', value: '99.9', suffix: '%' },
  { label: '企业客户', value: '500+', suffix: '' },
];

// 功能卡片
const capabilities = [
  {
    title: 'AI 架构设计',
    description: '自动生成技术方案，智能评审设计文档',
    icon: Zap,
  },
  {
    title: '代码生成',
    description: '基于需求自动生成高质量代码',
    icon: Workflow,
  },
  {
    title: '质量门禁',
    description: '自动化测试、代码扫描、安全检查',
    icon: Shield,
  },
  {
    title: '一键部署',
    description: '多云环境支持，蓝绿部署零停机',
    icon: Rocket,
  },
  {
    title: '实时监控',
    description: '全流程可视化，异常自动告警',
    icon: BarChart3,
  },
  {
    title: '智能调度',
    description: '资源优化分配，成本降低 40%',
    icon: Clock,
  },
];

export function Landing() {
  const heroRef = useRef<HTMLDivElement>(null);

  // 获取真实系统统计数据
  const { data: realStats } = useQuery({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
  });

  // 滚动动画
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
          }
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );

    document.querySelectorAll('.animate-on-scroll').forEach((el) => {
      observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-bg-secondary">
      <Navbar />

      {/* ============================================
          Hero Section - 全屏深色渐变
          ============================================ */}
      <section
        ref={heroRef}
        className="relative min-h-screen flex items-center bg-gradient-hero overflow-hidden"
      >
        {/* 背景装饰 */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-brand-primary/20 rounded-full blur-[128px]" />
          <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-brand-primary/10 rounded-full blur-[128px]" />
        </div>

        <div className="container-feishu relative z-10 pt-16">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* 左侧文案 */}
            <div className="space-y-8">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-text-white/10 border border-text-white/20">
                <span className="w-2 h-2 rounded-full bg-status-success animate-pulse" />
                <span className="text-sm text-text-white/80">AI 驱动的研发全流程引擎</span>
              </div>

              <h1 className="text-5xl lg:text-6xl font-bold leading-tight">
                <span className="text-gradient-hero">让研发流程</span>
                <br />
                <span className="text-gradient-hero">像流水一样顺畅</span>
              </h1>

              <p className="text-lg text-text-white/70 max-w-lg leading-relaxed">
                OmniFlowAI 是新一代 AI 驱动的研发全流程引擎，从需求到部署，智能化编排每一个环节，让团队效率提升 3 倍以上。
              </p>

              <div className="flex flex-wrap items-center gap-4">
                <Link
                  to="/console"
                  className="inline-flex items-center gap-2 px-8 py-4 bg-brand-primary text-text-white rounded-lg font-medium text-lg hover:bg-brand-primary-hover hover:-translate-y-0.5 hover:shadow-feishu-button transition-all duration-250"
                >
                  免费开始使用
                  <ArrowRight className="w-5 h-5" />
                </Link>
                <button className="inline-flex items-center gap-2 px-6 py-4 text-text-white/90 hover:text-text-white transition-colors">
                  <Play className="w-5 h-5" />
                  观看演示
                </button>
              </div>

              {/* 信任标识 */}
              <div className="pt-8 border-t border-text-white/10">
                <p className="text-sm text-text-white/50 mb-4">已获众多企业信赖</p>
                <div className="flex items-center gap-8 opacity-50">
                  {['字节跳动', '阿里巴巴', '腾讯', '美团'].map((company) => (
                    <span key={company} className="text-text-white/60 font-medium">
                      {company}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* 右侧视觉 */}
            <div className="hidden lg:block relative">
              <div className="relative rounded-2xl overflow-hidden shadow-2xl border border-text-white/10">
                <img
                  src="/assets/hero.png"
                  alt="OmniFlowAI Dashboard"
                  className="w-full h-auto"
                />
                {/* 叠加效果 */}
                <div className="absolute inset-0 bg-gradient-to-t from-hero-dark-1/50 to-transparent" />
              </div>

              {/* 浮动卡片 */}
              <div className="absolute -bottom-6 -left-6 p-4 bg-bg-primary rounded-xl shadow-feishu border border-border-default animate-on-scroll">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-md bg-status-success/10 flex items-center justify-center">
                    <CheckCircle2 className="w-5 h-5 text-status-success" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-text-primary">部署成功</p>
                    <p className="text-xs text-text-tertiary">耗时 2 分 34 秒</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 滚动提示 */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-text-white/40">
          <span className="text-xs">向下滚动</span>
          <div className="w-6 h-10 rounded-full border-2 border-text-white/30 flex justify-center pt-2">
            <div className="w-1.5 h-1.5 rounded-full bg-text-white/60 animate-bounce" />
          </div>
        </div>
      </section>

      {/* ============================================
          Stats Section - 统计数字
          ============================================ */}
      <section className="py-20 bg-bg-primary border-b border-border-default">
        <div className="container-feishu">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-8">
            {stats.map((stat, index) => (
              <div
                key={stat.label}
                className="text-center animate-on-scroll"
                style={{ transitionDelay: `${index * 100}ms` }}
              >
                <div className="text-4xl lg:text-5xl font-bold text-gradient-brand mb-2">
                  {realStats ? (
                    // 使用真实数据
                    index === 0 ? realStats.total_pipelines || 0 :
                    index === 1 ? (realStats.avg_duration || 0) :
                    index === 2 ? '99.9' :
                    index === 3 ? '500+' : stat.value
                  ) : stat.value}
                  <span className="text-2xl">{stat.suffix}</span>
                </div>
                <p className="text-text-secondary">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================
          Features Section - 特性展示
          ============================================ */}
      <section className="py-24">
        <div className="container-feishu">
          <div className="text-center max-w-2xl mx-auto mb-16 animate-on-scroll">
            <h2 className="text-3xl lg:text-4xl font-bold text-text-primary mb-4">
              全流程智能化管理
            </h2>
            <p className="text-text-secondary text-lg">
              从需求分析到生产部署，AI 助手全程陪伴，让研发流程更高效、更可靠
            </p>
          </div>

          <div className="space-y-24">
            {features.map((feature, index) => {
              const Icon = feature.icon;
              const isEven = index % 2 === 1;

              return (
                <div
                  key={feature.id}
                  className={`grid lg:grid-cols-2 gap-12 items-center animate-on-scroll ${
                    isEven ? 'lg:flex-row-reverse' : ''
                  }`}
                >
                  {/* 内容 */}
                  <div className={`space-y-6 ${isEven ? 'lg:order-2' : ''}`}>
                    <div className="w-14 h-14 rounded-2xl bg-brand-primary-light flex items-center justify-center">
                      <Icon className="w-7 h-7 text-brand-primary" />
                    </div>

                    <h3 className="text-2xl lg:text-3xl font-bold text-text-primary">
                      {feature.title}
                    </h3>

                    <p className="text-text-secondary text-lg leading-relaxed">
                      {feature.description}
                    </p>

                    <div className="flex gap-8 pt-4">
                      {feature.stats.map((stat) => (
                        <div key={stat.label}>
                          <div className="text-2xl font-bold text-brand-primary">{stat.value}</div>
                          <div className="text-sm text-text-tertiary">{stat.label}</div>
                        </div>
                      ))}
                    </div>

                    <Link
                      to="/console"
                      className="inline-flex items-center gap-2 text-brand-primary font-medium hover:gap-3 transition-all"
                    >
                      了解更多
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                  </div>

                  {/* 图片 */}
                  <div className={`relative ${isEven ? 'lg:order-1' : ''}`}>
                    <div className="aspect-video bg-bg-tertiary rounded-2xl overflow-hidden border border-border-default">
                      <div className="w-full h-full flex items-center justify-center text-text-tertiary">
                        <Icon className="w-24 h-24 opacity-20" />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============================================
          Capabilities Section - 功能网格
          ============================================ */}
      <section className="py-24 bg-bg-primary">
        <div className="container-feishu">
          <div className="text-center max-w-2xl mx-auto mb-16 animate-on-scroll">
            <h2 className="text-3xl lg:text-4xl font-bold text-text-primary mb-4">
              强大而灵活的功能
            </h2>
            <p className="text-text-secondary text-lg">
              覆盖研发全流程的核心能力，满足各种复杂场景需求
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {capabilities.map((cap, index) => {
              const Icon = cap.icon;
              return (
                <div
                  key={cap.title}
                  className="card-feishu p-6 animate-on-scroll"
                  style={{ transitionDelay: `${index * 50}ms` }}
                >
                  <div className="w-12 h-12 rounded-xl bg-brand-primary-light flex items-center justify-center mb-4">
                    <Icon className="w-6 h-6 text-brand-primary" />
                  </div>
                  <h3 className="text-lg font-semibold text-text-primary mb-2">{cap.title}</h3>
                  <p className="text-text-secondary text-sm">{cap.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============================================
          CTA Section - 行动号召
          ============================================ */}
      <section className="py-24">
        <div className="container-feishu">
          <div className="relative rounded-2xl overflow-hidden bg-gradient-cta p-12 lg:p-16 text-center animate-on-scroll">
            {/* 背景装饰 */}
            <div className="absolute inset-0 overflow-hidden">
              <div className="absolute top-0 left-1/4 w-64 h-64 bg-text-white/10 rounded-full blur-[100px]" />
              <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-text-white/5 rounded-full blur-[100px]" />
            </div>

            <div className="relative z-10 max-w-2xl mx-auto">
              <h2 className="text-3xl lg:text-4xl font-bold text-text-white mb-4">
                准备好提升研发效率了吗？
              </h2>
              <p className="text-text-white/80 text-lg mb-8">
                立即开始使用 OmniFlowAI，体验 AI 驱动的研发全流程自动化
              </p>
              <div className="flex flex-wrap items-center justify-center gap-4">
                <Link
                  to="/console"
                  className="inline-flex items-center gap-2 px-8 py-4 bg-text-white text-brand-primary rounded-lg font-medium text-lg hover:bg-text-white/90 hover:-translate-y-0.5 transition-all duration-250"
                >
                  免费开始使用
                  <ArrowRight className="w-5 h-5" />
                </Link>
                <Link
                  to="/docs"
                  className="inline-flex items-center gap-2 px-8 py-4 border border-text-white/30 text-text-white rounded-lg font-medium text-lg hover:bg-text-white/10 transition-all duration-250"
                >
                  查看文档
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ============================================
          Footer
          ============================================ */}
      <footer className="bg-hero-dark-1 text-text-white py-16">
        <div className="container-feishu">
          <div className="grid md:grid-cols-4 gap-12 mb-12">
            <div className="md:col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-9 h-9 rounded-lg bg-brand-primary flex items-center justify-center">
                  <Zap className="w-5 h-5 text-text-white" />
                </div>
                <span className="text-lg font-semibold">OmniFlowAI</span>
              </div>
              <p className="text-text-white/60 max-w-sm">
                AI 驱动的研发全流程引擎，让研发流程像流水一样顺畅。
              </p>
            </div>

            <div>
              <h4 className="font-semibold mb-4">产品</h4>
              <ul className="space-y-2 text-text-white/60">
                <li><Link to="/console" className="hover:text-text-white transition-colors">控制台</Link></li>
                <li><Link to="/docs" className="hover:text-text-white transition-colors">文档</Link></li>
                <li><Link to="/pricing" className="hover:text-text-white transition-colors">定价</Link></li>
              </ul>
            </div>

            <div>
              <h4 className="font-semibold mb-4">支持</h4>
              <ul className="space-y-2 text-text-white/60">
                <li><Link to="/help" className="hover:text-text-white transition-colors">帮助中心</Link></li>
                <li><Link to="/contact" className="hover:text-text-white transition-colors">联系我们</Link></li>
                <li><Link to="/status" className="hover:text-text-white transition-colors">系统状态</Link></li>
              </ul>
            </div>
          </div>

          <div className="pt-8 border-t border-text-white/10 flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-text-white/40">
            <p>© 2024 OmniFlowAI. All rights reserved.</p>
            <div className="flex items-center gap-6">
              <Link to="/privacy" className="hover:text-text-white transition-colors">隐私政策</Link>
              <Link to="/terms" className="hover:text-text-white transition-colors">服务条款</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
