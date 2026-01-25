import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/main/index.ts')
        }
      }
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/preload/index.ts')
        }
      }
    }
  },
  renderer: {
    root: 'src/renderer',
    base: './',
    server: {
      host: '0.0.0.0'
    },
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/renderer/index.html')
        }
      }
    },
    plugins: [
      react(),
      VitePWA({
        registerType: 'autoUpdate',
        injectRegister: 'auto',
        devOptions: {
          enabled: true
        },
        includeAssets: ['favicon.ico', 'images/*.png'],
        manifest: {
          name: 'PathLab',
          short_name: 'PathLab',
          description: 'PathLab: Digital Pathology Powered by AI',
          theme_color: '#3b82f6',
          icons: [
            {
              src: 'images/pwa-icon.png',
              sizes: '1024x1024',
              type: 'image/png'
            }
          ]
        }
      })
    ]
  }
})
