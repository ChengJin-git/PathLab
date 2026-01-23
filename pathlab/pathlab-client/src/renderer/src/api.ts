import { API_BASE, PREPROCESSING_BASE } from './config'

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

export interface LoginUrlResponse {
  login_url: string
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
 */
export async function getLoginUrl(): Promise<LoginUrlResponse> {
  const res = await fetch(`${API_BASE}/auth/login-url`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get login URL: ${errorText}`)
  }

  return res.json()
}

/**
 * Get the signup URL for registration on PathLab Server
 * @returns Signup URL and state token
 */
export async function getSignupUrl(): Promise<LoginUrlResponse> {
  const res = await fetch(`${API_BASE}/auth/signup-url`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get signup URL: ${errorText}`)
  }

  return res.json()
}

/**
 * Process OAuth callback with authorization code
 * @param code - Authorization code from OAuth callback
 * @param state - Optional state token for CSRF verification
 */
export async function processAuthCallback(code: string, state?: string): Promise<{
  success: boolean
  user_id: string
  username: string
  message: string
}> {
  const res = await fetch(`${API_BASE}/auth/callback`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ code, state })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Login failed: ${errorText}`)
  }

  return res.json()
}

/**
 * Logout current user
 */
export async function logout(): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/auth/logout`, {
    method: 'POST'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Logout failed: ${errorText}`)
  }

  return res.json()
}

/**
 * Get current logged-in user info
 */
export async function getCurrentUser(): Promise<UserInfoResponse> {
  const res = await fetch(`${API_BASE}/auth/me`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get user info: ${errorText}`)
  }

  return res.json()
}

/**
 * Refresh access token
 */
export async function refreshToken(): Promise<{
  success: boolean
  refreshed: boolean
  message: string
  expires_at?: string
}> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Token refresh failed: ${errorText}`)
  }

  return res.json()
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
 */
export async function checkDuplicateFilenames(filenames: string[]): Promise<CheckDuplicatesResponse> {
  if (filenames.length === 0) {
    return { duplicates: [], new: [] }
  }

  const res = await fetch(`${API_BASE}/wsi/check-duplicates`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(filenames)
  })

  if (!res.ok) {
    throw new Error('Failed to check duplicate filenames')
  }
  return res.json()
}

/**
 * Fetch WSI list from database via Gateway API
 * @param datasetName - Optional dataset name to filter by
 */
export async function fetchWSIList(datasetName?: string): Promise<WSIListResponse> {
  const url = new URL(`${API_BASE}/wsi`)
  if (datasetName) {
    url.searchParams.set('dataset_name', datasetName)
  }
  const res = await fetch(url.toString())
  if (!res.ok) {
    throw new Error('Failed to load WSI list from database')
  }
  return res.json()
}

/**
 * Dataset summary returned from list datasets endpoint
 */
export interface DatasetSummary {
  dataset_name: string
  file_count: number
  total_size: number
  dataset_type: 'classification' | 'survival'  // Determined by whether WSIs have event_time set
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
 */
export async function fetchDatasets(dataLevel?: string): Promise<DatasetsListResponse> {
  const params = new URLSearchParams()
  if (dataLevel) {
    params.append('data_level', dataLevel)
  }
  const queryString = params.toString()
  const url = queryString ? `${API_BASE}/wsi/datasets?${queryString}` : `${API_BASE}/wsi/datasets`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error('Failed to load datasets from database')
  }
  return res.json()
}

/**
 * Rename a dataset
 * @param oldName - Current dataset name
 * @param newName - New dataset name
 */
export async function renameDataset(oldName: string, newName: string): Promise<{ message: string; updated_count: number }> {
  const res = await fetch(`${API_BASE}/wsi/datasets`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ old_name: oldName, new_name: newName })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to rename dataset: ${errorText}`)
  }

  return res.json()
}

/**
 * Fetch WSI detail from database via Gateway API
 */
