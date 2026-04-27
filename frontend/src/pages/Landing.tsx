import { useEffect, useRef, useState } from 'react';
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
  Sparkles,
  Code2,
  Terminal,
  GitPullRequest,
  Cpu,
  Users,
  Globe,
  Award,
  TrendingUp,
  Layers,
  MousePointer2,
} from 'lucide-react';
import { Navbar } from '@components/Layout';
import { apiGet } from '@utils/axios';

// ============================================
// OmniFlowAI 企业级官网首页 - 现代化 SaaS 设计
// ============================================

// 核心特性数据
const coreFeatures = [
  {
    id: 'ai-driven',
    title: 'AI 驱动研发',
    description: '基于大语言模型的智能代码生成、架构设计和代码审查，让 AI 成为您的研发伙伴',
    icon: Sparkles,
    color: 'from-violet-500 to-purple-600',
    stats: { label: '效率提升', value: '3x' },
  },
  {
    id: 'visual-workspace',
    title: '可视化工作区',
    description: '所见即所得的元素圈选，直接在前端页面上选择元素并提交修改需求',
    icon: MousePointer2,
    color: 'from-blue-500 to-cyan-500',
    stats: { label: '修改响应', value: '<2min' },
  },
  {
    id: 'pipeline',
    title: '智能流水线',
    description: '从需求到部署的全流程自动化，支持人工审批节点和质量门禁',
    icon: Workflow,
    color: 'from-emerald-500 to-teal-500',
    stats: { label: '部署频率', value: '10x' },
  },
  {
    id: 'security',
    title: '企业级安全',
    description: '代码审计、合规检查、权限管理，确保每一次发布都符合企业标准',
    icon: Shield,
    color: 'from-orange-500 to-red-500',
    stats: { label: '安全漏洞', value: '-90%' },
  },
];

// 功能模块
const modules = [
  {
    title: '智能架构设计',
    description: 'AI 分析需求并生成技术方案，包括数据库设计、API 设计和系统架构',
    icon: Layers,
    features: ['需求分析', '技术选型', '架构图生成'],
  },
  {
    title: '代码自动生成',
    description: '基于技术设计自动生成前后端代码，支持多种框架和语言',
    icon: Code2,
    features: ['前端代码', '后端 API', '数据库模型'],
  },
  {
    title: '质量门禁',
    description: '自动化测试、代码扫描、安全检查，确保代码质量',
    icon: CheckCircle2,
    features: ['单元测试', '代码扫描', '安全审计'],
  },
  {
    title: '一键部署',
    description: '多云环境支持，蓝绿部署零停机，自动回滚保障',
    icon: Rocket,
    features: ['多云部署', '蓝绿发布', '自动回滚'],
  },
  {
    title: '实时监控',
    description: '全流程可视化监控，异常自动告警，性能实时分析',
    icon: BarChart3,
    features: ['流水线监控', '性能分析', '智能告警'],
  },
  {
    title: '团队协作',
    description: '审批工作流、代码评审、知识沉淀，提升团队协作效率',
    icon: Users,
    features: ['审批流', '代码评审', '知识库'],
  },
];

// 统计数据
const stats = [
  { label: '流水线执行', value: '1M+', suffix: '', icon: GitPullRequest },
  { label: '平均构建时间', value: '3.5', suffix: 'min', icon: Clock },
  { label: '部署成功率', value: '99.9', suffix: '%', icon: CheckCircle2 },
  { label: '企业客户', value: '500+', suffix: '', icon: Globe },
];

// 客户评价
const testimonials = [
  {
    content: 'OmniFlowAI 让我们的研发效率提升了 3 倍，从需求到上线的时间从 2 周缩短到 3 天。',
    author: '张明',
    role: 'CTO',
    company: '某独角兽企业',
  },
  {
    content: '可视化工作区功能太棒了，产品经理可以直接在页面上标注修改需求，AI 自动完成代码变更。',
    author: '李华',
    role: '产品总监',
    company: '某电商平台',
  },
  {
    content: '企业级安全管控让我们放心地将核心系统接入，合规检查和质量门禁确保了代码质量。',
    author: '王芳',
    role: '研发负责人',
    company: '某金融科技公司',
  },
];

// 定价方案
const pricingPlans = [
  {
    name: '免费版',
    description: '适合个人开发者和小团队',
    price: '0',
    period: '永久免费',
    features: [
      '每月 10 次 AI 代码生成',
      '基础流水线功能',
      '社区支持',
      '1 个工作区',
    ],
    cta: '免费开始',
    popular: false,
  },
  {
    name: '专业版',
    description: '适合成长型团队',
    price: '99',
    period: '/月',
    features: [
      '无限 AI 代码生成',
      '高级流水线编排',
      '可视化工作区',
      '优先技术支持',
      '5 个工作区',
      '自定义模板',
    ],
    cta: '开始试用',
    popular: true,
  },
  {
    name: '企业版',
    description: '适合大型企业',
    price: '定制',
    period: '',
    features: [
      '私有化部署',
      'SSO 单点登录',
      '高级安全合规',
      '专属客户成功经理',
      '无限工作区',
      'SLA 保障',
    ],
    cta: '联系销售',
    popular: false,
  },
];

