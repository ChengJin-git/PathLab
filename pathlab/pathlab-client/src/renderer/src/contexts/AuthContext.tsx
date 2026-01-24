/**
 * Authentication Context for PathLab Client
 *
 * Manages user authentication state and provides auth methods to components.
 * Uses JWT-based local authentication with email/password login.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import {
  AuthUser,
  RegisterRequest,
  logout as apiLogout,
  getCurrentUser,
  loginWithCredentials,
  registerUser,
  clearAuthToken,
  acceptAgreement as apiAcceptAgreement
} from '../api'

interface AuthContextType {
  // State
  user: AuthUser | null
  isLoggedIn: boolean
  isLoading: boolean
  error: string | null
  needsAgreement: boolean  // User needs to accept terms of service

  // Actions
  login: (email: string, password: string) => Promise<boolean>
  register: (data: RegisterRequest) => Promise<boolean>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  acceptAgreement: () => Promise<boolean>  // Accept terms of service
  clearError: () => void

  // Role checks
  isAdmin: boolean
  isPathologist: boolean
  canUseGpu: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  // Initialize - check current user on mount
  useEffect(() => {
    refreshUser()
  }, [refreshUser])

  // Clear error
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Login with email and password
  const login = useCallback(async (email: string, password: string): Promise<boolean> => {
    try {
      setIsLoading(true)
      setError(null)

      await loginWithCredentials(email, password)

      // Refresh user info after successful login
      await refreshUser()
      return true
    } catch (err) {
      console.error('Login error:', err)
      setError(err instanceof Error ? err.message : 'Login failed')
      setIsLoading(false)
      return false
    }
  }, [refreshUser])

  // Register new user
  const register = useCallback(async (data: RegisterRequest): Promise<boolean> => {
    try {
      setIsLoading(true)
      setError(null)

      await registerUser(data)

      // Auto-login after registration
      await loginWithCredentials(data.email, data.password)
      await refreshUser()
      return true
    } catch (err) {
      console.error('Registration error:', err)
      setError(err instanceof Error ? err.message : 'Registration failed')
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
    } catch (err) {
      console.error('Logout error:', err)
      // Still clear user on logout error (might be demo user)
      clearAuthToken()
      setUser(null)
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

  // Check if user needs to accept agreement (logged in but hasn't accepted)
  const needsAgreement = user !== null && !user.agreement_accepted_at

  const value: AuthContextType = {
    user,
    isLoggedIn: user !== null,
    isLoading,
    error,
    needsAgreement,
    login,
    register,
    logout,
    refreshUser,
    acceptAgreement,
    clearError,
    isAdmin,
    isPathologist,
    canUseGpu
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

