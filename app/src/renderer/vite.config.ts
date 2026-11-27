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
      // main.tsx owns registration and standalone-mode cleanup.
      injectRegister: false,
      devOptions: {
        enabled: false
      },
      workbox: {
        maximumFileSizeToCacheInBytes: 10 * 1024 * 1024, // 10 MB
        // Precache the shell, then cache route chunks when they are visited.
        // Precaching every JS file would immediately undo route lazy loading.
        globPatterns: ['**/*.{html,ico,png,svg}', 'assets/main-*.{js,css}'],
        runtimeCaching: [{
          urlPattern: /\/assets\/.*\.(?:js|css|woff2?)$/,
          handler: 'CacheFirst',
          options: {
            cacheName: 'pathlab-route-assets',
            expiration: { maxEntries: 250, maxAgeSeconds: 365 * 24 * 60 * 60 },
            cacheableResponse: { statuses: [200] }
          }
        }],
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
