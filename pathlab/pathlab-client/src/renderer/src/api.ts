import { API_BASE } from './config'
import { createCache, createKeyedCache, createPersistentCache, DEFAULT_CACHE_TTL, LONG_CACHE_TTL, ACTIVITY_CACHE_TTL, PERSISTENT_CACHE_TTL } from './lib/cache'

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
  avatar_url?: string
  role: 'admin' | 'pathologist' | 'guest'
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  agreement_accepted_at?: string | null
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

export interface UserUpdateRequest {
  nickname?: string
  role?: 'admin' | 'pathologist' | 'guest'
  password?: string
  is_active?: boolean
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
  // Permission flag - whether user can delete this WSI
  can_delete?: boolean
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
 * Note: patch_size is auto-determined by PrePATH-style tiling based on WSI magnification
 */
export interface ComputePatchesResponse {
  wsi_id: string
  num_patches: number
  level: number
  coords_file: string
  cached: boolean
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
  dataTaskId: string,
  metrics?: string[],
  charts?: string[],
  computeBootstrapCI?: boolean
): Promise<InferenceTaskResponse> {
  return apiFetch<InferenceTaskResponse>(
    `${API_BASE}/results/external-validation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        data_task_id: dataTaskId,
        metrics: metrics,
        charts: charts,
        compute_bootstrap_ci: computeBootstrapCI
      })
    },
    'Failed to start external validation'
  )
}

/**
 * Analysis request parameters
 */
export interface AnalysisRequest {
  metrics: string[]
  charts: string[]
  description?: string
  bootstrap_ci_metrics?: string[]  // List of metrics to compute 95% CI for (e.g., ["accuracy", "auc"])
}

/**
 * Analysis response
 */
export interface AnalysisResponse {
  task_id: string
  analysis_id: string
  summary: Record<string, unknown>
  chart_paths: string[]
}

/**
 * Run analysis on a training task (internal analysis on test set)
 * @param taskId - Training task ID to analyze
 * @param metrics - List of metrics to calculate (e.g., ["accuracy", "precision", "sensitivity", "f1", "auc", "specificity"])
 * @param charts - List of charts to generate (e.g., ["confusion_matrix", "roc_curve", "loss_curve"])
 * @param description - Optional description for the analysis
 * @param bootstrapCIMetrics - List of metrics to compute 95% CI for (e.g., ["accuracy", "auc"])
 * @returns Analysis response with summary and chart paths
 * @throws {ApiError} If the request fails
 */
export async function runTaskAnalysis(
  taskId: string,
  metrics: string[],
  charts: string[],
  description?: string,
  bootstrapCIMetrics?: string[]
): Promise<AnalysisResponse> {
  return apiFetch<AnalysisResponse>(
    `${API_BASE}/results/tasks/${taskId}/analysis`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        metrics,
        charts,
        description,
        bootstrap_ci_metrics: bootstrapCIMetrics
      })
    },
    'Failed to run analysis'
  )
}

/**
 * Bootstrap confidence interval for a metric
 */
export interface BootstrapCI {
  lower: number
  upper: number
  n_samples: number
}

/**
 * Bootstrap CI result structure
 */
export interface BootstrapCIResult {
  metrics_ci: Record<string, BootstrapCI | null>
  class_metrics_ci: Record<string, Record<string, BootstrapCI | null>>
  n_bootstrap: number
  confidence_level: number
}

/**
 * Quick analysis response - contains filtered metrics and chart data
 */
export interface QuickAnalysisResponse {
  task_id: string
  analysis_id?: string
  has_analysis: boolean
  message?: string
  timestamp?: string
  task_type?: string
  num_samples?: number
  classes?: string[]
  is_binary?: boolean
  metrics?: Record<string, number>
  class_metrics?: Record<string, Record<string, number>>
  bootstrap_ci?: BootstrapCIResult  // Bootstrap 95% confidence intervals if computed
  chart_data?: {
    confusion_matrix?: {
      classes: string[]
      data: [number, number, number][]
    }
    roc_curve?: {
      classes: string[]
      data: Record<string, { fpr: number[]; tpr: number[]; auc: number }>
    }
    loss_curve?: {
      epochs: number[]
      loss: number[]
      val_loss?: number[]
    }
    km_curve?: {
      high_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
      low_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
      cutoff: number
    }
  }
  chart_urls?: Record<string, string>
  // Async analysis fields (when analysis is pending/running)
  status?: 'pending' | 'running' | 'completed' | 'failed'
  progress?: number
  // K-Fold training details (if available)
  kfold_training?: {
    is_kfold: boolean
    num_folds: number
    folds: Record<string, {
      history?: Record<string, number[]>
      val_metrics?: Record<string, number>
    }>
    aggregated: Record<string, { mean: number; std: number }>
  }
}

/**
 * Analysis status response - for polling async analysis progress
 */
export interface AnalysisStatusResponse {
  analysis_id: string
  task_id?: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  error_message?: string
  message?: string
  created_at?: string
  started_at?: string
  finished_at?: string
}

/**
 * Get quick analysis results for a task.
 * If analysis exists, returns the most recent. If not, optionally runs analysis first.
 *
 * @param taskId - Training task ID
 * @param options - Optional filtering options
 * @returns Quick analysis response with metrics and chart data
 * @throws {ApiError} If the request fails
 */
export async function getTaskQuickAnalysis(
  taskId: string,
  options?: {
    metrics?: string[]   // Filter to specific metrics (e.g., ['accuracy', 'auc', 'f1'])
    charts?: string[]    // Filter to specific charts (e.g., ['roc_curve', 'confusion_matrix'])
    runIfMissing?: boolean  // Run analysis if not available (default: true)
    bootstrapCIMetrics?: string[]  // List of metrics to compute 95% CI for (e.g., ['accuracy', 'auc'])
  }
): Promise<QuickAnalysisResponse> {
  const params = new URLSearchParams()

  if (options?.metrics && options.metrics.length > 0) {
    params.set('metrics', options.metrics.join(','))
  }
  if (options?.charts && options.charts.length > 0) {
    params.set('charts', options.charts.join(','))
  }
  if (options?.runIfMissing !== undefined) {
    params.set('run_if_missing', String(options.runIfMissing))
  }
  if (options?.bootstrapCIMetrics && options.bootstrapCIMetrics.length > 0) {
    params.set('bootstrap_ci_metrics', options.bootstrapCIMetrics.join(','))
  }

  const queryString = params.toString()
  const url = `${API_BASE}/results/tasks/${taskId}/quick-analysis${queryString ? `?${queryString}` : ''}`

  return apiFetch<QuickAnalysisResponse>(url, undefined, 'Failed to get quick analysis')
}

/**
 * Get analysis task status for polling async analysis progress.
 *
 * @param analysisId - Analysis ID returned when analysis was submitted
 * @returns Analysis status including progress and error information
 * @throws {ApiError} If the request fails
 */
export async function getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse> {
  const url = `${API_BASE}/results/analysis/${analysisId}/status`
  return apiFetch<AnalysisStatusResponse>(url, undefined, 'Failed to get analysis status')
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

// Cache for fetchWSIList (keyed by datasetId + dataLevel)
const wsiListCache = createKeyedCache<WSIListResponse>(DEFAULT_CACHE_TTL)

/**
 * Fetch WSI list from database via Gateway API (with caching)
 * @param datasetId - Optional dataset UUID to filter by
 * @param dataLevel - Optional filter: "wsi" for WSI files, "patch" for image files
 * @throws {ApiError} If the request fails
 */
export async function fetchWSIList(datasetId?: string, dataLevel?: string): Promise<WSIListResponse> {
  const cacheKey = `${datasetId || '__all__'}:${dataLevel || '__all__'}`

  // Build URL manually to avoid issues with new URL() constructor
  const params = new URLSearchParams()
  if (datasetId) {
    params.set('dataset_id', datasetId)
  }
  if (dataLevel) {
    params.set('data_level', dataLevel)
  }
  const queryString = params.toString()
  const url = queryString ? `${API_BASE}/wsi?${queryString}` : `${API_BASE}/wsi`

  return wsiListCache.get(cacheKey, () =>
    apiFetch<WSIListResponse>(url, undefined, 'Failed to load WSI list from database')
  )
}

/**
 * Invalidate the WSI list cache (call after mutations like upload/delete)
 */
export function invalidateWSIListCache(): void {
  wsiListCache.invalidateAll()
}

/**
 * Dataset summary returned from list datasets endpoint
 */
export interface DatasetSummary {
  dataset_id: string | null  // UUID for API calls (null for uncategorized)
  dataset_name: string  // Display name
  user_id: string | null  // Dataset owner
  file_count: number
  total_size: number
  data_type: 'wsi' | 'patch'  // Data type: WSI collection or Patch collection
  dataset_type: 'classification' | 'survival' // Task type: classification or survival
  data_level: 'case' | 'file'  // Aggregation level: case-level or file-level dataset
  // Permission flag - whether user can delete this dataset
  can_delete?: boolean
  // Pre-defined split information (from CSV upload)
  has_predefined_splits?: boolean
  predefined_split_counts?: { train: number; val: number; test: number }
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
 * Response from update dataset type API
 */
export interface UpdateDatasetTypeResponse {
  message: string
  dataset_id: string
  new_type: 'classification' | 'survival'
  updated_count: number
}

/**
 * Update dataset type (classification or survival)
 * This modifies the event_time/event_status fields of all WSIs in the dataset.
 * @param datasetId - Dataset UUID
 * @param datasetType - New type: "classification" or "survival"
 * @throws {ApiError} If the request fails
 */
export async function updateDatasetType(
  datasetId: string,
  datasetType: 'classification' | 'survival'
): Promise<UpdateDatasetTypeResponse> {
  return apiFetch<UpdateDatasetTypeResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/type`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_type: datasetType })
    },
    'Failed to update dataset type'
  )
}

