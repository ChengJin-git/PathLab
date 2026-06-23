import { API_BASE } from '../config'
import { apiFetch } from './client'
import { invalidateTrainingTasksCache } from './training'

// ============================================================================
// GPU Task Queue APIs
// ============================================================================

/**
 * GPU information for a single device
 */
export interface GPUInfo {
  index: number
  name: string
  allocated_mb: number
  free_mb: number
  total_mb: number
}

/**
 * Running task with GPU assignment
 */
export interface RunningTaskInfo {
  task_id: string
  gpu: number | null
}

/**
 * GPU task queue status
 */
export interface QueueStatus {
  max_concurrent: number
  gpu_count: number
  running_count: number
  pending_count: number
  queue_size: number
  running_task_ids: string[]
  running_tasks: RunningTaskInfo[]
  pending_task_ids: string[]
  is_running: boolean
  gpus?: GPUInfo[]
  vram_available?: boolean
  vram_free_mb?: number
  vram_status?: string
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
  const result = await apiFetch<CancelQueueTaskResponse>(
    `${API_BASE}/queue/${taskId}`,
    { method: 'DELETE' },
    'Failed to cancel task'
  )
  if (result.cancelled) {
    invalidateTrainingTasksCache()
  }
  return result
}
