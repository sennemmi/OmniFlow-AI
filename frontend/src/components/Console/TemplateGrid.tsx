import { useState } from 'react';
import {
  Bug,
  Layers,
  Zap,
  Shield,
  RefreshCw,
  Palette,
  Code2,
  Database,
  ArrowRight,
  Sparkles,
  CheckCircle2,
} from 'lucide-react';

// ============================================
// 模板库组件 - 飞书多维表格风格
// ============================================

export interface Template {
  id: string;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bgColor: string;
  category: string;
  prompt: string;
  features: string[];
}

const templates: Template[] = [
  {
    id: 'bug-fixer',
    title: 'Bug Fixer',
    description: '自动回归并修复错误',
    icon: Bug,
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    category: '调试修复',
    prompt: '请分析以下错误日志，定位问题根源并修复：\n\n[在此处粘贴错误日志]\n\n要求：\n1. 找出导致错误的代码位置\n2. 提供修复方案\n3. 添加防御性代码防止类似错误',
    features: ['自动定位错误', '生成修复代码', '添加单元测试'],
  },
  {
    id: 'style-magic',
    title: 'Style Magic',
    description: '基于圈选修改样式',
    icon: Palette,
    color: 'text-brand-primary',
    bgColor: 'bg-brand-primary/10',
    category: '样式优化',
    prompt: '请修改以下元素的样式：\n\n元素选择器：[元素XPath或选择器]\n\n修改需求：\n- 调整颜色/字体/间距\n- 添加动画效果\n- 优化响应式布局\n\n要求保持设计一致性。',
    features: ['圈选即改', '实时预览', '设计系统对齐'],
  },
  {
    id: 'architecture-refactor',
    title: 'Architecture Refactor',
    description: '重构臃肿的 Service 层',
    icon: Layers,
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    category: '架构重构',
    prompt: '请重构以下 Service 层代码，解决臃肿问题：\n\n目标文件：[Service文件路径]\n\n重构目标：\n1. 拆分大型类为多个职责单一的类\n2. 应用设计模式（策略模式、工厂模式等）\n3. 优化依赖注入\n4. 保持接口兼容性',
    features: ['智能拆分', '设计模式应用', '接口兼容'],
  },
  {
    id: 'api-booster',
    title: 'API Booster',
    description: '自动生成 RESTful API',
    icon: Zap,
    color: 'text-status-success',
    bgColor: 'bg-status-success/10',
    category: 'API开发',
    prompt: '请为以下数据模型生成完整的 RESTful API：\n\n模型定义：[模型字段]\n\n需要生成：\n1. CRUD 接口\n2. 数据验证\n3. 错误处理\n4. API 文档注释\n5. 单元测试',
    features: ['自动生成', 'Swagger文档', '权限控制'],
  },
  {
    id: 'security-guard',
    title: 'Security Guard',
    description: '安全漏洞扫描与修复',
    icon: Shield,
    color: 'text-purple-600',
    bgColor: 'bg-purple-50',
    category: '安全加固',
    prompt: '请对以下代码进行安全审计并修复漏洞：\n\n目标文件：[文件路径]\n\n检查项：\n1. SQL 注入风险\n2. XSS 漏洞\n3. 敏感信息泄露\n4. 权限控制缺陷\n5. 不安全的依赖',
    features: ['漏洞扫描', '自动修复', '安全报告'],
  },
  {
    id: 'test-creator',
    title: 'Test Creator',
    description: '自动生成测试用例',
    icon: CheckCircle2,
    color: 'text-teal-600',
    bgColor: 'bg-teal-50',
    category: '测试生成',
    prompt: '请为以下代码生成完整的测试用例：\n\n目标代码：[代码片段]\n\n测试要求：\n1. 单元测试（覆盖率>80%）\n2. 边界条件测试\n3. 异常处理测试\n4. 使用适当的 Mock',
    features: ['高覆盖率', '边界测试', 'Mock生成'],
  },
  {
    id: 'db-optimizer',
    title: 'DB Optimizer',
    description: '数据库查询优化',
    icon: Database,
    color: 'text-orange-600',
    bgColor: 'bg-orange-50',
    category: '性能优化',
    prompt: '请优化以下数据库查询：\n\n当前查询：[SQL或ORM查询]\n\n优化目标：\n1. 添加合适的索引\n2. 优化查询语句\n3. 减少N+1查询\n4. 分析执行计划',
    features: ['索引建议', '查询重写', '性能分析'],
  },
  {
    id: 'code-modernizer',
    title: 'Code Modernizer',
    description: '代码现代化升级',
    icon: RefreshCw,
    color: 'text-pink-600',
    bgColor: 'bg-pink-50',
    category: '代码升级',
    prompt: '请将以下代码升级到最新语法和最佳实践：\n\n目标代码：[代码片段]\n\n升级内容：\n1. 使用现代语法特性\n2. 替换废弃的 API\n3. 应用新的语言特性\n4. 保持功能一致性',
    features: ['语法升级', 'API迁移', '兼容性保持'],
  },
];

