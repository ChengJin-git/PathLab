import { API_BASE } from '../config'
import { apiFetch, getAuthToken } from './client'

// ============================================================================
// Annotation Types
// ============================================================================

/**
 * A single annotation region (ROI) drawn on a WSI
 */
export interface AnnotationRegion {
  id: string              // unique id within the draft
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
 * Annotation draft returned from the server
 */
export interface AnnotationDraft {
  draft_id: string
  user_id: string
  source_dataset_id: string | null
  annotations: AnnotationsMap
  created_at: string
  updated_at: string
}

/**
 * Request to save/update a draft
 */
export interface SaveDraftRequest {
  draft_id: string
  source_dataset_id?: string
  annotations: AnnotationsMap
}

/**
 * Request to extract ROI regions into a new dataset
 */
export interface ExtractRegionsRequest {
  draft_id?: string
  annotations?: AnnotationsMap
  dataset_name: string
  task_type: string
  /** For segmentation: reuse existing dataset instead of creating a new one */
  source_dataset_id?: string
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
// Annotation Draft APIs
// ============================================================================

/**
 * Save or update an annotation draft (auto-save)
 */
export async function saveDraft(req: SaveDraftRequest): Promise<AnnotationDraft> {
  return apiFetch<AnnotationDraft>(
    `${API_BASE}/annotation/drafts`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    },
    'Failed to save annotation draft'
  )
}

/**
 * List all annotation drafts for the current user
 */
export async function listDrafts(): Promise<AnnotationDraft[]> {
  return apiFetch<AnnotationDraft[]>(
    `${API_BASE}/annotation/drafts`,
    {},
    'Failed to list annotation drafts'
  )
}

/**
 * Get a specific annotation draft by ID
 */
export async function getDraft(draftId: string): Promise<AnnotationDraft> {
  return apiFetch<AnnotationDraft>(
    `${API_BASE}/annotation/drafts/${encodeURIComponent(draftId)}`,
    {},
    'Failed to get annotation draft'
  )
}

/**
 * Delete an annotation draft
 */
export async function deleteDraft(draftId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `${API_BASE}/annotation/drafts/${encodeURIComponent(draftId)}`,
    { method: 'DELETE' },
    'Failed to delete annotation draft'
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
  const token = getAuthToken()
  if (!token) return null
  return `${API_BASE}/annotation/extract/${encodeURIComponent(taskId)}/stream?token=${encodeURIComponent(token)}`
}

