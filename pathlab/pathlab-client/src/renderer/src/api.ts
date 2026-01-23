import { API_BASE } from './config'

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

/**
 * Wrap fetch call with unified error handling
 * Catches network errors and converts them to ApiError
 */
async function apiFetch<T>(
  url: string,
  options?: RequestInit,
  context?: string
): Promise<T> {
  try {
    const response = await fetch(url, options)
    return handleResponse<T>(response, context)
  } catch (error) {
    // If it's already an ApiError, rethrow it
    if (error instanceof ApiError) {
      throw error
    }

    // Network errors (no internet, CORS, etc.)
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new ApiError(
        context ? `${context}: Network error` : 'Network error - please check your connection',
        0,
        ApiErrorCode.NETWORK_ERROR,
        error.message
      )
    }

    // Other unknown errors
    throw new ApiError(
      context ? `${context}: ${(error as Error).message}` : (error as Error).message,
      0,
      ApiErrorCode.UNKNOWN,
      (error as Error).message
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
// Authentication APIs
// ============================================================================

export interface AuthUser {
  user_id: string
  username: string
  nickname?: string
  email?: string
  phone?: string
  avatar_url?: string
  roles?: string[]
  is_current: boolean
  server_url?: string
  last_synced_at?: string
  token_expires_at?: string
  has_valid_token?: boolean
}

export interface AuthUrlResponse {
  url: string
  state: string
  message: string
}

export interface UserInfoResponse {
  is_logged_in: boolean
  user?: AuthUser
}

/**
 * Get the login URL for OAuth with PathLab Server
 * @returns Login URL and state token
 * @throws {ApiError} If the request fails
 */
export async function getLoginUrl(): Promise<AuthUrlResponse> {
  return apiFetch<AuthUrlResponse>(`${API_BASE}/auth/login-url`, undefined, 'Failed to get login URL')
}

/**
 * Get the signup URL for registration on PathLab Server
 * @returns Signup URL and state token
 * @throws {ApiError} If the request fails
 */
export async function getSignupUrl(): Promise<AuthUrlResponse> {
  return apiFetch<AuthUrlResponse>(`${API_BASE}/auth/signup-url`, undefined, 'Failed to get signup URL')
}

/**
 * Process OAuth callback with authorization code
 * @param code - Authorization code from OAuth callback
 * @param state - Optional state token for CSRF verification
 * @throws {ApiError} If the login fails
 */
export async function processAuthCallback(
  code: string,
  state?: string
): Promise<{
  success: boolean
  user_id: string
  username: string
  message: string
}> {
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

/**
 * Logout current user
 * @throws {ApiError} If the logout fails
 */
export async function logout(): Promise<{ success: boolean; message: string }> {
  return apiFetch(`${API_BASE}/auth/logout`, { method: 'POST' }, 'Logout failed')
}

/**
 * Get current logged-in user info
 * @throws {ApiError} If the request fails
 */
export async function getCurrentUser(): Promise<UserInfoResponse> {
  return apiFetch<UserInfoResponse>(`${API_BASE}/auth/me`, undefined, 'Failed to get user info')
}

/**
 * Refresh access token
 * @throws {ApiError} If the token refresh fails
 */
export async function refreshToken(): Promise<{
  success: boolean
  refreshed: boolean
  message: string
  expires_at?: string
}> {
  return apiFetch(`${API_BASE}/auth/refresh`, { method: 'POST' }, 'Token refresh failed')
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
 * @param datasetName - Optional dataset name to filter by
 * @throws {ApiError} If the request fails
 */
export async function fetchWSIList(datasetName?: string): Promise<WSIListResponse> {
  const url = new URL(`${API_BASE}/wsi`)
  if (datasetName) {
    url.searchParams.set('dataset_name', datasetName)
  }
  return apiFetch<WSIListResponse>(url.toString(), undefined, 'Failed to load WSI list from database')
}

/**
 * Dataset summary returned from list datasets endpoint
 */
export interface DatasetSummary {
  dataset_name: string
  file_count: number
  total_size: number
  dataset_type: 'classification' | 'survival' // Determined by whether WSIs have event_time set
}

/**
 * Datasets list response
 */
export interface DatasetsListResponse {
  datasets: DatasetSummary[]
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
 * Rename a dataset
 * @param oldName - Current dataset name
 * @param newName - New dataset name
 * @throws {ApiError} If the request fails
 */
export async function renameDataset(
  oldName: string,
  newName: string
): Promise<{ message: string; updated_count: number }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_name: oldName, new_name: newName })
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
 * @returns Result or null if not found or no prediction available
 */
export async function fetchResults(wsi_id: string): Promise<AIResult | null> {
  try {
    const result = await apiFetch<AIResult>(
      `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}`,
      undefined,
      'Failed to get results'
    )

    // Return null if no prediction available
    if (!result.pred) {
      return null
    }

    return result
  } catch (err) {
    // For results, we return null on error (expected when no results exist)
    if (err instanceof ApiError && err.isNotFound()) {
      return null
    }
    console.error('Failed to fetch results:', err)
    return null
  }
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

  return apiFetch<DeleteWSIResultsResponse>(url, { method: 'DELETE' }, 'Failed to delete WSI results')
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
 * @throws {ApiError} If the request fails
 */
export async function uploadDatasetSplits(datasetName: string, file: File): Promise<UploadSplitsResponse> {
  const formData = new FormData()
  formData.append('file', file)

  return apiFetch<UploadSplitsResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetName)}/splits`,
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
    dataset_name?: string
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

    // Send request
    xhr.open('POST', `${API_BASE}/wsi/upload/file`)
    xhr.send(formData)
  })
}

/**
 * Register a WSI by file path (without copying the file).
 *
 * @param wsi_path - Path to the WSI file on the server
 * @param options - Optional metadata (label, case_id, wsi_id, dataset_name)
 * @returns Upload result with wsi_id and metadata
 * @throws {ApiError} If the request fails
 */
export async function uploadWSIByPath(
  wsi_path: string,
  options?: {
    dataset_name?: string
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
  const response = await fetch(`${API_BASE}/wsi/upload/csv/template?task_type=${taskType}`)

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
 * Returns default values on error (non-throwing for dashboard resilience).
 */
export async function fetchStats(): Promise<SystemStats> {
  try {
    return await apiFetch<SystemStats>(`${API_BASE}/stats`, undefined, 'Failed to get stats')
  } catch (err) {
    console.error('Failed to fetch stats:', err)
    return {
      wsi_count: 0,
      task_count: 0,
      completed_count: 0,
      results_count: 0,
      labels: {}
    }
  }
}

/**
 * Chat with AI assistant (streaming)
 * @param messages - Array of chat messages
 * @param onChunk - Callback for each chunk of response
 * @param conversationId - Optional conversation ID to save messages to database
 * @returns Promise that resolves when streaming is complete
 * @throws {ApiError} If the request fails
 */
export async function chatWithAI(
  messages: Array<{ role: 'user' | 'assistant'; content: string }>,
  onChunk: (chunk: string) => void,
  conversationId?: string
): Promise<void> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-instruct'

  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-OpenRouter-API-Key': apiKey,
      'X-OpenRouter-Base-URL': baseUrl,
      'X-OpenRouter-Model': model
    },
    body: JSON.stringify({
      messages,
      conversation_id: conversationId
    })
  })

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
 * @param title - Optional conversation title
 * @param userId - Optional user ID (defaults to "default_user")
 * @returns Created conversation
 * @throws {ApiError} If the request fails
 */
export async function createConversation(title?: string, userId: string = 'default_user'): Promise<Conversation> {
  return apiFetch<Conversation>(
    `${API_BASE}/conversations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        title: title || 'New Conversation'
      })
    },
    'Failed to create conversation'
  )
}

