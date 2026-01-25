import { API_BASE } from './config'

// ============================================================================
// Security Constants
// ============================================================================

/**
 * Application-level salt for client-side password hashing.
 * MUST match the backend APP_SALT in auth_local.py
 */
const APP_SALT = 'PathLab2024SecureSalt'

/**
 * Pure JavaScript SHA-256 implementation for non-secure contexts.
 * Used when crypto.subtle is not available (HTTP non-localhost).
 */
function sha256Fallback(message: string): string {
  // SHA-256 constants
  const K: number[] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]

  // Helper functions
  const rotr = (n: number, x: number): number => (x >>> n) | (x << (32 - n))
  const ch = (x: number, y: number, z: number): number => (x & y) ^ (~x & z)
  const maj = (x: number, y: number, z: number): number => (x & y) ^ (x & z) ^ (y & z)
  const sigma0 = (x: number): number => rotr(2, x) ^ rotr(13, x) ^ rotr(22, x)
  const sigma1 = (x: number): number => rotr(6, x) ^ rotr(11, x) ^ rotr(25, x)
  const gamma0 = (x: number): number => rotr(7, x) ^ rotr(18, x) ^ (x >>> 3)
  const gamma1 = (x: number): number => rotr(17, x) ^ rotr(19, x) ^ (x >>> 10)

  // Convert string to bytes
  const encoder = new TextEncoder()
  const msgBytes = encoder.encode(message)
  const msgLen = msgBytes.length
  const bitLen = msgLen * 8

  // Calculate padded length: message + 1 byte (0x80) + padding + 8 bytes (length)
  // Total must be multiple of 64 bytes (512 bits)
  const totalLen = Math.ceil((msgLen + 9) / 64) * 64
  const padded = new Uint8Array(totalLen)
  padded.set(msgBytes)
  padded[msgLen] = 0x80

  // Append length in bits as 64-bit big-endian
  const view = new DataView(padded.buffer)
  // For messages < 2^32 bits, high 32 bits are 0
  view.setUint32(totalLen - 8, 0, false)
  view.setUint32(totalLen - 4, bitLen, false)

  // Initial hash values
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19

  // Process each 512-bit block
  for (let i = 0; i < padded.length; i += 64) {
    const W: number[] = new Array(64)

    // Copy block into first 16 words
    for (let t = 0; t < 16; t++) {
      W[t] = (padded[i + t * 4] << 24) | (padded[i + t * 4 + 1] << 16) |
             (padded[i + t * 4 + 2] << 8) | padded[i + t * 4 + 3]
    }

    // Extend to 64 words
    for (let t = 16; t < 64; t++) {
      W[t] = (gamma1(W[t - 2]) + W[t - 7] + gamma0(W[t - 15]) + W[t - 16]) >>> 0
    }

    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7

    for (let t = 0; t < 64; t++) {
      const T1 = (h + sigma1(e) + ch(e, f, g) + K[t] + W[t]) >>> 0
      const T2 = (sigma0(a) + maj(a, b, c)) >>> 0
      h = g
      g = f
      f = e
      e = (d + T1) >>> 0
      d = c
      c = b
      b = a
      a = (T1 + T2) >>> 0
    }

    h0 = (h0 + a) >>> 0
    h1 = (h1 + b) >>> 0
    h2 = (h2 + c) >>> 0
    h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0
    h5 = (h5 + f) >>> 0
    h6 = (h6 + g) >>> 0
    h7 = (h7 + h) >>> 0
  }

  // Convert to hex string
  const toHex = (n: number): string => n.toString(16).padStart(8, '0')
  return toHex(h0) + toHex(h1) + toHex(h2) + toHex(h3) + toHex(h4) + toHex(h5) + toHex(h6) + toHex(h7)
}

/**
 * Compute SHA-256 hash of a string.
 * Uses Web Crypto API when available (secure contexts), falls back to
 * pure JavaScript implementation for non-secure contexts (HTTP non-localhost).
 * @param message - String to hash
 * @returns Hex-encoded SHA-256 hash
 */
async function sha256(message: string): Promise<string> {
  // Check if crypto.subtle is available (requires secure context)
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const msgBuffer = new TextEncoder().encode(message)
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer)
    const hashArray = Array.from(new Uint8Array(hashBuffer))
    return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
  }

  // Fallback for non-secure contexts (HTTP non-localhost)
  console.warn('[Security] crypto.subtle not available - using JavaScript SHA-256 fallback. For production, use HTTPS.')
  return sha256Fallback(message)
}

// ============================================================================
// API Error Handling
// ============================================================================

/**
 * Custom API Error class for unified error handling
 * Provides structured error information including HTTP status, error code, and details
 */
export class ApiError extends Error {
  /** HTTP status code */
  public readonly status: number
  /** Error code for programmatic handling (e.g., 'NOT_FOUND', 'VALIDATION_ERROR') */
  public readonly code: string
  /** Original error details from the server */
  public readonly details?: string

  constructor(message: string, status: number, code: string = 'API_ERROR', details?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details

    // Maintains proper stack trace for where our error was thrown (only available on V8)
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, ApiError)
    }
  }

  /**
   * Check if this is a specific error type
   */
  is(code: string): boolean {
    return this.code === code
  }

  /**
   * Check if this is a not found error
   */
  isNotFound(): boolean {
    return this.status === 404 || this.code === 'NOT_FOUND'
  }

  /**
   * Check if this is an authentication error
   */
  isAuthError(): boolean {
    return this.status === 401 || this.status === 403 || this.code === 'AUTH_ERROR'
  }

  /**
   * Check if this is a validation error
   */
  isValidationError(): boolean {
    return this.status === 400 || this.status === 422 || this.code === 'VALIDATION_ERROR'
  }

  /**
   * Check if this is a server error
   */
  isServerError(): boolean {
    return this.status >= 500
  }

  /**
   * Check if this is a network/connection error
   */
  isNetworkError(): boolean {
    return this.code === 'NETWORK_ERROR'
  }
}

/**
 * Error codes for common API errors
 */
export const ApiErrorCode = {
  NETWORK_ERROR: 'NETWORK_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  AUTH_ERROR: 'AUTH_ERROR',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  SERVER_ERROR: 'SERVER_ERROR',
  TIMEOUT: 'TIMEOUT',
  CONFLICT: 'CONFLICT',
  UNKNOWN: 'UNKNOWN'
} as const

export type ApiErrorCodeType = (typeof ApiErrorCode)[keyof typeof ApiErrorCode]

/**
 * Parse error response from the server
 * Handles both JSON and text error responses
 */
async function parseErrorResponse(response: Response): Promise<{ message: string; detail?: string }> {
  const contentType = response.headers.get('content-type')

  if (contentType?.includes('application/json')) {
    try {
      const json = await response.json()
      return {
        message: json.detail || json.message || json.error || response.statusText,
        detail: json.detail
      }
    } catch {
      return { message: response.statusText }
    }
  }

  const text = await response.text()
  return { message: text || response.statusText, detail: text }
}

/**
 * Get error code from HTTP status
 */
function getErrorCodeFromStatus(status: number): ApiErrorCodeType {
  if (status === 404) return ApiErrorCode.NOT_FOUND
  if (status === 401 || status === 403) return ApiErrorCode.AUTH_ERROR
  if (status === 400 || status === 422) return ApiErrorCode.VALIDATION_ERROR
  if (status === 409) return ApiErrorCode.CONFLICT
  if (status >= 500) return ApiErrorCode.SERVER_ERROR
  return ApiErrorCode.UNKNOWN
}

/**
 * Handle API response and throw ApiError if not ok
 * This is the unified error handling function for all API calls
 */
async function handleResponse<T>(response: Response, context?: string): Promise<T> {
  if (response.ok) {
    // Handle empty responses (204 No Content, etc.)
    const contentLength = response.headers.get('content-length')
    if (response.status === 204 || contentLength === '0') {
      return undefined as T
    }
    return response.json()
  }

  const { message, detail } = await parseErrorResponse(response)
  const code = getErrorCodeFromStatus(response.status)
  const errorMessage = context ? `${context}: ${message}` : message

  throw new ApiError(errorMessage, response.status, code, detail)
}

// Token storage key (defined early for use in apiFetch)
const AUTH_TOKEN_KEY = 'pathlab_auth_token'

/**
 * Get stored auth token (internal use)
 */
function _getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY)
}

/**
 * Wrap fetch call with unified error handling
 * Catches network errors and converts them to ApiError
 * Automatically adds Authorization header if token is available
 */
