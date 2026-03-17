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
  created_by?: string
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
  source_dataset_id?: string
  dataset_scope?: boolean
  source_organ?: string
}

export interface DeleteDatasetAnnotationsByLabelsRequest {
  labels: string[]
}

export interface DeleteDatasetAnnotationsByLabelsResponse {
  ok: boolean
  annotation_id: string
  summary: DatasetAnnotationSummaryResponse
}

export interface ExtractRegionsResponse {
  task_id: string
  status: string
}

export interface ExtractProgressEvent {
  task_id: string
  progress: number | null
  done?: boolean
}

export interface SharedAnnotationResponse {
  annotation_id: string | null
  annotations: AnnotationsMap
  version: number
  last_edited_by: string | null
  updated_at: string | null
  is_prepopulated: boolean
}

export interface SharedAnnotationSaveResponse {
  annotation_id: string
  version: number
  updated_at: string | null
}

export interface FinalizeSharedAnnotationResponse {
  gt_annotation_id: string
  version: number
  region_count: number
}

export interface CollaboratorMember {
  user_id: string
  email: string | null
  nickname: string | null
  role: 'owner' | 'implicit_admin' | 'collaborator'
  added_by?: string
  created_at?: string
}

export interface CollaboratorsResponse {
  dataset_id: string
  members: CollaboratorMember[]
}

export type SharedAnnotationEvent =
  | { type: 'updated'; version: number; changed_by: string; annotations?: AnnotationsMap }
  | { type: 'finalized'; version: number; gt_annotation_id: string }
  | { type: 'gt_updated' }
  | { type: 'gt_deleted' }
  | { type: 'collaborator_removed'; user_id: string }
  | { type: 'shared_deleted' }
  | { type: 'keepalive' }

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

export function getExtractProgressSSEUrl(taskId: string): string | null {
  const baseUrl = `${API_BASE}/annotation/extract/${encodeURIComponent(taskId)}/stream`
  const authedUrl = withAuthTokenQuery(baseUrl)
  return authedUrl === baseUrl ? null : authedUrl
}

// ============================================================================
// Shared Annotation (Collaborative) APIs
// ============================================================================

export async function getSharedAnnotation(datasetId: string): Promise<SharedAnnotationResponse> {
  return apiFetch<SharedAnnotationResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared`,
    {},
    'Failed to load shared annotation'
  )
}

export async function saveSharedAnnotation(
  datasetId: string,
  req: { annotations: AnnotationsMap; version: number }
): Promise<SharedAnnotationSaveResponse> {
  return apiFetch<SharedAnnotationSaveResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
    'Failed to save shared annotation'
  )
}

export async function deleteSharedAnnotation(datasetId: string): Promise<{ ok: boolean; deleted_regions: number }> {
  return apiFetch(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared`,
    { method: 'DELETE' },
    'Failed to delete shared annotation'
  )
}

export async function finalizeSharedAnnotation(
  datasetId: string,
  force = false
): Promise<FinalizeSharedAnnotationResponse> {
  return apiFetch<FinalizeSharedAnnotationResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared/finalize`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    },
    'Failed to finalize shared annotation'
  )
}

export async function bulkDeleteSharedRegionsByCreator(
  datasetId: string,
  userId: string
): Promise<{ deleted_count: number }> {
  return apiFetch(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared/regions/bulk-delete`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    },
    'Failed to bulk delete regions'
  )
}

export function getSharedAnnotationSSEUrl(datasetId: string): string | null {
  const baseUrl = `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/shared/stream`
  const authedUrl = withAuthTokenQuery(baseUrl)
  return authedUrl === baseUrl ? null : authedUrl
}

// ============================================================================
// Collaborator Management APIs
// ============================================================================

export async function listCollaborators(datasetId: string): Promise<CollaboratorsResponse> {
  return apiFetch<CollaboratorsResponse>(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/collaborators`,
    {},
    'Failed to list collaborators'
  )
}

export async function addCollaborator(
  datasetId: string,
  userId: string
): Promise<{ collaborator: CollaboratorMember }> {
  return apiFetch(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/collaborators`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    },
    'Failed to add collaborator'
  )
}

export async function removeCollaborator(
  datasetId: string,
  targetUserId: string
): Promise<{ ok: boolean; residual_region_count: number }> {
  return apiFetch(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/collaborators/${encodeURIComponent(targetUserId)}`,
    { method: 'DELETE' },
    'Failed to remove collaborator'
  )
}

export async function deleteDatasetGroundTruth(datasetId: string): Promise<{ ok: boolean }> {
  return apiFetch(
    `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/ground-truth`,
    { method: 'DELETE' },
    'Failed to delete ground truth'
  )
}

// ============================================================================
// Annotation Audit Log APIs (admin only)
// ============================================================================

export interface AnnotationAuditEntry {
  id: number
  dataset_id: string
  dataset_name: string | null
  user_id: string | null
  user_display: string | null
  event_type: 'shared_write' | 'finalize' | 'collaborator_add' | 'collaborator_remove' | 'bulk_delete'
  event_metadata: Record<string, unknown>
  created_at: string
}

export interface AnnotationAuditResponse {
  entries: AnnotationAuditEntry[]
  count: number
}

export async function listAnnotationAudit(params: {
  dataset_id?: string
  event_type?: string
  limit?: number
  offset?: number
}): Promise<AnnotationAuditResponse> {
  const q = new URLSearchParams()
  if (params.dataset_id) q.set('dataset_id', params.dataset_id)
  if (params.event_type) q.set('event_type', params.event_type)
  if (params.limit !== undefined) q.set('limit', String(params.limit))
  if (params.offset !== undefined) q.set('offset', String(params.offset))
  return apiFetch<AnnotationAuditResponse>(
    `${API_BASE}/annotation/audit?${q}`,
    {},
    'Failed to fetch audit log'
  )
}

export function exportAnnotationAuditUrl(params: { dataset_id?: string; event_type?: string }): string {
  const q = new URLSearchParams()
  if (params.dataset_id) q.set('dataset_id', params.dataset_id)
  if (params.event_type) q.set('event_type', params.event_type)
  return `${API_BASE}/annotation/audit/export?${q}`
}

export function getPresenceWSUrl(datasetId: string): string | null {
  const httpUrl = `${API_BASE}/annotation/datasets/${encodeURIComponent(datasetId)}/presence`
  const authedUrl = withAuthTokenQuery(httpUrl)
  if (authedUrl === httpUrl) return null
  return authedUrl.replace(/^https/, 'wss').replace(/^http/, 'ws')
}
