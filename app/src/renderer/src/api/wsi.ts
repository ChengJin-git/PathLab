import { API_BASE } from '../config'
import { createKeyedCache, ACTIVITY_CACHE_TTL } from '../lib/utils/cache'
import type { TaskType } from '../constants/training'
import { apiFetch, apiFetchBlob, buildSearchParams, buildAuthHeaders, ApiError, getErrorCodeFromStatus, downloadApiFile, downloadBlobFile, getAuthToken, type DownloadApiFileResult, type PaginatedResponse } from './client'
import { invalidateHeatmapAvailabilityCache } from './heatmap'
import { getWorkspaceSelection } from '../lib/workspaceSelection'

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
  parent_wsi_name?: string | null
  parent_dataset_name?: string | null
  // Permission flag - whether user can delete this WSI
  can_delete?: boolean
  // External storage availability (only present for external-backed data)
  availability?: ExternalAvailability | null
}

export interface ExternalAvailability {
  status: 'unknown' | 'available' | 'unavailable' | 'stale'
  reason?: string | null
  counts?: { available: number; total: number } | null
  external_count?: number | null
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
export interface WSIListResponse extends PaginatedResponse<WSISummary> {
  total_cases: number
  has_multi_slide_cases: boolean
}

export interface ImageRecommendationQuery {
  dataset_id?: string
  data_type?: 'wsi' | 'patch'
  label?: string
  pred?: string
  has_predictions?: boolean
  correct_prediction?: boolean
  event_status?: number
  segmentation_class?: string
  task_id?: string
  feature_extractor?: string
  aggregator?: string
  result_task_type?: 'patch_segmentation'
  query?: string
  limit: number
}

export async function fetchRecommendedImages(query: ImageRecommendationQuery): Promise<{
  items: Array<WSISummary & { result_prediction?: string | null }>
}> {
  const params = buildSearchParams({ ...query })
  return apiFetch(`${API_BASE}/wsi/recommendations?${params}`, undefined, 'Failed to load recommended images')
}

export interface DatasetSourceOptionsResponse {
  items: string[]
}

/**
 * Lightweight WSI ID list response for bulk selection.
 */
export interface WSIIdListResponse {
  items: string[]
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
export async function checkDuplicateFilenames(filenames: string[], datasetId: string): Promise<CheckDuplicatesResponse> {
  if (filenames.length === 0) {
    return { duplicates: [], new: [] }
  }

  return apiFetch<CheckDuplicatesResponse>(
    `${API_BASE}/wsi/check-duplicates`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({filenames, dataset_id:datasetId})
    },
    'Failed to check duplicate filenames'
  )
}

// Cache for fetchWSIList (keyed by datasetId + query params)
const wsiListCache = createKeyedCache<WSIListResponse>(ACTIVITY_CACHE_TTL)
const datasetsListCache = createKeyedCache<DatasetsListResponse>(ACTIVITY_CACHE_TTL)

export interface WSIListPaginationOptions {
  page: number
  page_size: number
  search?: string
  forceRefresh?: boolean
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

function buildWSIListCacheKey(
  datasetId?: string,
  dataLevel?: string,
  options?: WSIListPaginationOptions
): string {
  return JSON.stringify({
    user: getAuthToken(),
    workspace: getWorkspaceSelection().workspaceId,
    datasetId: datasetId ?? null,
    dataLevel: dataLevel ?? null,
    page: options?.page ?? 1,
    page_size: options?.page_size ?? 20,
    search: options?.search ?? null,
    sort_by: options?.sort_by ?? null,
    sort_order: options?.sort_order ?? null,
  })
}

export async function fetchWSIList(
  datasetId?: string,
  dataLevel?: string,
  options?: WSIListPaginationOptions
): Promise<WSIListResponse> {
  const params = buildSearchParams({
    dataset_id: datasetId,
    data_type: dataLevel,
  })

  const page = options?.page ?? 1
  const pageSize = options?.page_size ?? 20

  if (options?.search) {
    params.set('search', options.search)
  }

  if (options?.sort_by) {
    params.set('sort_by', options.sort_by)
  }
  if (options?.sort_order) {
    params.set('sort_order', options.sort_order)
  }

  params.set('page', String(page))
  params.set('page_size', String(pageSize))

  const cacheKey = buildWSIListCacheKey(datasetId, dataLevel, options)
  const queryString = params.toString()
  const url = `${API_BASE}/wsi?${queryString}`

  return wsiListCache.get(
    cacheKey,
    () => apiFetch<WSIListResponse>(url, undefined, 'Failed to load WSI list from database'),
    options?.forceRefresh === true
  )
}

export async function fetchAllWSIList(
  datasetId?: string,
  dataLevel?: string,
  options?: Omit<WSIListPaginationOptions, 'page'>
): Promise<WSIListResponse> {
  const pageSize = options?.page_size ?? 100
  const allItems: WSISummary[] = []
  let page = 1
  let totalUnits = 0
  let hasMultiSlideCases = false

  while (true) {
    const response = await fetchWSIList(datasetId, dataLevel, {
      ...options,
      page,
      page_size: pageSize,
      forceRefresh: true,
    })

    if (!allItems.length) {
      totalUnits = (response.total_cases ?? 0) > 0 ? (response.total_cases ?? 0) : (response.total ?? 0)
      hasMultiSlideCases = response.has_multi_slide_cases ?? false
    }

    allItems.push(...response.items)

    const pageUnitCount = (response.total_cases ?? 0) > 0 ? (response.total_cases ?? 0) : (response.total ?? 0)
    const totalPages = Math.ceil(pageUnitCount / pageSize)
    if (response.items.length === 0 || page >= totalPages) {
      break
    }

    page++
  }

  return {
    items: allItems,
    total: allItems.length,
    total_cases: totalUnits,
    page: 1,
    page_size: pageSize,
    has_multi_slide_cases: hasMultiSlideCases,
  }
}

export async function prefetchWSIList(
  datasetId?: string,
  dataLevel?: string,
  options?: WSIListPaginationOptions
): Promise<void> {
  try {
    await fetchWSIList(datasetId, dataLevel, options)
  } catch {
    // Ignore prefetch failures so they don't affect the active page.
  }
}

/**
 * Fetch only WSI IDs for lightweight bulk selection.
 * Always uses an explicit no-cache query.
 */
export async function fetchWSIIds(
  datasetId: string,
  dataLevel?: string,
  search?: string
): Promise<WSIIdListResponse> {
  const params = buildSearchParams({
    dataset_id: datasetId,
    data_type: dataLevel,
    search,
  })

  const url = `${API_BASE}/wsi/ids?${params.toString()}`
  return apiFetch<WSIIdListResponse>(url, undefined, 'Failed to load WSI IDs from database')
}

/**
 * Invalidate the WSI list cache (call after mutations like upload/delete)
 */
export function invalidateWSIListCache(): void {
  wsiListCache.invalidateAll()
  datasetsListCache.invalidateAll()
}

export interface DatasetSplitSummary {
  has_predefined_splits?: boolean
  predefined_split_counts?: { train: number; val: number; test: number }
  predefined_split_unit?: 'files' | 'cases'
}

/**
 * Dataset summary returned by dataset list endpoints.
 */
export interface DatasetSummary extends DatasetSplitSummary {
  description?: string
  metadata: Record<string, unknown>
  revision: number
  tasks: { task_type: TaskType; description: string; labelled_count: number; sample_count: number; classes: string[]; status: 'unlabelled' | 'partial' | 'complete' }[]
  dataset_id: string | null  // UUID for API calls (null for uncategorized)
  dataset_name: string  // Display name
  user_id: string | null  // Dataset owner
  username?: string | null  // Username of dataset owner (only for admin users)
  source_organ?: string | null
  parent_dataset_id?: string | null
  parent_dataset_name?: string | null
  file_count: number
  total_size: number
  data_type: 'wsi' | 'patch'  // Data type: WSI collection or Patch collection
  task_types: TaskType[]
  aggregation_level: 'case' | 'file'  // Aggregation level: case-level or file-level dataset
  is_public?: boolean
  can_delete?: boolean
  availability?: ExternalAvailability | null
  coco_categories?: Array<{ id: number; name: string; supercategory?: string }>
  num_coco_categories?: number
}

/**
 * Datasets list response
 */
export interface DatasetsListResponse {
  items: DatasetSummary[]
  total: number
  page?: number
  page_size?: number
}

export interface DatasetListQueryOptions {
  purpose?: 'browse' | 'upload'
  page?: number
  page_size?: number
  search?: string
  task_type?: TaskType
  aggregation_level?: 'file' | 'case'
  source_organ?: string
  is_public?: boolean
  forceRefresh?: boolean
}

function buildDatasetListCacheKey(dataLevel?: string, options?: DatasetListQueryOptions): string {
  return JSON.stringify({
    user: getAuthToken(),
    workspace: getWorkspaceSelection().workspaceId,
    dataLevel: dataLevel ?? null,
    purpose: options?.purpose ?? 'browse',
    search: options?.search ?? null,
    task_type: options?.task_type ?? null,
    aggregation_level: options?.aggregation_level ?? null,
    source_organ: options?.source_organ ?? null,
    is_public: options?.is_public ?? null,
    page_size: options?.page_size ?? 20,
    page: options?.page ?? 1,
  })
}

export async function fetchDatasets(
  dataLevel?: string,
  options?: DatasetListQueryOptions
): Promise<DatasetsListResponse> {
  const page = options?.page ?? 1
  const pageSize = options?.page_size ?? 20

  const params = buildSearchParams({
    data_type: dataLevel,
    purpose: options?.purpose,
    search: options?.search || undefined,
    task_type: options?.task_type,
    aggregation_level: options?.aggregation_level,
    source_organ: options?.source_organ,
    is_public: options?.is_public,
    page_size: pageSize,
    page: page,
  })
  const queryString = params.toString()
  const url = queryString ? `${API_BASE}/wsi/datasets?${queryString}` : `${API_BASE}/wsi/datasets`
  const cacheKey = buildDatasetListCacheKey(dataLevel, options)

  return datasetsListCache.get(
    cacheKey,
    () => apiFetch<DatasetsListResponse>(url, undefined, 'Failed to load datasets from database'),
    options?.forceRefresh === true
  )
}

export async function fetchAllDatasets(
  dataLevel?: string,
  options?: Omit<DatasetListQueryOptions, 'page'>
): Promise<DatasetsListResponse> {
  const pageSize = options?.page_size ?? 100
  const allItems: DatasetSummary[] = []
  let page = 1
  let total = 0

  while (true) {
    const response = await fetchDatasets(dataLevel, {
      ...options,
      page,
      page_size: pageSize,
      forceRefresh: options?.forceRefresh ?? false,
    })

    if (!allItems.length) {
      total = response.total ?? 0
    }

    allItems.push(...response.items)

    if (response.items.length === 0 || allItems.length >= total) {
      break
    }

    page++
  }

  return {
    items: allItems,
    total: allItems.length,
    page: 1,
    page_size: pageSize,
  }
}

export async function prefetchDatasets(
  dataLevel?: string,
  options?: DatasetListQueryOptions
): Promise<void> {
  try {
    await fetchDatasets(dataLevel, options)
  } catch {
    // Ignore prefetch failures so they don't affect the active page.
  }
}

export async function fetchDatasetSourceOptions(): Promise<string[]> {
  const url = `${API_BASE}/wsi/dataset-source-options`
  const response = await apiFetch<DatasetSourceOptionsResponse>(url, undefined, 'Failed to load dataset source options')
  return response.items ?? []
}

export async function fetchDatasetSummary(datasetId: string, purpose: 'browse' | 'upload' = 'browse'): Promise<DatasetSummary> {
  return apiFetch<DatasetSummary>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}${purpose === 'upload' ? '?purpose=upload' : ''}`,
    undefined,
    'Failed to load dataset summary'
  )
}

export interface DatasetPropertiesUpdate {
  data_type?: 'wsi' | 'patch'
  parent_dataset_id?: string | null
  acquisition_metadata?: Record<string, unknown> | null
  task_descriptions?: Record<string, string>
  remove_metadata?: string[]
  name?: string
  task_types?: TaskType[]
  description?: string
  metadata?: Record<string, unknown>
  revision?: number
  aggregation_level?: 'case' | 'file'
  source?: string | null
  is_public?: boolean
}

export interface UpdatedDatasetProperties {
  dataset_id: string
  name: string
  data_type: 'wsi' | 'patch'
  task_types: TaskType[]
  aggregation_level: 'case' | 'file'
  source_organ: string | null
  is_public: boolean
  description: string
  metadata: Record<string, unknown>
  revision: number
}

export async function updateDatasetProperties(datasetId: string, updates: DatasetPropertiesUpdate): Promise<{ dataset: UpdatedDatasetProperties }> {
  const result = await apiFetch<{ dataset: UpdatedDatasetProperties }>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/properties`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) },
    'Failed to update dataset properties',
  )
  invalidateWSIListCache()
  return result
}