export async function fetchWSIDetail(wsi_id: string): Promise<WSIDetail> {
  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}`)
  if (!res.ok) {
    throw new Error('Failed to get WSI detail from database')
  }
  return res.json()
}

/**
 * Compute patch coordinates for a WSI using PrePATH-style tissue segmentation
 * Uses settings from localStorage if not provided
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
  const use_otsu = options?.use_otsu ?? (localStorage.getItem('seg_use_otsu') === 'true')
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

  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}/compute_patches?${params}`, {
    method: 'POST'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to compute patches: ${errorText}`)
  }

  return res.json()
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
 */
export async function analyzeWSI(wsi_id: string, params: AnalyzeWSIParams = {}): Promise<AITaskResponse> {
  console.log('Analyzing WSI:', wsi_id, 'with params:', params)

  // Extract classes and model_id to top level as expected by backend WSIClassifyRequest
  const { classes, model_id, ...restParams } = params

  const res = await fetch(`${API_BASE}/tasks/wsi_classification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      wsi_id,
      classes,
      model_id,
      params: Object.keys(restParams).length > 0 ? restParams : undefined
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to analyze WSI: ${errorText}`)
  }

  return res.json()
}

/**
 * Fetch AI analysis results from Gateway.
 * Gateway will get the latest results from AI Service or local cache.
 */
export async function fetchResults(wsi_id: string): Promise<AIResult | null> {
  try {
    const res = await fetch(`${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}`)
    if (!res.ok) {
      throw new Error('Failed to get results')
    }
    const result: AIResult = await res.json()

    // Return null if no prediction available
    if (!result.pred) {
      return null
    }

    return result
  } catch (err) {
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
 */
export async function deleteWSIResults(
  wsi_id: string,
  task_id?: string
): Promise<DeleteWSIResultsResponse> {
  const params = new URLSearchParams()
  if (task_id) {
    params.set('task_id', task_id)
  }

  const url = `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}${params.toString() ? '?' + params.toString() : ''}`

  const res = await fetch(url, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete WSI results')
  }

  return await res.json()
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
 */
export async function uploadDatasetSplits(
  datasetName: string,
  file: File
): Promise<UploadSplitsResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/wsi/datasets/${encodeURIComponent(datasetName)}/splits`, {
    method: 'POST',
    body: formData
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(errorText)
  }

  return res.json()
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
  const res = await fetch(`${API_BASE}/wsi/upload/path`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
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
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to register WSI by path: ${errorText}`)
  }

  return res.json()
}

export interface StorageConfig {
  uploads_dir: string
  source?: 'env' | 'config' | 'default' | string
}

export async function getStorageConfig(): Promise<StorageConfig> {
  const res = await fetch(`${API_BASE}/storage/config`)
  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to load storage config: ${errorText}`)
  }
  return res.json()
}

export async function updateStorageConfig(uploads_dir: string): Promise<{ uploads_dir: string; restart_required: boolean; message?: string }> {
  const res = await fetch(`${API_BASE}/storage/config`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ uploads_dir })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to update storage config: ${errorText}`)
  }

  return res.json()
}

export interface MigrationStatus {
  status: 'idle' | 'running' | 'completed' | 'failed'
  source: string | null
  destination: string | null
  progress: number
  error: string | null
  delete_source: boolean
  message?: string
  new_path?: string
}

export async function startMigration(targetPath: string, deleteSource: boolean = false): Promise<void> {
  const res = await fetch(`${API_BASE}/storage/migrate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ target_path: targetPath, delete_source: deleteSource })
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to start migration')
  }
}

export async function getMigrationStatus(): Promise<MigrationStatus> {
  const res = await fetch(`${API_BASE}/storage/migration/status`)
  if (!res.ok) {
    throw new Error('Failed to get migration status')
  }
  return res.json()
}

/**
 * Download CSV template for batch WSI metadata configuration.
 * @param taskType - 'classification' or 'survival'
 */
export async function downloadCSVTemplate(taskType: 'classification' | 'survival' = 'classification') {
  const res = await fetch(`${API_BASE}/wsi/upload/csv/template?task_type=${taskType}`)
  if (!res.ok) {
    throw new Error('Failed to download CSV template')
  }

  // Get the blob and create a download link
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // Use filename from Content-Disposition header or fallback
  const filename = taskType === 'survival'
    ? 'wsi_survival_metadata_template.csv'
    : 'wsi_classification_metadata_template.csv'
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
 */
export async function deleteWSI(wsi_id: string, mode: string = 'standard'): Promise<WSIDeleteResult> {
  const res = await fetch(`${API_BASE}/wsi/${wsi_id}?mode=${mode}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete WSI')
  }

  return await res.json()
}

/**
 * Update WSI metadata (label, case_id, age, gender, source).
 *
 * @param wsi_id - The WSI ID to update
 * @param metadata - Metadata to update
 * @returns Update result
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
  const res = await fetch(`${API_BASE}/wsi/${wsi_id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(metadata)
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to update WSI metadata')
  }

  return await res.json()
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
 */
export async function uploadWSIByCSV(file: File): Promise<BatchUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/wsi/upload/csv`, {
    method: 'POST',
    body: formData
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to upload CSV: ${errorText}`)
  }

  return res.json()
}

/**
 * Fetch system statistics from Gateway.
 * Returns WSI count, task count, completed count, results count, and label distribution.
 */