async function apiFetch<T>(
  url: string,
  options?: RequestInit,
  context?: string,
  skipAuth: boolean = false
): Promise<T> {
  try {
    // Add auth header if token exists and not skipping auth
    let headers = { ...(options?.headers || {}) } as Record<string, string>
    if (!skipAuth) {
      const token = _getAuthToken()
      if (token && !headers['Authorization']) {
        headers['Authorization'] = `Bearer ${token}`
      }
    }

    const response = await fetch(url, { ...options, headers })
    return handleResponse<T>(response, context)
  } catch (error) {
    // If it's already an ApiError, rethrow it
    if (error instanceof ApiError) {
      throw error
    }

    const errorMessage = error instanceof Error ? error.message : String(error)
    // "Failed to fetch" is the standard error message in Chrome/Electron for network issues
    // We check for various forms of network errors
    const isNetworkError =
      (error instanceof TypeError && errorMessage.includes('fetch')) ||
      errorMessage.toLowerCase().includes('failed to fetch') ||
      errorMessage.toLowerCase().includes('network request failed') ||
      errorMessage.toLowerCase().includes('network error')

    // Network errors (no internet, CORS, backend down)
    if (isNetworkError) {
      const friendlyMsg = 'Cannot connect to server. Please check your network connection and ensure the backend is running.'
      throw new ApiError(
        context ? `${context}: ${friendlyMsg}` : friendlyMsg,
        0,
        ApiErrorCode.NETWORK_ERROR,
        errorMessage
      )
    }

    // Other unknown errors
    throw new ApiError(
      context ? `${context}: ${errorMessage}` : errorMessage,
      0,
      ApiErrorCode.UNKNOWN,
      errorMessage
    )
  }
}

// ============================================================================
// Standard API Response Types
// ============================================================================

/**
 * Standard paginated list response
 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

/**
 * Standard success response for operations that don't return data
 */
export interface SuccessResponse {
  success: boolean
  message: string
}

/**
 * Standard delete response
 */
export interface DeleteResponse {
  message: string
  deleted?: boolean
}

// ============================================================================
// Authentication APIs (JWT-based local authentication)
// ============================================================================

/**
 * Get stored auth token
 */
export function getAuthToken(): string | null {
  return _getAuthToken()
}

/**
 * Set auth token in storage
 */
export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token)
}

/**
 * Clear auth token from storage
 */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY)
}

export interface AuthUser {
  id: string
  email: string
  nickname?: string
  role: 'admin' | 'pathologist' | 'guest'
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  agreement_accepted_at?: string | null
  created_at?: string
  updated_at?: string
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

export interface UserUpdateRequest {
  nickname?: string
  role?: 'admin' | 'pathologist' | 'guest'
  password?: string
  is_active?: boolean
}

/**
 * Migrate a legacy user's password to support secure login.
 * This is called automatically when a user without password_sha256 tries to login.
 *
 * @param username - Username
 * @param password - User password (sent via form data, verified with bcrypt)
 * @returns JWT access token
 */
async function migratePassword(
  username: string,
  password: string
): Promise<LoginResponse & { migrated?: boolean }> {
  const formData = new URLSearchParams()
  formData.append('username', username)
  formData.append('password', password)

  const response = await apiFetch<LoginResponse & { migrated?: boolean }>(
    `${API_BASE}/auth/migrate-password`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData.toString()
    },
    'Password migration failed'
  )

  // Store the token
  if (response.access_token) {
    setAuthToken(response.access_token)
  }

  return response
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
 * For legacy users (registered before secure login), automatically migrates
 * their password on first login attempt.
 *
 * @param username - Username (stored in email field internally)
 * @param password - User password
 * @returns JWT access token
 * @throws {ApiError} If login fails
 */
export async function loginWithCredentials(
  username: string,
  password: string
): Promise<LoginResponse> {
  // Step 1: Compute SHA256(password)
  const passwordHash = await sha256(password)

  // Step 2: Get current timestamp in milliseconds
  const timestamp = Date.now()

  // Step 3: Compute SHA256(passwordHash + timestamp + APP_SALT)
  const hashedCredential = await sha256(passwordHash + timestamp + APP_SALT)

  try {
    // Step 4: Send secure login request
    const response = await apiFetch<LoginResponse>(
      `${API_BASE}/auth/secure-login`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          hashed_password: hashedCredential,
          timestamp
        })
      },
      'Login failed'
    )

    // Store the token
    if (response.access_token) {
      setAuthToken(response.access_token)
    }

    return response
  } catch (error) {
    // Check if this is a legacy user who needs password migration
    if (
      error instanceof ApiError &&
      error.details?.includes('LOGIN_PASSWORD_MIGRATION_REQUIRED')
    ) {
      console.log('Legacy user detected, migrating password...')
      // Automatically migrate the password and login
      return migratePassword(username, password)
    }
    // Re-throw other errors
    throw error
  }
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
    // If token is invalid, clear it
    if (error instanceof ApiError && error.isAuthError()) {
      clearAuthToken()
    }
    return { is_logged_in: false }
  }
}

/**
 * Update current user info
 * @param data - Update data
 * @returns Updated user
 * @throws {ApiError} If update fails
 */
export async function updateCurrentUser(data: UserUpdateRequest): Promise<AuthUser> {
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

// ============================================================================
// User Management APIs (Admin only)
// ============================================================================

export interface UserListItem extends AuthUser {
  id: string
}

/**
 * List all users (admin only)
 * @throws {ApiError} If request fails or not authorized
 */
export async function listUsers(): Promise<UserListItem[]> {
  return apiFetch<UserListItem[]>(`${API_BASE}/auth/users`, undefined, 'Failed to list users')
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
export async function updateUser(userId: string, data: UserUpdateRequest): Promise<AuthUser> {
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
 * Accept the terms of service agreement
 * @returns Updated user with agreement_accepted_at set
 * @throws {ApiError} If request fails
 */
export async function acceptAgreement(): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/accept-agreement`,
    { method: 'POST' },
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

// Legacy OAuth functions (kept for backward compatibility, will be removed)
export interface AuthUrlResponse {
  url: string
  state: string
  message: string
}

export async function getLoginUrl(): Promise<AuthUrlResponse> {
  return apiFetch<AuthUrlResponse>(`${API_BASE}/auth/login-url`, undefined, 'Failed to get login URL')
}

export async function getSignupUrl(): Promise<AuthUrlResponse> {
  return apiFetch<AuthUrlResponse>(`${API_BASE}/auth/signup-url`, undefined, 'Failed to get signup URL')
}

export async function processAuthCallback(
  code: string,
  state?: string
): Promise<{ success: boolean; user_id: string; username: string; message: string }> {
  return apiFetch(
    `${API_BASE}/auth/callback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, state })
    },
    'Login failed'
  )
}

// ============================================================================
// Dataset Permission APIs (Temporary Elevated Access for Demo)
// ============================================================================

/**
 * Dataset permission info
 */
export interface DatasetPermission {
  id: number
  dataset_id: string
  user_id: string
  granted_by: string
  permission_level: string
  expires_at: string | null
  created_at: string
  is_expired: boolean
  is_valid: boolean
}

/**
 * Get current user's dataset permissions
 * Returns list of datasets where user has temporary elevated access
 */
export async function getMyDatasetPermissions(): Promise<{
  user_id: string
  permissions: DatasetPermission[]
  elevated_dataset_ids: string[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/my-permissions`,
    undefined,
    'Failed to get dataset permissions'
  )
}

/**
 * List permissions for a dataset (admin only)
 * @param datasetId - Dataset ID
 */
export async function listDatasetPermissions(datasetId: string): Promise<{
  dataset_id: string
  permissions: DatasetPermission[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions`,
    undefined,
    'Failed to list dataset permissions'
  )
}

/**
 * Grant temporary elevated permission to a user for a dataset (admin only)
 * @param datasetId - Dataset ID
 * @param userId - User ID to grant permission to
 * @param expiresInHours - Optional expiration time in hours (null = no expiration)
 */
