import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@utils/queryClient';
import { Landing } from '@pages/Landing';
import { Console } from '@pages/Console';
import { Pipelines } from '@pages/Pipelines';
import { PipelineDetail } from '@pages/PipelineDetail';
import { Workspace } from '@pages/Workspace';
import { Settings } from '@pages/Settings';
import { Analytics } from '@pages/Analytics';
import { Documents } from '@pages/Documents';
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
            <Route path="pipelines" element={<Pipelines />} />
            <Route path="pipelines/:id" element={<PipelineDetail />} />
            <Route path="workspace" element={<Workspace />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="documents" element={<Documents />} />
            <Route path="settings" element={<Settings />} />
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
