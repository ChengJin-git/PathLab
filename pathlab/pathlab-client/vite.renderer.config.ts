// Standalone Vite config for previewing the renderer in a plain browser.
// Bypasses electron-vite (which fails when Electron-only deps like `pg` are
// not installable). Use only for visual smoke testing.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  root: 'src/renderer',
  base: './',
  resolve: {
    alias: {
      '@renderer': resolve(__dirname, 'src/renderer/src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true
  },
  plugins: [react()]
})
