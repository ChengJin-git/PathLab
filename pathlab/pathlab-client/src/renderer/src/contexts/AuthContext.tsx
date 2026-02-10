/**
 * Authentication Context for PathLab Client
 *
 * Manages user authentication state and provides auth methods to components.
 * Uses JWT-based local authentication with username/password login.
 * Registration is only available through admin in Settings.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react'
import {
  AuthUser,
  logout as apiLogout,
  getCurrentUser,
  loginWithCredentials,
  clearAuthToken,
  acceptAgreement as apiAcceptAgreement,
  getMyDatasetPermissions,
  getClientIP,
  SESSION_EXPIRED_EVENT
} from '../api'
import { useToast } from './ToastContext'

interface AuthContextType {
  // State
  user: AuthUser | null
  isLoggedIn: boolean
  isLoading: boolean
  error: string | null
  needsAgreement: boolean  // User needs to accept terms of service
  elevatedDatasetIds: string[]  // Dataset IDs where user has temporary elevated access

  // Actions
  login: (username: string, password: string, recaptchaToken?: string) => Promise<boolean>
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
  const toast = useToast()

  // Track whether user was logged in, to show toast only on forced logout (not initial load)
  const userRef = useRef<AuthUser | null>(null)
  useEffect(() => { userRef.current = user }, [user])

  // Prevent duplicate session-expired toasts
  const sessionExpiredHandled = useRef(false)

  // Listen for session-expired events from apiFetch (401 while authenticated)
  useEffect(() => {
    const handleSessionExpired = () => {
      // Only show toast if user was previously logged in and not already handled
      if (userRef.current && !sessionExpiredHandled.current) {
        sessionExpiredHandled.current = true
        toast.warning(
          'Your account has been logged in on another device. Current session has ended.',
          5000
        )
        setUser(null)
        setElevatedDatasetIds([])
        // Reset the flag after a short delay to allow future detections
        setTimeout(() => { sessionExpiredHandled.current = false }, 6000)
      }
    }

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
  }, [toast])

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
    refreshUser()
  }, [refreshUser])

  // Clear error
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Login with username and password
  const login = useCallback(async (username: string, password: string, recaptchaToken?: string): Promise<boolean> => {
    try {
      setIsLoading(true)
      setError(null)

      await loginWithCredentials(username, password, recaptchaToken)

      // Refresh user info after successful login
      await refreshUser()
      return true
    } catch (err) {
      console.error('Login error:', err)
      // Check if the error is due to specific error codes from secure login
      let errorMessage = err instanceof Error ? err.message : 'Login failed'
      const errorLower = errorMessage.toLowerCase()

      // Handle specific error codes from secure login endpoint
      if (errorLower.includes('maintenance_mode')) {
        // System is in maintenance mode - non-admin users cannot log in
        errorMessage = 'System is under maintenance. Please try again later or contact administrator.'
      } else if (errorLower.includes('login_user_not_active') ||
          errorLower.includes('inactive') ||
          errorLower.includes('not active') ||
          errorLower.includes('deactivated')) {
        errorMessage = 'Account has been deactivated. Please contact administrator.'
      } else if (errorLower.includes('login_timestamp_expired')) {
        // Timestamp expired - this shouldn't happen normally, may indicate clock sync issue
        errorMessage = 'Login request expired. Please check your system clock and try again.'
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
      // Get client IP address before accepting agreement
      const clientIP = await getClientIP()
      const updatedUser = await apiAcceptAgreement(clientIP || undefined)
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