/**
 * Response from update dataset data level API
 */
export interface UpdateDatasetDataLevelResponse {
  message: string
  dataset_id: string
  new_data_level: 'case' | 'file'
}

/**
 * Update dataset data level (case-level or file-level)
 * @param datasetId - Dataset UUID
 * @param dataLevel - New data level: "case" or "file"
 * @throws {ApiError} If the request fails
 */
export async function updateDatasetDataLevel(
  datasetId: string,
  dataLevel: 'case' | 'file'
): Promise<UpdateDatasetDataLevelResponse> {
  return apiFetch<UpdateDatasetDataLevelResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/data-level`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_level: dataLevel })
    },
    'Failed to update dataset data level'
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
 * Note: patch_size and stride are auto-determined by backend based on WSI magnification
 * Uses settings from localStorage if not provided
 * @throws {ApiError} If the request fails
 */
export async function computePatches(
  wsi_id: string,
  options?: {
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
  // Get settings from localStorage (patch_size and stride removed - auto-determined by PrePATH-style)
  const level = options?.level ?? parseInt(localStorage.getItem('patch_level') || '0')
  const sthresh = options?.sthresh ?? parseInt(localStorage.getItem('seg_sthresh') || '5')
  const mthresh = options?.mthresh ?? parseInt(localStorage.getItem('seg_mthresh') || '7')
  const close = options?.close ?? parseInt(localStorage.getItem('seg_close') || '4')
  const use_otsu = options?.use_otsu ?? localStorage.getItem('seg_use_otsu') === 'true'
  const contour_fn = options?.contour_fn ?? (localStorage.getItem('seg_contour_fn') || 'four_pt')
  const force_recompute = options?.force_recompute ?? false

  // Build query parameters (patch_size and stride removed - auto-determined by PrePATH-style)
  const params = new URLSearchParams({
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

// Cache for fetchAllResults
const allResultsCache = createCache<AllResultsResponse>(DEFAULT_CACHE_TTL)

/**
 * Fetch all AI results with WSI info (with caching)
 * @returns List of results with predictions and WSI metadata
 * @throws {ApiError} If the request fails
 */
export async function fetchAllResults(): Promise<AllResultsResponse> {
  return allResultsCache.get(() =>
    apiFetch<AllResultsResponse>(`${API_BASE}/results`, undefined, 'Failed to load results')
  )
}

/**
 * Invalidate the results cache (call after mutations)
 */
export function invalidateResultsCache(): void {
  allResultsCache.invalidate()
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

  // Invalidate caches after deletion
  invalidateResultsCache()
  invalidateHeatmapAvailabilityCache(wsi_id)

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
    data_level?: 'case' | 'file'  // Aggregation level for new dataset
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
  if (options?.data_level) {
    formData.append('data_level', options.data_level)
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
          // Invalidate WSI list cache after successful upload
          invalidateWSIListCache()
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
    data_level?: 'case' | 'file'  // Aggregation level for new dataset
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
  const result = await apiFetch<WSIUploadResult>(
    `${API_BASE}/wsi/upload/path`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wsi_path,
        dataset_id: options?.dataset_id,
        dataset_name: options?.dataset_name,
        data_level: options?.data_level,
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
  // Invalidate WSI list cache after successful upload
  invalidateWSIListCache()
  return result
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
  const result = await apiFetch<WSIDeleteResult>(
    `${API_BASE}/wsi/${wsi_id}?mode=${mode}`,
    { method: 'DELETE' },
    'Failed to delete WSI'
  )
  // Invalidate caches after deletion
  invalidateWSIListCache()
  invalidateHeatmapAvailabilityCache(wsi_id)
  return result
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

  const result = await apiFetch<BatchUploadResult>(
    `${API_BASE}/wsi/upload/csv`,
    { method: 'POST', body: formData },
    'Failed to upload CSV'
  )
  // Invalidate WSI list cache after batch upload
  invalidateWSIListCache()
  return result
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
 * Recent upload item (WSI slide)
 */
export interface RecentUpload {
  wsi_id: string
  original_filename: string | null
  dataset_id: string | null
  dataset_name: string | null
  label: string | null
  created_at: string | null
}

/**
 * Recent task item (AI inference or training task)
 */
export interface RecentTask {
  task_id: string
  task_name?: string  // For training tasks
  task_type: string
  task_category: 'inference' | 'training'
  status: string
  progress: number
  created_at: string | null
}

/**
 * Recent activity response
 */
export interface RecentActivityResponse {
  recent_uploads: RecentUpload[]
  recent_tasks: RecentTask[]
}

// Cache for fetchRecentActivity (5 minutes TTL)
const recentActivityCache = createCache<RecentActivityResponse>(ACTIVITY_CACHE_TTL)

/**
 * Fetch recent activity from Gateway.
 * Returns recent uploads and recent tasks for the current user.
 * Uses caching to prevent repeated API calls.
 * @param uploadLimit - Number of recent uploads to fetch
 * @param taskLimit - Number of recent tasks to fetch
 * @param forceRefresh - If true, bypass cache and fetch fresh data
 * @throws {ApiError} If the request fails
 */
export async function fetchRecentActivity(
  uploadLimit: number = 5,
  taskLimit: number = 5,
  forceRefresh: boolean = false
): Promise<RecentActivityResponse> {
  const params = new URLSearchParams({
    upload_limit: uploadLimit.toString(),
    task_limit: taskLimit.toString()
  })

  return recentActivityCache.get(
    () => apiFetch<RecentActivityResponse>(
      `${API_BASE}/stats/recent-activity?${params.toString()}`,
      undefined,
      'Failed to get recent activity'
    ),
    forceRefresh
  )
}

/**
 * Invalidate the recent activity cache (call after mutations like new uploads or tasks)
 */
export function invalidateRecentActivityCache(): void {
  recentActivityCache.invalidate()
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
  conversationId?: string,
  onMessageId?: (messageId: number) => void
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
            // Handle message_id event for persistence
            if (parsed.message_id && onMessageId) {
              onMessageId(parsed.message_id)
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
  seed?: number // Random seed for reproducibility (also serves as invisible watermark)
}

export interface TrainingTaskConfig {
  task_name: string
  task_type: 'classification' | 'survival_prediction' | 'segmentation'
  data_level: 'wsi' | 'patch'
  task_description: string
  wsi_ids: string[]
  preprocessing: {
    // Note: tile_size removed - auto-determined by PrePATH-style tiling based on WSI magnification
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

/**
 * Delete a message and all subsequent messages in a conversation
 * Used for conversation branching - allows users to delete from a point and restart
 * @param conversationId - Conversation ID
 * @param messageId - Message ID (number) from which to delete (inclusive)
 * @returns Delete result with count of deleted messages
 * @throws {ApiError} If the request fails
 */
export async function deleteMessagesFrom(
  conversationId: string,
  messageId: number
): Promise<{ message: string; deleted_count: number }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}`,
    { method: 'DELETE' },
    'Failed to delete messages'
  )
}

