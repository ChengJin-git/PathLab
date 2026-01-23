import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { BackgroundTaskProvider } from './contexts/BackgroundTaskContext'
import { BackgroundTaskPanel } from './components/BackgroundTaskPanel'
import App from './App'
import './index.css'
import { initializeApiConfig, updateApiBase } from './config'

// Use the base URL from Vite config
const basename = import.meta.env.BASE_URL

// Initialize API configuration (dynamic port discovery)
initializeApiConfig().then(() => {
  updateApiBase()
  console.log('[Main] API configuration initialized')
})

// Register Service Worker for PWA support
// Only register in browser environment (not in Electron)
if ('serviceWorker' in navigator && !(window as any).electron) {
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

createRoot(document.getElementById('root')!).render(
  <BrowserRouter basename={basename}>
    <AuthProvider>
      <BackgroundTaskProvider>
        <App />
      </BackgroundTaskProvider>
    </AuthProvider>
  </BrowserRouter>
)

