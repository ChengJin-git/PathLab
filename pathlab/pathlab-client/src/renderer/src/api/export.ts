import { API_BASE } from '../config'
import { apiFetch, apiFetchBlob } from './client'

// ============================================================================
// Async Export APIs (for large datasets)
// ============================================================================

/**
 * Export task status from async export endpoint
 */
export interface ExportTaskStatus {
  task_id: string
  user_id: string
  export_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress: number
  error_message: string | null
  file_format: string | null
  total_records: number | null
  filter_params: {
    date_from?: string | null
    date_to?: string | null
    feedback_type?: string | null
    helpfulness?: string | null
  } | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

/**
 * Start async export of feedbacks (admin only)
 * Use this for large datasets to avoid blocking
 * @param format - Export format ('json' or 'csv')
 * @param dateFrom - Optional start date filter (ISO string)
 * @param dateTo - Optional end date filter (ISO string)
 * @param feedbackType - Optional feedback type filter
 * @param helpfulness - Optional helpfulness filter
 * @returns Task ID for polling status
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function startAsyncExport(
  format: 'json' | 'csv' = 'json',
  dateFrom?: string | null,
  dateTo?: string | null,
  feedbackType?: string | null,
  helpfulness?: string | null
): Promise<{ task_id: string; status: string }> {
  const params = new URLSearchParams()
  params.set('format', format)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  if (feedbackType) params.set('feedback_type', feedbackType)
  if (helpfulness) params.set('helpfulness', helpfulness)

  return apiFetch(
    `${API_BASE}/admin/feedbacks/export-async?${params.toString()}`,
    { method: 'POST' },
    'Failed to start async export'
  )
}

/**
 * Get async export task status (admin only)
 * @param taskId - Export task ID
 * @returns Task status with progress
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getExportTaskStatus(taskId: string): Promise<ExportTaskStatus> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/export-async/${taskId}`,
    undefined,
    'Failed to get export status'
  )
}

/**
 * Download async export file (admin only)
 * @param taskId - Export task ID
 * @returns Blob with file content
 * @throws {ApiError} If the request fails or export not ready
 */
export async function downloadExportFile(taskId: string): Promise<Blob> {
  return apiFetchBlob(
    `${API_BASE}/admin/feedbacks/export-async/${taskId}/download`,
    undefined,
    'Failed to download export file'
  )
}

