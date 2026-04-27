import { useState } from 'react';
import {
  Book,
  FileText,
  Code,
  Terminal,
  HelpCircle,
  Search,
  ChevronRight,
  ExternalLink,
  Copy,
  CheckCircle2,
  Play,
  AlertTriangle,
  Info,
  Lightbulb,
  Zap,
  GitBranch,
  Settings,
  Shield,
} from 'lucide-react';

// ============================================
// 文档中心 - 企业级知识库
// ============================================

type DocCategory = 'getting-started' | 'guides' | 'api' | 'cli' | 'best-practices' | 'faq';

interface DocSection {
  id: DocCategory;
  label: string;
  icon: React.ElementType;
  description: string;
}

const docSections: DocSection[] = [
  { id: 'getting-started', label: '快速开始', icon: Zap, description: '5 分钟上手 OmniFlowAI' },
  { id: 'guides', label: '使用指南', icon: Book, description: '详细的操作教程' },
  { id: 'api', label: 'API 文档', icon: Code, description: 'RESTful API 参考' },
  { id: 'cli', label: 'CLI 工具', icon: Terminal, description: '命令行工具使用' },
  { id: 'best-practices', label: '最佳实践', icon: Lightbulb, description: '企业级使用建议' },
  { id: 'faq', label: '常见问题', icon: HelpCircle, description: 'FAQ 和故障排除' },
];