/**
 * Add a message to a conversation
 * Used to persist task submission success messages
 * @param conversationId - Conversation ID
 * @param role - Message role ("user" or "assistant")
 * @param content - Message content
 * @returns Created message
 * @throws {ApiError} If the request fails
 */
export async function addMessage(
  conversationId: string,
  role: 'user' | 'assistant',
  content: string
): Promise<{ id: number; conversation_id: string; role: string; content: string; created_at: string }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, content })
    },
    'Failed to add message'
  )
}

// ============================================================================
// Message Feedback APIs
// ============================================================================

/**
 * Context message for feedback (previous message for context)
 */
export interface FeedbackContextMessage {
  role: 'user' | 'assistant'
  content: string
}

/**
 * Feedback data for a message
 */
export interface MessageFeedback {
  id: number
  message_id: number
  user_id: string
  username: string | null  // Display name (nickname or email) from User table
  feedback_type: 'thumbs_up' | 'thumbs_down' | null
  task_helpfulness: 'helpful' | 'not_helpful' | null
  related_task_id: string | null
  time_to_action_seconds: number | null
  message_content: string | null
  context_messages: FeedbackContextMessage[] | null
  task_type: 'training' | 'inference' | 'analysis' | null
  task_title: string | null
  created_at: string
  updated_at: string
}