export async function fetchStats(): Promise<SystemStats> {
  try {
    const res = await fetch(`${API_BASE}/stats`)
    if (!res.ok) {
      throw new Error('Failed to get stats')
    }
    return res.json()
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
 */
export async function chatWithAI(
  messages: Array<{ role: 'user' | 'assistant', content: string }>,
  onChunk: (chunk: string) => void,
  conversationId?: string
): Promise<void> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-instruct'

  const res = await fetch(`${API_BASE}/chat`, {
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

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to chat with AI: ${errorText}`)
  }

  // Handle streaming response
  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('Response body is not readable')
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
 * Parsed task result (placeholder - endpoint not yet implemented)
 */
export interface ParsedTaskResult {
  message: string
  [key: string]: unknown
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
 * Parse task description using LLM
 * @param description - Natural language task description
 * @returns Parsed task parameters
 */
export async function parseTaskDescription(description: string): Promise<ParsedTaskResult> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-instruct'

  const res = await fetch(`${API_BASE}/parse-task`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-OpenRouter-API-Key': apiKey,
      'X-OpenRouter-Base-URL': baseUrl,
      'X-OpenRouter-Model': model
    },
    body: JSON.stringify({ description })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to parse task: ${errorText}`)
  }

  return res.json()
}

/**
 * Get all training tasks
 * @returns List of training tasks
 */
export async function getTrainingTasks(): Promise<TrainingTask[]> {
  const res = await fetch(`${API_BASE}/tasks/training`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get training tasks: ${errorText}`)
  }

  const data = await res.json()
  return data.items || []
}

/**
 * Get training task by ID
 * @param taskId - Training task ID
 * @returns Training task details
 */
export async function getTrainingTask(taskId: string): Promise<TrainingTaskDetail> {
  const res = await fetch(`${API_BASE}/tasks/training/${taskId}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get training task: ${errorText}`)
  }

  return res.json()
}

/**
 * Delete training task
 * @param taskId - Training task ID
 * @param mode - Deletion mode: "standard" (keep models) or "complete" (delete all)
 */
export async function deleteTrainingTask(taskId: string, mode: string = 'standard'): Promise<TrainingTaskDeleteResult> {
  const res = await fetch(`${API_BASE}/tasks/training/${taskId}?mode=${mode}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to delete training task: ${errorText}`)
  }

  return res.json()
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
 */
export async function cancelQueueTask(taskId: string): Promise<CancelQueueTaskResponse> {
  const res = await fetch(`${API_BASE}/queue/${taskId}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to cancel task: ${errorText}`)
  }

  return res.json()
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
 */
export async function createTrainingTask(taskConfig: TrainingTaskConfig): Promise<TrainingTaskCreateResult> {
  // Get HuggingFace token from localStorage for gated models
  const huggingfaceToken = localStorage.getItem('huggingface_token') || ''

  const res = await fetch(`${API_BASE}/tasks/training`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      ...taskConfig,
      huggingface_token: huggingfaceToken
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to create training task: ${errorText}`)
  }

  return res.json()
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
 */
export async function createConversation(title?: string, userId: string = 'default_user'): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      user_id: userId,
      title: title || 'New Conversation'
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to create conversation: ${errorText}`)
  }

  return res.json()
}

/**
 * Get all conversations for a user
 * @param userId - User ID (defaults to "default_user")
 * @param skip - Number of conversations to skip
 * @param limit - Maximum number of conversations to return
 * @returns List of conversations
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

  const res = await fetch(`${API_BASE}/conversations?${params}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get conversations: ${errorText}`)
  }

  const data = await res.json()
  return data.items || []
}

/**
 * Get a conversation with all messages
 * @param conversationId - Conversation ID
 * @returns Conversation with messages
 */
export async function getConversation(conversationId: string): Promise<ConversationWithMessages> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get conversation: ${errorText}`)
  }

  return res.json()
}

/**
 * Delete a conversation
 * @param conversationId - Conversation ID
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to delete conversation: ${errorText}`)
  }
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
 */
export async function getDiskSpace(): Promise<DiskSpaceInfo> {
  const res = await fetch(`${API_BASE}/storage/disk-space`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get disk space: ${errorText}`)
  }

  return res.json()
}

/**
 * Check if there is enough disk space for an upload
 * @param requiredBytes - Required space in bytes
 * @returns Upload space check result
 */
export async function checkUploadSpace(requiredBytes: number): Promise<UploadSpaceCheck> {
  const res = await fetch(`${API_BASE}/storage/check-upload-space?required_bytes=${requiredBytes}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to check upload space: ${errorText}`)
  }

  return res.json()
}

/**
 * Get overall storage statistics
 * @returns Storage statistics with breakdown by category
 */
export async function getStorageStats(): Promise<StorageStats> {
  const res = await fetch(`${API_BASE}/storage/stats`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get storage stats: ${errorText}`)
  }

  return res.json()
}

