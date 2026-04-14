import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

/** 开发时 /api 转发目标；仅后端未启动时 Vite 终端会打印 ECONNREFUSED */
const DEFAULT_API_TARGET = 'http://127.0.0.1:8003'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_PROXY_TARGET || DEFAULT_API_TARGET

  return {
    plugins: [vue()],
    base: '/frontend/',
    server: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          ws: true,
          configure: (proxy) => {
            proxy.on('error', (err) => {
              console.error(
                `[vite proxy] /api → ${apiTarget} 失败: ${err.message}\n` +
                  `  请先启动后端（默认端口 8003）。在项目根目录运行: npm run dev\n` +
                  `  或单独启动: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8003 --reload`
              )
            })
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  }
})
