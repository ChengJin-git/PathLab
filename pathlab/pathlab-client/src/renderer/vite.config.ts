import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { VitePWA } from 'vite-plugin-pwa'

const devGatewayTarget = process.env.VITE_DEV_GATEWAY_TARGET || 'http://127.0.0.1:6100'

// Standalone Vite config for web-only build (no Electron)
// Usage: cd src/renderer && npx vite build
export default defineConfig({
  root: '.',
  base: '/',
  resolve: {
    alias: {
      '@renderer': resolve(__dirname, 'src')
    }
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      devOptions: {
        enabled: false
      },
      workbox: {
        maximumFileSizeToCacheInBytes: 10 * 1024 * 1024, // 10 MB
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff,woff2}'],
        skipWaiting: true,
        clientsClaim: true,
        // Clean up outdated precache entries from previous builds
        cleanupOutdatedCaches: true
      },
      includeAssets: ['favicon.ico', 'images/*.png'],
      manifest: {
        name: 'PathLab',
        short_name: 'PathLab',
        description: 'PathLab: Digital Pathology Powered by AI',
        theme_color: '#3b82f6',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          {
            src: 'images/pwa-icon.png',
            sizes: '1024x1024',
            type: 'image/png'
          }
        ]
      }
    })
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html')
      }
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: devGatewayTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