/**
 * Get storage information for a specific WSI
 * @param wsi_id - WSI ID
 * @returns Detailed storage information for the WSI
 */
export async function getWSIStorageInfo(wsi_id: string): Promise<WSIStorageInfo> {
  const res = await fetch(`${API_BASE}/storage/wsi/${encodeURIComponent(wsi_id)}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get WSI storage info: ${errorText}`)
  }

  return res.json()
}

/**
 * Get storage information for a specific training task
 * @param task_id - Training task ID
 * @returns Detailed storage information for the training task
 */
export async function getTrainingTaskStorageInfo(task_id: string): Promise<TrainingTaskStorageInfo> {
  const res = await fetch(`${API_BASE}/storage/training/${encodeURIComponent(task_id)}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get training task storage info: ${errorText}`)
  }

  return res.json()
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

export async function detectOrphanedFiles(): Promise<OrphanedFilesInfo> {
  const res = await fetch(`${API_BASE}/storage/orphaned`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to detect orphaned files: ${errorText}`)
  }

  return res.json()
}

export interface CleanupResult {
  deleted_files: string[]
  deleted_dirs: string[]
  failed: [string, string][]
  total_size: number
  summary: string
}

export async function cleanupOrphanedFiles(categories?: string[]): Promise<CleanupResult> {
  const res = await fetch(`${API_BASE}/storage/orphaned/cleanup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ categories })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to cleanup orphaned files: ${errorText}`)
  }

  return res.json()
}

/**
 * Fetch available feature extractors
 * @returns List of available feature extractors
 */
export async function fetchExtractors(): Promise<FeatureExtractor[]> {
  const res = await fetch(`${API_BASE}/tasks/extractors`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to fetch extractors: ${errorText}`)
  }

  const data: FeatureExtractorListResponse = await res.json()
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
 * @param wsi_id - The WSI ID
 * @returns List of available heatmaps
 */
export async function fetchAvailableHeatmaps(wsi_id: string): Promise<AvailableHeatmap[]> {
  try {
    const res = await fetch(`${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/available_heatmaps`)
    if (!res.ok) {
      console.warn('Failed to fetch available heatmaps:', res.statusText)
      return []
    }
    const data = await res.json()
    return data.heatmaps || []
  } catch (err) {
    console.error('Failed to fetch available heatmaps:', err)
    return []
  }
}

/**
 * Fetch heatmap data for a WSI
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @returns Heatmap data with top/bottom patches
 */
export async function fetchHeatmapData(wsi_id: string, task_id?: string): Promise<HeatmapData | null> {
  try {
    let url = `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/heatmap`
    if (task_id) {
      url += `?task_id=${encodeURIComponent(task_id)}`
    }
    const res = await fetch(url)
    if (!res.ok) {
      console.warn('Failed to fetch heatmap data:', res.statusText)
      return null
    }
    return await res.json()
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
  return `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/patch_image?x=${x}&y=${y}&size=${size}`
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
  cam_data: number[][]  // 2D array of CAM values
}

/**
 * Get patch CAM overlay image URL
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @returns URL for the CAM overlay PNG image
 */
export function getPatchCAMImageUrl(wsi_id: string, task_id?: string): string {
  let url = `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=image`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  return url
}

/**
 * Fetch patch CAM data as JSON
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @returns Patch CAM data
 */
export async function fetchPatchCAMData(wsi_id: string, task_id?: string): Promise<PatchCAMData | null> {
  try {
    let url = `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=json`
    if (task_id) {
      url += `&task_id=${encodeURIComponent(task_id)}`
    }
    const res = await fetch(url)
    if (!res.ok) {
      console.warn('Failed to fetch patch CAM data:', res.statusText)
      return null
    }
    return await res.json()
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
  return `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/image`
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
 */
export async function transcribeAudio(audioBlob: Blob): Promise<TranscribeResponse> {
  const dashscopeApiKey = localStorage.getItem('dashscope_api_key') || ''

  // Convert blob to base64
  const arrayBuffer = await audioBlob.arrayBuffer()
  const base64Audio = btoa(
    new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
  )

  const response = await fetch(`${API_BASE}/asr/transcribe`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-DashScope-API-Key': dashscopeApiKey
    },
    body: JSON.stringify({
      audio: base64Audio,
      language: 'zh'
    })
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`ASR request failed: ${errorText}`)
  }

  return response.json()
}