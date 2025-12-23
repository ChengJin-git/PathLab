/**
 * Authentication Context for PathStudio Client
 *
 * Manages user authentication state and provides auth methods to components.
 * Integrates with Electron's deep link handling for OAuth callback.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import {
  AuthUser,
  getLoginUrl,
  getSignupUrl,
  processAuthCallback,
  logout as apiLogout,
  getCurrentUser
} from '../api'

// Electron API interface exposed via preload
interface ElectronAuthApi {
  openLoginUrl: (url: string) => Promise<void>
  onAuthCallback: (callback: (data: { code: string; state?: string }) => void) => () => void
}

interface ElectronApi {
  auth: ElectronAuthApi
}

// Access window.api safely
declare const window: Window & { api?: ElectronApi }

interface AuthContextType {
  // State
  user: AuthUser | null
  isLoggedIn: boolean
  isLoading: boolean
  error: string | null

  // Actions
  login: () => Promise<void>
  signup: () => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  demoLogin: () => void  // Demo/test login without server
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingState, setPendingState] = useState<string | null>(null)

  // Check current user on mount
  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const response = await getCurrentUser()
      
      if (response.is_logged_in && response.user) {
        setUser(response.user)
      } else {
        setUser(null)
      }
    } catch (err) {
      console.error('Failed to get current user:', err)
      setError(err instanceof Error ? err.message : 'Failed to get user info')
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Initialize and listen for auth callbacks
  useEffect(() => {
    // Check current user on mount
    refreshUser()
    
    // Listen for OAuth callback from Electron deep link
    const cleanup = window.api?.auth?.onAuthCallback(async (data) => {
      console.log('Received auth callback:', data)
      
      try {
        setIsLoading(true)
        setError(null)
        
        // Verify state if we have a pending one
        if (pendingState && data.state && data.state !== pendingState) {
          throw new Error('Invalid state token - possible CSRF attack')
        }
        
        // Exchange code for token
        const result = await processAuthCallback(data.code, data.state)
        
        if (result.success) {
          // Refresh user info
          await refreshUser()
        } else {
          throw new Error(result.message || 'Login failed')
        }
      } catch (err) {
        console.error('Auth callback error:', err)
        setError(err instanceof Error ? err.message : 'Login failed')
      } finally {
        setIsLoading(false)
        setPendingState(null)
      }
    })
    
    return () => {
      cleanup?.()
    }
  }, [refreshUser, pendingState])

  // Helper to open URL in browser
  const openExternalUrl = useCallback(async (url: string) => {
    if (window.api?.auth?.openLoginUrl) {
      await window.api.auth.openLoginUrl(url)
    } else {
      // Fallback for non-Electron environment (browser)
      const w = window as unknown as { open: (url: string, target: string) => void }
      w.open(url, '_blank')
    }
  }, [])

  // Login - open browser to PathStudio login page
  const login = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      // Get login URL from backend
      const { login_url, state } = await getLoginUrl()

      // Save state for CSRF verification
      setPendingState(state)

      // Open login URL in system browser
      await openExternalUrl(login_url)
    } catch (err) {
      console.error('Login error:', err)
      setError(err instanceof Error ? err.message : 'Failed to start login')
      setIsLoading(false)
    }
    // Note: isLoading stays true until callback is received
  }, [openExternalUrl])

  // Signup - open browser to PathStudio signup page
  const signup = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      // Get signup URL from backend
      const { login_url: signup_url, state } = await getSignupUrl()

      // Save state for CSRF verification
      setPendingState(state)

      // Open signup URL in system browser
      await openExternalUrl(signup_url)
    } catch (err) {
      console.error('Signup error:', err)
      setError(err instanceof Error ? err.message : 'Failed to start signup')
      setIsLoading(false)
    }
    // Note: isLoading stays true until callback is received
  }, [openExternalUrl])

  // Logout
  const logout = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      await apiLogout()
      setUser(null)
    } catch (err) {
      console.error('Logout error:', err)
      // Still clear user on logout error (might be demo user)
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Demo login for testing without server
  const demoLogin = useCallback(() => {
    const demoUser: AuthUser = {
      user_id: 'demo-user-001',
      username: 'demo',
      nickname: 'Demo Doctor',
      email: 'demo@pathstudio.local',
      avatar: undefined,
      bio: 'PathStudio Demo Account',
    }
    setUser(demoUser)
    setError(null)
  }, [])

  const value: AuthContextType = {
    user,
    isLoggedIn: user !== null,
    isLoading,
    error,
    login,
    signup,
    logout,
    refreshUser,
    demoLogin
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

