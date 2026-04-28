import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import componentDebugger from 'vite-plugin-component-debugger'
import path from 'path'

// OmniFlowAI 悬浮对话框注入插件
const omniFlowOverlayPlugin = () => ({
  name: 'omniflow-overlay',
  transformIndexHtml(html) {
    // 在 body 末尾注入 injector.js 脚本
    return html.replace(
      '</body>',
      '  <script src="/injector.js" data-api-url="http://localhost:8000"></script>\n</body>'
    )
  },
})

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const isDev = mode === 'development'

  return {
    plugins: [
      // 开发模式下注入源码位置信息
      isDev ? componentDebugger({
        preset: 'minimal',
        attributePrefix: 'data-source',
      }) : null,
      react(),
      tailwindcss(),
      // OmniFlowAI 悬浮对话框注入
      omniFlowOverlayPlugin(),
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@components': path.resolve(__dirname, './src/components'),
        '@pages': path.resolve(__dirname, './src/pages'),
        '@hooks': path.resolve(__dirname, './src/hooks'),
        '@stores': path.resolve(__dirname, './src/stores'),
        '@utils': path.resolve(__dirname, './src/utils'),
        '@types': path.resolve(__dirname, './src/types'),
      },
    },
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
    // 开发模式下定义全局变量
    define: isDev ? {
      __DEV__: 'true',
    } : {
      __DEV__: 'false',
    },
  }
})
