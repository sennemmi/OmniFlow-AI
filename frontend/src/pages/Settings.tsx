import { useState } from 'react';
import {
  User,
  Bell,
  Shield,
  Palette,
  Save,
  CheckCircle2,
  Mail,
  Globe,
  Eye,
  EyeOff,
} from 'lucide-react';
import { useUIStore } from '@stores/uiStore';

// ============================================
// 设置页面 - 简化版
// ============================================

type SettingTab = 'profile' | 'notifications' | 'security' | 'appearance';

interface SettingSection {
  id: SettingTab;
  label: string;
  icon: React.ElementType;
  description: string;
}

const settingSections: SettingSection[] = [
  { id: 'profile', label: '个人资料', icon: User, description: '管理您的个人信息' },
  { id: 'notifications', label: '通知设置', icon: Bell, description: '配置消息提醒方式' },
  { id: 'security', label: '安全设置', icon: Shield, description: '密码和账户安全' },
  { id: 'appearance', label: '外观设置', icon: Palette, description: '主题和界面偏好' },
];

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingTab>('profile');
  const [isSaving, setIsSaving] = useState(false);
  const [showSaveSuccess, setShowSaveSuccess] = useState(false);
  const { addToast } = useUIStore();

  const handleSave = async () => {
    setIsSaving(true);
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
          <h1 className="text-2xl font-bold text-slate-900">系统设置</h1>
          <p className="text-slate-500 mt-1">管理您的账户和系统偏好</p>
        </div>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-all disabled:opacity-50"
        >
          {isSaving ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              保存中...
            </>
          ) : showSaveSuccess ? (
            <>
              <CheckCircle2 className="w-4 h-4" />
              已保存
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              保存更改
            </>
          )}
        </button>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* 左侧导航 */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
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
                        ? 'bg-blue-50 text-blue-600 font-medium'
                        : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                    }`}
                  >
                    <Icon className={`w-5 h-5 ${isActive ? 'text-blue-600' : 'text-slate-400'}`} />
                    <span className="text-sm">{section.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </div>

        {/* 右侧内容 */}
        <div className="lg:col-span-3">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
            {activeTab === 'profile' && <ProfileSettings />}
            {activeTab === 'notifications' && <NotificationSettings />}
            {activeTab === 'security' && <SecuritySettings />}
            {activeTab === 'appearance' && <AppearanceSettings />}
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
      <div className="flex items-center gap-4 pb-6 border-b border-slate-100">
        <div className="w-20 h-20 rounded-full bg-blue-50 flex items-center justify-center">
          <User className="w-10 h-10 text-blue-600" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-slate-900">个人资料</h3>
          <p className="text-slate-500 text-sm">更新您的基本信息</p>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700">显示名称</label>
          <input
            type="text"
            defaultValue="管理员"
            className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700">用户名</label>
          <input
            type="text"
            defaultValue="admin"
            disabled
            className="w-full px-4 py-2.5 bg-slate-100 border border-slate-200 rounded-lg text-slate-400 cursor-not-allowed"
          />
        </div>
        <div className="space-y-2 md:col-span-2">
          <label className="text-sm font-medium text-slate-700">邮箱地址</label>
          <input
            type="email"
            defaultValue="admin@omniflow.ai"
            className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 transition-colors"
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
    browserPipelineComplete: true,
    browserPipelineFailed: true,
  });

  const toggleSetting = (key: keyof typeof settings) => {
    setSettings((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-slate-100">
        <h3 className="text-lg font-semibold text-slate-900">通知设置</h3>
        <p className="text-slate-500 text-sm">选择您希望接收的通知类型</p>
      </div>

      {/* 邮件通知 */}
      <div className="space-y-4">
        <h4 className="font-medium text-slate-900 flex items-center gap-2">
          <Mail className="w-4 h-4 text-blue-600" />
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
        </div>
      </div>

      {/* 浏览器通知 */}
      <div className="space-y-4 pt-6 border-t border-slate-100">
        <h4 className="font-medium text-slate-900 flex items-center gap-2">
          <Globe className="w-4 h-4 text-blue-600" />
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
      <div className="pb-6 border-b border-slate-100">
        <h3 className="text-lg font-semibold text-slate-900">安全设置</h3>
        <p className="text-slate-500 text-sm">管理密码和账户安全</p>
      </div>

      {/* 修改密码 */}
      <div className="space-y-4">
        <h4 className="font-medium text-slate-900 flex items-center gap-2">
          <Shield className="w-4 h-4 text-blue-600" />
          修改密码
        </h4>
        <div className="space-y-4 pl-6">
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">当前密码</label>
            <div className="relative">
              <input
                type={showCurrentPassword ? 'text' : 'password'}
                placeholder="输入当前密码"
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 transition-colors"
              />
              <button
                onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700">新密码</label>
            <div className="relative">
              <input
                type={showNewPassword ? 'text' : 'password'}
                placeholder="输入新密码"
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500 transition-colors"
              />
              <button
                onClick={() => setShowNewPassword(!showNewPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
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

  return (
    <div className="p-6 space-y-6">
      <div className="pb-6 border-b border-slate-100">
        <h3 className="text-lg font-semibold text-slate-900">外观设置</h3>
        <p className="text-slate-500 text-sm">自定义主题和语言</p>
      </div>

      {/* 主题 */}
      <div className="space-y-4">
        <h4 className="font-medium text-slate-900 flex items-center gap-2">
          <Palette className="w-4 h-4 text-blue-600" />
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
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-slate-200 hover:border-blue-300'
              }`}
            >
              <div className={`w-full h-12 rounded-md ${t.color} border border-slate-200 mb-3`} />
              <p className="font-medium text-slate-900">{t.name}</p>
            </button>
          ))}
        </div>
      </div>

      {/* 语言 */}
      <div className="space-y-4 pt-6 border-t border-slate-100">
        <h4 className="font-medium text-slate-900 flex items-center gap-2">
          <Globe className="w-4 h-4 text-blue-600" />
          语言
        </h4>
        <div className="pl-6">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full md:w-64 px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:border-blue-500"
          >
            <option value="zh-CN">简体中文</option>
            <option value="en-US">English</option>
          </select>
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
    <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
      <div>
        <p className="font-medium text-slate-900">{label}</p>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <button
        onClick={onChange}
        className={`relative w-11 h-6 rounded-full transition-colors ${
          checked ? 'bg-blue-600' : 'bg-slate-300'
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