export async function grantDatasetPermission(
  datasetId: string,
  userId: string,
  expiresInHours?: number
): Promise<{ message: string; permission: DatasetPermission }> {
  const formData = new FormData()
  formData.append('user_id', userId)
  if (expiresInHours !== undefined && expiresInHours > 0) {
    formData.append('expires_in_hours', expiresInHours.toString())
  }

  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions`,
    {
      method: 'POST',
      body: formData
    },
    'Failed to grant dataset permission'
  )
}

/**
 * Revoke a user's permission for a dataset (admin only)
 * @param datasetId - Dataset ID
 * @param userId - User ID to revoke permission from
 */
export async function revokeDatasetPermission(
  datasetId: string,
  userId: string
): Promise<{ message: string }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions/${userId}`,
    { method: 'DELETE' },
    'Failed to revoke dataset permission'
  )
}

/**
 * Get all dataset permissions for a specific user (admin only)
 * @param userId - User ID to get permissions for
 */
export async function getUserDatasetPermissions(userId: string): Promise<{
  user_id: string
  permissions: DatasetPermission[]
  valid_permissions: DatasetPermission[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/user-permissions/${userId}`,
    undefined,
    'Failed to get user dataset permissions'
  )
}

// ============================================================================
// WSI APIs
// ============================================================================

/**
 * WSI Summary returned from list endpoint
 */
export interface WSISummary {
  wsi_id: string
  original_filename: string
  dataset_id: string | null
  dataset_name: string | null
  case_id: string | null
  label: string | null
  wsi_path: string
  age: number | null
  gender: string | null
  source: string | null
  // Survival analysis fields
  event_time: number | null
  event_status: number | null
  // Split assignment (from CSV upload)
  split: string | null  // "train", "val", "test"
  mpp: number | null
  vendor: string | null
  width: number | null
  height: number | null
  magnification: number | null
  file_size: number | null
  created_at: string | null
  updated_at: string | null
}

/**
 * WSI Detail response including latest result
 */
export interface WSIDetail {
  wsi_id: string
  meta: WSISummary
  last_run: AIResult | null
}

/**
 * AI Result response
 */
export interface AIResult {
  wsi_id: string
  task_id: string
  pred: string | null
  probs: Record<string, number> | null
  metadata: Record<string, unknown> | null
  created_at: string | null
}

/**
 * WSI List response
 */
export interface WSIListResponse {
  items: WSISummary[]
  total: number
}

/**
 * WSI Upload result
 */
export interface WSIUploadResult {
  message: string
  wsi_id: string
  wsi_path: string
  file_size: number
  associated_files_count?: number
  label?: string
  case_id?: string
  associated_data?: Record<string, unknown>
}

/**
 * Batch CSV upload result
 */
export interface BatchUploadResult {
  message: string
  total: number
  successful: number
  failed: number
  results: Array<{
    wsi_path: string
    wsi_id?: string
    success: boolean
    error?: string
  }>
}

/**
 * System statistics
 */
export interface SystemStats {
  wsi_count: number
  task_count: number
  completed_count: number
  results_count: number
  labels: Record<string, number>
}

/**
 * AI task creation response
 */
export interface AITaskResponse {
  task_id: string
  status: string
  message?: string
}

/**
 * Compute patches response
 */
export interface ComputePatchesResponse {
  wsi_id: string
  patches_computed: number
  patch_size: number
  stride: number
  level: number
  output_file: string
}

/**
 * Training task summary
 */
export interface TrainingTask {
  task_id: string
  task_name: string
  task_type: string
  data_level: string
  task_description: string | null
  status: string
  progress: number
  error_message: string | null
  preprocessing_config: Record<string, unknown> | null
  model_config: Record<string, unknown> | null
  classes: string[] | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
}

/**
 * Training task detail with WSI count and IDs
 */
export interface TrainingTaskDetail extends TrainingTask {
  wsi_count?: number
  wsi_ids?: string[]
}

/**
 * Trained model from training tasks
 */
export interface TrainedModel {
  model_id: string
  task_id: string
  model_name: string
  model_path: string
  config_path?: string
  classes: string[]
  feature_extractor?: string
  aggregator?: string
  train_metrics?: Record<string, unknown>
  val_metrics?: Record<string, unknown>
  is_default: boolean
  is_active: boolean
  created_at: string
}

/**
 * Response for trained models list
 */
export interface TrainedModelsResponse {
  items: TrainedModel[]
  total: number
}

/**
 * Get list of trained models
 * @param skip - Number of items to skip (pagination)
 * @param limit - Maximum number of items to return
 * @throws {ApiError} If the request fails
 */
export async function getTrainedModels(skip = 0, limit = 100): Promise<TrainedModelsResponse> {
  return apiFetch<TrainedModelsResponse>(
    `${API_BASE}/models?skip=${skip}&limit=${limit}`,
    undefined,
    'Failed to fetch trained models'
  )
}

/**
 * Get trained model by ID
 * @param modelId - Model ID
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function getTrainedModel(modelId: string): Promise<TrainedModel> {
  return apiFetch<TrainedModel>(
    `${API_BASE}/models/${encodeURIComponent(modelId)}`,
    undefined,
    'Failed to fetch model'
  )
}

/**
 * Update trained model properties
 * @param modelId - Model ID
 * @param updates - Properties to update (is_default, is_active)
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function updateTrainedModel(
  modelId: string,
  updates: { is_default?: boolean; is_active?: boolean }
): Promise<TrainedModel> {
  return apiFetch<TrainedModel>(
    `${API_BASE}/models/${encodeURIComponent(modelId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    },
    'Failed to update model'
  )
}

/**
 * Delete a trained model
 * @param modelId - Model ID
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function deleteTrainedModel(modelId: string): Promise<{ message: string; model_id: string }> {
  return apiFetch(
    `${API_BASE}/models/${encodeURIComponent(modelId)}`,
    { method: 'DELETE' },
    'Failed to delete model'
  )
}

// ============================================================================
// INFERENCE API
// ============================================================================

/**
 * Response from starting external validation or test split inference
 */
export interface InferenceTaskResponse {
  task_id: string
  status: string
  total_wsi: number
  message?: string
}

/**
 * Start external validation - use a trained model on data from a different task
 * @param modelId - TrainedModel ID
 * @param dataTaskId - Task ID whose WSIs will be used for validation
 * @returns Task response with task_id for tracking progress
 * @throws {ApiError} If the request fails
 */
export async function startExternalValidation(
  modelId: string,
  dataTaskId: string
): Promise<InferenceTaskResponse> {
  return apiFetch<InferenceTaskResponse>(
    `${API_BASE}/results/external-validation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        data_task_id: dataTaskId
      })
    },
    'Failed to start external validation'
  )
}

/**
 * Feature extractor info
 */
export interface FeatureExtractor {
  id: string
  name: string
  description: string
}

/**
 * Feature extractor list response
 */
export interface FeatureExtractorListResponse {
  items: FeatureExtractor[]
}

/**
 * Check duplicate filenames response
 */
export interface CheckDuplicatesResponse {
  duplicates: string[]
  new: string[]
}

/**
 * Check which filenames already exist in the database
 * Used to skip uploading files that already exist
 * @param filenames - List of filenames to check (original_filename)
 * @returns Object with duplicates and new filenames
 * @throws {ApiError} If the request fails
 */
export async function checkDuplicateFilenames(filenames: string[]): Promise<CheckDuplicatesResponse> {
  if (filenames.length === 0) {
    return { duplicates: [], new: [] }
  }

  return apiFetch<CheckDuplicatesResponse>(
    `${API_BASE}/wsi/check-duplicates`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(filenames)
    },
    'Failed to check duplicate filenames'
  )
}

/**
 * Fetch WSI list from database via Gateway API
 * @param datasetId - Optional dataset UUID to filter by
 * @throws {ApiError} If the request fails
 */
export async function fetchWSIList(datasetId?: string): Promise<WSIListResponse> {
  const url = new URL(`${API_BASE}/wsi`)
  if (datasetId) {
    url.searchParams.set('dataset_id', datasetId)
  }
  return apiFetch<WSIListResponse>(url.toString(), undefined, 'Failed to load WSI list from database')
}

/**
 * Dataset summary returned from list datasets endpoint
 */
export interface DatasetSummary {
  dataset_id: string | null  // UUID for API calls (null for uncategorized)
  dataset_name: string  // Display name
  file_count: number
  total_size: number
  dataset_type: 'classification' | 'survival' // Determined by whether WSIs have event_time set
}

/**
 * Datasets list response
 */
export interface DatasetsListResponse {
  items: DatasetSummary[]
  total: number
}

/**
 * Fetch all datasets from database via Gateway API
 * @param dataLevel - Optional filter: "wsi" for WSI files, "patch" for image files
 * @throws {ApiError} If the request fails
 */
export async function fetchDatasets(dataLevel?: string): Promise<DatasetsListResponse> {
  const params = new URLSearchParams()
  if (dataLevel) {
    params.append('data_level', dataLevel)
  }
  const queryString = params.toString()
  const url = queryString ? `${API_BASE}/wsi/datasets?${queryString}` : `${API_BASE}/wsi/datasets`
  return apiFetch<DatasetsListResponse>(url, undefined, 'Failed to load datasets from database')
}

/**
 * Rename a dataset (update display name)
 * @param datasetId - Dataset UUID
 * @param newName - New display name
 * @throws {ApiError} If the request fails
 */
export async function renameDataset(
  datasetId: string,
  newName: string
): Promise<{ message: string; dataset: { dataset_id: string; name: string } }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId, new_name: newName })
    },
    'Failed to rename dataset'
  )
}

/**
 * Fetch WSI detail from database via Gateway API
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function fetchWSIDetail(wsi_id: string): Promise<WSIDetail> {
  return apiFetch<WSIDetail>(
    `${API_BASE}/wsi/${encodeURIComponent(wsi_id)}`,
    undefined,
    'Failed to get WSI detail from database'
  )
}

/**
 * Compute patch coordinates for a WSI using PrePATH-style tissue segmentation
 * Uses settings from localStorage if not provided
 * @throws {ApiError} If the request fails
 */
export async function computePatches(
  wsi_id: string,
  options?: {
    patch_size?: number
    stride?: number
    level?: number
    force_recompute?: boolean
    // Segmentation parameters
    sthresh?: number
    mthresh?: number
    close?: number
    use_otsu?: boolean
    contour_fn?: string
  }
): Promise<ComputePatchesResponse> {
  // Get settings from localStorage
  const patch_size = options?.patch_size ?? parseInt(localStorage.getItem('patch_size') || '512')
  const stride = options?.stride ?? parseInt(localStorage.getItem('patch_stride') || '0')
  const level = options?.level ?? parseInt(localStorage.getItem('patch_level') || '0')
  const sthresh = options?.sthresh ?? parseInt(localStorage.getItem('seg_sthresh') || '5')
  const mthresh = options?.mthresh ?? parseInt(localStorage.getItem('seg_mthresh') || '7')
  const close = options?.close ?? parseInt(localStorage.getItem('seg_close') || '4')
  const use_otsu = options?.use_otsu ?? localStorage.getItem('seg_use_otsu') === 'true'
  const contour_fn = options?.contour_fn ?? (localStorage.getItem('seg_contour_fn') || 'four_pt')
  const force_recompute = options?.force_recompute ?? false

  // Build query parameters
  const params = new URLSearchParams({
    patch_size: String(patch_size),
    stride: String(stride),
    level: String(level),
    force_recompute: String(force_recompute),
    sthresh: String(sthresh),
    mthresh: String(mthresh),
    close: String(close),
    use_otsu: String(use_otsu),
    contour_fn: contour_fn
  })

  return apiFetch<ComputePatchesResponse>(
    `${API_BASE}/wsi/${encodeURIComponent(wsi_id)}/compute_patches?${params}`,
    { method: 'POST' },
    'Failed to compute patches'
  )
}

/**
 * Analyze WSI parameters
 */
export interface AnalyzeWSIParams {
  classes?: string[]
  model_id?: string
  [key: string]: unknown
}

/**
 * Call Gateway to create a WSI classification task.
 * Gateway will orchestrate the request to AI Service.
 * @throws {ApiError} If the request fails
 */
export async function analyzeWSI(wsi_id: string, params: AnalyzeWSIParams = {}): Promise<AITaskResponse> {
  console.log('Analyzing WSI:', wsi_id, 'with params:', params)

  // Extract classes and model_id to top level as expected by backend WSIClassifyRequest
  const { classes, model_id, ...restParams } = params

  return apiFetch<AITaskResponse>(
    `${API_BASE}/tasks/wsi_classification`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wsi_id,
        classes,
        model_id,
        params: Object.keys(restParams).length > 0 ? restParams : undefined
      })
    },
    'Failed to analyze WSI'
  )
}

/**
 * Fetch AI analysis results from Gateway.
 * Gateway will get the latest results from AI Service or local cache.
 * @returns Result, or null if no prediction available yet
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function fetchResults(wsi_id: string): Promise<AIResult | null> {
  const result = await apiFetch<AIResult>(
    `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}`,
    undefined,
    'Failed to get results'
  )

  // Return null if no prediction available (valid state, not an error)
  if (!result.pred) {
    return null
  }

  return result
}

/**
 * Result item with WSI info from /results endpoint
 */
export interface ResultWithWSI {
  wsi_id: string
  task_id: string
  pred: string
  probs: Record<string, number> | null
  label: string | null  // Ground truth
  case_id: string | null
  original_filename: string
  created_at: string | null
}

/**
 * Response from /results endpoint
 */
export interface AllResultsResponse {
  items: ResultWithWSI[]
  total: number
}

// Cache for fetchAllResults to prevent repeated calls
let allResultsCache: {
  data: AllResultsResponse | null
  timestamp: number
  promise: Promise<AllResultsResponse> | null
} = {
  data: null,
  timestamp: 0,
  promise: null
}

const RESULTS_CACHE_TTL = 30000 // 30 seconds TTL

/**
 * Fetch all AI results with WSI info (with caching)
 * @returns List of results with predictions and WSI metadata
 * @throws {ApiError} If the request fails
 */
export async function fetchAllResults(): Promise<AllResultsResponse> {
  const now = Date.now()

  // Return cached data if still valid
  if (allResultsCache.data && now - allResultsCache.timestamp < RESULTS_CACHE_TTL) {
    return allResultsCache.data
  }

  // If a request is already in progress, wait for it
  if (allResultsCache.promise) {
    return allResultsCache.promise
  }

  // Make new request
  allResultsCache.promise = apiFetch<AllResultsResponse>(
    `${API_BASE}/results`,
    undefined,
    'Failed to load results'
  )
    .then((data) => {
      allResultsCache.data = data
      allResultsCache.timestamp = Date.now()
      allResultsCache.promise = null
      return data
    })
    .catch((err) => {
      allResultsCache.promise = null
      throw err
    })

  return allResultsCache.promise
}

/**
 * Invalidate the results cache (call after mutations)
 */
export function invalidateResultsCache(): void {
  allResultsCache.data = null
  allResultsCache.timestamp = 0
}

/**
 * Delete result for WSI AI results
 */
export interface DeleteWSIResultsResponse {
  message: string
  wsi_id: string
  task_id: string | null
  database_deleted: number
  storage_cleanup: {
    deleted_files: string[]
    deleted_dirs: string[]
    failed: [string, string][]
    total_size: number
    summary: string
  }
}

/**
 * Delete AI analysis results for a WSI.
 *
 * @param wsi_id - The WSI ID to delete results for
 * @param task_id - Optional task ID to delete results for a specific task only
 * @returns Delete result with cleanup info
 * @throws {ApiError} If the request fails
 */
export async function deleteWSIResults(wsi_id: string, task_id?: string): Promise<DeleteWSIResultsResponse> {
  const params = new URLSearchParams()
  if (task_id) {
    params.set('task_id', task_id)
  }

  const url = `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}${params.toString() ? '?' + params.toString() : ''}`

  const result = await apiFetch<DeleteWSIResultsResponse>(url, { method: 'DELETE' }, 'Failed to delete WSI results')

  // Invalidate cache after deletion
  invalidateResultsCache()

  return result
}

/**
 * Response type for dataset splits upload
 */
export interface UploadSplitsResponse {
  message: string
  updated_count: number
  auto_val_count: number
  not_found_count: number
  not_found_files: string[]
}

/**
 * Upload dataset split configuration (CSV)
 * @param datasetId - Dataset UUID
 * @param file - CSV file with split configuration
 * @throws {ApiError} If the request fails
 */
export async function uploadDatasetSplits(datasetId: string, file: File): Promise<UploadSplitsResponse> {
  const formData = new FormData()
  formData.append('file', file)

  return apiFetch<UploadSplitsResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/splits`,
    { method: 'POST', body: formData },
    'Failed to upload dataset splits'
  )
}

