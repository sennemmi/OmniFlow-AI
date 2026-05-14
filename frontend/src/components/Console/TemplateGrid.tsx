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
    id: 'new-api-endpoint',
    title: 'New API Endpoint',
    description: '为现有资源新增 RESTful 接口',
    icon: Zap,
    color: 'text-status-success',
    bgColor: 'bg-status-success/10',
    category: '功能开发',
    prompt: '请在现有项目中新增以下 API 接口：\n\n功能描述：[用一句话描述接口做什么，如"新增用户收藏文章功能"]\n\n参考现有接口：[可选，如 app/api/v1/user.py 中的 get_user 接口]\n\n要求：\n- 遵循项目现有的 ResponseModel 响应格式\n- 复用现有的 Service 层和 Repository 层，不重复造轮子\n- 自动生成分层测试',
    features: ['自动读取现有代码', '接口契约验证', '自动写测试'],
  },
  {
    id: 'service-refactor',
    title: 'Service Layer Refactor',
    description: '拆分职责混乱的 Service，提取独立逻辑',
    icon: Layers,
    color: 'text-status-warning',
    bgColor: 'bg-status-warning/10',
    category: '架构重构',
    prompt: '请重构以下 Service 文件，解决职责混乱问题：\n\n目标文件：[如 app/service/order_service.py]\n\n重构方向：[如"将支付逻辑拆分为独立的 PaymentService，订单状态管理保留在 OrderService"]\n\n约束：\n- 保持所有现有接口签名不变（不破坏调用方）\n- 回归测试必须全部通过\n- 新 Service 需有对应测试覆盖',
    features: ['影响分析', '接口兼容保证', '回归测试保护'],
  },
  {
    id: 'data-model-extension',
    title: 'Data Model Extension',
    description: '扩展现有数据模型，新增字段和迁移脚本',
    icon: Database,
    color: 'text-brand-primary',
    bgColor: 'bg-brand-primary/10',
    category: '功能开发',
    prompt: '请扩展现有数据模型：\n\n目标模型：[如 app/models/user.py 中的 User]\n\n新增字段：[如"新增 avatar_url: Optional[str]、bio: Optional[str]、updated_at: datetime"]\n\n需要同步更新：\n- 数据库迁移脚本（Alembic）\n- 相关 API 的请求/响应 schema\n- 现有的读写接口',
    features: ['模型联动更新', 'Schema 同步', '迁移脚本生成'],
  },
  {
    id: 'bug-fix-from-log',
    title: 'Bug Fix from Log',
    description: '粘贴报错日志，自动定位并修复',
    icon: Bug,
    color: 'text-status-error',
    bgColor: 'bg-status-error/10',
    category: '调试修复',
    prompt: '请根据以下错误日志修复代码：\n\n【错误日志】\n[在此处粘贴完整的 traceback 或错误信息]\n\n【复现条件】（可选）\n[描述什么操作会触发这个错误]\n\n要求：\n- 只修改导致错误的代码，不做无关改动\n- 添加针对该错误的回归测试，防止复现',
    features: ['Traceback 精准定位', '最小化修改', '防复现测试'],
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
