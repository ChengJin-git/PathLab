import { API_BASE } from '../config'
import { apiFetch, buildSearchParams } from './client'
import type { AdminUserUpdateRequest, AuthUser } from './auth'

// ============================================================================
// User Management APIs (Admin only)
// ============================================================================

export interface UserListItem extends AuthUser {
  id: string
}

export interface ListUsersPagedOptions {
  search?: string
  page?: number
  page_size?: number
  exclude_admin?: boolean
}

export interface PaginatedUserListResponse {
  items: UserListItem[]
  total: number
  page: number
  page_size: number
}

/**
 * List all users (admin only)
 * @throws {ApiError} If request fails or not authorized
 */
export async function listUsers(): Promise<UserListItem[]> {
  return apiFetch<UserListItem[]>(`${API_BASE}/auth/users`, undefined, 'Failed to list users')
}

/**
 * List users with pagination/search (admin only)
 */
export async function listUsersPaged(options: ListUsersPagedOptions = {}): Promise<PaginatedUserListResponse> {
  const params = buildSearchParams({
    search: options.search?.trim() || undefined,
    page: options.page || undefined,
    page_size: options.page_size || undefined,
    exclude_admin: options.exclude_admin ? 'true' : undefined,
  })

  const query = params.toString()
  return apiFetch<PaginatedUserListResponse>(
    `${API_BASE}/auth/users/paged${query ? `?${query}` : ''}`,
    undefined,
    'Failed to list users'
  )
}

/**
 * Get user by ID (admin only)
 * @param userId - User ID
 * @throws {ApiError} If request fails or not authorized
 */
export async function getUserById(userId: string): Promise<AuthUser> {
  return apiFetch<AuthUser>(`${API_BASE}/auth/users/${userId}`, undefined, 'Failed to get user')
}

/**
 * Update user (admin only)
 * @param userId - User ID
 * @param data - Update data
 * @throws {ApiError} If request fails or not authorized
 */
export async function updateUser(userId: string, data: AdminUserUpdateRequest): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/users/${userId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    },
    'Failed to update user'
  )
}

/**
 * Delete user (admin only)
 * @param userId - User ID
 * @throws {ApiError} If request fails or not authorized
 */
export async function deleteUser(userId: string): Promise<void> {
  await apiFetch<void>(
    `${API_BASE}/auth/users/${userId}`,
    { method: 'DELETE' },
    'Failed to delete user'
  )
}

/**
 * Get the client's public IP address using an external service
 * @returns Client IP address or null if failed
 */
export async function getClientIP(): Promise<string | null> {
  try {
    // Try multiple IP services for reliability
    const services = [
      'https://api.ipify.org?format=json',
      'https://api.ip.sb/ip'
    ]

    for (const url of services) {
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(5000) })
        if (response.ok) {
          const text = await response.text()
          // Handle JSON response from ipify
          if (url.includes('ipify')) {
            const data = JSON.parse(text)
            return data.ip
          }
          // Handle plain text response from ip.sb
          return text.trim()
        }
      } catch {
        continue
      }
    }
    return null
  } catch {
    return null
  }
}

/**
 * Accept the terms of service agreement
 * @param ip - Optional client IP address
 * @returns Updated user with agreement_accepted_at set
 * @throws {ApiError} If request fails
 */
export async function acceptAgreement(ip?: string): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/accept-agreement`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip })
    },
    'Failed to accept agreement'
  )
}

/**
 * Revoke user's agreement acceptance (admin only)
 * @param userId - User ID
 * @returns Updated user with agreement_accepted_at cleared
 * @throws {ApiError} If request fails or not authorized
 */
export async function revokeUserAgreement(userId: string): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/users/${userId}/revoke-agreement`,
    { method: 'POST' },
    'Failed to revoke agreement'
  )
}

// ============================================================================
// Batch User Operations (Admin only)
// ============================================================================

/**
 * Batch activate users (admin only)
 * @param userIds - Array of user IDs to activate
 * @throws {ApiError} If request fails or not authorized
 */
export async function batchActivateUsers(userIds: string[]): Promise<{ updated: number }> {
  return apiFetch<{ updated: number }>(
    `${API_BASE}/auth/users/batch/activate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds })
    },
    'Failed to batch activate users'
  )
}

/**
 * Batch deactivate users (admin only)
 * @param userIds - Array of user IDs to deactivate
 * @throws {ApiError} If request fails or not authorized
 */
export async function batchDeactivateUsers(userIds: string[]): Promise<{ updated: number }> {
  return apiFetch<{ updated: number }>(
    `${API_BASE}/auth/users/batch/deactivate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds })
    },
    'Failed to batch deactivate users'
  )
}

/**
 * Batch delete users (admin only)
 * @param userIds - Array of user IDs to delete
 * @throws {ApiError} If request fails or not authorized
 */
export async function batchDeleteUsers(userIds: string[]): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>(
    `${API_BASE}/auth/users/batch/delete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds })
    },
    'Failed to batch delete users'
  )
}

// ============================================================================
// Maintenance Mode (Admin only)
// ============================================================================

/**
 * Get maintenance mode status
 * @throws {ApiError} If request fails
 */
export async function getMaintenanceMode(): Promise<{ enabled: boolean }> {
  return apiFetch<{ enabled: boolean }>(
    `${API_BASE}/auth/maintenance-mode`,
    undefined,
    'Failed to get maintenance mode status'
  )
}

/**
 * Set maintenance mode (admin only)
 * When enabled, all non-admin users are deactivated and cannot log in.
 * When disabled, users deactivated by maintenance mode are restored automatically.
 * @param enabled - Whether to enable maintenance mode
 * @throws {ApiError} If request fails or not authorized
 */
export async function setMaintenanceMode(enabled: boolean): Promise<{ enabled: boolean; affected_users: number }> {
  return apiFetch<{ enabled: boolean; affected_users: number }>(
    `${API_BASE}/auth/maintenance-mode`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    },
    'Failed to set maintenance mode'
  )
}

// ============================================================================
// Maintenance Notice (Announcement for non-admin users)
// ============================================================================

export interface MaintenanceNotice {
  active: boolean
  message: string | null
  updated_at?: string
  needs_acknowledgment: boolean
}

/**
 * Get current maintenance notice and whether user needs to acknowledge it
 * @throws {ApiError} If request fails
 */
export async function getMaintenanceNotice(): Promise<MaintenanceNotice> {
  return apiFetch<MaintenanceNotice>(
    `${API_BASE}/auth/maintenance-notice`,
    undefined,
    'Failed to get maintenance notice'
  )
}

/**
 * Set or clear maintenance notice (admin only)
 * @param message - Notice message, or null/empty to clear
 * @throws {ApiError} If request fails or not authorized
 */
export async function setMaintenanceNotice(message: string | null): Promise<{ active: boolean; message: string | null }> {
  return apiFetch<{ active: boolean; message: string | null }>(
    `${API_BASE}/auth/maintenance-notice`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    },
    'Failed to set maintenance notice'
  )
}

/**
 * Acknowledge the current maintenance notice
 * @returns Updated user
 * @throws {ApiError} If request fails
 */
export async function acknowledgeNotice(): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/acknowledge-notice`,
    { method: 'POST' },
    'Failed to acknowledge notice'
  )
}