/**
 * Upload a WSI file to the server.
 * For MRXS format: also upload associated data folder files
 * For TMAP format: also upload associated DT files
 *
 * @param file - The WSI file to upload
 * @param options - Optional metadata and associated files
 * @returns Upload result with wsi_id and metadata
 */
export async function uploadWSIFile(
  file: File,
  options?: {
    dataset_id?: string  // Dataset UUID (for existing dataset)
    dataset_name?: string  // Dataset display name (for creating new dataset)
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    wsi_id?: string
    // Survival analysis fields
    event_time?: number
    event_status?: number
    onProgress?: (progress: number) => void
    /** Associated files for special formats (MRXS data folder files, TMAP DT files) */
    associatedFiles?: File[]
  }
): Promise<WSIUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  if (options?.dataset_id) {
    formData.append('dataset_id', options.dataset_id)
  }
  if (options?.dataset_name) {
    formData.append('dataset_name', options.dataset_name)
  }
  if (options?.label) {
    formData.append('label', options.label)
  }
  if (options?.case_id) {
    formData.append('case_id', options.case_id)
  }
  if (options?.age !== undefined) {
    formData.append('age', options.age.toString())
  }
  if (options?.gender) {
    formData.append('gender', options.gender)
  }
  if (options?.source) {
    formData.append('source', options.source)
  }
  if (options?.wsi_id) {
    formData.append('wsi_id', options.wsi_id)
  }
  // Survival analysis fields
  if (options?.event_time !== undefined) {
    formData.append('event_time', options.event_time.toString())
  }
  if (options?.event_status !== undefined) {
    formData.append('event_status', options.event_status.toString())
  }

  // Add associated files for MRXS/TMAP formats
  if (options?.associatedFiles && options.associatedFiles.length > 0) {
    options.associatedFiles.forEach((assocFile) => {
      formData.append('associated_files', assocFile)
    })
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    // Track upload progress
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && options?.onProgress) {
        const progress = Math.round((e.loaded / e.total) * 100)
        options.onProgress(progress)
      }
    })

    // Handle completion
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const result = JSON.parse(xhr.responseText) as WSIUploadResult
          resolve(result)
        } catch (err) {
          reject(new Error('Failed to parse response'))
        }
      } else {
        reject(new Error(`Failed to upload WSI file: ${xhr.responseText}`))
      }
    })

    // Handle errors
    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'))
    })

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload aborted'))
    })

    // Send request with auth header
    xhr.open('POST', `${API_BASE}/wsi/upload/file`)
    const token = getAuthToken()
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }
    xhr.send(formData)
  })
}

