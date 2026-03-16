import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { AuthProvider } from './contexts/AuthContext'
import { BackgroundTaskProvider } from './contexts/BackgroundTaskContext'
import { ToastProvider } from './contexts/ToastContext'
import App from './App'
import './index.css'
import { initializeApiConfig, updateApiBase } from './config'
import './i18n'
import { queryClient } from './lib/queryClient'
import { bootstrapTrainingOptions } from './constants/trainingOptionsBootstrap'

// Use the base URL from Vite config
const basename = import.meta.env.BASE_URL

// Detect if running in Electron (file:// protocol or electron window object)
const isElectron = !!(window as any).electron || window.location.protocol === 'file:'

// Register Service Worker for PWA support
// Only register in browser environment (not in Electron)
if ('serviceWorker' in navigator && !isElectron) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then((registration) => {
        // Check for SW updates every 30 minutes
        const UPDATE_INTERVAL = 30 * 60 * 1000
        setInterval(() => {
          registration.update().catch(() => {})
        }, UPDATE_INTERVAL)

        // When a new SW is found and installed, reload the page to use it
        registration.addEventListener('updatefound', () => {
          const newWorker = registration.installing
          if (newWorker) {
            newWorker.addEventListener('statechange', () => {
              if (newWorker.state === 'activated' && navigator.serviceWorker.controller) {
                // Defer reload if uploads are in progress.
                // window.__activeUploadCount is managed by useTaskActions and will
                // trigger reload when it reaches 0 (if __pendingSWReload is set).
                if ((window as any).__activeUploadCount > 0) {
                  console.log('[SW] New version available, deferring reload until uploads complete...')
                  ;(window as any).__pendingSWReload = true
                } else {
                  console.log('[SW] New version available, reloading...')
                  window.location.reload()
                }
              }
            })
          }
        })
      })
      .catch(() => {})
  })
}

// Use HashRouter for Electron (file:// protocol), BrowserRouter for web
// HashRouter uses URL hash (#) which works with file:// protocol
const Router = isElectron ? HashRouter : BrowserRouter

async function bootstrap(): Promise<void> {
  try {
    await initializeApiConfig()
  } catch (error) {
    console.error('[Main] Failed to initialize API configuration:', error)
  }

  updateApiBase()
  await bootstrapTrainingOptions()
  console.log('[Main] API configuration initialized')

  createRoot(document.getElementById('root')!).render(
    <QueryClientProvider client={queryClient}>
      <Router basename={isElectron ? undefined : basename}>
        <ToastProvider>
          <AuthProvider>
            <BackgroundTaskProvider>
              <App />
            </BackgroundTaskProvider>
          </AuthProvider>
        </ToastProvider>
      </Router>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}

void bootstrap()
