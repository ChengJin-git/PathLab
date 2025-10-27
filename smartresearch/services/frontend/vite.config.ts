import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/SmartResearch/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    fs: {
      // Allow serving files from the uploads directory
      allow: ['..', '../../..']
    },
    proxy: {
      // Proxy WSI tile requests to WSI service
      '/wsi': {
        target: 'http://127.0.0.1:6101',
        changeOrigin: true
      }
    }
  }
})

