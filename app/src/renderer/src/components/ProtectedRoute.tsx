import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import AccessDenied from './AccessDenied'
import PageLoading from './common/PageLoading'
import { AgreementGate } from './legal/AgreementGate'

interface ProtectedRouteProps {
  children: React.ReactNode
  requireAdmin?: boolean
  requireGpu?: boolean
  requireResearch?: boolean
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
export function ProtectedRoute({ children, requireAdmin = false, requireGpu = false, requireResearch = false }: ProtectedRouteProps): React.ReactElement {
  const { isLoggedIn, isLoading, isAdmin, canUseGpu, isPathologist, needsAgreement } = useAuth()

  if (isLoggedIn && needsAgreement) return <AgreementGate />

  // Show loading state while checking authentication
  if (isLoading) {
    return <PageLoading fullPage/>
  }

  // Redirect to login if not authenticated
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />
  }

  if (requireAdmin && !isAdmin) {
    return <AccessDenied />
  }
  if (requireResearch && !isAdmin && !isPathologist) return <AccessDenied />

  if (requireGpu && !canUseGpu) {
    return <Navigate to="/tools" replace />
  }

  // Render protected content
  return <>{children}</>
}
