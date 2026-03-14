import { API_BASE } from '../config'
import { createKeyedCache, DEFAULT_CACHE_TTL } from '../lib/cache'
import { apiFetch, buildSearchParams, downloadApiFile, PaginatedResponse } from './client'

// ============================================================================
// Training Task & Model APIs
// ============================================================================

/**
 * Training task summary
 */
export interface TrainingTask {
  task_id: string
  task_name: string
  task_type: string
  data_type: string
  task_description: string | null
  status: string
  progress: number
  error_message: string | null
  preprocessing_config: Record<string, unknown> | null
  model_config: Record<string, unknown> | null
  classes: string[] | null
  source_dataset_id?: string | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
  user_id?: string | null  // User ID of task creator
  username?: string | null  // Username of task creator (only for admin users)
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
 * Download trained model export bundle
 * @param modelId - Model ID
 * @throws {ApiError} If the request fails
 */
export async function downloadTrainedModelExport(modelId: string): Promise<void> {
  await downloadApiFile(
    `${API_BASE}/models/${encodeURIComponent(modelId)}/export`,
    `${modelId}_export.zip`,
    undefined,
    'Failed to export model'
  )
}

/**
 * Update training task name
 * @param taskId - Task ID
 * @param taskName - New task name
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function updateTrainingTaskName(
  taskId: string,
  taskName: string
): Promise<TrainingTask> {
  const result = await apiFetch<TrainingTask>(
    `${API_BASE}/tasks/training/${encodeURIComponent(taskId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_name: taskName })
    },
    'Failed to update task name'
  )
  invalidateTrainingTasksCache()
  return result
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
  supports_spatial?: boolean
}

/**
 * Feature extractor list response
 */
export interface FeatureExtractorListResponse {
  items: FeatureExtractor[]
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

export interface TrainingTaskListStats {
  total: number
  running: number
  completed: number
  failed: number
  cancelled: number
}

export interface TrainingTaskListQuery {
  page?: number
  page_size?: number
  search?: string
  status_filter?: 'all' | 'running' | 'completed' | 'failed' | 'cancelled'
  sort_by?: 'updated' | 'created' | 'name'
  forceRefresh?: boolean
}

export interface TrainingTaskListResponse extends PaginatedResponse<TrainingTask> {
  page: number
  page_size: number
  stats: TrainingTaskListStats
}

const trainingTaskListCache = createKeyedCache<TrainingTaskListResponse>(DEFAULT_CACHE_TTL)

function buildTrainingTaskListUrl(options?: TrainingTaskListQuery): string {
  const params = buildSearchParams({
    page: options?.page,
    page_size: options?.page_size,
    search: options?.search || undefined,
    status_filter: options?.status_filter || undefined,
    sort_by: options?.sort_by || undefined,
  })

  const queryString = params.toString()
  return queryString ? `${API_BASE}/tasks/training?${queryString}` : `${API_BASE}/tasks/training`
}

function buildTrainingTaskListCacheKey(options?: TrainingTaskListQuery): string {
  return JSON.stringify({
    page: options?.page ?? 1,
    page_size: options?.page_size ?? null,
    search: options?.search ?? null,
    status_filter: options?.status_filter ?? null,
    sort_by: options?.sort_by ?? null,
  })
}

export function invalidateTrainingTasksCache(): void {
  trainingTaskListCache.invalidateAll()
}

export async function prefetchTrainingTasks(options?: TrainingTaskListQuery): Promise<void> {
  try {
    await getTrainingTasks(options)
  } catch {
    // Ignore prefetch failures so they don't affect the active page.
  }
}

/**
 * Get all training tasks
 * @returns List of training tasks
 * @throws {ApiError} If the request fails
 */
export async function getTrainingTasks(options?: TrainingTaskListQuery): Promise<TrainingTaskListResponse> {
  const url = buildTrainingTaskListUrl(options)
  const cacheKey = buildTrainingTaskListCacheKey(options)

  return trainingTaskListCache.get(
    cacheKey,
    () => apiFetch<TrainingTaskListResponse>(url, undefined, 'Failed to get training tasks'),
    options?.forceRefresh === true
  )
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
  const result = await apiFetch<TrainingTaskDeleteResult>(
    `${API_BASE}/tasks/training/${taskId}?mode=${mode}`,
    { method: 'DELETE' },
    'Failed to delete training task'
  )
  invalidateTrainingTasksCache()
  return result
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
  task_id?: string     // Client-generated task_id for fire-and-forget submission
  rerun_from_task_id?: string  // Admin rerun only: preserve owner from source task
  task_name: string
  task_type: 'classification' | 'survival' | 'segmentation' | 'external_validation'
  data_type: 'wsi' | 'patch'
  task_description: string
  dataset_id?: string  // If provided, wsi_ids are resolved from this dataset on server
  wsi_ids?: string[]   // Optional when dataset_id is provided
  preprocessing: {
    // Note: tile_size removed - auto-determined by PrePATH-style tiling based on WSI magnification
    level?: number
    feature_extractor: string  // Classification/WSI extractor; for segmentation should mirror model.backbone for metadata consistency
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
    aggregator?: string  // Required for classification/survival; omitted for segmentation
    classifier?: string  // Classifier head for patch-level: linear, mlp, attention
    backbone?: string  // Patch classification extractor or segmentation seg_backbone
    learning_rate: number
    epochs: number
    optimizer: string
    batch_size: number
    auto_balance?: boolean  // Auto-balance class weights for imbalanced datasets
    early_stopping_patience?: number  // Number of epochs to wait before early stopping
    // Segmentation-specific fields
    architecture?: string      // Segmentation architecture; MUST be conv_decoder when backbone is an FM extractor
    loss_names?: string[]      // Segmentation loss function names
    loss_weights?: number[]    // Segmentation loss function weights
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

  const result = await apiFetch<TrainingTaskCreateResult>(
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
  invalidateTrainingTasksCache()
  return result
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

