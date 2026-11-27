import { API_BASE } from '../config'
import { createPersistentCache, PERSISTENT_CACHE_TTL } from '../lib/utils/cache'
import type { TaskType } from '../constants/training'
import { apiFetch } from './client'

// ============================================================================
// Storage Configuration & Migration
// ============================================================================

export interface StorageConfig {
  uploads_dir: string
  source?: 'env' | 'config' | 'default' | string
}

export async function getStorageConfig(): Promise<StorageConfig> {
  return apiFetch<StorageConfig>(`${API_BASE}/storage/config`, undefined, 'Failed to load storage config')
}

export async function updateStorageConfig(
  uploads_dir: string
): Promise<{ uploads_dir: string; restart_required: boolean; message?: string }> {
  return apiFetch(
    `${API_BASE}/storage/config`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uploads_dir }),
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

export async function startMigration(targetPath: string, deleteSource: boolean = false): Promise<void> {
  await apiFetch<{ message: string }>(
    `${API_BASE}/storage/migrate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_path: targetPath, delete_source: deleteSource }),
    },
    'Failed to start migration'
  )
}

export async function getMigrationStatus(): Promise<MigrationStatus> {
  return apiFetch<MigrationStatus>(
    `${API_BASE}/storage/migration/status`,
    undefined,
    'Failed to get migration status'
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
  quick?: boolean
  ai_results: {
    path: string
    size: number
    exists: boolean
    file_count: number
    wsi_dir_count: number
  }
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
    exists?: boolean
  }>
  total_size: number
  total_size_mb: number
  total_size_gb: number
  total_files: number
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
export async function getTrainingTaskStorageInfo(
  task_id: string,
  options: { quick?: boolean } = {}
): Promise<TrainingTaskStorageInfo> {
  const quickParam = options.quick ? '?quick=true' : ''
  return apiFetch<TrainingTaskStorageInfo>(
    `${API_BASE}/storage/training/${encodeURIComponent(task_id)}${quickParam}`,
    undefined,
    'Failed to get training task storage info'
  )
}

export type StorageItemState = 'orphaned' | 'cached' | 'referenced' | 'recent' | 'managed'
export interface InventoryCategory {
  category: string; size: number; allocated: number; files: number; links: number
  items: number; reclaimable: number; orphaned: number; cached: number
  states: Record<StorageItemState, { items: number; allocated: number }>
}
export interface InventoryOperation {
  id: string; kind: string; status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  processed: number; total: number; error: string | null
  result: { stage?: string; deleted?: number; skipped?: number; freed?: number; total?: number } | null
}
export interface StorageInventory {
  generation: string | null; scanned_at: number | null; size: number; allocated: number
  files: number; links: number; categories: InventoryCategory[]; operation: InventoryOperation | null
}
export interface InventoryItem {
  id: string; path: string; category: string; owner: string; state: StorageItemState
  reason: string; size: number; allocated: number; files: number; links: number
}
export interface InventoryPage { generation: string | null; items: InventoryItem[]; next_cursor: string | null; total: number; allocated: number }
export type InventorySelection = {
  generation: string; category?: string; state: 'orphaned' | 'cached'
} & ({ scope: 'selected'; ids: string[] } | { scope: 'all'; excluded_ids: string[] })
export const getStorageInventory = (signal?: AbortSignal) => apiFetch<StorageInventory>(`${API_BASE}/storage/inventory`, { signal })
export const scanStorageInventory = () => apiFetch<InventoryOperation>(`${API_BASE}/storage/inventory/scan`, { method: 'POST' })
export function getInventoryItems(category: string, state: string, cursor?: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: '50' })
  if (category) params.set('category', category)
  if (state) params.set('state', state)
  if (cursor) params.set('cursor', cursor)
  return apiFetch<InventoryPage>(`${API_BASE}/storage/inventory/items?${params}`, { signal })
}
export const cleanStorageInventory = (selection: InventorySelection) =>
  apiFetch<InventoryOperation>(`${API_BASE}/storage/inventory/cleanup`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection) })
export const cancelInventoryOperation = (id: string) => apiFetch<InventoryOperation>(`${API_BASE}/storage/inventory/operations/${encodeURIComponent(id)}`, { method: 'DELETE' })

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
  has_annotation_json?: boolean  // Whether a matching COCO JSON annotation file exists
}

export interface ScanDirectoryResponse {
  scan_id: string
  directory: string
  files: ScannedWSIFile[]
  total_count: number
  valid_count: number
  total_size: number
  wsi_count: number
  patch_count: number
  annotation_scan_enabled?: boolean
  page: number
  page_size: number
  total_pages: number
}

export interface ScanDirectoryOptions {
  scanId?: string
  taskType?: TaskType
  page?: number
  pageSize?: number
}

/**
 * Scan a directory for WSI files (Admin only)
 * @param directoryPath - Path to the directory to scan
 * @returns Scanned files with validation info
 * @throws {ApiError} If the request fails
 */
export async function scanDirectory(directoryPath: string, options: ScanDirectoryOptions = {}): Promise<ScanDirectoryResponse> {
  return apiFetch<ScanDirectoryResponse>(
    `${API_BASE}/storage/scan-directory`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        directory_path: directoryPath,
        scan_id: options.scanId,
        task_type: options.taskType,
        page: options.page ?? 1,
        page_size: options.pageSize ?? 100,
      })
    },
    'Failed to scan directory'
  )
}

export interface BatchRegisterFileInfo {
  path: string
  format_type: 'standard' | 'mrxs' | 'tmap'
  associated_data?: string | string[] | null  // string for mrxs (data folder), string[] for tmap (DT files)
  data_type?: 'wsi' | 'patch'
}

export interface BatchRegisterRequest {
  files?: BatchRegisterFileInfo[]
  dataset_id?: string
  dataset_name?: string
  scan_root?: string
  scan_id?: string
  select_all_valid?: boolean
  selected_paths?: string[]
  excluded_paths?: string[]
  aggregation_level?: 'case' | 'file'
  task_type?: TaskType
  is_public?: boolean
  default_label?: string
  default_event_time?: number
  default_event_status?: number
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
export async function checkExternalFiles(datasetId?: string,onProgress?:(value:StorageInspection)=>void,signal?:AbortSignal): Promise<CheckExternalFilesResponse> {
  return awaitInspection<CheckExternalFilesResponse>('external-health',onProgress,signal,datasetId)
}

export type InspectionKind='external-health';
export interface StorageInspection {id?:string;kind:InspectionKind;status:'idle'|'queued'|'running'|'completed'|'failed'|'cancelled'|'interrupted';processed?:number;total?:number|null;stage?:string;started_at?:number;finished_at?:number;error?:string;reused?:boolean;result?:unknown}
export const getStorageInspection=(kind:InspectionKind,scope='',result=false,signal?:AbortSignal)=>apiFetch<StorageInspection>(`${API_BASE}/storage/inspections/${kind}?${new URLSearchParams({dataset_id:scope,result:String(result)})}`,{signal});
export const cancelStorageInspection=(kind:InspectionKind,scope='')=>apiFetch(`${API_BASE}/storage/inspections/${kind}?${new URLSearchParams({dataset_id:scope})}`,{method:'DELETE'});
export async function awaitInspection<T>(kind:InspectionKind,onProgress?:(value:StorageInspection)=>void,signal?:AbortSignal,scope='',resume=false):Promise<T>{
 const url=`${API_BASE}/storage/inspections/${kind}?${new URLSearchParams({dataset_id:scope})}`;
 let value=await apiFetch<StorageInspection>(url,{method:resume?'GET':'POST',signal});
 while(true){
  onProgress?.(value);
  if(value.status==='completed'){const finished=await getStorageInspection(kind,scope,true,signal);if(finished.status==='completed')return finished.result as T;value=finished;continue}
  if(['failed','cancelled','interrupted','idle'].includes(value.status))throw new Error(value.error||value.status);
  await new Promise<void>((resolve,reject)=>{if(signal?.aborted){reject(new DOMException('Aborted','AbortError'));return}const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))};const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve()},800);signal?.addEventListener('abort',abort,{once:true})});
  value=await getStorageInspection(kind,scope,false,signal);
 }
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
  task_type: 'batch_import' | 'delete_external' | 'batch_update_metadata' | 'unbind_dataset' | 'delete_dataset' | 'cleanup_empty_datasets' | 'scan_directory'
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
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
  }> | ScanDirectoryTaskResult | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ScanDirectoryTaskResult {
  scan_id: string
  directory: string
  total_count: number
  valid_count: number
  wsi_count: number
  patch_count: number
  page_size: number
  annotation_scan_enabled: boolean
}

/**
 * Response from starting a batch import task
 */
export interface StartBatchImportResponse {
  task_id: string
  message: string
  total_files: number
}

export interface StartScanDirectoryTaskResponse {
  task_id: string
  message: string
}

/**
 * Response from starting a delete external task
 */
export interface StartDeleteExternalResponse {
  task_id: string
  message: string
  total_files: number
}

export interface StartDeleteWSIsRequest {
  wsi_ids: string[]
}

export interface StartDeleteWSIsResponse {
  task_id: string
  message: string
  total_items: number
}

export interface StartDeleteDatasetRequest {
  dataset_id: string
}

export interface StartDeleteDatasetResponse {
  task_id: string
  message: string
  dataset_id: string
  dataset_name: string
  total_items: number
}

export interface StartCleanupEmptyDatasetsResponse {
  task_id: string
  message: string
  total_items: number
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

export async function startScanDirectoryTask(
  directoryPath: string,
  options: Pick<ScanDirectoryOptions, 'taskType' | 'pageSize'> = {}
): Promise<StartScanDirectoryTaskResponse> {
  return apiFetch<StartScanDirectoryTaskResponse>(
    `${API_BASE}/storage/tasks/scan-directory`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        directory_path: directoryPath,
        task_type: options.taskType,
        page_size: options.pageSize ?? 100,
      })
    },
    'Failed to start directory scan task'
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

export async function startDeleteWSIsTask(
  request: StartDeleteWSIsRequest
): Promise<StartDeleteWSIsResponse> {
  return apiFetch<StartDeleteWSIsResponse>(
    `${API_BASE}/storage/tasks/delete-wsis`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    },
    'Failed to start delete WSI task'
  )
}

/**
 * Start an asynchronous dataset deletion task.
 * The heavy work runs on the server so the UI does not block on per-file requests.
 */
export async function startDeleteDatasetTask(
  request: StartDeleteDatasetRequest
): Promise<StartDeleteDatasetResponse> {
  return apiFetch<StartDeleteDatasetResponse>(
    `${API_BASE}/storage/tasks/delete-dataset`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    },
    'Failed to start delete dataset task'
  )
}

/**
 * Start an asynchronous cleanup task that removes historical empty datasets.
 */
export async function startCleanupEmptyDatasetsTask(): Promise<StartCleanupEmptyDatasetsResponse> {
  return apiFetch<StartCleanupEmptyDatasetsResponse>(
    `${API_BASE}/storage/tasks/cleanup-empty-datasets`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    },
    'Failed to start cleanup empty datasets task'
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
 * Get storage task status by ID
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
 * Cancel a storage task owned by the current user
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