/**
 * Submit or update feedback for a message
 * @param messageId - Message ID (number)
 * @param feedbackType - 'thumbs_up', 'thumbs_down', or null
 * @param taskHelpfulness - 'helpful', 'not_helpful', or null
 * @param relatedTaskId - Optional task ID for task helpfulness feedback
 * @param timeToActionSeconds - Time from user message to task submission
 * @param messageContent - The rated message content (preserved for admin review)
 * @param contextMessages - Previous message(s) for context
 * @param taskType - Task type: 'training', 'inference', 'analysis'
 * @param taskTitle - Task name/title
 * @returns Created or updated feedback
 * @throws {ApiError} If the request fails
 */
export async function submitMessageFeedback(
  messageId: number,
  feedbackType?: 'thumbs_up' | 'thumbs_down' | null,
  taskHelpfulness?: 'helpful' | 'not_helpful' | null,
  relatedTaskId?: string | null,
  timeToActionSeconds?: number | null,
  messageContent?: string | null,
  contextMessages?: FeedbackContextMessage[] | null,
  taskType?: 'training' | 'inference' | 'analysis' | null,
  taskTitle?: string | null
): Promise<MessageFeedback> {
  return apiFetch(
    `${API_BASE}/messages/${messageId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_type: feedbackType,
        task_helpfulness: taskHelpfulness,
        related_task_id: relatedTaskId,
        time_to_action_seconds: timeToActionSeconds,
        message_content: messageContent,
        context_messages: contextMessages,
        task_type: taskType,
        task_title: taskTitle
      })
    },
    'Failed to submit feedback'
  )
}

/**
 * Get feedback for a specific message
 * @param messageId - Message ID (number)
 * @returns Feedback data or null if not found
 * @throws {ApiError} If the request fails
 */
export async function getMessageFeedback(
  messageId: number
): Promise<MessageFeedback | null> {
  const result = await apiFetch<{ message_id: number; feedback: null } | MessageFeedback>(
    `${API_BASE}/messages/${messageId}/feedback`,
    undefined,
    'Failed to get feedback'
  )
  // API returns { message_id, feedback: null } if no feedback exists
  if ('feedback' in result && result.feedback === null) {
    return null
  }
  return result as MessageFeedback
}

/**
 * Delete feedback for a message
 * @param messageId - Message ID (number)
 * @throws {ApiError} If the request fails
 */
export async function deleteMessageFeedback(messageId: number): Promise<void> {
  await apiFetch(
    `${API_BASE}/messages/${messageId}/feedback`,
    { method: 'DELETE' },
    'Failed to delete feedback'
  )
}

/**
 * Get all feedbacks for messages in a conversation
 * @param conversationId - Conversation ID
 * @returns Array of feedbacks
 * @throws {ApiError} If the request fails
 */
export async function getConversationFeedbacks(
  conversationId: string
): Promise<MessageFeedback[]> {
  const result = await apiFetch<{ feedbacks: MessageFeedback[] }>(
    `${API_BASE}/conversations/${conversationId}/feedbacks`,
    undefined,
    'Failed to get conversation feedbacks'
  )
  return result.feedbacks
}

// ============================================================================
// Admin Feedback Management APIs
// ============================================================================

/**
 * Feedback statistics from admin endpoint
 */
export interface FeedbackStats {
  total_feedbacks: number
  thumbs_up_count: number
  thumbs_down_count: number
  helpful_count: number
  not_helpful_count: number
  unique_users: number
  avg_time_to_action_seconds: number | null
}

/**
 * Paginated feedback list response from admin endpoint
 */
export interface AdminFeedbackListResponse {
  feedbacks: MessageFeedback[]
  total: number
  skip: number
  limit: number
}

/**
 * Get all feedbacks with pagination and filtering (admin only)
 * @param skip - Number of records to skip
 * @param limit - Maximum number of records to return
 * @param feedbackType - Filter by feedback type ('thumbs_up' or 'thumbs_down')
 * @param helpfulness - Filter by helpfulness ('helpful' or 'not_helpful')
 * @param userId - Filter by user ID
 * @returns Paginated feedback list
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getAdminFeedbacks(
  skip: number = 0,
  limit: number = 50,
  feedbackType?: 'thumbs_up' | 'thumbs_down' | null,
  helpfulness?: 'helpful' | 'not_helpful' | null,
  userId?: string | null
): Promise<AdminFeedbackListResponse> {
  const params = new URLSearchParams()
  params.append('skip', skip.toString())
  params.append('limit', limit.toString())
  if (feedbackType) params.append('feedback_type', feedbackType)
  if (helpfulness) params.append('helpfulness', helpfulness)
  if (userId) params.append('user_id', userId)

  return apiFetch(
    `${API_BASE}/admin/feedbacks?${params.toString()}`,
    undefined,
    'Failed to get feedbacks'
  )
}

/**
 * Get feedback statistics (admin only)
 * @returns Feedback statistics
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getFeedbackStats(): Promise<FeedbackStats> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/stats`,
    undefined,
    'Failed to get feedback statistics'
  )
}