export function Landing() {
  const heroRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState(0);

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

  // 自动轮播
  useEffect(() => {
    const timer = setInterval(() => {
      setActiveTab((prev) => (prev + 1) % coreFeatures.length);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="min-h-screen bg-bg-secondary">
      <Navbar />

      {/* ============================================
          Hero Section - 现代化企业级设计
          ============================================ */}
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

        <div className="container-feishu relative z-10 pt-20">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            {/* 左侧文案 */}
            <div className="space-y-8">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 border border-white/20 backdrop-blur-sm">
                <Sparkles className="w-4 h-4 text-yellow-400" />
                <span className="text-sm text-white/90">AI 驱动的研发全流程引擎</span>
              </div>

              <h1 className="text-5xl lg:text-7xl font-bold leading-tight">
                <span className="bg-gradient-to-r from-white via-white to-white/70 bg-clip-text text-transparent">
                  让 AI 重新定义
                </span>
                <br />
                <span className="bg-gradient-to-r from-brand-primary to-purple-500 bg-clip-text text-transparent">
                  软件研发流程
                </span>
              </h1>

              <p className="text-xl text-white/60 max-w-xl leading-relaxed">
                OmniFlowAI 是新一代企业级 AI 研发平台，从需求分析到生产部署，
                智能化编排每一个环节，让团队效率提升 3 倍以上。
              </p>

              <div className="flex flex-wrap items-center gap-4">
                <Link
                  to="/console"
                  className="group inline-flex items-center gap-2 px-8 py-4 bg-brand-primary text-white rounded-xl font-semibold text-lg hover:bg-brand-primary-hover hover:shadow-lg hover:shadow-brand-primary/25 hover:-translate-y-0.5 transition-all duration-300"
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

              {/* 信任标识 */}
              <div className="pt-8 border-t border-white/10">
                <p className="text-sm text-white/40 mb-6">已获得众多行业领先企业信赖</p>
                <div className="flex items-center gap-8 opacity-40">
                  {['字节跳动', '阿里巴巴', '腾讯', '美团', '京东'].map((company) => (
                    <span key={company} className="text-white/70 font-semibold text-lg">
                      {company}
                    </span>
                  ))}
                </div>
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
                      <div className="text-green-400">+ import {'{'} useState {'}'} from 'react';</div>
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

        {/* 滚动提示 */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-white/30">
          <span className="text-xs">探索更多</span>
          <div className="w-6 h-10 rounded-full border-2 border-white/20 flex justify-center pt-2">
            <div className="w-1.5 h-1.5 rounded-full bg-white/50 animate-bounce" />
          </div>
        </div>
      </section>

      {/* ============================================
          Stats Section - 数据统计
          ============================================ */}
      <section className="py-20 bg-bg-primary border-y border-border-default">
        <div className="container-feishu">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-8">
            {stats.map((stat, index) => {
              const Icon = stat.icon;
              return (
                <div
                  key={stat.label}
                  className="text-center animate-on-scroll group"
                  style={{ transitionDelay: `${index * 100}ms` }}
                >
                  <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-brand-primary/10 mb-4 group-hover:bg-brand-primary/20 transition-colors">
                    <Icon className="w-7 h-7 text-brand-primary" />
                  </div>
                  <div className="text-4xl lg:text-5xl font-bold text-gradient-brand mb-2">
                    {realStats ? (
                      index === 0 ? realStats.total_pipelines || 0 :
                      index === 1 ? (realStats.avg_duration || 0) :
                      index === 2 ? '99.9' :
                      index === 3 ? '500+' : stat.value
                    ) : stat.value}
                    <span className="text-2xl text-text-tertiary">{stat.suffix}</span>
                  </div>
                  <p className="text-text-secondary">{stat.label}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============================================
          Core Features Section - 核心特性
          ============================================ */}
      <section className="py-24">
        <div className="container-feishu">
          <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
              <Sparkles className="w-4 h-4" />
              核心能力
            </div>
            <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
              AI 重新定义研发流程
            </h2>
            <p className="text-text-secondary text-lg">
              从需求到部署，每一个环节都有 AI 的智能加持，让研发效率实现质的飞跃
            </p>
          </div>

          {/* 特性标签页 */}
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

      {/* ============================================
          Modules Section - 功能模块
          ============================================ */}
      <section className="py-24 bg-bg-primary">
        <div className="container-feishu">
          <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
              <Layers className="w-4 h-4" />
              功能模块
            </div>
            <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
              覆盖研发全流程
            </h2>
            <p className="text-text-secondary text-lg">
              从架构设计到生产部署，提供完整的企业级研发工具链
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {modules.map((module, index) => {
              const Icon = module.icon;
              return (
                <div
                  key={module.title}
                  className="group p-8 rounded-2xl bg-bg-secondary border border-border-default hover:border-brand-primary/30 hover:shadow-xl hover:shadow-brand-primary/5 transition-all duration-300 animate-on-scroll"
                  style={{ transitionDelay: `${index * 50}ms` }}
                >
                  <div className="w-14 h-14 rounded-2xl bg-brand-primary/10 flex items-center justify-center mb-6 group-hover:bg-brand-primary group-hover:scale-110 transition-all duration-300">
                    <Icon className="w-7 h-7 text-brand-primary group-hover:text-white transition-colors" />
                  </div>
                  <h3 className="text-xl font-semibold text-text-primary mb-3">{module.title}</h3>
                  <p className="text-text-secondary mb-6 leading-relaxed">{module.description}</p>
                  <div className="flex flex-wrap gap-2">
                    {module.features.map((feature) => (
                      <span
                        key={feature}
                        className="px-3 py-1 rounded-full bg-bg-tertiary text-text-secondary text-xs"
                      >
                        {feature}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ============================================
          Testimonials Section - 客户评价
          ============================================ */}
      <section className="py-24">
        <div className="container-feishu">
          <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
              <Award className="w-4 h-4" />
              客户评价
            </div>
            <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
              深受企业信赖
            </h2>
            <p className="text-text-secondary text-lg">
              超过 500 家企业选择 OmniFlowAI 提升研发效率
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {testimonials.map((testimonial, index) => (
              <div
                key={index}
                className="p-8 rounded-2xl bg-bg-primary border border-border-default shadow-feishu-card animate-on-scroll"
                style={{ transitionDelay: `${index * 100}ms` }}
              >
                <div className="flex gap-1 mb-6">
                  {[...Array(5)].map((_, i) => (
                    <Sparkles key={i} className="w-5 h-5 text-yellow-400 fill-yellow-400" />
                  ))}
                </div>
                <p className="text-text-primary text-lg leading-relaxed mb-6">
                  "{testimonial.content}"
                </p>
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-brand-primary/10 flex items-center justify-center">
                    <span className="text-brand-primary font-semibold">
                      {testimonial.author[0]}
                    </span>
                  </div>
                  <div>
                    <p className="font-semibold text-text-primary">{testimonial.author}</p>
                    <p className="text-sm text-text-tertiary">
                      {testimonial.role} · {testimonial.company}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================
          Pricing Section - 定价方案
          ============================================ */}
      <section className="py-24 bg-bg-primary">
        <div className="container-feishu">
          <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
              <Zap className="w-4 h-4" />
              定价方案
            </div>
            <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
              选择适合您的方案
            </h2>
            <p className="text-text-secondary text-lg">
              从免费开始，随业务增长灵活升级
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8 max-w-6xl mx-auto">
            {pricingPlans.map((plan, index) => (
              <div
                key={plan.name}
                className={`relative p-8 rounded-2xl border-2 transition-all duration-300 animate-on-scroll ${
                  plan.popular
                    ? 'border-brand-primary bg-brand-primary/5 shadow-xl shadow-brand-primary/10 scale-105'
                    : 'border-border-default bg-bg-secondary hover:border-brand-primary/30'
                }`}
                style={{ transitionDelay: `${index * 100}ms` }}
              >
                {plan.popular && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full bg-brand-primary text-white text-sm font-medium">
                    最受欢迎
                  </div>
                )}
                <div className="text-center mb-8">
                  <h3 className="text-xl font-semibold text-text-primary mb-2">{plan.name}</h3>
                  <p className="text-text-secondary text-sm mb-6">{plan.description}</p>
                  <div className="flex items-baseline justify-center gap-1">
                    <span className="text-2xl text-text-tertiary">¥</span>
                    <span className="text-5xl font-bold text-text-primary">{plan.price}</span>
                    <span className="text-text-tertiary">{plan.period}</span>
                  </div>
                </div>
                <ul className="space-y-4 mb-8">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex items-center gap-3">
                      <CheckCircle2 className={`w-5 h-5 ${plan.popular ? 'text-brand-primary' : 'text-text-tertiary'}`} />
                      <span className="text-text-secondary">{feature}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  to="/console"
                  className={`block w-full py-3 rounded-xl text-center font-semibold transition-all duration-300 ${
                    plan.popular
                      ? 'bg-brand-primary text-white hover:bg-brand-primary-hover shadow-lg shadow-brand-primary/25'
                      : 'bg-bg-tertiary text-text-primary hover:bg-border-default'
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================
          CTA Section - 行动号召
          ============================================ */}
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

      {/* ============================================
          Footer - 页脚
          ============================================ */}
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
    </div>
  );
}
