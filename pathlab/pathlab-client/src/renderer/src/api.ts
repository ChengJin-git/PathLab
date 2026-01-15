import { API_BASE } from './config'

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
 * Fetch WSI list from database via Gateway API
 */
export async function fetchWSIList() {
  const res = await fetch(`${API_BASE}/wsi`)
  if (!res.ok) {
    throw new Error('Failed to load WSI list from database')
  }
  return res.json()
}

/**
 * Fetch WSI detail from database via Gateway API
 */
export async function fetchWSIDetail(wsi_id: string) {
  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}`)
  if (!res.ok) {
    throw new Error('Failed to get WSI detail from database')
  }
  return res.json()
}

/**
 * Compute patch coordinates for a WSI using PrePATH/CLAM-style tissue segmentation
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
) {
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

export async function analyzeWSI(wsi_id: string, params: any = {}) {
  /**
   * Call Gateway to create a WSI classification task.
   * Gateway will orchestrate the request to AI Service.
   */
  console.log('Analyzing WSI:', wsi_id, 'with params:', params)

  const res = await fetch(`${API_BASE}/tasks/wsi_classification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      wsi_id,
      params
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to analyze WSI: ${errorText}`)
  }

  return res.json()
}

export async function fetchResults(wsi_id: string) {
  /**
   * Fetch AI analysis results from Gateway.
   * Gateway will get the latest results from AI Service or local cache.
   */
  try {
    const res = await fetch(`${API_BASE}/results/${encodeURIComponent(wsi_id)}`)
    if (!res.ok) {
      throw new Error('Failed to get results')
    }
    const result = await res.json()

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

export async function uploadWSIFile(
  file: File,
  options?: {
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    wsi_id?: string
    onProgress?: (progress: number) => void
    /** Associated files for special formats (MRXS data folder files, TMAP DT files) */
    associatedFiles?: File[]
  }
) {
  /**
   * Upload a WSI file to the server.
   * For MRXS format: also upload associated data folder files
   * For TMAP format: also upload associated DT files
   *
   * @param file - The WSI file to upload
   * @param options - Optional metadata and associated files
   * @returns Upload result with wsi_id and metadata
   */
  const formData = new FormData()
  formData.append('file', file)

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
          const result = JSON.parse(xhr.responseText)
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

export async function uploadWSIByPath(
  wsi_path: string,
  options?: {
    label?: string
    case_id?: string
    wsi_id?: string
    age?: number
    gender?: string
    source?: string
  }
) {
  /**
   * Register a WSI by file path (without copying the file).
   *
   * @param wsi_path - Path to the WSI file on the server
   * @param options - Optional metadata (label, case_id, wsi_id)
   * @returns Upload result with wsi_id and metadata
   */
  const res = await fetch(`${API_BASE}/wsi/upload/path`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      wsi_path,
      label: options?.label,
      case_id: options?.case_id,
      wsi_id: options?.wsi_id,
      age: options?.age,
      gender: options?.gender,
      source: options?.source
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

export async function downloadCSVTemplate() {
  /**
   * Download CSV template for batch WSI upload.
   */
  const res = await fetch(`${API_BASE}/wsi/upload/csv/template`)
  if (!res.ok) {
    throw new Error('Failed to download CSV template')
  }

  // Get the blob and create a download link
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'wsi_upload_template.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export async function deleteWSI(wsi_id: string, mode: string = 'standard') {
  /**
   * Delete a WSI and its associated data.
   *
   * @param wsi_id - The WSI ID to delete
   * @param mode - Deletion mode: "standard" (keep training features) or "complete" (delete all)
   * @returns Delete result
   */
  const res = await fetch(`${API_BASE}/wsi/${wsi_id}?mode=${mode}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete WSI')
  }

  return await res.json()
}

export async function updateWSIMetadata(
  wsi_id: string,
  metadata: {
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
  }
) {
  /**
   * Update WSI metadata (label, case_id, age, gender, source).
   *
   * @param wsi_id - The WSI ID to update
   * @param metadata - Metadata to update
   * @returns Update result
   */
  const params = new URLSearchParams()
  if (metadata.label !== undefined) {
    params.append('label', metadata.label)
  }
  if (metadata.case_id !== undefined) {
    params.append('case_id', metadata.case_id)
  }
  if (metadata.age !== undefined) {
    params.append('age', metadata.age.toString())
  }
  if (metadata.gender !== undefined) {
    params.append('gender', metadata.gender)
  }
  if (metadata.source !== undefined) {
    params.append('source', metadata.source)
  }

  const res = await fetch(`${API_BASE}/wsi/${wsi_id}?${params.toString()}`, {
    method: 'PATCH'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to update WSI metadata')
  }

  return await res.json()
}

export async function uploadWSIByCSV(file: File) {
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

export async function fetchStats() {
  /**
   * Fetch system statistics from Gateway.
   * Returns WSI count, task count, completed count, results count, and label distribution.
   */
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
 * Parse task description using LLM
 * @param description - Natural language task description
 * @returns Parsed task parameters
 */
export async function parseTaskDescription(description: string) {
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
export async function getTrainingTasks() {
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
export async function getTrainingTask(taskId: string) {
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
 */
export async function deleteTrainingTask(taskId: string) {
  const res = await fetch(`${API_BASE}/tasks/training/${taskId}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to delete training task: ${errorText}`)
  }

  return res.json()
}

/**
 * Create a custom training task
 * @param taskConfig - Training task configuration
 * @returns Task creation result with task_id
 */
export async function createTrainingTask(taskConfig: {
  task_name: string
  task_type: 'classification' | 'segmentation'
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
  }
  model: {
    aggregator: string
    backbone?: string  // For patch-level tasks
    learning_rate: number
    epochs: number
    optimizer: string
    batch_size: number
  }
}) {
  const res = await fetch(`${API_BASE}/tasks/training`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(taskConfig)
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
  thumbnail: {
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
  log_file: {
    path: string
    size: number
    exists: boolean
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
  orphaned_thumbnails: OrphanedFile[]
  orphaned_masks: OrphanedFile[]
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