interface TemplateGridProps {
  onSelectTemplate: (template: Template) => void;
}

export function TemplateGrid({ onSelectTemplate }: TemplateGridProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>('全部');
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const categories = ['全部', ...Array.from(new Set(templates.map((t) => t.category)))];

  const filteredTemplates =
    selectedCategory === '全部'
      ? templates
      : templates.filter((t) => t.category === selectedCategory);

  return (
    <div className="space-y-6">
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-brand-primary" />
            AI 模板库
          </h2>
          <p className="text-sm text-text-secondary mt-1">
            选择预设模板快速启动 AI 研发流程
          </p>
        </div>
      </div>

      {/* 分类筛选 */}
      <div className="flex items-center gap-2 flex-wrap">
        {categories.map((category) => (
          <button
            key={category}
            onClick={() => setSelectedCategory(category)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
              selectedCategory === category
                ? 'bg-brand-primary text-text-white shadow-feishu-button'
                : 'bg-bg-secondary text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
            }`}
          >
            {category}
          </button>
        ))}
      </div>

      {/* 模板网格 */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filteredTemplates.map((template) => {
          const Icon = template.icon;
          const isHovered = hoveredId === template.id;

          return (
            <div
              key={template.id}
              className={`
                group relative p-5 rounded-xl border cursor-pointer
                transition-all duration-300 overflow-hidden
                ${isHovered 
                  ? 'border-brand-primary shadow-feishu -translate-y-1' 
                  : 'border-border-default bg-bg-primary hover:border-brand-primary/30 hover:shadow-feishu-card'
                }
              `}
              onMouseEnter={() => setHoveredId(template.id)}
              onMouseLeave={() => setHoveredId(null)}
              onClick={() => onSelectTemplate(template)}
            >
              {/* 背景装饰 */}
              <div
                className={`
                  absolute inset-0 opacity-0 transition-opacity duration-300
                  ${isHovered ? 'opacity-100' : ''}
                `}
                style={{
                  background: `linear-gradient(135deg, ${template.bgColor.replace('bg-', '').replace('/10', '')}10 0%, transparent 50%)`,
                }}
              />

              {/* 内容 */}
              <div className="relative z-10">
                {/* 图标 */}
                <div
                  className={`
                    w-12 h-12 rounded-xl flex items-center justify-center mb-4
                    transition-all duration-300
                    ${template.bgColor}
                    ${isHovered ? 'scale-110' : ''}
                  `}
                >
                  <Icon className={`w-6 h-6 ${template.color}`} />
                </div>

                {/* 标题 */}
                <h3 className="font-semibold text-text-primary mb-1 group-hover:text-brand-primary transition-colors">
                  {template.title}
                </h3>

                {/* 描述 */}
                <p className="text-sm text-text-secondary mb-3 line-clamp-2">
                  {template.description}
                </p>

                {/* 分类标签 */}
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs bg-bg-tertiary text-text-tertiary">
                  {template.category}
                </span>

                {/* 特性列表（悬停显示） */}
                <div
                  className={`
                    mt-4 pt-4 border-t border-border-default/50
                    transition-all duration-300
                    ${isHovered ? 'opacity-100 max-h-32' : 'opacity-0 max-h-0 overflow-hidden'}
                  `}
                >
                  <ul className="space-y-1.5">
                    {template.features.map((feature, idx) => (
                      <li
                        key={idx}
                        className="flex items-center gap-2 text-xs text-text-secondary"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 text-status-success" />
                        {feature}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* 操作按钮（悬停显示） */}
                <div
                  className={`
                    mt-4 flex items-center gap-2
                    transition-all duration-300
                    ${isHovered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'}
                  `}
                >
                  <span className="text-sm font-medium text-brand-primary flex items-center gap-1">
                    使用此模板
                    <ArrowRight className="w-4 h-4" />
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 底部提示 */}
      <div className="flex items-center justify-center p-6 bg-bg-secondary rounded-xl border border-border-default border-dashed">
        <div className="text-center">
          <Code2 className="w-8 h-8 text-text-tertiary mx-auto mb-2" />
          <p className="text-sm text-text-secondary">
            没有找到合适的模板？
          </p>
          <button className="mt-2 text-sm font-medium text-brand-primary hover:underline">
            创建自定义需求 →
          </button>
        </div>
      </div>
    </div>
  );
}
