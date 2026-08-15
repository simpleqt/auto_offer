import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发模式下把 /api 与 /ws 代理到本地服务（127.0.0.1:8765）；
// 生产模式由 FastAPI 直接挂载构建产物，同源访问，无需代理。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
