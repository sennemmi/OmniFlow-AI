import { useState } from 'react';
import {
  User,
  Bell,
  Shield,
  Key,
  Database,
  Globe,
  Palette,
  Save,
  CheckCircle2,
  Mail,
  Lock,
  Eye,
  EyeOff,
  Upload,
  Trash2,
} from 'lucide-react';
import { useUIStore } from '@stores/uiStore';

// ============================================
// 设置页面 - 企业级配置中心
// ============================================

type SettingTab = 'profile' | 'notifications' | 'security' | 'integrations' | 'appearance' | 'advanced';

interface SettingSection {
  id: SettingTab;
  label: string;
  icon: React.ElementType;
  description: string;
}

const settingSections: SettingSection[] = [
  { id: 'profile', label: '个人资料', icon: User, description: '管理您的个人信息和头像' },
  { id: 'notifications', label: '通知设置', icon: Bell, description: '配置消息提醒和通知方式' },
  { id: 'security', label: '安全设置', icon: Shield, description: '密码、双因素认证和登录历史' },
  { id: 'integrations', label: '集成配置', icon: Database, description: '连接第三方服务和 API' },
  { id: 'appearance', label: '外观设置', icon: Palette, description: '主题、语言和界面偏好' },
  { id: 'advanced', label: '高级设置', icon: Key, description: '开发者选项和系统配置' },
];

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingTab>('profile');
  const [isSaving, setIsSaving] = useState(false);
  const [showSaveSuccess, setShowSaveSuccess] = useState(false);
  const { addToast } = useUIStore();

  const handleSave = async () => {
    setIsSaving(true);
    // 模拟保存
    await new Promise((resolve) => setTimeout(resolve, 1000));
    setIsSaving(false);
    setShowSaveSuccess(true);
    addToast({ message: '设置已保存', type: 'success' });
    setTimeout(() => setShowSaveSuccess(false), 3000);
  };

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">系统设置</h1>
          <p className="text-text-secondary mt-1">管理您的账户和系统偏好</p>
        </div>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="btn-primary"
        >
          {isSaving ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              保存中...
            </>
          ) : showSaveSuccess ? (
            <>
              <CheckCircle2 className="w-4 h-4 mr-2" />
              已保存
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              保存更改
            </>
          )}
        </button>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* 左侧导航 */}
        <div className="lg:col-span-1">
          <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card overflow-hidden">
            <nav className="p-2 space-y-1">
              {settingSections.map((section) => {
                const Icon = section.icon;
                const isActive = activeTab === section.id;
                return (
                  <button
                    key={section.id}
                    onClick={() => setActiveTab(section.id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-all duration-200 ${
                      isActive
                        ? 'bg-brand-primary-light text-brand-primary font-medium'
                        : 'text-text-secondary hover:bg-bg-secondary hover:text-text-primary'
                    }`}
                  >
                    <Icon className={`w-5 h-5 ${isActive ? 'text-brand-primary' : 'text-text-tertiary'}`} />
                    <span className="text-sm">{section.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </div>

        {/* 右侧内容 */}
        <div className="lg:col-span-3">
          <div className="bg-bg-primary rounded-xl border border-border-default shadow-feishu-card">
            {activeTab === 'profile' && <ProfileSettings />}
            {activeTab === 'notifications' && <NotificationSettings />}
            {activeTab === 'security' && <SecuritySettings />}
            {activeTab === 'integrations' && <IntegrationSettings />}
            {activeTab === 'appearance' && <AppearanceSettings />}
            {activeTab === 'advanced' && <AdvancedSettings />}
          </div>
        </div>
      </div>
    </div>
  );
}

// 个人资料设置
function ProfileSettings() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4 pb-6 border-b border-border-default">
        <div className="relative">
          <div className="w-20 h-20 rounded-full bg-brand-primary-light flex items-center justify-center">
            <User className="w-10 h-10 text-brand-primary" />
          </div>
          <button className="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-brand-primary text-white flex items-center justify-center hover:bg-brand-primary-hover transition-colors">
            <Upload className="w-4 h-4" />
          </button>
        </div>
        <div>
          <h3 className="text-lg font-semibold text-text-primary">个人资料</h3>
          <p className="text-text-secondary text-sm">更新您的头像和基本信息</p>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <label className="text-sm font-medium text-text-primary">显示名称</label>
          <input
            type="text"
            defaultValue="管理员"
            className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-text-primary">用户名</label>
          <input
            type="text"
            defaultValue="admin"
            disabled
            className="w-full px-4 py-2.5 bg-bg-tertiary border border-border-default rounded-lg text-text-tertiary cursor-not-allowed"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-text-primary">邮箱地址</label>
          <input
            type="email"
            defaultValue="admin@omniflow.ai"
            className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-text-primary">手机号码</label>
          <input
            type="tel"
            placeholder="请输入手机号码"
            className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
          />
        </div>
        <div className="space-y-2 md:col-span-2">
          <label className="text-sm font-medium text-text-primary">个人简介</label>
          <textarea
            rows={3}
            placeholder="介绍一下自己..."
            className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors resize-none"
          />
        </div>
      </div>
    </div>
  );
}

// 通知设置
function NotificationSettings() {
  const [settings, setSettings] = useState({
    emailPipelineComplete: true,
    emailPipelineFailed: true,
    emailApprovalRequired: true,
    emailWeeklyReport: false,
    browserPipelineComplete: true,
    browserPipelineFailed: true,
    browserApprovalRequired: true,
    slackEnabled: false,
    webhookEnabled: false,
  });

  const toggleSetting = (key: keyof typeof settings) => {
    setSettings((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-border-default">
        <h3 className="text-lg font-semibold text-text-primary">通知设置</h3>
        <p className="text-text-secondary text-sm">选择您希望接收的通知类型和方式</p>
      </div>

      {/* 邮件通知 */}
      <div className="space-y-4">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Mail className="w-4 h-4 text-brand-primary" />
          邮件通知
        </h4>
        <div className="space-y-3 pl-6">
          <ToggleItem
            label="流水线完成"
            description="当流水线成功完成时发送邮件"
            checked={settings.emailPipelineComplete}
            onChange={() => toggleSetting('emailPipelineComplete')}
          />
          <ToggleItem
            label="流水线失败"
            description="当流水线执行失败时发送邮件"
            checked={settings.emailPipelineFailed}
            onChange={() => toggleSetting('emailPipelineFailed')}
          />
          <ToggleItem
            label="需要审批"
            description="当有流水线需要您审批时发送邮件"
            checked={settings.emailApprovalRequired}
            onChange={() => toggleSetting('emailApprovalRequired')}
          />
          <ToggleItem
            label="周报"
            description="每周发送研发效率报告"
            checked={settings.emailWeeklyReport}
            onChange={() => toggleSetting('emailWeeklyReport')}
          />
        </div>
      </div>

      {/* 浏览器通知 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Globe className="w-4 h-4 text-brand-primary" />
          浏览器通知
        </h4>
        <div className="space-y-3 pl-6">
          <ToggleItem
            label="流水线完成"
            description="在浏览器中显示完成通知"
            checked={settings.browserPipelineComplete}
            onChange={() => toggleSetting('browserPipelineComplete')}
          />
          <ToggleItem
            label="流水线失败"
            description="在浏览器中显示失败通知"
            checked={settings.browserPipelineFailed}
            onChange={() => toggleSetting('browserPipelineFailed')}
          />
          <ToggleItem
            label="需要审批"
            description="在浏览器中显示审批提醒"
            checked={settings.browserApprovalRequired}
            onChange={() => toggleSetting('browserApprovalRequired')}
          />
        </div>
      </div>

      {/* 第三方集成 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Database className="w-4 h-4 text-brand-primary" />
          第三方集成
        </h4>
        <div className="space-y-3 pl-6">
          <ToggleItem
            label="Slack 通知"
            description="将通知发送到 Slack 频道"
            checked={settings.slackEnabled}
            onChange={() => toggleSetting('slackEnabled')}
          />
          <ToggleItem
            label="Webhook"
            description="通过 Webhook 接收通知"
            checked={settings.webhookEnabled}
            onChange={() => toggleSetting('webhookEnabled')}
          />
        </div>
      </div>
    </div>
  );
}

// 安全设置
function SecuritySettings() {
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-border-default">
        <h3 className="text-lg font-semibold text-text-primary">安全设置</h3>
        <p className="text-text-secondary text-sm">管理密码、双因素认证和登录历史</p>
      </div>

      {/* 修改密码 */}
      <div className="space-y-4">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Lock className="w-4 h-4 text-brand-primary" />
          修改密码
        </h4>
        <div className="grid md:grid-cols-2 gap-4 pl-6">
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm font-medium text-text-primary">当前密码</label>
            <div className="relative">
              <input
                type={showCurrentPassword ? 'text' : 'password'}
                placeholder="输入当前密码"
                className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
              />
              <button
                onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary"
              >
                {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-text-primary">新密码</label>
            <div className="relative">
              <input
                type={showNewPassword ? 'text' : 'password'}
                placeholder="输入新密码"
                className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
              />
              <button
                onClick={() => setShowNewPassword(!showNewPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary"
              >
                {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-text-primary">确认新密码</label>
            <input
              type="password"
              placeholder="再次输入新密码"
              className="w-full px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary transition-colors"
            />
          </div>
        </div>
        <div className="pl-6">
          <button className="btn-primary">更新密码</button>
        </div>
      </div>

      {/* 双因素认证 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Shield className="w-4 h-4 text-brand-primary" />
          双因素认证 (2FA)
        </h4>
        <div className="pl-6 p-4 bg-bg-secondary rounded-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-text-primary">启用双因素认证</p>
              <p className="text-sm text-text-secondary">通过验证码增强账户安全性</p>
            </div>
            <button className="btn-secondary">启用</button>
          </div>
        </div>
      </div>

      {/* 登录历史 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Key className="w-4 h-4 text-brand-primary" />
          登录历史
        </h4>
        <div className="pl-6 space-y-3">
          {[
            { device: 'Chrome on Windows', location: '北京, 中国', time: '当前会话', current: true },
            { device: 'Safari on macOS', location: '上海, 中国', time: '2 小时前', current: false },
            { device: 'Firefox on Linux', location: '深圳, 中国', time: '昨天', current: false },
          ].map((session, index) => (
            <div key={index} className="flex items-center justify-between p-3 bg-bg-secondary rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-brand-primary/10 flex items-center justify-center">
                  <Globe className="w-5 h-5 text-brand-primary" />
                </div>
                <div>
                  <p className="font-medium text-text-primary">{session.device}</p>
                  <p className="text-sm text-text-secondary">{session.location} · {session.time}</p>
                </div>
              </div>
              {session.current ? (
                <span className="px-2 py-1 rounded-full bg-status-success/10 text-status-success text-xs font-medium">
                  当前
                </span>
              ) : (
                <button className="text-status-error hover:text-status-error/80 text-sm">
                  登出
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// 集成设置
function IntegrationSettings() {
  const integrations = [
    { id: 'github', name: 'GitHub', description: '代码仓库集成', connected: true, icon: Database },
    { id: 'gitlab', name: 'GitLab', description: '自托管 Git 服务', connected: false, icon: Database },
    { id: 'slack', name: 'Slack', description: '团队通讯工具', connected: true, icon: Bell },
    { id: 'jira', name: 'Jira', description: '项目管理工具', connected: false, icon: Database },
    { id: 'docker', name: 'Docker Hub', description: '容器镜像仓库', connected: true, icon: Database },
    { id: 'aws', name: 'AWS', description: '云服务提供商', connected: false, icon: Globe },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-border-default">
        <h3 className="text-lg font-semibold text-text-primary">集成配置</h3>
        <p className="text-text-secondary text-sm">连接第三方服务和 API</p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {integrations.map((integration) => {
          const Icon = integration.icon;
          return (
            <div
              key={integration.id}
              className="flex items-center justify-between p-4 bg-bg-secondary rounded-lg border border-border-default hover:border-brand-primary/30 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-brand-primary/10 flex items-center justify-center">
                  <Icon className="w-5 h-5 text-brand-primary" />
                </div>
                <div>
                  <p className="font-medium text-text-primary">{integration.name}</p>
                  <p className="text-sm text-text-secondary">{integration.description}</p>
                </div>
              </div>
              {integration.connected ? (
                <div className="flex items-center gap-2">
                  <span className="flex items-center gap-1 text-status-success text-sm">
                    <CheckCircle2 className="w-4 h-4" />
                    已连接
                  </span>
                  <button className="p-2 text-text-tertiary hover:text-status-error transition-colors">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <button className="btn-secondary text-sm">连接</button>
              )}
            </div>
          );
        })}
      </div>

      {/* API 密钥 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Key className="w-4 h-4 text-brand-primary" />
          API 密钥
        </h4>
        <div className="pl-6 p-4 bg-bg-secondary rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="font-medium text-text-primary">个人访问令牌</p>
              <p className="text-sm text-text-secondary">用于程序化访问 API</p>
            </div>
            <button className="btn-primary">生成新令牌</button>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between p-3 bg-bg-tertiary rounded-lg">
              <div>
                <p className="font-medium text-text-primary">生产环境令牌</p>
                <p className="text-sm text-text-secondary">创建于 2024-01-15 · 最后使用 2 小时前</p>
              </div>
              <button className="p-2 text-text-tertiary hover:text-status-error transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// 外观设置
function AppearanceSettings() {
  const [theme, setTheme] = useState('light');
  const [language, setLanguage] = useState('zh-CN');
  const [density, setDensity] = useState('comfortable');

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-border-default">
        <h3 className="text-lg font-semibold text-text-primary">外观设置</h3>
        <p className="text-text-secondary text-sm">自定义主题、语言和界面偏好</p>
      </div>

      {/* 主题 */}
      <div className="space-y-4">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Palette className="w-4 h-4 text-brand-primary" />
          主题
        </h4>
        <div className="pl-6 grid grid-cols-3 gap-4">
          {[
            { id: 'light', name: '浅色', color: 'bg-white' },
            { id: 'dark', name: '深色', color: 'bg-slate-800' },
            { id: 'auto', name: '跟随系统', color: 'bg-gradient-to-r from-white to-slate-800' },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setTheme(t.id)}
              className={`p-4 rounded-lg border-2 transition-all ${
                theme === t.id
                  ? 'border-brand-primary bg-brand-primary/5'
                  : 'border-border-default hover:border-brand-primary/30'
              }`}
            >
              <div className={`w-full h-12 rounded-md ${t.color} border border-border-default mb-3`} />
              <p className="font-medium text-text-primary">{t.name}</p>
            </button>
          ))}
        </div>
      </div>

      {/* 语言 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Globe className="w-4 h-4 text-brand-primary" />
          语言
        </h4>
        <div className="pl-6">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full md:w-64 px-4 py-2.5 bg-bg-secondary border border-border-default rounded-lg text-text-primary focus:outline-none focus:border-brand-primary"
          >
            <option value="zh-CN">简体中文</option>
            <option value="zh-TW">繁體中文</option>
            <option value="en-US">English</option>
            <option value="ja-JP">日本語</option>
          </select>
        </div>
      </div>

      {/* 界面密度 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Database className="w-4 h-4 text-brand-primary" />
          界面密度
        </h4>
        <div className="pl-6 space-y-2">
          {[
            { id: 'compact', name: '紧凑', description: '更小的间距，显示更多内容' },
            { id: 'comfortable', name: '舒适', description: '平衡的间距，推荐设置' },
            { id: 'spacious', name: '宽松', description: '更大的间距，更易阅读' },
          ].map((d) => (
            <label
              key={d.id}
              className={`flex items-center justify-between p-4 rounded-lg border cursor-pointer transition-all ${
                density === d.id
                  ? 'border-brand-primary bg-brand-primary/5'
                  : 'border-border-default hover:border-brand-primary/30'
              }`}
            >
              <div>
                <p className="font-medium text-text-primary">{d.name}</p>
                <p className="text-sm text-text-secondary">{d.description}</p>
              </div>
              <input
                type="radio"
                name="density"
                value={d.id}
                checked={density === d.id}
                onChange={() => setDensity(d.id)}
                className="w-4 h-4 text-brand-primary"
              />
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

// 高级设置
function AdvancedSettings() {
  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-border-default">
        <h3 className="text-lg font-semibold text-text-primary">高级设置</h3>
        <p className="text-text-secondary text-sm">开发者选项和系统配置</p>
      </div>

      {/* 开发者模式 */}
      <div className="space-y-4">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Database className="w-4 h-4 text-brand-primary" />
          开发者选项
        </h4>
        <div className="pl-6 space-y-3">
          <ToggleItem
            label="开发者模式"
            description="启用调试信息和高级功能"
            checked={false}
            onChange={() => {}}
          />
          <ToggleItem
            label="实验性功能"
            description="启用尚未正式发布的实验性功能"
            checked={false}
            onChange={() => {}}
          />
        </div>
      </div>

      {/* 缓存管理 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Database className="w-4 h-4 text-brand-primary" />
          缓存管理
        </h4>
        <div className="pl-6 space-y-3">
          <div className="flex items-center justify-between p-4 bg-bg-secondary rounded-lg">
            <div>
              <p className="font-medium text-text-primary">本地缓存</p>
              <p className="text-sm text-text-secondary">当前缓存大小: 24.5 MB</p>
            </div>
            <button className="btn-secondary">清除缓存</button>
          </div>
        </div>
      </div>

      {/* 数据导出 */}
      <div className="space-y-4 pt-6 border-t border-border-default">
        <h4 className="font-medium text-text-primary flex items-center gap-2">
          <Database className="w-4 h-4 text-brand-primary" />
          数据管理
        </h4>
        <div className="pl-6 space-y-3">
          <div className="flex items-center justify-between p-4 bg-bg-secondary rounded-lg">
            <div>
              <p className="font-medium text-text-primary">导出数据</p>
              <p className="text-sm text-text-secondary">下载您的所有数据副本</p>
            </div>
            <button className="btn-secondary">导出</button>
          </div>
          <div className="flex items-center justify-between p-4 bg-status-error/5 border border-status-error/20 rounded-lg">
            <div>
              <p className="font-medium text-status-error">删除账户</p>
              <p className="text-sm text-text-secondary">永久删除您的账户和所有数据</p>
            </div>
            <button className="px-4 py-2 bg-status-error text-white rounded-lg hover:bg-status-error/90 transition-colors">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// 切换项组件
interface ToggleItemProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: () => void;
}

function ToggleItem({ label, description, checked, onChange }: ToggleItemProps) {
  return (
    <div className="flex items-center justify-between p-3 bg-bg-secondary rounded-lg">
      <div>
        <p className="font-medium text-text-primary">{label}</p>
        <p className="text-sm text-text-secondary">{description}</p>
      </div>
      <button
        onClick={onChange}
        className={`relative w-11 h-6 rounded-full transition-colors ${
          checked ? 'bg-brand-primary' : 'bg-bg-tertiary'
        }`}
      >
        <span
          className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}
