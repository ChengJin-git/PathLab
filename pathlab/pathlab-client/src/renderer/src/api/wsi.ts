import { API_BASE } from '../config'
import { createKeyedCache, DEFAULT_CACHE_TTL } from '../lib/cache'
import { apiFetch, apiFetchBlob, downloadBlobFile, getAuthToken } from './client'
import { invalidateHeatmapAvailabilityCache } from './heatmap'

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
  has_segmentation_annotation?: boolean
  file_extension: string  // e.g. ".svs", ".png" - for file type determination (wsi_path no longer exposed)
  age: number | null
  gender: string | null
  source: string | null
  // Survival analysis fields
  event_time: number | null
  event_status: number | null
  // Split assignment (from CSV upload)
  split: string | null  // "train", "val", "test"
  file_size: number | null
  data_type?: 'wsi' | 'patch' | null
  created_at: string | null
  // Detail-only fields (present in to_dict() but not in to_summary_dict())
  mpp?: number | null
  vendor?: string | null
  width?: number | null
  height?: number | null
  magnification?: number | null
  updated_at?: string | null
  // Parent WSI reference (cropped region source)
  parent_wsi_id?: string | null
  // Permission flag - whether user can delete this WSI
  can_delete?: boolean
}

/**
 * WSI Detail response including latest result
 */
