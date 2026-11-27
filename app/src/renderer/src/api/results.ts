import { API_BASE } from '../config'
import { createCache, DEFAULT_CACHE_TTL } from '../lib/utils/cache'
import { apiFetch, buildSearchParams } from './client'
import { invalidateHeatmapAvailabilityCache } from './heatmap'

// ============================================================================
// AI Results APIs
// ============================================================================

/**
 * AI Result response
 */
export interface AIResult {
  wsi_id: string
  task_id: string
  pred: string | null
  probs: Record<string, number> | null
  metadata: Record<string, unknown> | null
  created_at: string | null
}

/**
 * Fetch AI analysis results from Gateway.
 * Gateway will get the latest results from AI Service or local cache.
 * @returns Result, or null if no prediction available yet
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function fetchResults(wsi_id: string): Promise<AIResult | null> {
  const result = await apiFetch<AIResult>(
    `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}`,
    undefined,
    'Failed to get results'
  )

  // Return null if no prediction available (valid state, not an error)
  if (!result.pred) {
    return null
  }

  return result
}

/**
 * Result item with WSI info from /results endpoint
 */
export interface ResultWithWSI {
  wsi_id: string
  task_id: string
  pred: string
  probs: Record<string, number> | null
  label: string | null  // Ground truth
  case_id: string | null
  original_filename: string
  created_at: string | null
}

/**
 * Response from /results endpoint
 */
export interface AllResultsResponse {
  items: ResultWithWSI[]
  total: number
}

// Cache for fetchAllResults
const allResultsCache = createCache<AllResultsResponse>(DEFAULT_CACHE_TTL)

/**
 * Fetch all AI results with WSI info (with caching)
 * @returns List of results with predictions and WSI metadata
 * @throws {ApiError} If the request fails
 */
export async function fetchAllResults(): Promise<AllResultsResponse> {
  return allResultsCache.get(() =>
    apiFetch<AllResultsResponse>(`${API_BASE}/results`, undefined, 'Failed to load results')
  )
}

/**
 * Invalidate the results cache (call after mutations)
 */
export function invalidateResultsCache(): void {
  allResultsCache.invalidate()
}

/**
 * Delete result for WSI AI results
 */
export interface DeleteWSIResultsResponse {
  message: string
  wsi_id: string
  task_id: string | null
  database_deleted: number
  storage_cleanup: {
    deleted_files: string[]
    deleted_dirs: string[]
    failed: [string, string][]
    total_size: number
    summary: string
  }
}

/**
 * Delete AI analysis results for a WSI.
 *
 * @param wsi_id - The WSI ID to delete results for
 * @param task_id - Optional task ID to delete results for a specific task only
 * @returns Delete result with cleanup info
 * @throws {ApiError} If the request fails
 */
export async function deleteWSIResults(wsi_id: string, task_id?: string): Promise<DeleteWSIResultsResponse> {
  const params = buildSearchParams({ task_id })

  const url = `${API_BASE}/results/wsi/${encodeURIComponent(wsi_id)}${params.toString() ? '?' + params.toString() : ''}`

  const result = await apiFetch<DeleteWSIResultsResponse>(url, { method: 'DELETE' }, 'Failed to delete WSI results')

  // Invalidate caches after deletion
  invalidateResultsCache()
  invalidateHeatmapAvailabilityCache(wsi_id)

  return result
}