/**
 * Register a WSI by file path (without copying the file).
 *
 * @param wsi_path - Path to the WSI file on the server
 * @param options - Optional metadata (label, case_id, wsi_id, dataset_id/dataset_name)
 * @returns Upload result with wsi_id and metadata
 * @throws {ApiError} If the request fails
 */
export async function uploadWSIByPath(
  wsi_path: string,
  options?: {
    dataset_id?: string  // Dataset UUID (for existing dataset)
    dataset_name?: string  // Dataset display name (for creating new dataset)
    label?: string
    case_id?: string
    wsi_id?: string
    age?: number
    gender?: string
    source?: string
    // Survival analysis fields
    event_time?: number
    event_status?: number
  }
): Promise<WSIUploadResult> {
  return apiFetch<WSIUploadResult>(
    `${API_BASE}/wsi/upload/path`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wsi_path,
        dataset_id: options?.dataset_id,
        dataset_name: options?.dataset_name,
        label: options?.label,
        case_id: options?.case_id,
        wsi_id: options?.wsi_id,
        age: options?.age,
        gender: options?.gender,
        source: options?.source,
        event_time: options?.event_time,
        event_status: options?.event_status
      })
    },
    'Failed to register WSI by path'
  )
}

export interface StorageConfig {
  uploads_dir: string
  source?: 'env' | 'config' | 'default' | string
}

/**
 * Get storage configuration
 * @throws {ApiError} If the request fails
 */
export async function getStorageConfig(): Promise<StorageConfig> {
  return apiFetch<StorageConfig>(`${API_BASE}/storage/config`, undefined, 'Failed to load storage config')
}

/**
 * Update storage configuration
 * @throws {ApiError} If the request fails
 */
export async function updateStorageConfig(
  uploads_dir: string
): Promise<{ uploads_dir: string; restart_required: boolean; message?: string }> {
  return apiFetch(
    `${API_BASE}/storage/config`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uploads_dir })
    },
    'Failed to update storage config'
  )
}

export interface MigrationStatus {
  status: 'idle' | 'running' | 'completed' | 'failed' | 'success' | 'error'
  source: string | null
  destination: string | null
  progress: number
  error: string | null
  delete_source: boolean
  message?: string
  new_path?: string
}

/**
 * Start storage migration to a new location
 * @throws {ApiError} If the request fails
 */
export async function startMigration(targetPath: string, deleteSource: boolean = false): Promise<void> {
  await apiFetch<{ message: string }>(
    `${API_BASE}/storage/migrate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_path: targetPath, delete_source: deleteSource })
    },
    'Failed to start migration'
  )
}

/**
 * Get migration status
 * @throws {ApiError} If the request fails
 */
export async function getMigrationStatus(): Promise<MigrationStatus> {
  return apiFetch<MigrationStatus>(`${API_BASE}/storage/migration/status`, undefined, 'Failed to get migration status')
}

/**
 * Download CSV template for batch WSI metadata configuration.
 * @param taskType - 'classification' or 'survival'
 * @throws {ApiError} If the request fails
 */
export async function downloadCSVTemplate(taskType: 'classification' | 'survival' = 'classification'): Promise<void> {
  let response: Response
  try {
    const headers: Record<string, string> = {}
    const token = getAuthToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    response = await fetch(`${API_BASE}/wsi/upload/csv/template?task_type=${taskType}`, { headers })
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    if (
      errorMessage.toLowerCase().includes('fetch') ||
      errorMessage.toLowerCase().includes('network')
    ) {
      throw new ApiError(
        'Cannot connect to server. Please check your network connection.',
        0,
        ApiErrorCode.NETWORK_ERROR,
        errorMessage
      )
    }
    throw error
  }

  if (!response.ok) {
    const { message, detail } = await parseErrorResponse(response)
    throw new ApiError(
      `Failed to download CSV template: ${message}`,
      response.status,
      getErrorCodeFromStatus(response.status),
      detail
    )
  }

  // Get the blob and create a download link
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // Use filename from Content-Disposition header or fallback
  const filename =
    taskType === 'survival' ? 'wsi_survival_metadata_template.csv' : 'wsi_classification_metadata_template.csv'
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

/**
 * WSI delete result
 */
export interface WSIDeleteResult {
  message: string
  wsi_id: string
  storage_cleanup: {
    deleted_files: string[]
    deleted_dirs: string[]
    failed: [string, string][]
    total_size: number
    summary: string
  }
}

/**
 * WSI metadata update result
 */
export interface WSIMetadataUpdateResult {
  message: string
  wsi: WSISummary
}

/**
 * Delete a WSI and its associated data.
 *
 * @param wsi_id - The WSI ID to delete
 * @param mode - Deletion mode: "standard" (keep training features) or "complete" (delete all)
 * @returns Delete result
 * @throws {ApiError} If the request fails
 */
export async function deleteWSI(wsi_id: string, mode: string = 'standard'): Promise<WSIDeleteResult> {
  return apiFetch<WSIDeleteResult>(
    `${API_BASE}/wsi/${wsi_id}?mode=${mode}`,
    { method: 'DELETE' },
    'Failed to delete WSI'
  )
}

/**
 * Update WSI metadata (label, case_id, age, gender, source).
 *
 * @param wsi_id - The WSI ID to update
 * @param metadata - Metadata to update
 * @returns Update result
 * @throws {ApiError} If the request fails
 */
export async function updateWSIMetadata(
  wsi_id: string,
  metadata: {
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    // Survival analysis fields
    event_time?: number
    event_status?: number
  }
): Promise<WSIMetadataUpdateResult> {
  return apiFetch<WSIMetadataUpdateResult>(
    `${API_BASE}/wsi/${wsi_id}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    },
    'Failed to update WSI metadata'
  )
}

/**
 * Batch register WSI files by uploading a CSV file.
 *
 * CSV format (with header):
 * wsi_path,label,case_id,wsi_id
 * /path/to/slide1.svs,HSIL,case_001,slide_001
 * /path/to/slide2.svs,LSIL,case_002,slide_002
 *
 * @param file - CSV file containing WSI paths and metadata
 * @returns Batch upload result with success/failed counts
 * @throws {ApiError} If the request fails
 */
