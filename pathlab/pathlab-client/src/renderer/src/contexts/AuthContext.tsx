/**
 * Authentication Context for PathLab Client
 *
 * Manages user authentication state and provides auth methods to components.
 * Uses JWT-based local authentication with username/password login.
 * Registration is only available through admin in Settings.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import {
  AuthUser,
  logout as apiLogout,
  getCurrentUser,
  loginWithCredentials as apiLoginWithCredentials,
  clearAuthToken,
  acceptAgreement as apiAcceptAgreement,
  getMyDatasetPermissions
} from '../api'
import { initializeApiConfig, getApiBase } from '../config'

interface AuthContextType {
  // State
  user: AuthUser | null
  isLoggedIn: boolean
  isLoading: boolean
  error: string | null
  needsAgreement: boolean  // User needs to accept terms of service
  elevatedDatasetIds: string[]  // Dataset IDs where user has temporary elevated access

  // Actions
  login: (username: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  refreshDatasetPermissions: () => Promise<void>  // Refresh elevated dataset permissions
  acceptAgreement: () => Promise<boolean>  // Accept terms of service
  clearError: () => void

  // Role checks
  isAdmin: boolean
  isPathologist: boolean
  canUseGpu: boolean
  canUseGpuForDataset: (datasetId: string) => boolean  // Check if user can use GPU for specific dataset
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [elevatedDatasetIds, setElevatedDatasetIds] = useState<string[]>([])

  // Refresh dataset permissions (for temporary elevated access)
  const refreshDatasetPermissions = useCallback(async () => {
    try {
      const response = await getMyDatasetPermissions()
      setElevatedDatasetIds(response.elevated_dataset_ids)
    } catch (err) {
      console.error('Failed to get dataset permissions:', err)
      setElevatedDatasetIds([])
    }
  }, [])

  // Check current user on mount
  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const response = await getCurrentUser()

      if (response.is_logged_in && response.user) {
        setUser(response.user)
        // Also refresh dataset permissions when refreshing user
        await refreshDatasetPermissions()
      } else {
        setUser(null)
        setElevatedDatasetIds([])
      }
    } catch (err) {
      console.error('Failed to get current user:', err)
      setError(err instanceof Error ? err.message : 'Failed to get user info')
      setUser(null)
      setElevatedDatasetIds([])
    } finally {
      setIsLoading(false)
    }
  }, [refreshDatasetPermissions])

  // Initialize - check current user on mount
  useEffect(() => {
    // Ensure API config is initialized before attempting login
    const initAndLogin = async () => {
      // Wait for API config to be initialized
      await initializeApiConfig()
      console.log('[Auth] API config initialized, API_BASE:', getApiBase())
      
      // In test/development environment, try auto-login
      const isDev = import.meta.env.DEV || import.meta.env.MODE === 'development'
      const autoLoginEnabled = import.meta.env.VITE_AUTO_LOGIN === 'true' || 
                              localStorage.getItem('auto_login') === 'true' ||
                              (isDev && localStorage.getItem('auto_login') !== 'false')
      
      if (autoLoginEnabled) {
        // Try auto-login with default test credentials
        const testUsername = import.meta.env.VITE_TEST_USERNAME || 'admin'
        const testPassword = import.meta.env.VITE_TEST_PASSWORD || 'Smartlab2022'
        
        console.log('[Auth] Auto-login enabled, attempting login...')
        // Use loginWithCredentials directly to avoid dependency issues
        try {
          await apiLoginWithCredentials(testUsername, testPassword)
          // Refresh user info after successful login
          await refreshUser()
        } catch (err) {
          console.warn('[Auth] Auto-login failed, falling back to normal login:', err)
          // Retry once after a short delay (in case backend is still starting)
          setTimeout(async () => {
            try {
              await apiLoginWithCredentials(testUsername, testPassword)
              await refreshUser()
            } catch (retryErr) {
              console.warn('[Auth] Auto-login retry also failed:', retryErr)
              refreshUser()
            }
          }, 2000) // Wait 2 seconds before retry
        }
      } else {
        refreshUser()
      }
    }
    
    initAndLogin()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Only run once on mount

  // Clear error
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Login with username and password
  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    try {
      setIsLoading(true)
      setError(null)

      await apiLoginWithCredentials(username, password)

      // Refresh user info after successful login
      await refreshUser()
      return true
    } catch (err) {
      console.error('Login error:', err)
      // Check if the error is due to specific error codes from secure login
      let errorMessage = err instanceof Error ? err.message : 'Login failed'
      const errorLower = errorMessage.toLowerCase()

      // Handle specific error codes from secure login endpoint
      if (errorLower.includes('login_user_not_active') ||
          errorLower.includes('inactive') ||
          errorLower.includes('not active') ||
          errorLower.includes('deactivated')) {
        errorMessage = 'Account has been deactivated. Please contact administrator.'
      } else if (errorLower.includes('login_timestamp_expired')) {
        // Timestamp expired - this shouldn't happen normally, may indicate clock sync issue
        errorMessage = 'Login request expired. Please check your system clock and try again.'
      } else if (errorLower.includes('password migration failed')) {
        // Migration endpoint failed (shouldn't happen if password is correct)
        errorMessage = 'Password migration failed. Please contact administrator.'
      } else if (errorLower.includes('bad credentials') ||
                 errorLower.includes('login_bad_credentials')) {
        errorMessage = 'Invalid username or password'
      }

      setError(errorMessage)
      setIsLoading(false)
      return false
    }
  }, [refreshUser])

  // Logout
  const logout = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      await apiLogout()
      setUser(null)
      setElevatedDatasetIds([])
    } catch (err) {
      console.error('Logout error:', err)
      // Still clear user on logout error (might be demo user)
      clearAuthToken()
      setUser(null)
      setElevatedDatasetIds([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Accept terms of service agreement
  const acceptAgreement = useCallback(async (): Promise<boolean> => {
    try {
      setIsLoading(true)
      setError(null)
      const updatedUser = await apiAcceptAgreement()
      setUser(updatedUser)
      return true
    } catch (err) {
      console.error('Accept agreement error:', err)
      setError(err instanceof Error ? err.message : 'Failed to accept agreement')
      return false
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Role checks
  const isAdmin = user?.role === 'admin'
  const isPathologist = user?.role === 'pathologist'
  const canUseGpu = isAdmin || isPathologist

  // Check if user can use GPU for a specific dataset
  // Either base GPU access OR temporary elevated permission
  const canUseGpuForDataset = useCallback((datasetId: string): boolean => {
    if (canUseGpu) return true
    return elevatedDatasetIds.includes(datasetId)
  }, [canUseGpu, elevatedDatasetIds])

  // Check if user needs to accept agreement (logged in but hasn't accepted)
  // Admin users don't need to accept agreement - only pathologist and guest
  const needsAgreement = user !== null && !user.agreement_accepted_at && user.role !== 'admin'

  const value: AuthContextType = {
    user,
    isLoggedIn: user !== null,
    isLoading,
    error,
    needsAgreement,
    elevatedDatasetIds,
    login,
    logout,
    refreshUser,
    refreshDatasetPermissions,
    acceptAgreement,
    clearError,
    isAdmin,
    isPathologist,
    canUseGpu,
    canUseGpuForDataset
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

