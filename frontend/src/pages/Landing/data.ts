import {
  Zap,
  Workflow,
  Shield,
  Rocket,
  BarChart3,
  Clock,
  CheckCircle2,
  Code2,
  Layers,
  MousePointer2,
  Users,
  Globe,
  GitPullRequest,
  ArrowRight,
  Play,
  ChevronRight,
} from 'lucide-react';

export const coreFeatures = [
  {
    id: 'ai-driven',
    title: 'AI 驱动研发',
    description: '基于大语言模型的智能代码生成、架构设计和代码审查，让 AI 成为您的研发伙伴',
    icon: Zap,
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
    features: ['分层测试', '代码扫描', '安全审计'],
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

export { ArrowRight, Play, ChevronRight };