export interface WSIDetail {
  wsi_id: string
  meta: WSISummary
  last_run: import('./results').AIResult | null
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
 * WSI List response (server-side case-level pagination)
 */
export interface WSIListResponse {
  items: WSISummary[]
  total: number
  total_cases: number
  page: number
  page_size: number
  has_multi_slide_cases: boolean
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

// Cache for fetchWSIList (keyed by datasetId + dataLevel) — only used for non-paginated requests
const wsiListCache = createKeyedCache<WSIListResponse>(DEFAULT_CACHE_TTL)

/**
 * Pagination options for fetchWSIList.
 * When provided, the request uses server-side case-level pagination (no caching).
 * When omitted, all items are returned with caching (page_size=0).
 */
export interface WSIListPaginationOptions {
  page: number
  page_size: number
  search?: string
}

/**
 * Fetch WSI list from database via Gateway API.
 *
 * Without `options`: returns ALL items (page_size=0) with caching.
 * With `options`: returns a single page of case-grouped items (no caching).
 *
 * @param datasetId - Optional dataset UUID to filter by
 * @param dataLevel - Optional filter: "wsi" for WSI files, "patch" for image files
 * @param options - Optional pagination/search params for server-side pagination
 * @throws {ApiError} If the request fails
 */
export async function fetchWSIList(
  datasetId?: string,
  dataLevel?: string,
  options?: WSIListPaginationOptions
): Promise<WSIListResponse> {
  const params = new URLSearchParams()
  if (datasetId) {
    params.set('dataset_id', datasetId)
  }
  if (dataLevel) {
    params.set('data_type', dataLevel)
  }

  if (options) {
    // Paginated request — no caching
    params.set('page', String(options.page))
    params.set('page_size', String(options.page_size))
    if (options.search) {
      params.set('search', options.search)
    }
    const url = `${API_BASE}/wsi?${params.toString()}`
    return apiFetch<WSIListResponse>(url, undefined, 'Failed to load WSI list from database')
  }

  // Non-paginated request — return all items with caching
  params.set('page_size', '0')
  const cacheKey = `${datasetId || '__all__'}:${dataLevel || '__all__'}`
  const queryString = params.toString()
  const url = `${API_BASE}/wsi?${queryString}`

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
  username?: string | null  // Username of dataset owner (only for admin users)
  file_count: number
  total_size: number
  data_type: 'wsi' | 'patch'  // Data type: WSI collection or Patch collection
  task_type: 'classification' | 'survival' | 'segmentation' // Task type: classification, survival, or segmentation
  aggregation_level: 'case' | 'file'  // Aggregation level: case-level or file-level dataset
  // Permission flag - whether user can delete this dataset
  can_delete?: boolean
  // Pre-defined split information (from CSV upload)
  has_predefined_splits?: boolean
  predefined_split_counts?: { train: number; val: number; test: number }
  // COCO categories for segmentation datasets
  coco_categories?: Array<{ id: number; name: string; supercategory?: string }>
  num_coco_categories?: number
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
    params.append('data_type', dataLevel)
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
  new_type: 'classification' | 'survival' | 'segmentation'
  updated_count: number
}

/**
 * Update dataset type (classification, survival, or segmentation)
 * @param datasetId - Dataset UUID
 * @param datasetType - New type: "classification", "survival", or "segmentation"
 * @throws {ApiError} If the request fails
 */
export async function updateDatasetType(
  datasetId: string,
  datasetType: 'classification' | 'survival' | 'segmentation'
): Promise<UpdateDatasetTypeResponse> {
  return apiFetch<UpdateDatasetTypeResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/type`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_type: datasetType })
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
  new_aggregation_level: 'case' | 'file'
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
      body: JSON.stringify({ aggregation_level: dataLevel })
    },
    'Failed to update dataset data level'
  )
}

/**
 * Options for exporting dataset labels
 */
export interface ExportLabelsOptions {
  generateSplit?: boolean
  seed?: number
  stratified?: boolean
  trainRatio?: number
  valRatio?: number
  testRatio?: number
}

/**
 * Export dataset labels as CSV file
 *
 * If dataset has predefined splits, exports them directly.
 * If generateSplit=true and no predefined splits, generates splits using training logic.
 *
 * @param datasetId - Dataset UUID
 * @param options - Export options (split generation parameters)
 * @throws {ApiError} If the request fails
 */
export async function exportDatasetLabels(
  datasetId: string,
  options: ExportLabelsOptions = {}
): Promise<void> {
  const params = new URLSearchParams()

  if (options.generateSplit) {
    params.append('generate_split', 'true')
    params.append('seed', String(options.seed ?? 42))
    params.append('stratified', String(options.stratified !== false))
    params.append('train_ratio', String(options.trainRatio ?? 0.7))
    params.append('val_ratio', String(options.valRatio ?? 0.1))
    params.append('test_ratio', String(options.testRatio ?? 0.2))
  }

  const url = `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/export-labels?${params.toString()}`

  // Fetch with authentication
  const token = getAuthToken()
  const response = await fetch(url, {
    headers: {
      'Authorization': token ? `Bearer ${token}` : ''
    }
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(errorText || 'Failed to export labels')
  }

  // Trigger browser download
  const blob = await response.blob()
  const downloadUrl = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = downloadUrl

  // Extract filename from Content-Disposition header
  const contentDisposition = response.headers.get('Content-Disposition')
  const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
  a.download = filenameMatch ? filenameMatch[1] : 'dataset_labels.csv'

  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(downloadUrl)
}

/**
      body: JSON.stringify({ aggregation_level: dataLevel })
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
    dataset_id?: string
    dataset_name?: string
    aggregation_level?: 'case' | 'file'
    task_type?: 'classification' | 'survival' | 'segmentation'
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    wsi_id?: string
    event_time?: number
    event_status?: number
    onProgress?: (progress: number) => void
    associatedFiles?: File[]
    signal?: AbortSignal
  }
): Promise<WSIUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  if (options?.dataset_id) formData.append('dataset_id', options.dataset_id)
  if (options?.dataset_name) formData.append('dataset_name', options.dataset_name)
  if (options?.aggregation_level) formData.append('aggregation_level', options.aggregation_level)
  if (options?.task_type) formData.append('task_type', options.task_type)
  if (options?.label) formData.append('label', options.label)
  if (options?.case_id) formData.append('case_id', options.case_id)
  if (options?.age !== undefined) formData.append('age', options.age.toString())
  if (options?.gender) formData.append('gender', options.gender)
  if (options?.source) formData.append('source', options.source)
  if (options?.wsi_id) formData.append('wsi_id', options.wsi_id)
  if (options?.event_time !== undefined) formData.append('event_time', options.event_time.toString())
  if (options?.event_status !== undefined) formData.append('event_status', options.event_status.toString())

  // Add associated files for MRXS/TMAP formats
  if (options?.associatedFiles && options.associatedFiles.length > 0) {
    options.associatedFiles.forEach((assocFile) => {
      formData.append('associated_files', assocFile)
    })
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    // Handle AbortSignal for cancellation support
    if (options?.signal) {
      if (options.signal.aborted) {
        reject(new Error('Upload aborted'))
        return
      }
      options.signal.addEventListener('abort', () => {
        xhr.abort()
      })
    }

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
          invalidateWSIListCache()
          resolve(result)
        } catch (err) {
          reject(new Error('Failed to parse response'))
        }
      } else {
        reject(new Error(`Failed to upload WSI file: ${xhr.responseText}`))
      }
    })

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
    dataset_id?: string
    dataset_name?: string
    aggregation_level?: 'case' | 'file'
    task_type?: 'classification' | 'survival' | 'segmentation'
    label?: string
    case_id?: string
    wsi_id?: string
    age?: number
    gender?: string
    source?: string
    event_time?: number
    event_status?: number
    signal?: AbortSignal
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
        aggregation_level: options?.aggregation_level,
        task_type: options?.task_type,
        label: options?.label,
        case_id: options?.case_id,
        wsi_id: options?.wsi_id,
        age: options?.age,
        gender: options?.gender,
        source: options?.source,
        event_time: options?.event_time,
        event_status: options?.event_status
      }),
      signal: options?.signal
    },
    'Failed to register WSI by path'
  )
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
 * @param taskType - 'classification', 'survival', or 'segmentation'
 * @throws {ApiError} If the request fails
 */
export async function downloadCSVTemplate(taskType: 'classification' | 'survival' | 'segmentation' = 'classification'): Promise<void> {
  const filenames: Record<string, string> = {
    survival: 'wsi_survival_metadata_template.csv',
    segmentation: 'segmentation_metadata_template.csv',
    classification: 'wsi_classification_metadata_template.csv',
  }
  const blob = await apiFetchBlob(
    `${API_BASE}/wsi/upload/csv/template?task_type=${taskType}`,
    undefined,
    'Failed to download CSV template'
  )
  downloadBlobFile(blob, filenames[taskType] || filenames.classification)
}

/**
 * Download COCO JSON annotation template for segmentation datasets.
 * @throws {ApiError} If the request fails
 */
export async function downloadCocoTemplate(): Promise<void> {
  const blob = await apiFetchBlob(
    `${API_BASE}/wsi/upload/coco/template`,
    undefined,
    'Failed to download COCO template'
  )
  downloadBlobFile(blob, 'segmentation_annotation_template.json')
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

