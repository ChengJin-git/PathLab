import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
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

createRoot(document.getElementById('root')!).render(
  <BrowserRouter basename={basename}>
    <AuthProvider>
      <App />
    </AuthProvider>
  </BrowserRouter>
)

