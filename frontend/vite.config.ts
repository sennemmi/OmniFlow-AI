import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import componentDebugger from 'vite-plugin-component-debugger'
import path from 'path'

// 【修改点 1】: 接收 isDev 参数，动态判断注入路径
const omniFlowOverlayPlugin = (isDev: boolean) => ({
  name: 'omniflow-overlay',
  transformIndexHtml(html: string) {
    // 开发模式直接以 module 方式引入 TS 源文件，生产模式使用打包后的 IIFE 产物
    const scriptSrc = isDev ? '/src/injector/index.ts' : '/omni-injector.iife.js'
    const typeAttr = isDev ? ' type="module"' : ''

    return html.replace(
      '</body>',
      `  <script${typeAttr} src="${scriptSrc}" data-api-url="http://localhost:8000"></script>\n</body>`
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
      // 【修改点 2】: 传入 isDev 变量
      omniFlowOverlayPlugin(isDev),
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
        '@injector': path.resolve(__dirname, './src/injector'),
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
      rollupOptions: {
        input: {
          main: path.resolve(__dirname, 'index.html'),
          injector: path.resolve(__dirname, 'src/injector/index.ts'),
        },
        output: {
          entryFileNames: (chunkInfo) => {
            if (chunkInfo.name === 'injector') {
              return 'omni-injector.iife.js'
            }
            return 'assets/[name]-[hash].js'
          },
          format: 'iife',
        },
      },
    },
    // 开发模式下定义全局变量
    define: isDev ? {
      __DEV__: 'true',
    } : {
      __DEV__: 'false',
    },
  }
})
