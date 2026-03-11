import { API_BASE } from '../config'
import { apiFetch, buildSearchParams } from './client'

// ============================================================================
// INFERENCE API
// ============================================================================

/**
 * Response from starting external validation or test split inference
 */
export interface InferenceTaskResponse {
  task_id: string
  status: string
  total_wsi: number
  message?: string
}

/**
 * Dataset info for external validation selection
 */
export interface ValidationDataset {
  dataset_id: string
  name: string
  data_type: string
  aggregation_level: string
  task_type: string
  total_wsi_count: number
  total_case_count: number
  display_count: number
  distinct_label_count: number
  distinct_labels: string[]
  segmentation_labels: string[]
  available_feature_extractors: string[]
  wsi_ids: string[]
}

/**
 * Fetch datasets available for external validation selection
 * @returns List of datasets with metadata for filtering
 * @throws {ApiError} If the request fails
 */
export async function fetchDatasetsForValidation(): Promise<{ items: ValidationDataset[]; total: number }> {
  return apiFetch<{ items: ValidationDataset[]; total: number }>(
    `${API_BASE}/results/datasets-for-validation`,
    {},
    'Failed to fetch datasets for validation'
  )
}

/**
 * Start external validation - use a trained model on data from a dataset
 * @param modelId - TrainedModel ID
 * @param datasetId - Dataset ID whose WSIs will be used for validation
 * @returns Task response with task_id for tracking progress
 * @throws {ApiError} If the request fails
 */
