import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { GoogleReCaptchaProvider } from 'react-google-recaptcha-v3'
import { AuthProvider } from './contexts/AuthContext'
import { BackgroundTaskProvider } from './contexts/BackgroundTaskContext'
import { ToastProvider } from './contexts/ToastContext'
import { BackgroundTaskPanel } from './components/BackgroundTaskPanel'
import App from './App'
import './index.css'
import { initializeApiConfig, updateApiBase } from './config'
import { getPublicSettings } from './api'

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

// Component to wrap app with reCAPTCHA provider
function AppWithProviders() {
  const [recaptchaSiteKey, setRecaptchaSiteKey] = React.useState<string>('')
  const [recaptchaEnabled, setRecaptchaEnabled] = React.useState<boolean>(false)

  React.useEffect(() => {
    // Fetch reCAPTCHA settings from backend (public endpoint, no auth required)
    getPublicSettings()
      .then((settings) => {
        setRecaptchaEnabled(settings.recaptcha_enabled)
        setRecaptchaSiteKey(settings.recaptcha_site_key)
      })
      .catch((err) => {
        console.error('[Main] Failed to fetch reCAPTCHA settings:', err)
      })
  }, [])

  const content = (
    <ToastProvider>
      <AuthProvider>
        <BackgroundTaskProvider>
          <App />
        </BackgroundTaskProvider>
      </AuthProvider>
    </ToastProvider>
  )

  // Only wrap with GoogleReCaptchaProvider if reCAPTCHA is enabled and site key is available
  if (recaptchaEnabled && recaptchaSiteKey) {
    return (
      <GoogleReCaptchaProvider reCaptchaKey={recaptchaSiteKey}>
        {content}
      </GoogleReCaptchaProvider>
    )
  }

  return content
}

createRoot(document.getElementById('root')!).render(
  <Router basename={isElectron ? undefined : basename}>
    <AppWithProviders />
  </Router>
)