/**
 * Options for exporting dataset labels
 */
export interface ExportLabelsOptions {
  generateSplit?: boolean
  strategy?: 'random' | 'k_fold'
  nSplits?: number
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
): Promise<DownloadApiFileResult> {
  const strategy = options.strategy ?? 'random'
  const params = buildSearchParams(
    options.generateSplit
      ? {
          generate_split: 'true',
          strategy,
          ...(strategy === 'k_fold' ? { n_splits: options.nSplits ?? 5 } : {}),
          seed: options.seed ?? 42,
          stratified: options.stratified !== false,
          ...(strategy === 'random'
            ? {
                train_ratio: options.trainRatio ?? 0.7,
                val_ratio: options.valRatio ?? 0.1,
                test_ratio: options.testRatio ?? 0.2,
              }
            : {}),
        }
      : undefined
  )

  const queryString = params.toString()
  const url = `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/export-labels${queryString ? `?${queryString}` : ''}`

  return downloadApiFile(url, 'dataset_labels.csv', undefined, 'Failed to export labels')
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

  const result = await apiFetch<UploadSplitsResponse>(
    `${API_BASE}/wsi/datasets/${encodeURIComponent(datasetId)}/splits`,
    { method: 'POST', body: formData },
    'Failed to upload dataset splits'
  )
  invalidateWSIListCache()
  return result
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
    source_organ?: string
    aggregation_level?: 'case' | 'file'
    is_public?: boolean
    task_type?: TaskType
    label?: string
    case_id?: string
    age?: number
    gender?: string
    wsi_id?: string
    event_time?: number
    event_status?: number
    split?: string
    onProgress?: (progress: number) => void
    associatedFiles?: File[]
    signal?: AbortSignal
  }
): Promise<WSIUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  if (options?.dataset_id) formData.append('dataset_id', options.dataset_id)
  if (options?.dataset_name) formData.append('dataset_name', options.dataset_name)
  if (options?.source_organ) formData.append('source_organ', options.source_organ)
  if (options?.aggregation_level) formData.append('aggregation_level', options.aggregation_level)
  if (options?.is_public !== undefined) formData.append('is_public', options.is_public.toString())
  if (options?.task_type) formData.append('task_type', options.task_type)
  if (options?.label) formData.append('label', options.label)
  if (options?.case_id) formData.append('case_id', options.case_id)
  if (options?.age !== undefined) formData.append('age', options.age.toString())
  if (options?.gender) formData.append('gender', options.gender)
  if (options?.wsi_id) formData.append('wsi_id', options.wsi_id)
  if (options?.event_time !== undefined) formData.append('event_time', options.event_time.toString())
  if (options?.event_status !== undefined) formData.append('event_status', options.event_status.toString())
  if (options?.split) formData.append('split', options.split)

  // Add associated files for MRXS/TMAP formats
  if (options?.associatedFiles && options.associatedFiles.length > 0) {
    options.associatedFiles.forEach((assocFile) => {
      formData.append('associated_files', assocFile)
    })
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()

    // Handle AbortSignal for cancellation support
    if (options?.signal) {
      if (options.signal.aborted) {
        reject(new Error('Upload aborted'))
        return
      }
      options.signal.addEventListener('abort', abort, {once:true})
    }
    xhr.addEventListener('loadend',()=>options?.signal?.removeEventListener('abort',abort))

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
        let detail=''
        try { const parsed=JSON.parse(xhr.responseText);detail=typeof parsed.detail==='string' ? parsed.detail : '' } catch { /* non-JSON upstream error */ }
        reject(new ApiError(detail || `Upload failed (${xhr.status})`,xhr.status,getErrorCodeFromStatus(xhr.status),detail))
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
    buildAuthHeaders().forEach((value,name)=>xhr.setRequestHeader(name,value))
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
    source_organ?: string
    aggregation_level?: 'case' | 'file'
    is_public?: boolean
    task_type?: TaskType
    label?: string
    case_id?: string
    wsi_id?: string
    age?: number
    gender?: string
    event_time?: number
    event_status?: number
    split?: string
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
        source_organ: options?.source_organ,
        aggregation_level: options?.aggregation_level,
        is_public: options?.is_public,
        task_type: options?.task_type,
        label: options?.label,
        case_id: options?.case_id,
        wsi_id: options?.wsi_id,
        age: options?.age,
        gender: options?.gender,
        event_time: options?.event_time,
        event_status: options?.event_status,
        split: options?.split,
      }),
      signal: options?.signal
    },
    'Failed to register WSI by path'
  )
  invalidateWSIListCache()
  return result
}