export async function uploadWSIByCSV(file: File): Promise<BatchUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  return apiFetch<BatchUploadResult>(
    `${API_BASE}/wsi/upload/csv`,
    { method: 'POST', body: formData },
    'Failed to upload CSV'
  )
}

/**
 * Fetch system statistics from Gateway.
 * Returns WSI count, task count, completed count, results count, and label distribution.
 * @throws {ApiError} If the request fails
 */
export async function fetchStats(): Promise<SystemStats> {
  return apiFetch<SystemStats>(`${API_BASE}/stats`, undefined, 'Failed to get stats')
}

/**
 * Chat message content type - supports both text and multimodal
 */
export type ChatMessageContent =
  | string
  | Array<
      | { type: 'text'; text: string }
      | { type: 'image_url'; image_url: { url: string } }
    >

/**
 * Chat message type
 */
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: ChatMessageContent
}

/**
 * Chat with AI assistant (streaming)
 * Supports both text-only and multimodal messages (with images)
 *
 * @param messages - Array of chat messages (text or multimodal)
 * @param onChunk - Callback for each chunk of response
 * @param conversationId - Optional conversation ID to save messages to database
 * @returns Promise that resolves when streaming is complete
 * @throws {ApiError} If the request fails
 *
 * @example
 * // Text-only message
 * chatWithAI([{ role: 'user', content: 'Hello' }], onChunk)
 *
 * // Multimodal message with image
 * chatWithAI([{
 *   role: 'user',
 *   content: [
 *     { type: 'text', text: 'What is in this image?' },
 *     { type: 'image_url', image_url: { url: 'data:image/jpeg;base64,...' } }
 *   ]
 * }], onChunk)
 */
export async function chatWithAI(
  messages: ChatMessage[],
  onChunk: (chunk: string) => void,
  conversationId?: string
): Promise<void> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-instruct'

  let response: Response
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-OpenRouter-API-Key': apiKey,
      'X-OpenRouter-Base-URL': baseUrl,
      'X-OpenRouter-Model': model
    }
    const token = getAuthToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages,
        conversation_id: conversationId
      })
    })
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    if (
      errorMessage.toLowerCase().includes('fetch') ||
      errorMessage.toLowerCase().includes('network')
    ) {
      throw new ApiError(
        'Failed to connect to AI service. Please check your network connection.',
        0,
        ApiErrorCode.NETWORK_ERROR,
        errorMessage
      )
    }
    throw error
  }

  if (!response.ok) {
    const { message, detail } = await parseErrorResponse(response)
    throw new ApiError(`Failed to chat with AI: ${message}`, response.status, getErrorCodeFromStatus(response.status), detail)
  }

  // Handle streaming response
  const reader = response.body?.getReader()
  if (!reader) {
    throw new ApiError('Response body is not readable', 0, ApiErrorCode.UNKNOWN)
  }

  const decoder = new TextDecoder()

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') {
            return
          }
          try {
            const parsed = JSON.parse(data)
            if (parsed.content) {
              onChunk(parsed.content)
            }
          } catch (e) {
            // Skip invalid JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Training task delete result
 */
export interface TrainingTaskDeleteResult {
  message: string
  task_id: string
  storage_cleanup?: {
    deleted_files: string[]
    deleted_dirs: string[]
    failed: [string, string][]
    total_size: number
    summary: string
  }
}

/**
 * Training task creation result
 */
export interface TrainingTaskCreateResult extends TrainingTask {
  wsi_count: number
}

/**
 * Get all training tasks
 * @returns List of training tasks
 * @throws {ApiError} If the request fails
 */
export async function getTrainingTasks(): Promise<TrainingTask[]> {
  const data = await apiFetch<PaginatedResponse<TrainingTask>>(
    `${API_BASE}/tasks/training`,
    undefined,
    'Failed to get training tasks'
  )
  return data.items || []
}

/**
 * Get training task by ID
 * @param taskId - Training task ID
 * @returns Training task details
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function getTrainingTask(taskId: string): Promise<TrainingTaskDetail> {
  return apiFetch<TrainingTaskDetail>(
    `${API_BASE}/tasks/training/${taskId}`,
    undefined,
    'Failed to get training task'
  )
}

/**
 * Delete training task
 * @param taskId - Training task ID
 * @param mode - Deletion mode: "standard" (keep models) or "complete" (delete all)
 * @throws {ApiError} If the request fails
 */
export async function deleteTrainingTask(
  taskId: string,
  mode: string = 'standard'
): Promise<TrainingTaskDeleteResult> {
  return apiFetch<TrainingTaskDeleteResult>(
    `${API_BASE}/tasks/training/${taskId}?mode=${mode}`,
    { method: 'DELETE' },
    'Failed to delete training task'
  )
}

/**
 * GPU task queue status
 */
export interface QueueStatus {
  max_concurrent: number
  running_count: number
  pending_count: number
  queue_size: number
  running_task_ids: string[]
  pending_task_ids: string[]
  is_running: boolean
}

/**
 * Queue and task configuration
 */
export interface QueueConfig {
  max_concurrent: number
  task_timeout: number
}

/**
 * Get GPU task queue status
 * @returns Queue status
 * @throws {ApiError} If the request fails
 */
export async function getQueueStatus(): Promise<QueueStatus> {
  return apiFetch<QueueStatus>(`${API_BASE}/queue`, undefined, 'Failed to get queue status')
}

/**
 * Get queue and task configuration
 * @returns Current configuration
 * @throws {ApiError} If the request fails
 */
export async function getQueueConfig(): Promise<QueueConfig> {
  return apiFetch<QueueConfig>(`${API_BASE}/queue/config`, undefined, 'Failed to get queue config')
}

/**
 * Update queue configuration
 * @param config - Configuration to update (max_concurrent and/or task_timeout)
 * @returns Updated configuration
 * @throws {ApiError} If the request fails
 */
export async function updateQueueConfig(config: {
  max_concurrent?: number
  task_timeout?: number
}): Promise<{ message: string; config: QueueConfig }> {
  return apiFetch<{ message: string; config: QueueConfig }>(
    `${API_BASE}/queue/config`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    },
    'Failed to update queue config'
  )
}

/**
 * Cancel queue task response
 */
export interface CancelQueueTaskResponse {
  cancelled: boolean
  message: string
}

/**
 * Cancel a task in the GPU queue
 * @param taskId - Task ID to cancel
 * @returns Cancel result
 * @throws {ApiError} If the request fails
 */
export async function cancelQueueTask(taskId: string): Promise<CancelQueueTaskResponse> {
  return apiFetch<CancelQueueTaskResponse>(
    `${API_BASE}/queue/${taskId}`,
    { method: 'DELETE' },
    'Failed to cancel task'
  )
}

/**
 * Training task configuration
 */
export interface SplitConfig {
  strategy: 'random' | 'k_fold' | 'manual'
  n_splits?: number // for k_fold
  ratios?: { train: number; val: number; test: number }
  manual_splits?: Record<string, string> // map wsi_id -> split
}

export interface TrainingTaskConfig {
  task_name: string
  task_type: 'classification' | 'survival_prediction' | 'segmentation'
  data_level: 'wsi' | 'patch'
  task_description: string
  wsi_ids: string[]
  preprocessing: {
    tile_size: number
    stride: number
    level?: number
    feature_extractor: string
    feature_batch_size: number
    use_gpu: boolean
    // Tissue segmentation parameters
    sthresh?: number
    mthresh?: number
    close?: number
    use_otsu?: boolean
    contour_fn?: string
    use_padding?: boolean
    // Filter parameters
    a_t?: number  // Area threshold for contours
    a_h?: number  // Hole area filter threshold
    max_n_holes?: number  // Maximum number of holes to keep
  }
  model: {
    aggregator: string
    backbone?: string  // For patch-level tasks
    learning_rate: number
    epochs: number
    optimizer: string
    batch_size: number
    auto_balance?: boolean  // Auto-balance class weights for imbalanced datasets
    early_stopping_patience?: number  // Number of epochs to wait before early stopping
  }
  split_config?: SplitConfig
}

/**
 * Create a custom training task
 * @param taskConfig - Training task configuration
 * @returns Task creation result with task_id
 * @throws {ApiError} If the request fails
 */
export async function createTrainingTask(taskConfig: TrainingTaskConfig): Promise<TrainingTaskCreateResult> {
  // Get HuggingFace token from localStorage for gated models
  const huggingfaceToken = localStorage.getItem('huggingface_token') || ''

  return apiFetch<TrainingTaskCreateResult>(
    `${API_BASE}/tasks/training`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...taskConfig,
        huggingface_token: huggingfaceToken
      })
    },
    'Failed to create training task'
  )
}