/**
 * Get all conversations for a user
 * @param userId - User ID (defaults to "default_user")
 * @param skip - Number of conversations to skip
 * @param limit - Maximum number of conversations to return
 * @returns List of conversations
 * @throws {ApiError} If the request fails
 */
export async function getConversations(
  userId: string = 'default_user',
  skip: number = 0,
  limit: number = 50
): Promise<Conversation[]> {
  const params = new URLSearchParams({
    user_id: userId,
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
 * @returns Storage statistics with breakdown by category
 * @throws {ApiError} If the request fails
 */
export async function getStorageStats(): Promise<StorageStats> {
  return apiFetch<StorageStats>(`${API_BASE}/storage/stats`, undefined, 'Failed to get storage stats')
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
}

/**
 * Fetch available heatmaps (attention data) for a WSI
 * Returns empty array on error (non-throwing for UI resilience).
 * @param wsi_id - The WSI ID
 * @returns List of available heatmaps
 */
export async function fetchAvailableHeatmaps(wsi_id: string): Promise<AvailableHeatmap[]> {
  try {
    const data = await apiFetch<{ heatmaps: AvailableHeatmap[] }>(
      `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/available`,
      undefined,
      'Failed to fetch available heatmaps'
    )
    return data.heatmaps || []
  } catch (err) {
    console.error('Failed to fetch available heatmaps:', err)
    return []
  }
}

/**
 * Fetch heatmap data for a WSI
 * Returns null on error (non-throwing for UI resilience).
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @returns Heatmap data with top/bottom patches
 */
export async function fetchHeatmapData(wsi_id: string, task_id?: string): Promise<HeatmapData | null> {
  try {
    let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/data`
    if (task_id) {
      url += `?task_id=${encodeURIComponent(task_id)}`
    }
    return await apiFetch<HeatmapData>(url, undefined, 'Failed to fetch heatmap data')
  } catch (err) {
    console.error('Failed to fetch heatmap data:', err)
    return null
  }
}

/**
 * Get patch image URL for a WSI at specific coordinates
 * @param wsi_id - The WSI ID
 * @param x - X coordinate
 * @param y - Y coordinate
 * @param size - Patch size (default 256)
 * @returns URL for the patch image
 */
export function getPatchImageUrl(wsi_id: string, x: number, y: number, size: number = 256): string {
  return `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_image?x=${x}&y=${y}&size=${size}`
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
 * @returns URL for the CAM overlay PNG image
 */
export function getPatchCAMImageUrl(wsi_id: string, task_id?: string): string {
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=image`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  return url
}

/**
 * Fetch patch CAM data as JSON
 * Returns null on error (non-throwing for UI resilience).
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @returns Patch CAM data
 */
export async function fetchPatchCAMData(wsi_id: string, task_id?: string): Promise<PatchCAMData | null> {
  try {
    let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=json`
    if (task_id) {
      url += `&task_id=${encodeURIComponent(task_id)}`
    }
    return await apiFetch<PatchCAMData>(url, undefined, 'Failed to fetch patch CAM data')
  } catch (err) {
    console.error('Failed to fetch patch CAM data:', err)
    return null
  }
}

/**
 * Get patch image URL for a simple patch file (not WSI)
 * This endpoint returns the entire patch image for patch classification tasks
 * @param wsi_id - The patch ID
 * @returns URL for the patch image
 */
export function getPatchFileImageUrl(wsi_id: string): string {
  return `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/image`
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