/**
 * Download CSV template for batch WSI metadata configuration.
 * @param taskType - Canonical task id.
 * @throws {ApiError} If the request fails
 */
export async function downloadCSVTemplate(
  taskType: TaskType = 'wsi_classification'
): Promise<void> {
  const filenames: Record<TaskType, string> = {
    wsi_classification: 'wsi_classification_metadata_template.csv',
    patch_classification: 'patch_classification_metadata_template.csv',
    wsi_survival: 'wsi_survival_metadata_template.csv',
    patch_segmentation: 'segmentation_metadata_template.csv',
    patch_detection: 'detection_metadata_template.csv',
  }
  const blob = await apiFetchBlob(
    `${API_BASE}/wsi/upload/csv/template?task_type=${taskType}`,
    undefined,
    'Failed to download CSV template'
  )
  downloadBlobFile(blob, filenames[taskType])
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
    status: 'scheduled'
    task_id: string
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
 * @returns Delete result
 * @throws {ApiError} If the request fails
 */
export async function deleteWSI(wsi_id: string): Promise<WSIDeleteResult> {
  const result = await apiFetch<WSIDeleteResult>(
    `${API_BASE}/wsi/${wsi_id}`,
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
    event_time?: number
    event_status?: number
  }
): Promise<WSIMetadataUpdateResult> {
  const result = await apiFetch<WSIMetadataUpdateResult>(
    `${API_BASE}/wsi/${wsi_id}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata)
    },
    'Failed to update WSI metadata'
  )
  invalidateWSIListCache()
  return result
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