/**
 * Export all feedbacks (admin only)
 * @param format - Export format ('json' or 'csv')
 * @returns For JSON: Object with feedbacks array. For CSV: Blob with CSV content.
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function exportFeedbacks(
  format: 'json' | 'csv' = 'json'
): Promise<{ feedbacks: MessageFeedback[] } | Blob> {
  const token = await getAuthToken()

  const response = await fetch(`${API_BASE}/admin/feedbacks/export?format=${format}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!response.ok) {
    throw new ApiError('Failed to export feedbacks', response.status)
  }

  if (format === 'csv') {
    return response.blob()
  } else {
    return response.json()
  }
}

/**
 * Reset (delete) all feedbacks (admin only)
 * @returns Object with deleted count
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function resetAllFeedbacks(): Promise<{ message: string; deleted_count: number }> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/reset`,
    { method: 'DELETE' },
    'Failed to reset feedbacks'
  )
}

// ============================================================================
// Async Export APIs (for large datasets)
// ============================================================================

/**
 * Export task status from async export endpoint
 */
export interface ExportTaskStatus {
  task_id: string
  user_id: string
  export_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  error_message: string | null
  file_format: string | null
  total_records: number | null
  filter_params: {
    date_from?: string | null
    date_to?: string | null
    feedback_type?: string | null
    helpfulness?: string | null
  } | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

/**
 * Start async export of feedbacks (admin only)
 * Use this for large datasets to avoid blocking
 * @param format - Export format ('json' or 'csv')
 * @param dateFrom - Optional start date filter (ISO string)
 * @param dateTo - Optional end date filter (ISO string)
 * @param feedbackType - Optional feedback type filter
 * @param helpfulness - Optional helpfulness filter
 * @returns Task ID for polling status
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function startAsyncExport(
  format: 'json' | 'csv' = 'json',
  dateFrom?: string | null,
  dateTo?: string | null,
  feedbackType?: string | null,
  helpfulness?: string | null
): Promise<{ task_id: string; status: string }> {
  const params = new URLSearchParams()
  params.set('format', format)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (feedbackType) params.set('feedback_type', feedbackType)
  if (helpfulness) params.set('helpfulness', helpfulness)

  return apiFetch(
    `${API_BASE}/admin/feedbacks/export-async?${params.toString()}`,
    { method: 'POST' },
    'Failed to start async export'
  )
}

/**
 * Get async export task status (admin only)
 * @param taskId - Export task ID
 * @returns Task status with progress
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getExportTaskStatus(taskId: string): Promise<ExportTaskStatus> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/export-async/${taskId}`,
    undefined,
    'Failed to get export status'
  )
}

/**
 * Download async export file (admin only)
 * @param taskId - Export task ID
 * @returns Blob with file content
 * @throws {ApiError} If the request fails or export not ready
 */
export async function downloadExportFile(taskId: string): Promise<Blob> {
  const token = await getAuthToken()

  const response = await fetch(`${API_BASE}/admin/feedbacks/export-async/${taskId}/download`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!response.ok) {
    throw new ApiError('Failed to download export file', response.status)
  }

  return response.blob()
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
  stale?: boolean   // True if cache is stale (background refresh triggered)
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
  total_orphaned_file_count: number
  total_orphaned_dir_count: number
  total_orphaned_size_mb: number
  total_orphaned_size_gb: number
  cached?: boolean  // True if result is from cache
  stale?: boolean   // True if data is stale and being refreshed in background
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

// Orphaned Records (database records with missing references) - Admin only

export interface OrphanedAITask {
  task_id: string
  wsi_id: string
  status: string
}

export interface OrphanedAIResult {
  id: number
  wsi_id: string
  task_id: string
}

export interface OrphanedTrainingTaskWSI {
  id: number
  task_id: string
  wsi_id: string
}

export interface OrphanedTrainingLog {
  id: number
  task_id: string
  level: string
}

export interface OrphanedTrainedModel {
  model_id: string
  task_id: string
  model_name: string
}

export interface OrphanedMessageFeedback {
  id: number
  message_id: number
  feedback_type: string
}

export interface OrphanedDatasetPermission {
  id: number
  dataset_id: string
  user_id: string
}

export interface OrphanedRecordsInfo {
  orphaned_ai_tasks: OrphanedAITask[]
  orphaned_ai_results: OrphanedAIResult[]
  orphaned_training_task_wsi: OrphanedTrainingTaskWSI[]
  orphaned_training_logs: OrphanedTrainingLog[]
  orphaned_trained_models: OrphanedTrainedModel[]
  orphaned_message_feedbacks: OrphanedMessageFeedback[]
  orphaned_dataset_permissions: OrphanedDatasetPermission[]
  total_orphaned_count: number
  summary: Record<string, number>
}

/**
 * Detect orphaned database records (records with missing referenced entities)
 * @returns Orphaned records information
 * @throws {ApiError} If the request fails
 */
export async function detectOrphanedRecords(): Promise<OrphanedRecordsInfo> {
  return apiFetch<OrphanedRecordsInfo>(`${API_BASE}/storage/orphaned-records`, undefined, 'Failed to detect orphaned records')
}

export interface OrphanedRecordsCleanupResult {
  deleted_counts: Record<string, number>
  total_deleted: number
  summary: string
}

/**
 * Cleanup orphaned database records
 * @param categories - Optional list of categories to cleanup
 * @returns Cleanup result
 * @throws {ApiError} If the request fails
 */
export async function cleanupOrphanedRecords(categories?: string[]): Promise<OrphanedRecordsCleanupResult> {
  return apiFetch<OrphanedRecordsCleanupResult>(
    `${API_BASE}/storage/orphaned-records/cleanup`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories })
    },
    'Failed to cleanup orphaned records'
  )
}

