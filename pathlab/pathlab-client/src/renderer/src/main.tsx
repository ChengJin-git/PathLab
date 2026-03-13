import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { BackgroundTaskProvider } from './contexts/BackgroundTaskContext'
import { ToastProvider } from './contexts/ToastContext'
import { BackgroundTaskPanel } from './components/BackgroundTaskPanel'
import App from './App'
import './index.css'
import { initializeApiConfig, updateApiBase } from './config'
import './i18n'

// Use the base URL from Vite config
const basename = import.meta.env.BASE_URL

// Detect if running in Electron (file:// protocol or electron window object)
const isElectron = !!(window as any).electron || window.location.protocol === 'file:'

// Register Service Worker for PWA support
// Only register in browser environment (not in Electron)
if ('serviceWorker' in navigator && !isElectron && !import.meta.env.DEV) {
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
                // New version activated, reload to use updated resources
                console.log('[SW] New version available, reloading...')
                window.location.reload()
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
  console.log('[Main] API configuration initialized')

  createRoot(document.getElementById('root')!).render(
    <Router basename={isElectron ? undefined : basename}>
      <ToastProvider>
        <AuthProvider>
          <BackgroundTaskProvider>
            <App />
          </BackgroundTaskProvider>
        </AuthProvider>
      </ToastProvider>
    </Router>
  )
}

void bootstrap()

