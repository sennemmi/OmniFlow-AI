import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';

// ============================================
// 控制台布局 - 飞书文档风格
// ============================================

export function ConsoleLayout() {
  return (
    <div className="h-screen flex overflow-hidden bg-bg-secondary">
      {/* 侧边栏 */}
      <Sidebar />

      {/* 主内容区 */}
      <main className="flex-1 overflow-auto">
        <div className="min-h-full p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
