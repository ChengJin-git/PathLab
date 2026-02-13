import { API_BASE } from '../config'
import { createPersistentCache, PERSISTENT_CACHE_TTL } from '../lib/cache'
import { apiFetch } from './client'

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
  cached?: boolean
  stale?: boolean
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

/**
 * Response from starting a reset derived data task
 */
export interface StartResetDerivedDataResponse {
  task_id: string
  message: string
  total_items: number
}

/**
 * Start a reset derived data background task
 * This is a DESTRUCTIVE operation that deletes all processed data
 * @returns Task info with task_id for tracking
 * @throws {ApiError} If the request fails
 */
export async function resetDerivedData(): Promise<StartResetDerivedDataResponse> {
  return apiFetch<StartResetDerivedDataResponse>(
    `${API_BASE}/storage/reset-derived-data`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    },
    'Failed to start reset derived data task'
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
  aggregation_level?: 'case' | 'file'  // Default: 'file' - how to organize data
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
 * External dataset summary info returned from get-external-datasets-summary endpoint.
 * Lightweight: only contains dataset name and file count (no file availability status).
 */
export interface ExternalDatasetInfo {
  dataset_id: string | null
  dataset_name: string
  total_files: number
}

/**
 * Response from get-external-datasets-summary endpoint
 */
export interface ExternalDatasetsResponse {
  datasets: ExternalDatasetInfo[]
  total: number
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
 * Get a lightweight summary of datasets containing externally imported WSI files (Admin only)
 * Uses persistent localStorage cache for instant display after login.
 * @param forceRefresh - Force refresh from server, ignoring cache
 * @returns List of datasets with external file counts (no availability status)
 * @throws {ApiError} If the request fails
 */
export async function getExternalDatasets(forceRefresh = false): Promise<ExternalDatasetsResponse> {
  return externalDatasetsCache.get(
    () => apiFetch<ExternalDatasetsResponse>(
      `${API_BASE}/storage/external-datasets-summary`,
      undefined,
      'Failed to get external datasets summary'
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