export async function startExternalValidation(
  modelId: string,
  datasetId: string,
  metrics?: string[],
  charts?: string[],
  computeBootstrapCI?: boolean
): Promise<InferenceTaskResponse> {
  return apiFetch<InferenceTaskResponse>(
    `${API_BASE}/results/external-validation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        dataset_id: datasetId,
        metrics: metrics,
        charts: charts,
        compute_bootstrap_ci: computeBootstrapCI
      })
    },
    'Failed to start external validation'
  )
}

/**
 * Analysis request parameters
 */
export interface AnalysisRequest {
  metrics: string[]
  charts: string[]
  description?: string
  bootstrap_ci_metrics?: string[]  // List of metrics to compute 95% CI for (e.g., ["accuracy", "auc"])
}

/**
 * Analysis response
 */
export interface AnalysisResponse {
  task_id: string
  analysis_id: string
  summary: Record<string, unknown>
  chart_paths: string[]
}

/**
 * Run analysis on a training task (internal analysis on test set)
 * @param taskId - Training task ID to analyze
 * @param metrics - List of metrics to calculate
 * @param charts - List of charts to generate
 * @param description - Optional description for the analysis
 * @param bootstrapCIMetrics - List of metrics to compute 95% CI for
 * @returns Analysis response with summary and chart paths
 * @throws {ApiError} If the request fails
 */
export async function runTaskAnalysis(
  taskId: string,
  metrics: string[],
  charts: string[],
  description?: string,
  bootstrapCIMetrics?: string[]
): Promise<AnalysisResponse> {
  return apiFetch<AnalysisResponse>(
    `${API_BASE}/results/tasks/${taskId}/analysis`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        metrics,
        charts,
        description,
        bootstrap_ci_metrics: bootstrapCIMetrics
      })
    },
    'Failed to run analysis'
  )
}

/**
 * Bootstrap confidence interval for a metric
 */
export interface BootstrapCI {
  lower: number
  upper: number
  n_samples: number
}

/**
 * Bootstrap CI result structure
 */
export interface BootstrapCIResult {
  metrics_ci: Record<string, BootstrapCI | null>
  class_metrics_ci: Record<string, Record<string, BootstrapCI | null>>
  n_bootstrap: number
  confidence_level: number
}

/**
 * Quick analysis response - contains filtered metrics and chart data
 */
export interface QuickAnalysisResponse {
  task_id: string
  analysis_id?: string
  has_analysis: boolean
  message?: string
  timestamp?: string
  task_type?: string
  num_samples?: number
  classes?: string[]
  is_binary?: boolean
  metrics?: Record<string, number>
  class_metrics?: Record<string, Record<string, number>>
  bootstrap_ci?: BootstrapCIResult  // Bootstrap 95% confidence intervals if computed
  chart_data?: {
    confusion_matrix?: {
      classes: string[]
      data: [number, number, number][]
    }
    roc_curve?: {
      classes: string[]
      data: Record<string, { fpr: number[]; tpr: number[]; auc: number }>
    }
    loss_curve?: {
      epochs: number[]
      loss: number[]
      val_loss?: number[]
    }
    km_curve?: {
      high_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
      low_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
      cutoff: number
    }
    iou_curve?: {
      epochs: number[]
      train_values: number[]
      val_values?: number[]
      metric_name: string
    }
    dice_curve?: {
      epochs: number[]
      train_values: number[]
      val_values?: number[]
      metric_name: string
    }
    per_class_iou?: {
      classes: string[]
      means: number[]
      stds?: number[]
      metric_name?: string
    }
    per_class_dice?: {
      classes: string[]
      means: number[]
      stds?: number[]
      metric_name?: string
    }
  }
  chart_urls?: Record<string, string>
  // Async analysis fields (when analysis is pending/running)
  status?: 'pending' | 'running' | 'completed' | 'failed'
  progress?: number
  // K-Fold training details (if available)
  kfold_training?: {
    is_kfold: boolean
    num_folds: number
    folds: Record<string, {
      history?: Record<string, number[]>
      val_metrics?: Record<string, number>
    }>
    aggregated: Record<string, { mean: number; std: number }>
  }
}

/**
 * Analysis status response - for polling async analysis progress
 */
export interface AnalysisStatusResponse {
  analysis_id: string
  task_id?: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  error_message?: string
  message?: string
  created_at?: string
  started_at?: string
  finished_at?: string
}

/**
 * Get quick analysis results for a task.
 * If analysis exists, returns the most recent. If not, optionally runs analysis first.
 *
 * @param taskId - Training task ID
 * @param options - Optional filtering options
 * @returns Quick analysis response with metrics and chart data
 * @throws {ApiError} If the request fails
 */
export async function getTaskQuickAnalysis(
  taskId: string,
  options?: {
    metrics?: string[]   // Filter to specific metrics (e.g., ['accuracy', 'auc', 'f1'])
    charts?: string[]    // Filter to specific charts (e.g., ['roc_curve', 'confusion_matrix'])
    runIfMissing?: boolean  // Run analysis if not available (default: true)
    bootstrapCIMetrics?: string[]  // List of metrics to compute 95% CI for (e.g., ['accuracy', 'auc'])
  }
): Promise<QuickAnalysisResponse> {
  const params = buildSearchParams({
    metrics: options?.metrics?.length ? options.metrics.join(',') : undefined,
    charts: options?.charts?.length ? options.charts.join(',') : undefined,
    run_if_missing: options?.runIfMissing,
    bootstrap_ci_metrics: options?.bootstrapCIMetrics?.length
      ? options.bootstrapCIMetrics.join(',')
      : undefined,
  })

  const queryString = params.toString()
  const url = `${API_BASE}/results/tasks/${taskId}/quick-analysis${queryString ? `?${queryString}` : ''}`

  return apiFetch<QuickAnalysisResponse>(url, undefined, 'Failed to get quick analysis')
}

/**
 * Get analysis task status for polling async analysis progress.
 *
 * @param analysisId - Analysis ID returned when analysis was submitted
 * @returns Analysis status including progress and error information
 * @throws {ApiError} If the request fails
 */
export async function getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse> {
  const url = `${API_BASE}/results/analysis/${analysisId}/status`
  return apiFetch<AnalysisStatusResponse>(url, undefined, 'Failed to get analysis status')
}

