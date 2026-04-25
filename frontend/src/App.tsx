import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@utils/queryClient';
import { Landing, Console, PipelineDetail } from '@pages';
import { ConsoleLayout } from '@components/Layout';

// ============================================
// OmniFlowAI 主应用
// ============================================

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* 官网首页 */}
          <Route path="/" element={<Landing />} />

          {/* 控制台路由 */}
          <Route path="/console" element={<ConsoleLayout />}>
            <Route index element={<Console />} />
            <Route path="pipelines" element={<Console />} />
            <Route path="pipelines/:id" element={<PipelineDetail />} />
            <Route path="analytics" element={<div className="p-8 text-text-secondary">统计页面开发中...</div>} />
            <Route path="documents" element={<div className="p-8 text-text-secondary">文档页面开发中...</div>} />
            <Route path="settings" element={<div className="p-8 text-text-secondary">设置页面开发中...</div>} />
          </Route>

          {/* 文档页面 */}
          <Route path="/docs" element={<div className="p-8 text-text-secondary">文档页面开发中...</div>} />

          {/* 404 重定向 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