// ============================================================================
// Chat Conversation Management APIs
// ============================================================================

export interface Conversation {
  conversation_id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationWithMessages extends Conversation {
  messages: Array<{
    id: number
    conversation_id: string
    role: 'user' | 'assistant'
    content: string
    created_at: string
  }>
}

/**
 * Create a new conversation
 * User ID is automatically determined from JWT token.
 * @param title - Optional conversation title
 * @returns Created conversation
 * @throws {ApiError} If the request fails
 */
export async function createConversation(title?: string): Promise<Conversation> {
  return apiFetch<Conversation>(
    `${API_BASE}/conversations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: title || 'New Conversation'
      })
    },
    'Failed to create conversation'
  )
}

/**
 * Get all conversations for the current user.
 * User ID is automatically determined from JWT token.
 * @param skip - Number of conversations to skip
 * @param limit - Maximum number of conversations to return
 * @returns List of conversations
 * @throws {ApiError} If the request fails
 */
export async function getConversations(
  skip: number = 0,
  limit: number = 50
): Promise<Conversation[]> {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit)
  })

  const data = await apiFetch<PaginatedResponse<Conversation>>(
    `${API_BASE}/conversations?${params}`,
    undefined,
    'Failed to get conversations'
  )
  return data.items || []
}

/**
 * Get a conversation with all messages
 * @param conversationId - Conversation ID
 * @returns Conversation with messages
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function getConversation(conversationId: string): Promise<ConversationWithMessages> {
  return apiFetch<ConversationWithMessages>(
    `${API_BASE}/conversations/${conversationId}`,
    undefined,
    'Failed to get conversation'
  )
}

/**
 * Delete a conversation
 * @param conversationId - Conversation ID
 * @throws {ApiError} If the request fails
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  await apiFetch(
    `${API_BASE}/conversations/${conversationId}`,
    { method: 'DELETE' },
    'Failed to delete conversation'
  )
}

/**
 * Update a message's content
 * Used to persist task submission status in the message content
 * @param conversationId - Conversation ID
 * @param messageId - Message ID (number)
 * @param content - New message content
 * @returns Updated message
 * @throws {ApiError} If the request fails
 */
export async function updateMessage(
  conversationId: string,
  messageId: number,
  content: string
): Promise<{ id: number; conversation_id: string; role: string; content: string; created_at: string }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    },
    'Failed to update message'
  )
}

// ============================================================================
// Storage Management APIs
// ============================================================================

export interface StorageCleanupResult {
  deleted_files: string[]
  deleted_dirs: string[]
  failed: Array<[string, string]>
  total_size: number
  summary: string
}

export interface WSIStorageInfo {
  wsi_id: string
  wsi_file: {
    path: string
    size: number
    exists: boolean
  }
  coordinates: {
    path: string
    size: number
    exists: boolean
  }
  mask: {
    path: string
    size: number
    exists: boolean
  }
  ai_results: {
    path: string
    size: number
    exists: boolean
    file_count: number
  }
  features: Array<{
    path: string
    size: number
    task_id: string
  }>
  total_size: number
  total_size_mb: number
  total_size_gb: number
  total_files: number
}

export interface TrainingTaskStorageInfo {
  task_id: string
  training_dir: {
    path: string
    size: number
    exists: boolean
    file_count: number
  }
  training_logs: {
    path: string
    size: number
    exists: boolean
    file_count: number
  }
  analysis_logs: {
    path: string
    size: number
    exists: boolean
    file_count: number
  }
  models: Array<{
    path: string
    size: number
    file_count: number
  }>
  total_size: number
  total_size_mb: number
  total_size_gb: number
  total_files: number
}

export interface StorageStats {
  uploads_dir: string
  total_size: number
  total_size_mb: number
  total_size_gb: number
  breakdown: {
    [category: string]: {
      size: number
      file_count: number
    }
  }
  timestamp: string
  cached?: boolean  // True if result is from cache
}

/**
 * Disk space information
 */
export interface DiskSpaceInfo {
  uploads_dir: string
  total: number
  used: number
  free: number
  total_gb: number
  used_gb: number
  free_gb: number
  usage_percent: number
  warning: boolean
  critical: boolean
}

/**
 * Upload space check result
 */
export interface UploadSpaceCheck {
  can_upload: boolean
  required_bytes: number
  required_gb: number
  free_bytes: number
  free_gb: number
  remaining_after_upload_gb: number
  message: string
}

/**
 * Get disk space information for the uploads directory
 * @returns Disk space information including free space and warnings
 * @throws {ApiError} If the request fails
 */
export async function getDiskSpace(): Promise<DiskSpaceInfo> {
  return apiFetch<DiskSpaceInfo>(`${API_BASE}/storage/disk-space`, undefined, 'Failed to get disk space')
}

/**
 * Check if there is enough disk space for an upload
 * @param requiredBytes - Required space in bytes
 * @returns Upload space check result
 * @throws {ApiError} If the request fails
 */
export async function checkUploadSpace(requiredBytes: number): Promise<UploadSpaceCheck> {
  return apiFetch<UploadSpaceCheck>(
    `${API_BASE}/storage/check-upload-space?required_bytes=${requiredBytes}`,
    undefined,
    'Failed to check upload space'
  )
}

/**
 * Get overall storage statistics
 * @param refresh - Force refresh cache (bypass 60s cache TTL)
 * @returns Storage statistics with breakdown by category
 * @throws {ApiError} If the request fails
 */
export async function getStorageStats(refresh: boolean = false): Promise<StorageStats> {
  const url = refresh ? `${API_BASE}/storage/stats?refresh=true` : `${API_BASE}/storage/stats`
  return apiFetch<StorageStats>(url, undefined, 'Failed to get storage stats')
}

/**
 * Get storage information for a specific WSI
 * @param wsi_id - WSI ID
 * @returns Detailed storage information for the WSI
 * @throws {ApiError} If the request fails
 */
export async function getWSIStorageInfo(wsi_id: string): Promise<WSIStorageInfo> {
  return apiFetch<WSIStorageInfo>(
    `${API_BASE}/storage/wsi/${encodeURIComponent(wsi_id)}`,
    undefined,
    'Failed to get WSI storage info'
  )
}

/**
 * Get storage information for a specific training task
 * @param task_id - Training task ID
 * @returns Detailed storage information for the training task
 * @throws {ApiError} If the request fails
 */
export async function getTrainingTaskStorageInfo(task_id: string): Promise<TrainingTaskStorageInfo> {
  return apiFetch<TrainingTaskStorageInfo>(
    `${API_BASE}/storage/training/${encodeURIComponent(task_id)}`,
    undefined,
    'Failed to get training task storage info'
  )
}

// Orphaned files management
export interface OrphanedFile {
  path: string
  size: number
  wsi_id?: string
  task_id?: string
}

export interface OrphanedFilesInfo {
  orphaned_wsi_files: OrphanedFile[]
  orphaned_coordinates: OrphanedFile[]
  orphaned_masks: OrphanedFile[]
  orphaned_features_cache: OrphanedFile[]
  orphaned_ai_results: OrphanedFile[]
  orphaned_training_dirs: OrphanedFile[]
  orphaned_logs: OrphanedFile[]
  total_orphaned_size: number
  total_orphaned_count: number
  total_orphaned_size_mb: number
  total_orphaned_size_gb: number
}

/**
 * Detect orphaned files in storage
 * @returns Orphaned files information
 * @throws {ApiError} If the request fails
 */
export async function detectOrphanedFiles(): Promise<OrphanedFilesInfo> {
  return apiFetch<OrphanedFilesInfo>(`${API_BASE}/storage/orphaned`, undefined, 'Failed to detect orphaned files')
}

export interface CleanupResult {
  deleted_files: string[]
  deleted_dirs: string[]
  failed: [string, string][]
  total_size: number
  summary: string
}

/**
 * Cleanup orphaned files in storage
 * @param categories - Optional list of categories to cleanup
 * @returns Cleanup result
 * @throws {ApiError} If the request fails
 */
export async function cleanupOrphanedFiles(categories?: string[]): Promise<CleanupResult> {
  return apiFetch<CleanupResult>(
    `${API_BASE}/storage/orphaned/cleanup`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories })
    },
    'Failed to cleanup orphaned files'
  )
}

/**
 * Fetch available feature extractors
 * @returns List of available feature extractors
 * @throws {ApiError} If the request fails
 */
export async function fetchExtractors(): Promise<FeatureExtractor[]> {
  const data = await apiFetch<FeatureExtractorListResponse>(
    `${API_BASE}/tasks/extractors`,
    undefined,
    'Failed to fetch extractors'
  )
  return data.items
}

// ============================================================================
// Heatmap and Attention APIs
// ============================================================================

/**
 * Heatmap point with coordinates and attention weight
 */
export interface HeatmapPoint {
  index: number
  x: number
  y: number
  weight: number
  raw_weight: number
}

/**
 * Available heatmap info for a WSI
 */
export interface AvailableHeatmap {
  task_id: string | null
  task_type: string
  task_name: string
  prediction: string | null
  probs: Record<string, number> | null
  classes: string[] | null
  feature_extractor: string | null
  aggregator?: string | null  // MIL aggregator type (e.g., abmil, clam_sb, transmil)
  created_at: number
  attention_file: string
  data_level?: 'wsi' | 'patch'  // WSI-level attention or patch-level CAM
  cam_size?: [number, number]   // CAM size for patch-level
}

/**
 * Heatmap data response
 */
export interface HeatmapData {
  wsi_id: string
  task_id: string | null
  task_name: string | null
  patch_size: number
  slide_width: number
  slide_height: number
  num_patches: number
  attention_min: number
  attention_max: number
  prediction: string | null
  probs: Record<string, number> | null
  heatmap: HeatmapPoint[]
  top_patches: HeatmapPoint[]
  bottom_patches: HeatmapPoint[]
  // Multi-class attention info
  aggregator?: string | null
  attention_type?: 'none' | 'single' | 'multi_class'
  num_attention_classes?: number | null
  selected_class_idx?: number | null
  classes?: string[]
}

/**
 * Fetch available heatmaps (attention data) for a WSI
 * @param wsi_id - The WSI ID
 * @returns List of available heatmaps
 * @throws {ApiError} If the request fails
 */
export async function fetchAvailableHeatmaps(wsi_id: string): Promise<AvailableHeatmap[]> {
  const data = await apiFetch<{ heatmaps: AvailableHeatmap[] }>(
    `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/available`,
    undefined,
    'Failed to fetch available heatmaps'
  )
  return data.heatmaps || []
}

/**
 * Fetch heatmap data for a WSI
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @param patch_size - Patch size used during inference (default 512)
 * @returns Heatmap data with top/bottom patches
 * @throws {ApiError} If the request fails
 */
export async function fetchHeatmapData(
  wsi_id: string,
  task_id?: string,
  patch_size: number = 512
): Promise<HeatmapData> {
  const params = new URLSearchParams()
  params.set('patch_size', String(patch_size))
  if (task_id) {
    params.set('task_id', task_id)
  }
  const url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/data?${params.toString()}`
  return apiFetch<HeatmapData>(url, undefined, 'Failed to fetch heatmap data')
}

/**
 * Get patch image URL for a WSI at specific coordinates
 * @param wsi_id - The WSI ID
 * @param x - X coordinate
 * @param y - Y coordinate
 * @param size - Patch size (default 256)
 * @returns URL for the patch image (with auth token for <img> tags)
 */
export function getPatchImageUrl(wsi_id: string, x: number, y: number, size: number = 256): string {
  const token = getAuthToken()
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_image?x=${x}&y=${y}&size=${size}`
  if (token) {
    url += `&token=${encodeURIComponent(token)}`
  }
  return url
}

/**
 * Patch CAM data response (for patch classification tasks)
 */
export interface PatchCAMData {
  wsi_id: string
  task_id: string | null
  prediction: string | null
  probs: Record<string, number> | null
  classes: string[] | null
  cam_size: [number, number]
  cam_min: number
  cam_max: number
  cam_data: number[][] // 2D array of CAM values
}

/**
 * Get patch CAM overlay image URL
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @returns URL for the CAM overlay PNG image (with auth token for <img> tags)
 */
export function getPatchCAMImageUrl(wsi_id: string, task_id?: string): string {
  const token = getAuthToken()
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=image`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  if (token) {
    url += `&token=${encodeURIComponent(token)}`
  }
  return url
}

/**
 * Fetch patch CAM data as JSON
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @returns Patch CAM data
 * @throws {ApiError} If the request fails
 */
export async function fetchPatchCAMData(wsi_id: string, task_id?: string): Promise<PatchCAMData> {
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=json`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  return apiFetch<PatchCAMData>(url, undefined, 'Failed to fetch patch CAM data')
}

/**
 * Get patch image URL for a simple patch file (not WSI)
 * This endpoint returns the entire patch image for patch classification tasks
 * @param wsi_id - The patch ID
 * @returns URL for the patch image (with auth token for <img> tags)
 */
export function getPatchFileImageUrl(wsi_id: string): string {
  const token = getAuthToken()
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/image`
  if (token) {
    url += `?token=${encodeURIComponent(token)}`
  }
  return url
}

/**
 * Get thumbnail image URL for a WSI or patch
 * @param wsi_id - The WSI/patch ID
 * @param size - Max thumbnail size (default 256)
 * @returns URL for the thumbnail image with auth token
 */
export function getThumbnailUrl(wsi_id: string, size: number = 256): string {
  const token = getAuthToken()
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/thumbnail?size=${size}`
  if (token) {
    url += `&token=${encodeURIComponent(token)}`
  }
  return url
}

/**
 * Determine if a file is a WSI or Patch based on path and file size
 * @param wsiPath - The file path
 * @param fileSize - The file size in bytes
 * @returns 'WSI' or 'Patch'
 */
export function getFileType(wsiPath: string | null, fileSize: number | null): 'WSI' | 'Patch' {
  if (!wsiPath) return 'WSI'
  const path = wsiPath.toLowerCase()

  // Patch/image file extensions
  const patchExtensions = ['.png', '.jpg', '.jpeg', '.bmp']

  // Check if it's a patch image format
  if (patchExtensions.some(ext => path.endsWith(ext))) {
    return 'Patch'
  }

  // For .tif/.tiff files, check file size (100 MB threshold)
  if (path.endsWith('.tif') || path.endsWith('.tiff')) {
    const SIZE_THRESHOLD = 100 * 1024 * 1024 // 100 MB
    return (fileSize || 0) >= SIZE_THRESHOLD ? 'WSI' : 'Patch'
  }

  return 'WSI'
}

// ============================================================================
// ASR (Automatic Speech Recognition) APIs
// ============================================================================

export interface TranscribeResponse {
  text: string
  success: boolean
  error?: string
}

/**
 * Transcribe audio using DashScope Qwen3-ASR API
 * @param audioBlob - Audio blob (PCM 16kHz mono)
 * @returns Transcription result
 * @throws {ApiError} If the request fails
 */
export async function transcribeAudio(audioBlob: Blob): Promise<TranscribeResponse> {
  const dashscopeApiKey = localStorage.getItem('dashscope_api_key') || ''

  // Convert blob to base64
  const arrayBuffer = await audioBlob.arrayBuffer()
  const base64Audio = btoa(new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), ''))

  return apiFetch<TranscribeResponse>(
    `${API_BASE}/asr/transcribe`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-DashScope-API-Key': dashscopeApiKey
      },
      body: JSON.stringify({
        audio: base64Audio,
        language: 'zh'
      })
    },
    'ASR request failed'
  )
}

// ========== Global Settings API ==========

/**
 * Global settings interface
 */
export interface GlobalSettings {
  openrouter_api_key: string
  openrouter_base_url: string
  openrouter_model: string
  huggingface_token: string
  dashscope_api_key: string
}

/**
 * Get global settings
 * @returns Global settings
 * @throws {ApiError} If the request fails
 */
export async function getGlobalSettings(): Promise<GlobalSettings> {
  return apiFetch<GlobalSettings>(
    `${API_BASE}/settings`,
    undefined,
    'Failed to get global settings'
  )
}

/**
 * Update global settings (admin only)
 * @param settings - Settings to update (only provided fields will be updated)
 * @returns Updated global settings
 * @throws {ApiError} If the request fails
 */
export async function updateGlobalSettings(
  settings: Partial<GlobalSettings>
): Promise<GlobalSettings> {
  return apiFetch<GlobalSettings>(
    `${API_BASE}/settings`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    },
    'Failed to update global settings'
  )
}