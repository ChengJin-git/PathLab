import React from 'react'
import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'

interface ProtectedRouteProps {
  children: React.ReactNode
  requireAdmin?: boolean
  requireGpu?: boolean
}

/**
 * ProtectedRoute - Wrapper component that requires authentication
 *
 * - If loading, shows a loading spinner
 * - If not logged in, redirects to /login
 * - If role is insufficient, redirects to /dashboard
 * - If GPU capability is required but unavailable, redirects to /tools
 * - If checks pass, renders children
 */
export function ProtectedRoute({ children, requireAdmin = false, requireGpu = false }: ProtectedRouteProps): React.ReactElement {
  const { isLoggedIn, isLoading, isAdmin, canUseGpu } = useAuth()
  const { t } = useTranslation()

  // Show loading state while checking authentication
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{t('common.loading')}</p>
        </div>
      </div>
    )
  }

  // Redirect to login if not authenticated
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/dashboard" replace />
  }

  if (requireGpu && !canUseGpu) {
    return <Navigate to="/tools" replace />
  }

  // Render protected content
  return <>{children}</>
}

