import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { BackgroundTaskProvider } from './contexts/BackgroundTaskContext'
import { ToastProvider } from './contexts/ToastContext'
import { BackgroundTaskPanel } from './components/BackgroundTaskPanel'
import App from './App'
import './index.css'
import './i18n'
import { initializeApiConfig, updateApiBase } from './config'

// Use the base URL from Vite config
const basename = import.meta.env.BASE_URL

// Detect if running in Electron (file:// protocol or electron window object)
const isElectron = !!(window as any).electron || window.location.protocol === 'file:'

// Initialize API configuration (dynamic port discovery)
initializeApiConfig().then(() => {
  updateApiBase()
  console.log('[Main] API configuration initialized')
  console.log('[Main] API_BASE:', import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5100')
}).catch((error) => {
  console.error('[Main] Failed to initialize API config:', error)
})

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

const rootElement = document.getElementById('root')
if (!rootElement) {
  console.error('[Main] Root element not found!')
  throw new Error('Root element not found')
}

console.log('[Main] Rendering app...')
console.log('[Main] isElectron:', isElectron)
console.log('[Main] basename:', basename)

createRoot(rootElement).render(
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
