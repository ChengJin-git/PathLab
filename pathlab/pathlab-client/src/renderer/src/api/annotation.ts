import { API_BASE } from '../config'
import { apiFetch, withAuthTokenQuery } from './client'

// ============================================================================
// Annotation Types
// ============================================================================

/**
 * A single annotation region (ROI) drawn on a WSI
 */
export interface AnnotationRegion {
  id: string              // unique id within the annotation
  type: 'rect' | 'polygon'
  x: number               // bounding box x (level-0 pixel)
  y: number               // bounding box y (level-0 pixel)
  width: number           // bounding box width (level-0 pixel)
  height: number          // bounding box height (level-0 pixel)
  label: string
  color: string           // hex color for display
  points?: number[][]     // polygon vertices [[x,y], ...] (polygon only)
}

/**
 * Annotations map: wsi_id → list of regions
 */
export type AnnotationsMap = Record<string, AnnotationRegion[]>

/**
 * Segmentation annotation returned from the server
 */
export interface SegmentationAnnotation {
  annotation_id: string
  user_id: string
  source_dataset_id: string | null
  annotations: AnnotationsMap
  status: string
  source: string
  created_at: string
  updated_at: string
}

export interface DatasetGroundTruthResponse {
  dataset_id: string
  annotations: AnnotationsMap
  record_count: number
  source: 'ground_truth'
  width?: number | null
  height?: number | null
}

export interface AnnotationSummaryLabel {
  total_regions: number
  total_slides: number
  color?: string | null
}

export interface DatasetAnnotationSummaryResponse {
  dataset_id: string
  total_regions: number
  total_slides: number
  labels: Record<string, AnnotationSummaryLabel>
  has_wsi_sources: boolean
  source: 'effective_dataset'
  annotation_id?: string | null
}

/**
 * Request to save/update an annotation
 */
export interface SaveAnnotationRequest {
  annotation_id: string
  source_dataset_id?: string
  annotations: AnnotationsMap
}

/**
 * Request to extract ROI regions into a new dataset
 */
export interface ExtractRegionsRequest {
  annotation_id?: string
  annotations?: AnnotationsMap
  dataset_name: string
  task_type: string
  /** For segmentation: reuse existing dataset instead of creating a new one */
  source_dataset_id?: string
  /** Resolve the whole dataset on the backend using GT + saved draft overlay */
  dataset_scope?: boolean
}

export interface DeleteDatasetAnnotationsByLabelsRequest {
  labels: string[]
}

export interface DeleteDatasetAnnotationsByLabelsResponse {
  ok: boolean
  annotation_id: string
  summary: DatasetAnnotationSummaryResponse
}

/**
 * Response from extract endpoint
 */
export interface ExtractRegionsResponse {
  task_id: string
  status: string
}

/**
 * SSE progress event data
 */
export interface ExtractProgressEvent {
  task_id: string
  progress: number | null
  done?: boolean
}

// ============================================================================
// Segmentation Annotation APIs
// ============================================================================

/**
 * Save or update a segmentation annotation (auto-save)
 */
export async function saveAnnotation(req: SaveAnnotationRequest): Promise<SegmentationAnnotation> {
  return apiFetch<SegmentationAnnotation>(
    `${API_BASE}/annotation/drafts`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    },
    'Failed to save annotation'
  )
}

/**
 * List all annotations for the current user
 */
export async function listAnnotations(): Promise<SegmentationAnnotation[]> {
  return apiFetch<SegmentationAnnotation[]>(
    `${API_BASE}/annotation/drafts`,
    {},
    'Failed to list annotations'
  )
}

/**
 * Get a specific annotation by ID
 */
export async function getAnnotation(annotationId: string): Promise<SegmentationAnnotation> {
  return apiFetch<SegmentationAnnotation>(
    `${API_BASE}/annotation/drafts/${encodeURIComponent(annotationId)}`,
    {},
    'Failed to get annotation'
  )
}

/**
 * Delete an annotation
 */
export async function deleteAnnotation(annotationId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `${API_BASE}/annotation/drafts/${encodeURIComponent(annotationId)}`,
    { method: 'DELETE' },
    'Failed to delete annotation'
  )
}

/**
 * Get dataset ground-truth annotations converted to viewer ROI format.
 */
export async function getDatasetGroundTruth(datasetId: string): Promise<DatasetGroundTruthResponse> {
  return apiFetch<DatasetGroundTruthResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/ground-truth`,
    {},
    'Failed to load dataset ground truth'
  )
}

/**
 * Get ground-truth annotations for the current WSI/patch only.
 */
export async function getWSIGroundTruth(wsiId: string): Promise<DatasetGroundTruthResponse> {
  return apiFetch<DatasetGroundTruthResponse>(
    `${API_BASE}/annotation/wsi/${encodeURIComponent(wsiId)}/ground-truth`,
    {},
    'Failed to load WSI ground truth'
  )
}

/**
 * Get a cached GT thumbnail image URL for recommendation card previews.
 */
export function getGroundTruthThumbnailUrl(wsiId: string, size: number = 160): string {
  return withAuthTokenQuery(
    `${API_BASE}/annotation/wsi/${encodeURIComponent(wsiId)}/ground-truth-thumbnail?size=${encodeURIComponent(String(size))}`
  )
}

/**
 * Get a lightweight whole-dataset annotation summary.
 */
export async function getDatasetAnnotationSummary(datasetId: string): Promise<DatasetAnnotationSummaryResponse> {
  return apiFetch<DatasetAnnotationSummaryResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/summary`,
    {},
    'Failed to load dataset annotation summary'
  )
}

/**
 * Delete labels across the effective whole-dataset annotation view.
 */
export async function deleteDatasetAnnotationsByLabels(
  datasetId: string,
  req: DeleteDatasetAnnotationsByLabelsRequest,
): Promise<DeleteDatasetAnnotationsByLabelsResponse> {
  return apiFetch<DeleteDatasetAnnotationsByLabelsResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/delete-by-labels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
    'Failed to delete dataset annotations by labels'
  )
}

// ============================================================================
// ROI Extraction APIs
// ============================================================================

/**
 * Submit ROI extraction task (returns immediately with task_id)
 */
export async function extractRegions(req: ExtractRegionsRequest): Promise<ExtractRegionsResponse> {
  return apiFetch<ExtractRegionsResponse>(
    `${API_BASE}/annotation/extract`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    },
    'Failed to start ROI extraction'
  )
}

/**
 * Get the SSE URL for streaming extraction progress.
 * Returns null if not authenticated.
 */
export function getExtractProgressSSEUrl(taskId: string): string | null {
  const baseUrl = `${API_BASE}/annotation/extract/${encodeURIComponent(taskId)}/stream`
  const authedUrl = withAuthTokenQuery(baseUrl)
  return authedUrl === baseUrl ? null : authedUrl
}
