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

// Initialize API configuration (dynamic port discovery)
initializeApiConfig().then(() => {
  updateApiBase()
  console.log('[Main] API configuration initialized')
})

// Register Service Worker for PWA support
// Only register in browser environment (not in Electron)
if ('serviceWorker' in navigator && !isElectron) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then((registration) => {
        // console.log('[SW] Service Worker registered with scope:', registration.scope)
      })
      .catch((error) => {
        // console.log('[SW] Service Worker registration failed:', error)
      })
  })
}

// Use HashRouter for Electron (file:// protocol), BrowserRouter for web
// HashRouter uses URL hash (#) which works with file:// protocol
const Router = isElectron ? HashRouter : BrowserRouter

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