// Batch scan and register APIs (Admin only)

export interface ScannedWSIFile {
  path: string
  filename: string
  size: number
  extension: string
  format_type: 'standard' | 'mrxs' | 'tmap'
  data_type: 'wsi' | 'patch'  // File type: WSI or patch image
  valid: boolean
  validation_message: string | null
  associated_data?: string | string[] | null
}

export interface ScanDirectoryResponse {
  directory: string
  files: ScannedWSIFile[]
  total_count: number
  valid_count: number
  total_size: number
}

/**
 * Scan a directory for WSI files (Admin only)
 * @param directoryPath - Path to the directory to scan
 * @returns Scanned files with validation info
 * @throws {ApiError} If the request fails
 */
export async function scanDirectory(directoryPath: string): Promise<ScanDirectoryResponse> {
  return apiFetch<ScanDirectoryResponse>(
    `${API_BASE}/storage/scan-directory`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ directory_path: directoryPath })
    },
    'Failed to scan directory'
  )
}

export interface BatchRegisterFileInfo {
  path: string
  format_type: 'standard' | 'mrxs' | 'tmap'
  associated_data?: string | string[] | null  // string for mrxs (data folder), string[] for tmap (DT files)
}

export interface BatchRegisterRequest {
  files: BatchRegisterFileInfo[]
  dataset_id?: string
  dataset_name?: string
  data_level?: 'case' | 'file'  // Default: 'file' - how to organize data
  task_type?: 'classification' | 'survival'  // Default: 'classification'
  default_label?: string  // For classification (default: 'External Import')
  default_event_time?: number  // For survival
  default_event_status?: number  // For survival (1 = event occurred, 0 = censored)
}

/**
 * External file info returned from check-external-files endpoint
 */
export interface ExternalFileInfo {
  wsi_id: string
  original_filename: string
  wsi_path: string
  dataset_id: string | null
  dataset_name: string | null
  label: string | null
  status: 'available' | 'unavailable'
}

/**
 * Response from check-external-files endpoint
 */
export interface CheckExternalFilesResponse {
  total_external: number
  available_count: number
  unavailable_count: number
  available: ExternalFileInfo[]
  unavailable: ExternalFileInfo[]
}

/**
 * External dataset info returned from get-external-datasets endpoint
 */
export interface ExternalDatasetInfo {
  dataset_id: string | null
  dataset_name: string
  total_files: number
  available_files: number
  unavailable_files: number
}

/**
 * Response from get-external-datasets endpoint
 */
export interface ExternalDatasetsResponse {
  datasets: ExternalDatasetInfo[]
  total: number
}

/**
 * Response from delete-unavailable-files endpoint
 */
export interface DeleteUnavailableFilesResponse {
  deleted: number
  failed: number
  results: Array<{
    wsi_id: string
    status: 'deleted' | 'failed'
    message: string
  }>
}

/**
 * Check availability of externally imported WSI files (Admin only)
 * External files are those imported from outside the system's uploads directory
 * @param datasetId - Optional dataset ID to filter by
 * @returns Check results with available and unavailable files
 * @throws {ApiError} If the request fails
 */
export async function checkExternalFiles(datasetId?: string): Promise<CheckExternalFilesResponse> {
  return apiFetch<CheckExternalFilesResponse>(
    `${API_BASE}/storage/check-external-files`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId })
    },
    'Failed to check external files'
  )
}