export function Documents() {
  const [activeSection, setActiveSection] = useState<DocCategory>('getting-started');
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const handleCopyCode = (codeId: string, code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(codeId);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <div className="h-[calc(100vh-6rem)] flex gap-6">
      {/* 左侧导航 */}
      <aside className="w-64 flex-shrink-0 bg-bg-primary rounded-xl border border-border-default shadow-feishu-card overflow-hidden">
        {/* 搜索 */}
        <div className="p-4 border-b border-border-default">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文档..."
              className="w-full pl-9 pr-4 py-2 bg-bg-secondary border border-border-default rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary"
            />
          </div>
        </div>

        {/* 导航菜单 */}
        <nav className="p-2 space-y-1 overflow-y-auto">
          {docSections.map((section) => {
            const Icon = section.icon;
            const isActive = activeSection === section.id;
            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-start gap-3 px-3 py-3 rounded-lg text-left transition-all duration-200 ${
                  isActive
                    ? 'bg-brand-primary-light text-brand-primary'
                    : 'text-text-secondary hover:bg-bg-secondary hover:text-text-primary'
                }`}
              >
                <Icon className={`w-5 h-5 mt-0.5 ${isActive ? 'text-brand-primary' : 'text-text-tertiary'}`} />
                <div>
                  <p className={`font-medium text-sm ${isActive ? 'text-brand-primary' : ''}`}>
                    {section.label}
                  </p>
                  <p className="text-xs text-text-tertiary mt-0.5">{section.description}</p>
                </div>
              </button>
            );
          })}
        </nav>

        {/* 底部链接 */}
        <div className="p-4 border-t border-border-default">
          <a
            href="#"
            className="flex items-center gap-2 text-sm text-text-secondary hover:text-brand-primary transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            访问完整文档站点
          </a>
        </div>
      </aside>

      {/* 右侧内容 */}
      <main className="flex-1 bg-bg-primary rounded-xl border border-border-default shadow-feishu-card overflow-hidden">
        <div className="h-full overflow-y-auto">
          {activeSection === 'getting-started' && <GettingStartedContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'guides' && <GuidesContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'api' && <ApiContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'cli' && <CliContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'best-practices' && <BestPracticesContent />}
          {activeSection === 'faq' && <FaqContent />}
        </div>
      </main>
    </div>
  );
}

// 快速开始内容
function GettingStartedContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <Zap className="w-4 h-4" />
          快速开始
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">5 分钟上手 OmniFlowAI</h1>
        <p className="text-text-secondary text-lg">
          本指南将帮助您快速了解 OmniFlowAI 的核心功能，并创建您的第一个 AI 驱动流水线。
        </p>
      </div>

      {/* 步骤 1 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-brand-primary text-white flex items-center justify-center text-sm font-bold">1</span>
          创建账户
        </h2>
        <p className="text-text-secondary mb-4">
          首先，您需要创建一个 OmniFlowAI 账户。访问控制台，点击"免费开始使用"按钮完成注册。
        </p>
        <div className="bg-bg-secondary rounded-lg p-4 border border-border-default">
          <p className="text-sm text-text-secondary">
            <Info className="w-4 h-4 inline mr-2 text-brand-primary" />
            免费版包含每月 10 次 AI 代码生成，足够个人开发者体验核心功能。
          </p>
        </div>
      </section>

      {/* 步骤 2 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-brand-primary text-white flex items-center justify-center text-sm font-bold">2</span>
          连接代码仓库
        </h2>
        <p className="text-text-secondary mb-4">
          OmniFlowAI 需要访问您的代码仓库才能进行 AI 代码生成。我们支持 GitHub、GitLab 等主流平台。
        </p>
        <CodeBlock
          id="connect-repo"
          language="bash"
          code={`# 在设置页面连接 GitHub 账户
# 1. 进入 设置 → 集成配置
# 2. 点击 GitHub 的"连接"按钮
# 3. 授权 OmniFlowAI 访问您的仓库`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>

      {/* 步骤 3 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-brand-primary text-white flex items-center justify-center text-sm font-bold">3</span>
          创建第一个流水线
        </h2>
        <p className="text-text-secondary mb-4">
          在控制台首页，点击"创建流水线"按钮，输入您的需求描述，AI 将自动为您生成完整的研发流程。
        </p>
        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <div className="p-4 bg-bg-secondary rounded-lg border border-border-default">
            <h4 className="font-medium text-text-primary mb-2">示例需求</h4>
            <p className="text-sm text-text-secondary">
              "创建一个用户登录页面，包含邮箱验证、密码强度检查和记住我功能"
            </p>
          </div>
          <div className="p-4 bg-bg-secondary rounded-lg border border-border-default">
            <h4 className="font-medium text-text-primary mb-2">AI 输出</h4>
            <ul className="text-sm text-text-secondary space-y-1">
              <li>✓ 技术架构设计</li>
              <li>✓ React 登录组件</li>
              <li>✓ 后端 API 接口</li>
              <li>✓ 单元测试用例</li>
            </ul>
          </div>
        </div>
      </section>

      {/* 步骤 4 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-brand-primary text-white flex items-center justify-center text-sm font-bold">4</span>
          使用可视化工作区
        </h2>
        <p className="text-text-secondary mb-4">
          进入"工作区看板"，在浏览器中直接圈选页面元素，提交修改需求，AI 将自动定位并修改对应代码。
        </p>
        <div className="bg-brand-primary/5 border border-brand-primary/20 rounded-lg p-4">
          <p className="text-sm text-brand-primary">
            <Lightbulb className="w-4 h-4 inline mr-2" />
            提示：确保在开发模式下运行前端项目，以获得最精确的源码定位。
          </p>
        </div>
      </section>

      {/* 下一步 */}
      <section className="p-6 bg-gradient-to-br from-brand-primary/5 to-purple-500/5 rounded-xl border border-brand-primary/20">
        <h3 className="text-lg font-semibold text-text-primary mb-2">继续学习</h3>
        <p className="text-text-secondary mb-4">
          恭喜！您已完成快速入门。接下来可以深入了解各个功能模块。
        </p>
        <div className="flex flex-wrap gap-3">
          <a href="#" className="inline-flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg text-sm font-medium hover:bg-brand-primary-hover transition-colors">
            查看使用指南
            <ChevronRight className="w-4 h-4" />
          </a>
          <a href="#" className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-border-default text-text-primary rounded-lg text-sm font-medium hover:bg-bg-secondary transition-colors">
            阅读 API 文档
          </a>
        </div>
      </section>
    </div>
  );
}

// 使用指南内容
function GuidesContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  const guides = [
    {
      title: '流水线配置指南',
      description: '学习如何配置和自定义 AI 研发流水线',
      icon: GitBranch,
      sections: ['创建流水线', '配置阶段', '设置审批节点', '触发器配置'],
    },
    {
      title: '工作区使用指南',
      description: '掌握可视化圈选和代码修改技巧',
      icon: Settings,
      sections: ['启动工作区', '元素圈选', '提交修改', '查看变更'],
    },
    {
      title: '团队协作指南',
      description: '配置团队权限和审批工作流',
      icon: Shield,
      sections: ['邀请成员', '角色权限', '审批流程', '代码评审'],
    },
  ];

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <Book className="w-4 h-4" />
          使用指南
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">详细操作教程</h1>
        <p className="text-text-secondary text-lg">
          深入了解 OmniFlowAI 的各项功能，掌握企业级研发自动化的最佳实践。
        </p>
      </div>

      <div className="grid gap-6">
        {guides.map((guide, index) => {
          const Icon = guide.icon;
          return (
            <div key={index} className="p-6 bg-bg-secondary rounded-xl border border-border-default hover:border-brand-primary/30 transition-colors">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-brand-primary/10 flex items-center justify-center flex-shrink-0">
                  <Icon className="w-6 h-6 text-brand-primary" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-text-primary mb-2">{guide.title}</h3>
                  <p className="text-text-secondary mb-4">{guide.description}</p>
                  <div className="flex flex-wrap gap-2">
                    {guide.sections.map((section) => (
                      <span
                        key={section}
                        className="px-3 py-1 rounded-full bg-bg-tertiary text-text-secondary text-sm"
                      >
                        {section}
                      </span>
                    ))}
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-text-tertiary" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// API 文档内容
function ApiContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <Code className="w-4 h-4" />
          API 文档
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">RESTful API 参考</h1>
        <p className="text-text-secondary text-lg">
          通过 API 程序化地管理流水线、获取状态和触发构建。
        </p>
      </div>

      {/* 基础信息 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">基础信息</h2>
        <div className="bg-bg-secondary rounded-lg p-4 border border-border-default space-y-3">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-text-secondary w-20">Base URL</span>
            <code className="px-3 py-1 bg-bg-tertiary rounded text-sm text-text-primary">
              https://api.omniflow.ai/v1
            </code>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-text-secondary w-20">认证方式</span>
            <span className="text-sm text-text-primary">Bearer Token</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-text-secondary w-20">Content-Type</span>
            <span className="text-sm text-text-primary">application/json</span>
          </div>
        </div>
      </section>

      {/* 认证 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">认证</h2>
        <p className="text-text-secondary mb-4">
          所有 API 请求都需要在 Header 中携带认证令牌。
        </p>
        <CodeBlock
          id="auth-header"
          language="bash"
          code={`Authorization: Bearer YOUR_API_TOKEN`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>

      {/* 创建流水线 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">创建流水线</h2>
        <div className="flex items-center gap-3 mb-4">
          <span className="px-2 py-1 bg-green-500 text-white text-xs font-bold rounded">POST</span>
          <code className="text-sm text-text-primary">/pipelines</code>
        </div>
        <p className="text-text-secondary mb-4">创建一个新的 AI 驱动流水线。</p>
        
        <h4 className="font-medium text-text-primary mb-2">请求参数</h4>
        <CodeBlock
          id="create-pipeline-request"
          language="json"
          code={`{
  "requirement": "创建一个用户登录页面",
  "element_context": {
    "tag": "div",
    "class": "login-form",
    "selector": ".login-form"
  },
  "source_context": {
    "file": "src/pages/Login.tsx",
    "line": 15
  }
}`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />

        <h4 className="font-medium text-text-primary mb-2 mt-4">响应示例</h4>
        <CodeBlock
          id="create-pipeline-response"
          language="json"
          code={`{
  "success": true,
  "data": {
    "pipeline_id": 123,
    "status": "running",
    "current_stage": "architecture",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "request_id": "req_abc123"
}`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>

      {/* 获取流水线状态 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">获取流水线状态</h2>
        <div className="flex items-center gap-3 mb-4">
          <span className="px-2 py-1 bg-blue-500 text-white text-xs font-bold rounded">GET</span>
          <code className="text-sm text-text-primary">/pipelines/{'{'}id{'}'}</code>
        </div>
        <p className="text-text-secondary mb-4">获取指定流水线的详细状态和进度。</p>
      </section>
    </div>
  );
}

// CLI 内容
function CliContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <Terminal className="w-4 h-4" />
          CLI 工具
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">命令行工具</h1>
        <p className="text-text-secondary text-lg">
          使用 OmniFlow CLI 在终端中管理流水线，适合 CI/CD 集成。
        </p>
      </div>

      {/* 安装 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">安装</h2>
        <CodeBlock
          id="install-cli"
          language="bash"
          code={`# 使用 npm 安装
npm install -g @omniflow/cli

# 或使用 yarn
yarn global add @omniflow/cli

# 验证安装
omniflow --version`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>

      {/* 认证 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">登录</h2>
        <CodeBlock
          id="cli-login"
          language="bash"
          code={`# 登录到 OmniFlowAI
omniflow login

# 或者使用 API Token
omniflow login --token YOUR_API_TOKEN`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>

      {/* 常用命令 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-text-primary mb-4">常用命令</h2>
        
        <div className="space-y-6">
          <div>
            <h4 className="font-medium text-text-primary mb-2">创建流水线</h4>
            <CodeBlock
              id="cli-create"
              language="bash"
              code={`# 从需求创建流水线
omniflow pipeline create "优化登录页面的加载速度"

# 从文件创建
omniflow pipeline create --file ./requirement.md`}
              onCopy={onCopy}
              copiedCode={copiedCode}
            />
          </div>

          <div>
            <h4 className="font-medium text-text-primary mb-2">查看流水线状态</h4>
            <CodeBlock
              id="cli-status"
              language="bash"
              code={`# 查看所有流水线
omniflow pipeline list

# 查看特定流水线
omniflow pipeline status 123

# 实时跟踪流水线进度
omniflow pipeline logs 123 --follow`}
              onCopy={onCopy}
              copiedCode={copiedCode}
            />
          </div>

          <div>
            <h4 className="font-medium text-text-primary mb-2">审批操作</h4>
            <CodeBlock
              id="cli-approve"
              language="bash"
              code={`# 批准流水线
omniflow pipeline approve 123

# 驳回流水线
omniflow pipeline reject 123 --reason "需要修改数据库设计"`}
              onCopy={onCopy}
              copiedCode={copiedCode}
            />
          </div>
        </div>
      </section>
    </div>
  );
}

// 最佳实践内容
function BestPracticesContent() {
  const practices = [
    {
      title: '需求描述规范',
      description: '编写清晰、具体的需求描述，帮助 AI 更好地理解您的意图',
      tips: [
        '明确功能目标和业务场景',
        '提供具体的输入输出示例',
        '说明技术栈和约束条件',
        '包含错误处理要求',
      ],
    },
    {
      title: '流水线设计原则',
      description: '设计高效、可靠的 AI 研发流水线',
      tips: [
        '合理设置阶段和依赖关系',
        '配置适当的质量门禁',
        '设置关键节点的审批',
        '保留必要的日志和审计信息',
      ],
    },
    {
      title: '代码审查策略',
      description: '建立有效的 AI 生成代码审查机制',
      tips: [
        '重点关注架构设计合理性',
        '检查安全漏洞和性能问题',
        '验证业务逻辑正确性',
        '确保代码风格一致性',
      ],
    },
    {
      title: '团队协作规范',
      description: '在团队中高效使用 OmniFlowAI',
      tips: [
        '统一需求提交模板',
        '建立审批权限体系',
        '定期进行经验总结',
        '分享有效的提示词',
      ],
    },
  ];

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <Lightbulb className="w-4 h-4" />
          最佳实践
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">企业级使用建议</h1>
        <p className="text-text-secondary text-lg">
          从行业领先企业的实践中总结出的使用建议，帮助您最大化 OmniFlowAI 的价值。
        </p>
      </div>

      <div className="space-y-8">
        {practices.map((practice, index) => (
          <div key={index} className="p-6 bg-bg-secondary rounded-xl border border-border-default">
            <h3 className="text-lg font-semibold text-text-primary mb-2">{practice.title}</h3>
            <p className="text-text-secondary mb-4">{practice.description}</p>
            <ul className="space-y-2">
              {practice.tips.map((tip, tipIndex) => (
                <li key={tipIndex} className="flex items-start gap-2 text-text-secondary">
                  <CheckCircle2 className="w-5 h-5 text-status-success flex-shrink-0 mt-0.5" />
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// FAQ 内容
function FaqContent() {
  const faqs = [
    {
      question: 'OmniFlowAI 支持哪些编程语言？',
      answer: 'OmniFlowAI 支持主流的前后端技术栈，包括但不限于：React、Vue、Angular、TypeScript、Python、Go、Java、Node.js 等。AI 会根据您的项目现有技术栈自动选择合适的语言。',
      category: 'general',
    },
    {
      question: 'AI 生成的代码质量如何？',
      answer: 'OmniFlowAI 采用先进的大语言模型，生成的代码经过多轮质量检查。系统会自动运行单元测试、代码扫描和安全检查，确保代码符合企业级标准。同时，所有变更都需要经过人工审批才能合并。',
      category: 'quality',
    },
    {
      question: '如何确保代码安全？',
      answer: '我们采用多层安全机制：1) 代码在隔离环境中生成和执行；2) 自动安全扫描检测漏洞；3) 敏感信息自动脱敏；4) 完整的审计日志；5) 企业版支持私有化部署，数据完全在您的控制之下。',
      category: 'security',
    },
    {
      question: '可视化工作区支持哪些浏览器？',
      answer: '可视化工作区支持所有现代浏览器，包括 Chrome、Firefox、Safari 和 Edge。推荐使用最新版本以获得最佳体验。对于 iframe 嵌入的场景，需要确保目标页面允许跨域访问。',
      category: 'workspace',
    },
    {
      question: '免费版和专业版有什么区别？',
      answer: '免费版适合个人开发者，包含每月 10 次 AI 代码生成和基础功能。专业版提供无限 AI 生成、高级流水线编排、可视化工作区、优先技术支持等功能。企业版额外提供私有化部署和 SLA 保障。',
      category: 'pricing',
    },
    {
      question: '如何集成到现有的 CI/CD 流程？',
      answer: 'OmniFlowAI 提供完整的 API 和 CLI 工具，可以轻松集成到 Jenkins、GitLab CI、GitHub Actions 等主流 CI/CD 平台。我们还提供预构建的插件和模板，简化集成过程。',
      category: 'integration',
    },
  ];

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-4">
          <HelpCircle className="w-4 h-4" />
          常见问题
        </div>
        <h1 className="text-3xl font-bold text-text-primary mb-4">FAQ</h1>
        <p className="text-text-secondary text-lg">
          常见问题解答和故障排除指南。
        </p>
      </div>

      <div className="space-y-4">
        {faqs.map((faq, index) => (
          <div key={index} className="p-6 bg-bg-secondary rounded-xl border border-border-default">
            <h3 className="text-lg font-semibold text-text-primary mb-3 flex items-start gap-2">
              <span className="text-brand-primary">Q:</span>
              {faq.question}
            </h3>
            <p className="text-text-secondary pl-6">
              <span className="text-status-success mr-2">A:</span>
              {faq.answer}
            </p>
          </div>
        ))}
      </div>

      {/* 更多帮助 */}
      <div className="mt-8 p-6 bg-brand-primary/5 border border-brand-primary/20 rounded-xl">
        <h3 className="text-lg font-semibold text-text-primary mb-2">还有其他问题？</h3>
        <p className="text-text-secondary mb-4">
          如果您没有找到需要的答案，可以通过以下方式获取帮助：
        </p>
        <div className="flex flex-wrap gap-3">
          <a href="#" className="inline-flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg text-sm font-medium hover:bg-brand-primary-hover transition-colors">
            联系支持团队
          </a>
          <a href="#" className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-border-default text-text-primary rounded-lg text-sm font-medium hover:bg-bg-secondary transition-colors">
            访问社区论坛
          </a>
        </div>
      </div>
    </div>
  );
}

// 代码块组件
interface CodeBlockProps {
  id: string;
  language: string;
  code: string;
  onCopy: (id: string, code: string) => void;
  copiedCode: string | null;
}

function CodeBlock({ id, language, code, onCopy, copiedCode }: CodeBlockProps) {
  return (
    <div className="relative group">
      <div className="flex items-center justify-between px-4 py-2 bg-slate-800 rounded-t-lg">
        <span className="text-xs text-white/60">{language}</span>
        <button
          onClick={() => onCopy(id, code)}
          className="flex items-center gap-1 text-xs text-white/60 hover:text-white transition-colors"
        >
          {copiedCode === id ? (
            <>
              <CheckCircle2 className="w-3 h-3" />
              已复制
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              复制
            </>
          )}
        </button>
      </div>
      <pre className="p-4 bg-slate-900 rounded-b-lg overflow-x-auto">
        <code className="text-sm text-white/90 font-mono">{code}</code>
      </pre>
    </div>
  );
}
