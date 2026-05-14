import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  GitBranch,
  Settings,
  FileText,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Monitor,
  Zap,
} from 'lucide-react';
import { useUIStore } from '@stores/uiStore';

// ============================================
// 侧边栏 - 飞书风格
// ============================================

const sidebarItems = [
  { id: 'dashboard', label: '概览', icon: LayoutDashboard, path: '/console' },
  { id: 'pipelines', label: '流水线', icon: GitBranch, path: '/console/pipelines' },
  { id: 'workspace', label: '工作区看板', icon: Monitor, path: '/console/workspace' },
  { id: 'analytics', label: '统计', icon: BarChart3, path: '/console/analytics' },
  { id: 'documents', label: '文档', icon: FileText, path: '/console/documents' },
  { id: 'settings', label: '设置', icon: Settings, path: '/console/settings' },
];

export function Sidebar() {
  const location = useLocation();
  const { isSidebarCollapsed, toggleSidebar } = useUIStore();

  const isActive = (path: string) => {
    if (path === '/console') {
      return location.pathname === '/console' || location.pathname === '/console/';
    }
    return location.pathname.startsWith(path);
  };

  return (
    <aside
      className={`h-full bg-white border-r border-gray-200 flex flex-col transition-all duration-300 ${
        isSidebarCollapsed ? 'w-16' : 'w-64'
      }`}
    >
      {/* Logo 区域 */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200/50">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center flex-shrink-0">
            <Zap className="w-5 h-5 text-white" />
          </div>
          {!isSidebarCollapsed && (
            <span className="font-semibold text-gray-900">OmniFlowAI</span>
          )}
        </Link>
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors"
        >
          {isSidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* 导航项 */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {sidebarItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);

          return (
            <Link
              key={item.id}
              to={item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md transition-all duration-200 group ${
                active
                  ? 'bg-blue-50 text-blue-600 font-medium'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
              title={isSidebarCollapsed ? item.label : undefined}
            >
              <Icon className={`w-5 h-5 flex-shrink-0 ${active ? 'text-blue-600' : 'text-gray-400 group-hover:text-gray-600'}`} />
              {!isSidebarCollapsed && (
                <span className="text-sm truncate flex-1">{item.label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* 底部信息 */}
      {!isSidebarCollapsed && (
        <div className="p-4 border-t border-gray-200/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center">
              <span className="text-xs font-semibold text-blue-600">AI</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">OmniFlowAI</p>
              <p className="text-xs text-gray-500 truncate">v1.0.0</p>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
