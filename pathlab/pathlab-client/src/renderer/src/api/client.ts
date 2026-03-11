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
export async function parseErrorResponse(response: Response): Promise<{ message: string; detail?: string }> {
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

  // If the response is HTML (e.g. nginx 502/503 error page), don't use raw HTML as message
  if (contentType?.includes('text/html')) {
    return { message: response.statusText || `Server error (${response.status})` }
  }

  const text = await response.text()
  return { message: text || response.statusText, detail: text }
}

/**
 * Get error code from HTTP status
 */
export function getErrorCodeFromStatus(status: number): ApiErrorCodeType {
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
  const okResponse = await ensureSuccessfulResponse(response, context)

  // Handle empty responses (204 No Content, etc.)
  const contentLength = okResponse.headers.get('content-length')
  if (okResponse.status === 204 || contentLength === '0') {
    return undefined as T
  }
  return okResponse.json()
}

// Token storage key (defined early for use in apiFetch)
const AUTH_TOKEN_KEY = 'pathlab_auth_token'

/**
 * Custom event fired when a 401 response is received while the user had a valid token.
 * This indicates the session was invalidated (e.g., logged in on another device).
 * AuthContext listens for this event to show a user-friendly notification and redirect to login.
 */
export const SESSION_EXPIRED_EVENT = 'pathlab:session-expired'

/**
 * Get stored auth token (internal use)
 */
function _getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY)
}

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

export type QueryParamValue = string | number | boolean | null | undefined
export type QueryParamInput = QueryParamValue | QueryParamValue[]

function isPresentQueryParamValue(value: QueryParamValue): value is string | number | boolean {
  return value !== null && value !== undefined
}

/**
 * Append a plain object of query parameters into an existing URLSearchParams.
 * Single values use set(); arrays append repeated entries.
 */
export function appendSearchParams(
  params: URLSearchParams,
  entries?: Record<string, QueryParamInput>
): URLSearchParams {
  if (!entries) {
    return params
  }

  Object.entries(entries).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (isPresentQueryParamValue(item)) {
          params.append(key, String(item))
        }
      })
      return
    }

    if (isPresentQueryParamValue(value)) {
      params.set(key, String(value))
    }
  })

  return params
}

/**
 * Build URLSearchParams from a plain object while ignoring null/undefined values.
 */
export function buildSearchParams(entries?: Record<string, QueryParamInput>): URLSearchParams {
  return appendSearchParams(new URLSearchParams(), entries)
}

/**
 * Merge request headers and inject Authorization when a token is available.
 */
export function buildAuthHeaders(headers?: HeadersInit, skipAuth: boolean = false): Headers {
  const mergedHeaders = new Headers(headers)

  if (!skipAuth) {
    const token = _getAuthToken()
    if (token && !mergedHeaders.has('Authorization')) {
      mergedHeaders.set('Authorization', `Bearer ${token}`)
    }
  }

  return mergedHeaders
}

/**
 * Build fetch options with merged headers and optional Authorization injection.
 */
export function buildAuthRequestInit(options: RequestInit = {}, skipAuth: boolean = false): RequestInit {
  return {
    ...options,
    headers: buildAuthHeaders(options.headers, skipAuth)
  }
}

/**
 * Append the stored auth token to a URL query string for SSE/image endpoints.
 */
export function withAuthTokenQuery(url: string, tokenParam: string = 'token'): string {
  const token = _getAuthToken()
  if (!token) {
    return url
  }

  const hashIndex = url.indexOf('#')
  const baseWithQuery = hashIndex >= 0 ? url.slice(0, hashIndex) : url
  const hash = hashIndex >= 0 ? url.slice(hashIndex) : ''
  const queryIndex = baseWithQuery.indexOf('?')
  const base = queryIndex >= 0 ? baseWithQuery.slice(0, queryIndex) : baseWithQuery
  const existingQuery = queryIndex >= 0 ? baseWithQuery.slice(queryIndex + 1) : ''
  const params = new URLSearchParams(existingQuery)

  if (!params.has(tokenParam)) {
    params.set(tokenParam, token)
  }

  const queryString = params.toString()
  return `${base}${queryString ? `?${queryString}` : ''}${hash}`
}

function getFilenameFromContentDisposition(
  contentDisposition: string | null,
  fallbackFilename: string
): string {
  if (!contentDisposition) {
    return fallbackFilename
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const quotedMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  return quotedMatch?.[1] || fallbackFilename
}

async function ensureSuccessfulResponse(response: Response, context?: string): Promise<Response> {
  if (response.ok) {
    return response
  }

  const { message, detail } = await parseErrorResponse(response)
  const code = getErrorCodeFromStatus(response.status)
  const errorMessage = context ? `${context}: ${message}` : message

  throw new ApiError(errorMessage, response.status, code, detail)
}

async function runApiRequest<T>(operation: () => Promise<T>, context?: string): Promise<T> {
  const hadToken = !!_getAuthToken()

  try {
    return await operation()
  } catch (error) {
    // If it's already an ApiError, check for session expiry (401 while authenticated)
    if (error instanceof ApiError) {
      if (error.status === 401 && hadToken) {
        clearAuthToken()
        window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
      }
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

async function fetchWithAuth(
  url: string,
  options?: RequestInit,
  skipAuth: boolean = false
): Promise<Response> {
  return fetch(url, buildAuthRequestInit(options, skipAuth))
}

/**
 * Wrap fetch call with unified error handling
 * Catches network errors and converts them to ApiError
 * Automatically adds Authorization header if token is available
 */
export async function apiFetch<T>(
  url: string,
  options?: RequestInit,
  context?: string,
  skipAuth: boolean = false
): Promise<T> {
  return runApiRequest(async () => {
    const response = await fetchWithAuth(url, options, skipAuth)
    return handleResponse<T>(response, context)
  }, context)
}

/**
 * Fetch a binary response with the same auth and error handling as apiFetch.
 */
export async function apiFetchBlob(
  url: string,
  options?: RequestInit,
  context?: string,
  skipAuth: boolean = false
): Promise<Blob> {
  return runApiRequest(async () => {
    const response = await fetchWithAuth(url, options, skipAuth)
    const okResponse = await ensureSuccessfulResponse(response, context)
    return okResponse.blob()
  }, context)
}

/**
 * Download a file response with auth/error handling and Content-Disposition filename support.
 */
export async function downloadApiFile(
  url: string,
  fallbackFilename: string,
  options?: RequestInit,
  context?: string,
  skipAuth: boolean = false
): Promise<void> {
  return runApiRequest(async () => {
    const response = await fetchWithAuth(url, options, skipAuth)
    const okResponse = await ensureSuccessfulResponse(response, context)
    const blob = await okResponse.blob()
    const filename = getFilenameFromContentDisposition(
      okResponse.headers.get('Content-Disposition'),
      fallbackFilename
    )
    downloadBlobFile(blob, filename)
  }, context)
}

/**
 * Trigger a browser download for a Blob.
 */
export function downloadBlobFile(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
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