// Persistent cache for external datasets (survives page refresh and logout/login)
const externalDatasetsCache = createPersistentCache<ExternalDatasetsResponse>(
  'pathlab-external-datasets-cache',
  PERSISTENT_CACHE_TTL
)

/**
 * Get all datasets that contain externally imported WSI files (Admin only)
 * External files are those imported from outside the system's uploads directory
 * Uses persistent localStorage cache for instant display after login.
 * @param forceRefresh - Force refresh from server, ignoring cache
 * @returns List of datasets with external file counts and availability status
 * @throws {ApiError} If the request fails
 */
export async function getExternalDatasets(forceRefresh = false): Promise<ExternalDatasetsResponse> {
  return externalDatasetsCache.get(
    () => apiFetch<ExternalDatasetsResponse>(
      `${API_BASE}/storage/external-datasets`,
      undefined,
      'Failed to get external datasets'
    ),
    forceRefresh
  )
}

/**
 * Invalidate the external datasets cache
 * Call this after mutations (import, unbind, delete)
 */
export function invalidateExternalDatasetsCache(): void {
  externalDatasetsCache.invalidate()
}

/**
 * Get cached external datasets synchronously (returns null if no valid cache)
 * Useful for instant display without async call
 */
export function getExternalDatasetsCachedSync(): ExternalDatasetsResponse | null {
  return externalDatasetsCache.getCachedSync()
}

/**
 * Delete unavailable WSI records (Admin only)
 * This removes database records for files that are no longer accessible
 * @param wsiIds - List of WSI IDs to delete
 * @returns Deletion results
 * @throws {ApiError} If the request fails
 */
export async function deleteUnavailableFiles(wsiIds: string[]): Promise<DeleteUnavailableFilesResponse> {
  const result = await apiFetch<DeleteUnavailableFilesResponse>(
    `${API_BASE}/storage/delete-unavailable-files`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wsi_ids: wsiIds })
    },
    'Failed to delete unavailable files'
  )
  // Invalidate WSI list cache after deletion
  invalidateWSIListCache()
  return result
}

// ============================================================================
// Storage Background Task APIs (for batch import and delete external files)
// ============================================================================

/**
 * Storage task status from background task endpoints
 */
export interface StorageTaskStatus {
  task_id: string
  user_id: string
  task_type: 'batch_import' | 'delete_external'
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  error_message: string | null
  total_items: number
  processed_items: number
  success_count: number
  failed_count: number
  params: Record<string, unknown> | null
  results: Array<{
    path?: string
    wsi_id?: string
    status: string
    message: string
  }> | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

/**
 * Response from starting a batch import task
 */
export interface StartBatchImportResponse {
  task_id: string
  message: string
  total_files: number
}

/**
 * Response from starting a delete external task
 */
export interface StartDeleteExternalResponse {
  task_id: string
  message: string
  total_files: number
}

/**
 * Start a batch import background task (Admin only)
 * Files are registered asynchronously in the background
 * @param request - Batch register request with file paths and dataset info
 * @returns Task info with task_id for tracking
 * @throws {ApiError} If the request fails
 */
export async function startBatchImportTask(request: BatchRegisterRequest): Promise<StartBatchImportResponse> {
  return apiFetch<StartBatchImportResponse>(
    `${API_BASE}/storage/tasks/batch-import`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    },
    'Failed to start batch import task'
  )
}

/**
 * Start a delete external files background task (Admin only)
 * Files are deleted asynchronously in the background
 * @param wsiIds - List of WSI IDs to delete
 * @returns Task info with task_id for tracking
 * @throws {ApiError} If the request fails
 */
export async function startDeleteExternalTask(wsiIds: string[]): Promise<StartDeleteExternalResponse> {
  return apiFetch<StartDeleteExternalResponse>(
    `${API_BASE}/storage/tasks/delete-external`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wsi_ids: wsiIds })
    },
    'Failed to start delete external task'
  )
}

/**
 * Response from starting an unbind dataset task
 */
export interface StartUnbindDatasetResponse {
  task_id: string
  message: string
  dataset_id: string
  dataset_name: string
  total_files: number
}

/**
 * Start an unbind dataset background task (Admin only)
 * Removes database records for all external files in a dataset
 * Does NOT delete the actual files on the external drive
 * @param datasetId - Dataset ID to unbind
 * @returns Task info with task_id for tracking
 * @throws {ApiError} If the request fails
 */
