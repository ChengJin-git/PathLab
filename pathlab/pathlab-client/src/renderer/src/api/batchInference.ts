import { API_BASE } from '../config'
import { apiFetch, apiFetchBlob, buildSearchParams, downloadBlobFile } from './client'

// ============================================================================
// TYPES
// ============================================================================

export interface InferenceDataset {
  dataset_id: string
  name: string
  data_type: string
  task_type: string
  aggregation_level: string
  slide_count: number
}

export interface BatchInferenceTask {
  task_id: string
  task_name: string
  status: string
  progress: number
  model_task_id: string | null
  model_id: string | null
  dataset_id: string | null
  model_task_type: string | null
  model_data_type: string | null
  data_type: string | null
  task_type: string | null
  total_wsi: number
  results_count: number
  error: string | null
  created_at: string | null
  finished_at: string | null
}

export interface BatchInferenceResult {
  wsi_id: string
  original_filename: string | null
  case_id: string | null
  pred: string | null
  probs: Record<string, number> | null
  metadata: Record<string, unknown> | null
  created_at: string | null
}

export interface BatchInferenceSummary {
  task_id: string
  task_name: string
  status: string
  task_type: string
  data_type: string | null
  model_task_id: string | null
  model_id: string | null
  dataset_id: string | null
  total_slides: number
  processed_slides: number
  created_at: string | null
  completed_at: string | null
  class_distribution?: Record<string, number>
  risk_high_count?: number
  risk_low_count?: number
  mean_risk_score?: number | null
  masks_generated?: number
}

export interface StartBatchInferenceResponse {
  task_id: string
  status: string
  message: string
}

export interface StartBatchInferenceRequest {
  model_task_id: string
  model_id: string
  dataset_id: string
}

// ============================================================================
// API FUNCTIONS
// ============================================================================

export async function fetchDatasetsForInference(
  unlabledOnly = true,
  taskType?: string
): Promise<{ items: InferenceDataset[]; total: number }> {
  const params = buildSearchParams({
    unlabeled_only: unlabledOnly,
    task_type: taskType,
  })
  const qs = params.toString()
  const url = `${API_BASE}/results/datasets-for-inference${qs ? `?${qs}` : ''}`
  return apiFetch<{ items: InferenceDataset[]; total: number }>(
    url,
    {},
    'Failed to fetch datasets for inference'
  )
}

export async function startBatchInference(
  req: StartBatchInferenceRequest
): Promise<StartBatchInferenceResponse> {
  return apiFetch<StartBatchInferenceResponse>(
    `${API_BASE}/results/batch-inference`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
    'Failed to start batch inference'
  )
}

export async function listBatchInferenceTasks(
  skip = 0,
  limit = 50
): Promise<{ items: BatchInferenceTask[]; total: number }> {
  const params = buildSearchParams({ skip, limit })
  const qs = params.toString()
  const url = `${API_BASE}/results/batch-inference/tasks${qs ? `?${qs}` : ''}`
  return apiFetch<{ items: BatchInferenceTask[]; total: number }>(
    url,
    {},
    'Failed to list batch inference tasks'
  )
}

export async function getBatchInferenceResults(
  taskId: string,
  skip = 0,
  limit = 100
): Promise<{
  task_type: string
  data_type: string | null
  items: BatchInferenceResult[]
  total: number
  skip: number
  limit: number
}> {
  const params = buildSearchParams({ skip, limit })
  const qs = params.toString()
  const url = `${API_BASE}/results/batch-inference/${taskId}/results${qs ? `?${qs}` : ''}`
  return apiFetch(url, {}, 'Failed to get batch inference results')
}

export async function getBatchInferenceSummary(taskId: string): Promise<BatchInferenceSummary> {
  return apiFetch<BatchInferenceSummary>(
    `${API_BASE}/results/batch-inference/${taskId}/summary`,
    {},
    'Failed to get batch inference summary'
  )
}

export async function exportBatchInferenceCsv(taskId: string, filename?: string): Promise<void> {
  const blob = await apiFetchBlob(
    `${API_BASE}/results/batch-inference/${taskId}/export-csv`,
    {},
    'Failed to export batch inference CSV'
  )
  downloadBlobFile(blob, filename ?? `batch_inference_${taskId}.csv`)
}
