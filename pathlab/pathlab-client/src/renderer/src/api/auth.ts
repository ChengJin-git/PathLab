import { API_BASE } from '../config'
import { apiFetch, ApiError, clearAuthToken, getAuthToken, setAuthToken } from './client'
import { sha256, APP_SALT } from './crypto'
import { invalidateRecentActivityCache } from './stats'

// ============================================================================
// Authentication APIs (JWT-based local authentication)
// ============================================================================

export interface AuthUser {
  id: string
  email: string
  nickname?: string
  avatar_url?: string
  role: 'admin' | 'pathologist' | 'guest'
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  agreement_accepted_at?: string | null
  agreement_ip?: string | null
  notice_acknowledged_at?: string | null
  registration_email?: string | null
  created_at?: string
  updated_at?: string
}

/**
 * Upload a new avatar for the current user
 * @param file - Image file to upload
 * @returns Updated user
 * @throws {ApiError} If upload fails
 */
export async function uploadAvatar(file: File): Promise<AuthUser> {
  const formData = new FormData()
  formData.append('file', file)

  return apiFetch<AuthUser>(
    `${API_BASE}/auth/avatar`,
    {
      method: 'POST',
      body: formData
    },
    'Avatar upload failed'
  )
}

/**
 * Delete current user's avatar
 * @returns Updated user
 * @throws {ApiError} If deletion fails
 */
export async function deleteAvatar(): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/avatar`,
    { method: 'DELETE' },
    'Avatar deletion failed'
  )
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface UserInfoResponse {
  is_logged_in: boolean
  user?: AuthUser
}

export interface RegisterRequest {
  email: string
  password: string
  nickname?: string
  role?: 'pathologist' | 'guest'
}

export interface AccessRequest {
  username: string
  password: string
  registration_email: string
  nickname?: string
}

export interface CurrentUserUpdateRequest {
  email?: string
  nickname?: string
  password?: string
}

export interface AdminUserUpdateRequest extends CurrentUserUpdateRequest {
  role?: 'admin' | 'pathologist' | 'guest'
  is_active?: boolean
  is_superuser?: boolean
  is_verified?: boolean
}

/**
 * Login with email and password using secure client-side hashing.
 *
 * Security features:
 * - Password is never transmitted in plaintext
 * - Client sends: SHA256(SHA256(password) + timestamp + APP_SALT)
 * - Timestamp validation on server prevents replay attacks (5 minute window)
 * - Rainbow table attacks are mitigated by timestamp + salt
 *
 * @param username - Username (stored in email field internally)
 * @param password - User password
 * @param turnstileToken - Optional Cloudflare Turnstile token
 * @returns JWT access token
 * @throws {ApiError} If login fails
 */
export async function loginWithCredentials(
  username: string,
  password: string,
  turnstileToken?: string
): Promise<LoginResponse> {
  // Step 1: Compute SHA256(password)
  const passwordHash = await sha256(password)

  // Step 2: Get current timestamp in milliseconds
  const timestamp = Date.now()

  // Step 3: Compute SHA256(passwordHash + timestamp + APP_SALT)
  const hashedCredential = await sha256(passwordHash + timestamp + APP_SALT)

  // Step 4: Send secure login request
  const response = await apiFetch<LoginResponse>(
    `${API_BASE}/auth/secure-login`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        hashed_password: hashedCredential,
        timestamp,
        turnstile_token: turnstileToken
      })
    },
    'Login failed'
  )

  // Store the token
  if (response.access_token) {
    setAuthToken(response.access_token)
    // Clear user-specific caches on login to ensure fresh data for new user
    invalidateRecentActivityCache()
  }

  return response
}

/**
 * Register a new user
 * @param data - Registration data
 * @returns Created user
 * @throws {ApiError} If registration fails
 */
export async function registerUser(data: RegisterRequest): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/register`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    },
    'Registration failed'
  )
}

/**
 * Logout current user
 * @throws {ApiError} If the logout fails
 */
export async function logout(): Promise<void> {
  try {
    await apiFetch(`${API_BASE}/auth/jwt/logout`, { method: 'POST' }, 'Logout failed')
  } finally {
    // Always clear token on logout
    clearAuthToken()
    // Clear user-specific caches to prevent data leakage between users
    invalidateRecentActivityCache()
  }
}

/**
 * Get current logged-in user info
 * @throws {ApiError} If the request fails
 */
export async function getCurrentUser(): Promise<UserInfoResponse> {
  const token = getAuthToken()
  if (!token) {
    return { is_logged_in: false }
  }

  try {
    const user = await apiFetch<AuthUser>(`${API_BASE}/auth/me`, undefined, 'Failed to get user info')
    return { is_logged_in: true, user }
  } catch (error) {
    // Token clearing and session-expired event are handled by apiFetch for 401 responses.
    // For other auth errors (403), clear token here.
    if (error instanceof ApiError && error.status === 403) {
      clearAuthToken()
    }
    return { is_logged_in: false }
  }
}

/**
 * Submit a public access request (self-registration).
 * The account is created as inactive and must be activated by an admin.
 * @param data - Registration data including educational email
 * @returns Created (inactive) user
 * @throws {ApiError} If registration fails
 */
export async function requestAccess(data: AccessRequest): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/request-access`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    },
    'Access request failed'
  )
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<AuthUser> {
  const currentPasswordSha256 = await sha256(currentPassword)
  const newPasswordSha256 = await sha256(newPassword)
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/me/change-password`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password_sha256: currentPasswordSha256, new_password_sha256: newPasswordSha256 })
    },
    'Failed to change password'
  )
}

export async function updateCurrentUser(data: CurrentUserUpdateRequest): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/me`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    },
    'Failed to update user'
  )
}

