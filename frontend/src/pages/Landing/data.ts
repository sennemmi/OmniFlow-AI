import {
  Zap,
  Workflow,
  Shield,
  Rocket,
  BarChart3,
  Clock,
  CheckCircle2,
  Sparkles,
  Code2,
  Layers,
  MousePointer2,
  Users,
  Globe,
  GitPullRequest,
  TrendingUp,
  Award,
  ArrowRight,
  Play,
  ChevronRight,
} from 'lucide-react';

export const coreFeatures = [
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

export const modules = [
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

export const stats = [
  { label: '流水线执行', value: '1M+', suffix: '', icon: GitPullRequest },
  { label: '平均构建时间', value: '3.5', suffix: 'min', icon: Clock },
  { label: '部署成功率', value: '99.9', suffix: '%', icon: CheckCircle2 },
  { label: '企业客户', value: '500+', suffix: '', icon: Globe },
];

export const testimonials = [
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

export const pricingPlans = [
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

export { TrendingUp, Zap, Sparkles, Award, ArrowRight, Play, ChevronRight };
