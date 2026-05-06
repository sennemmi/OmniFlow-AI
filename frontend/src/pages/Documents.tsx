import { useState } from 'react';
import {
  Book,
  Code,
  Terminal,
  Search,
  Copy,
  CheckCircle2,
  Lightbulb,
  Zap,
} from 'lucide-react';

// ============================================
// 文档中心 - 简化版
// ============================================

type DocCategory = 'getting-started' | 'guides' | 'api' | 'cli';

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
      <aside className="w-64 flex-shrink-0 bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
        {/* 搜索 */}
        <div className="p-4 border-b border-gray-200">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文档..."
              className="w-full pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:border-blue-500"
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
                    ? 'bg-blue-50 text-blue-600'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`}
              >
                <Icon className={`w-5 h-5 mt-0.5 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
                <div>
                  <p className={`font-medium text-sm ${isActive ? 'text-blue-600' : ''}`}>
                    {section.label}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{section.description}</p>
                </div>
              </button>
            );
          })}
        </nav>
      </aside>

      {/* 右侧内容 */}
      <main className="flex-1 bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
        <div className="h-full overflow-y-auto">
          {activeSection === 'getting-started' && <GettingStartedContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'guides' && <GuidesContent />}
          {activeSection === 'api' && <ApiContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
          {activeSection === 'cli' && <CliContent onCopy={handleCopyCode} copiedCode={copiedCode} />}
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
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-sm font-medium mb-4">
          <Zap className="w-4 h-4" />
          快速开始
        </div>
        <h1 className="text-3xl font-bold text-gray-900 mb-4">5 分钟上手 OmniFlowAI</h1>
        <p className="text-gray-600 text-lg">
          本指南将帮助您快速了解 OmniFlowAI 的核心功能，并创建您的第一个 AI 驱动流水线。
        </p>
      </div>

      {/* 步骤 1 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-sm font-bold">1</span>
          访问控制台
        </h2>
        <p className="text-gray-600 mb-4">
          点击导航栏的"控制台"进入主界面，您可以在这里查看系统概览和创建流水线。
        </p>
      </section>

      {/* 步骤 2 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-sm font-bold">2</span>
          创建流水线
        </h2>
        <p className="text-gray-600 mb-4">
          点击"创建流水线"按钮，输入您的需求描述，AI 将自动为您生成完整的研发流程。
        </p>
      </section>

      {/* 步骤 3 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-sm font-bold">3</span>
          使用可视化工作区
        </h2>
        <p className="text-gray-600 mb-4">
          进入"工作区看板"，在浏览器中直接圈选页面元素，提交修改需求，AI 将自动定位并修改对应代码。
        </p>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-sm text-blue-700">
            <Lightbulb className="w-4 h-4 inline mr-2" />
            提示：确保在开发模式下运行前端项目，以获得最精确的源码定位。
          </p>
        </div>
      </section>
    </div>
  );
}

// 使用指南内容
function GuidesContent() {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-sm font-medium mb-4">
          <Book className="w-4 h-4" />
          使用指南
        </div>
        <h1 className="text-3xl font-bold text-gray-900 mb-4">操作教程</h1>
        <p className="text-gray-600 text-lg">
          深入了解 OmniFlowAI 的各项功能，掌握企业级研发自动化的使用方法。
        </p>
      </div>

      <div className="p-6 bg-gray-50 rounded-xl border border-gray-200">
        <p className="text-gray-600">文档内容正在完善中...</p>
      </div>
    </div>
  );
}

// API 文档内容
function ApiContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-sm font-medium mb-4">
          <Code className="w-4 h-4" />
          API 文档
        </div>
        <h1 className="text-3xl font-bold text-gray-900 mb-4">RESTful API 参考</h1>
        <p className="text-gray-600 text-lg">
          通过 API 程序化地管理流水线、获取状态和触发构建。
        </p>
      </div>

      {/* 基础信息 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">基础信息</h2>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200 space-y-3">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-gray-500 w-20">Base URL</span>
            <code className="px-3 py-1 bg-white rounded text-sm text-gray-900">
              /api/v1
            </code>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-gray-500 w-20">认证方式</span>
            <span className="text-sm text-gray-900">Session Cookie</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-gray-500 w-20">Content-Type</span>
            <span className="text-sm text-gray-900">application/json</span>
          </div>
        </div>
      </section>

      {/* 创建流水线 */}
      <section className="mb-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">创建流水线</h2>
        <div className="flex items-center gap-3 mb-4">
          <span className="px-2 py-1 bg-green-500 text-white text-xs font-bold rounded">POST</span>
          <code className="text-sm text-gray-900">/pipeline</code>
        </div>
        <p className="text-gray-600 mb-4">创建一个新的 AI 驱动流水线。</p>
        
        <h4 className="font-medium text-gray-900 mb-2">请求参数</h4>
        <CodeBlock
          id="create-pipeline-request"
          language="json"
          code={`{
  "description": "创建一个用户登录页面"
}`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />

        <h4 className="font-medium text-gray-900 mb-2 mt-4">响应示例</h4>
        <CodeBlock
          id="create-pipeline-response"
          language="json"
          code={`{
  "success": true,
  "data": {
    "pipeline_id": 123,
    "status": "running",
    "current_stage": "architecture"
  },
  "request_id": "req_abc123"
}`}
          onCopy={onCopy}
          copiedCode={copiedCode}
        />
      </section>
    </div>
  );
}

// CLI 内容
function CliContent({ onCopy, copiedCode }: { onCopy: (id: string, code: string) => void; copiedCode: string | null }) {
  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-sm font-medium mb-4">
          <Terminal className="w-4 h-4" />
          CLI 工具
        </div>
        <h1 className="text-3xl font-bold text-gray-900 mb-4">命令行工具</h1>
        <p className="text-gray-600 text-lg">
          使用 CLI 在终端中管理流水线，适合 CI/CD 集成。
        </p>
      </div>

      <div className="p-6 bg-gray-50 rounded-xl border border-gray-200">
        <p className="text-gray-600">CLI 工具正在开发中...</p>
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
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 rounded-t-lg">
        <span className="text-xs text-gray-400">{language}</span>
        <button
          onClick={() => onCopy(id, code)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
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
        <code className="text-sm text-gray-300 font-mono">{code}</code>
      </pre>
    </div>
  );
}
