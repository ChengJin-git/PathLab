import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    globals: true,
    include: ['test/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/renderer/src/**'],
      exclude: ['src/renderer/src/**/*.d.ts'],
    },
    env: {
      VITE_API_BASE: '',
      VITE_PREPROCESSING_BASE: '',
      VITE_AI_BASE: '',
      VITE_DEBUG: '',
    },
  },
  resolve: {
    alias: {
        '@renderer': resolve(__dirname, 'src/renderer/src'),
    },
  },
})
