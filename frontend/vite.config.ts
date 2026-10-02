import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式:/api 代理到本地 BFF(novel-story web 默认 8080)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
})
