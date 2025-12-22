import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/PathLab/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    fs: {
      // Allow serving files from the uploads directory
      allow: ['..', '../../..']
    },
    proxy: {
      // Proxy API requests to Gateway service
      '/tasks': {
        target: 'http://127.0.0.1:6100',
        changeOrigin: true
      },
      '/api': {
        target: 'http://127.0.0.1:6100',
        changeOrigin: true
      },
      // Proxy WSI tile requests to WSI service
      '/wsi': {
        target: 'http://127.0.0.1:6101',
        changeOrigin: true
      }
    }
  }
})

