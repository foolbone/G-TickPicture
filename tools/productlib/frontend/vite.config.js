import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到 ../web-app-dist（入库，PyInstaller 打包直接收录）。
// base '/app/' —— 服务端把新前端挂在 /app/ 前缀下，与旧版 index.html 并存。
export default defineConfig({
  plugins: [vue()],
  base: '/app/',
  build: {
    outDir: '../web-app-dist',
    emptyOutDir: true,
  },
  server: {
    port: 5175,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/thumb': 'http://127.0.0.1:8765',
      '/img': 'http://127.0.0.1:8765',
      '/view': 'http://127.0.0.1:8765',
      '/file': 'http://127.0.0.1:8765',
    },
  },
})