export async function startUnbindDatasetTask(datasetId: string): Promise<StartUnbindDatasetResponse> {
  return apiFetch<StartUnbindDatasetResponse>(
    `${API_BASE}/storage/tasks/unbind-dataset?dataset_id=${encodeURIComponent(datasetId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    },
    'Failed to start unbind dataset task'
  )
}

/**
 * Get storage task status by ID (Admin only)
 * @param taskId - Storage task ID
 * @returns Task status with progress
 * @throws {ApiError} If the request fails
 */
export async function getStorageTaskStatus(taskId: string): Promise<StorageTaskStatus> {
  return apiFetch<StorageTaskStatus>(
    `${API_BASE}/storage/tasks/${taskId}`,
    undefined,
    'Failed to get storage task status'
  )
}

/**
 * Cancel storage task response
 */
export interface CancelStorageTaskResponse {
  cancelled: boolean
  message: string
}

/**
 * Cancel a storage task (batch_import or delete_external) (Admin only)
 * @param taskId - Storage task ID to cancel
 * @returns Cancel result
 * @throws {ApiError} If the request fails
 */
export async function cancelStorageTask(taskId: string): Promise<CancelStorageTaskResponse> {
  return apiFetch<CancelStorageTaskResponse>(
    `${API_BASE}/storage/tasks/${taskId}`,
    { method: 'DELETE' },
    'Failed to cancel storage task'
  )
}

/**
 * Request for starting a batch update metadata task
 */
export interface StartBatchUpdateMetadataRequest {
  wsi_ids: string[]
  label?: string
  case_id?: string
  age?: number
  gender?: string
  source?: string
  event_time?: number
  event_status?: number
}

/**
 * Response from starting a batch update metadata task
 */
export interface StartBatchUpdateMetadataResponse {
  task_id: string
  message: string
  total_items: number
}

/**
 * Start a batch update metadata background task
 * Updates WSI metadata in the background with progress tracking.
 * Skips updates when values are unchanged.
 * @param request - Request with WSI IDs and metadata to update
 * @returns Task info with task_id for tracking
 * @throws {ApiError} If the request fails
 */
export async function startBatchUpdateMetadataTask(
  request: StartBatchUpdateMetadataRequest
): Promise<StartBatchUpdateMetadataResponse> {
  return apiFetch<StartBatchUpdateMetadataResponse>(
    `${API_BASE}/storage/tasks/batch-update-metadata`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    },
    'Failed to start batch update metadata task'
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
  fold_key?: string | null  // K-fold: which fold this attention comes from (e.g., 'fold_0')
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
  is_best_fold?: boolean | null  // Whether this is the best fold (for k-fold training)
  is_kfold?: boolean  // Whether this task was trained with K-Fold cross-validation
  num_folds?: number | null  // Number of folds if K-Fold training
  val_accuracy?: number  // Validation accuracy of the model (for sorting by best model)
  attention_type?: 'single' | 'multi_class'  // Type of attention: single (most models) or multi_class (CLAM_MB)
  num_attention_classes?: number | null  // Number of attention classes for multi_class type
  // Survival prediction fields
  risk_score?: number | null  // Risk score for survival prediction
  risk_group?: 'High Risk' | 'Low Risk' | null  // Risk group based on median cutoff
}

/**
 * Heatmap data response
 */
export interface HeatmapData {
  wsi_id: string
  task_id: string | null
  task_type?: string  // Task type: "train" (classification), "survival" (survival prediction), etc.
  fold_key?: string | null  // K-fold: which fold this attention comes from
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
  // Survival prediction fields
  risk_score?: number | null  // Risk score for survival prediction
  risk_group?: 'High Risk' | 'Low Risk' | null  // Risk group based on median cutoff
}

// Cache for fetchAvailableHeatmaps (keyed by wsi_id, 60s TTL)
const heatmapAvailabilityCache = createKeyedCache<AvailableHeatmap[]>(LONG_CACHE_TTL)

/**
 * Fetch available heatmaps (attention data) for a WSI (with caching)
 * @param wsi_id - The WSI ID
 * @returns List of available heatmaps
 * @throws {ApiError} If the request fails
 */
export async function fetchAvailableHeatmaps(wsi_id: string): Promise<AvailableHeatmap[]> {
  return heatmapAvailabilityCache.get(wsi_id, async () => {
    const response = await apiFetch<{ heatmaps: AvailableHeatmap[] }>(
      `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/available`,
      undefined,
      'Failed to fetch available heatmaps'
    )
    return response.heatmaps || []
  })
}

/**
 * Invalidate the heatmap availability cache (call after training completes)
 */
export function invalidateHeatmapAvailabilityCache(wsi_id?: string): void {
  if (wsi_id) {
    heatmapAvailabilityCache.invalidate(wsi_id)
  } else {
    heatmapAvailabilityCache.invalidateAll()
  }
}

/**
 * Fetch heatmap data for a WSI
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @param patch_size - Patch size used during inference (default 512)
 * @param fold_key - Optional fold key for k-fold results (e.g., 'fold_0')
 * @returns Heatmap data with top/bottom patches
 * @throws {ApiError} If the request fails
 */
export async function fetchHeatmapData(
  wsi_id: string,
  task_id?: string,
  patch_size: number = 512,
  fold_key?: string
): Promise<HeatmapData> {
  const params = new URLSearchParams()
  params.set('patch_size', String(patch_size))
  if (task_id) {
    params.set('task_id', task_id)
  }
  if (fold_key) {
    params.set('fold_key', fold_key)
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
 * Get WSI heatmap thumbnail URL (rendered heatmap overlay on thumbnail)
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @param size - Max thumbnail size (default 256)
 * @param class_idx - Optional class index for multi-class attention (e.g., CLAM_MB)
 * @returns URL for the heatmap thumbnail PNG image (with auth token for <img> tags)
 */
export function getHeatmapThumbnailUrl(
  wsi_id: string,
  task_id?: string,
  size: number = 256,
  class_idx?: number
): string {
  const token = getAuthToken()
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/heatmap_thumbnail?size=${size}`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  if (class_idx !== undefined) {
    url += `&class_idx=${class_idx}`
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
  // Local vLLM settings (OpenAI-compatible server for LLM)
  local_vllm_enabled: boolean
  local_vllm_base_url: string
  local_vllm_model: string
  local_vllm_api_key: string
  // Local ASR settings (OpenAI-compatible server for ASR)
  local_asr_enabled: boolean
  local_asr_base_url: string
  local_asr_model: string
  local_asr_api_key: string
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