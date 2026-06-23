import { API_BASE } from '../config'
import { createKeyedCache, LONG_CACHE_TTL } from '../lib/cache'
import { apiFetch, buildSearchParams, withAuthTokenQuery } from './client'

// ============================================================================
// Heatmap and Attention APIs
// ============================================================================

/**
 * Heatmap point with coordinates and attention weight
 */
export interface HeatmapPoint {
  index: number
  x: number
  y: number
  weight: number
  raw_weight: number
}

/**
 * Available heatmap info for a WSI
 */
export interface AvailableHeatmap {
  task_id: string | null
  fold_key?: string | null  // K-fold: which fold this attention comes from (e.g., 'fold_0')
  task_type: string
  task_name: string
  prediction: string | null
  probs: Record<string, number> | null
  classes: string[] | null
  feature_extractor: string | null
  aggregator?: string | null  // MIL aggregator type (e.g., abmil, clam_sb, transmil)
  created_at: number
  attention_file: string
  patch_size?: number | null
  data_type?: 'wsi' | 'patch'  // WSI-level attention or patch-level CAM/segmentation mask
  cam_size?: [number, number]   // CAM size for patch-level
  is_best_fold?: boolean | null  // Whether this is the best fold (for k-fold training)
  is_kfold?: boolean  // Whether this task was trained with K-Fold cross-validation
  num_folds?: number | null  // Number of folds if K-Fold training
  val_accuracy?: number  // Validation accuracy of the model (for sorting by best model)
  attention_type?: 'single' | 'multi_class'  // Type of attention: single (most models) or multi_class (CLAM_MB)
  num_attention_classes?: number | null  // Number of attention classes for multi_class type
  // Survival prediction fields
  risk_score?: number | null  // Risk score for survival prediction
  risk_group?: 'High Risk' | 'Low Risk' | null  // Risk group based on median cutoff
}

/**
 * Heatmap data response
 */
export interface HeatmapData {
  wsi_id: string
  task_id: string | null
  task_type?: string  // Task type: "train" (classification), "survival" (survival prediction), etc.
  fold_key?: string | null  // K-fold: which fold this attention comes from
  task_name: string | null
  patch_size: number
  slide_width: number
  slide_height: number
  num_patches: number
  attention_min: number
  attention_max: number
  prediction: string | null
  probs: Record<string, number> | null
  heatmap: HeatmapPoint[]
  top_patches: HeatmapPoint[]
  bottom_patches: HeatmapPoint[]
  // Multi-class attention info
  aggregator?: string | null
  attention_type?: 'none' | 'single' | 'multi_class'
  num_attention_classes?: number | null
  selected_class_idx?: number | null
  classes?: string[]
  // Survival prediction fields
  risk_score?: number | null  // Risk score for survival prediction
  risk_group?: 'High Risk' | 'Low Risk' | null  // Risk group based on median cutoff
}

export const SEGMENTATION_MASK_COLORS = [
  '#ff0000',
  '#00ff00',
  '#0000ff',
  '#ffff00',
  '#ff00ff',
  '#00ffff',
  '#ff8000',
  '#8000ff',
  '#0080ff',
  '#ff0080',
]

// Cache for fetchAvailableHeatmaps (keyed by wsi_id, 60s TTL)
const heatmapAvailabilityCache = createKeyedCache<AvailableHeatmap[]>(LONG_CACHE_TTL)

function buildAuthedHeatmapUrl(
  path: string,
  params?: Record<string, string | number | undefined | null>
): string {
  const search = buildSearchParams(params)
  const query = search.toString()
  return withAuthTokenQuery(`${API_BASE}${path}${query ? `?${query}` : ''}`)
}

/**
 * Fetch available heatmaps (attention data) for a WSI (with caching)
 * @param wsi_id - The WSI ID
 * @returns List of available heatmaps
 * @throws {ApiError} If the request fails
 */
export async function fetchAvailableHeatmaps(wsi_id: string): Promise<AvailableHeatmap[]> {
  return heatmapAvailabilityCache.get(wsi_id, async () => {
    const response = await apiFetch<{ heatmaps: AvailableHeatmap[] }>(
      `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/available`,
      undefined,
      'Failed to fetch available heatmaps'
    )
    return response.heatmaps || []
  })
}

/**
 * Invalidate the heatmap availability cache (call after training completes)
 */
export function invalidateHeatmapAvailabilityCache(wsi_id?: string): void {
  if (wsi_id) {
    heatmapAvailabilityCache.invalidate(wsi_id)
  } else {
    heatmapAvailabilityCache.invalidateAll()
  }
}

/**
 * Fetch heatmap data for a WSI
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @param patch_size - Patch size used during inference (default 512)
 * @param fold_key - Optional fold key for k-fold results (e.g., 'fold_0')
 * @returns Heatmap data with top/bottom patches
 * @throws {ApiError} If the request fails
 */
export async function fetchHeatmapData(
  wsi_id: string,
  task_id?: string,
  patch_size: number = 512,
  fold_key?: string
): Promise<HeatmapData> {
  const params = buildSearchParams({
    patch_size,
    task_id,
    fold_key,
  })
  const url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/data?${params.toString()}`
  return apiFetch<HeatmapData>(url, undefined, 'Failed to fetch heatmap data')
}

/**
 * Get patch image URL for a WSI at specific coordinates
 * @param wsi_id - The WSI ID
 * @param x - X coordinate
 * @param y - Y coordinate
 * @param size - Patch size (default 256)
 * @returns URL for the patch image (with auth token for <img> tags)
 */
export function getPatchImageUrl(wsi_id: string, x: number, y: number, size: number = 256): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_image`, { x, y, size })
}

/**
 * Patch CAM data response (for patch classification tasks)
 */
export interface PatchCAMData {
  wsi_id: string
  task_id: string | null
  prediction: string | null
  probs: Record<string, number> | null
  classes: string[] | null
  cam_size: [number, number]
  cam_min: number
  cam_max: number
  cam_data: number[][] // 2D array of CAM values
}

/**
 * Get patch CAM overlay image URL
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @param fold_key - Optional fold key for k-fold results (e.g., 'fold_0')
 * @returns URL for the CAM overlay PNG image (with auth token for <img> tags)
 */
export function getPatchCAMImageUrl(wsi_id: string, task_id?: string, fold_key?: string, size?: number): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam`, {
    format: 'image',
    task_id,
    fold_key,
    size,
  })
}

/**
 * Get patch CAM overlay image URL optimized for recommendation card previews.
 */
export function getRecommendationPatchCAMImageUrl(
  wsi_id: string,
  task_id?: string,
  fold_key?: string,
  size: number = 160,
): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam`, {
    format: 'image',
    task_id,
    fold_key,
    preset: 'recommendation',
    size,
    opacity: 0.68,
    blur_scale: 0.6,
    contrast_boost: 1.18,
    saturation_boost: 1.25,
  })
}

/**
 * Get segmentation mask overlay image URL
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific mask
 * @param fold_key - Optional fold key for k-fold results
 * @param size - Optional max thumbnail size for faster preview rendering
 * @returns URL for the seg mask overlay PNG image (with auth token for <img> tags)
 */
export function getSegMaskImageUrl(wsi_id: string, task_id?: string, fold_key?: string, size?: number): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/seg_mask`, {
    task_id,
    fold_key,
    size,
  })
}

/**
 * Get segmentation mask overlay image URL optimized for recommendation card previews.
 */
export function getRecommendationSegMaskImageUrl(
  wsi_id: string,
  task_id?: string,
  fold_key?: string,
  size: number = 160,
): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/seg_mask`, {
    task_id,
    fold_key,
    preset: 'recommendation',
    size,
  })
}

/**
 * Get WSI heatmap thumbnail URL (rendered heatmap overlay on thumbnail)
 * @param wsi_id - The WSI ID
 * @param task_id - Optional task ID for specific heatmap
 * @param size - Max thumbnail size (default 256)
 * @param class_idx - Optional class index for multi-class attention (e.g., CLAM_MB)
 * @returns URL for the heatmap thumbnail PNG image (with auth token for <img> tags)
 */
export function getHeatmapThumbnailUrl(
  wsi_id: string,
  task_id?: string,
  size: number = 256,
  class_idx?: number,
  fold_key?: string
): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/heatmap_thumbnail`, {
    size,
    task_id,
    class_idx,
    fold_key,
  })
}

/**
 * Get WSI heatmap thumbnail URL optimized for recommendation card previews.
 */
export function getRecommendationHeatmapThumbnailUrl(
  wsi_id: string,
  task_id?: string,
  size: number = 160,
  class_idx?: number,
  fold_key?: string,
  patch_size?: number | null,
): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/heatmap_thumbnail`, {
    size,
    task_id,
    class_idx,
    fold_key,
    patch_size,
    preset: 'recommendation',
    opacity: 0.68,
    blur_scale: 0.6,
    contrast_boost: 1.18,
    saturation_boost: 1.25,
  })
}

/**
 * Fetch patch CAM data as JSON
 * @param wsi_id - The WSI/patch ID
 * @param task_id - Optional task ID for specific CAM
 * @param fold_key - Optional fold key for k-fold results (e.g., 'fold_0')
 * @returns Patch CAM data
 * @throws {ApiError} If the request fails
 */
export async function fetchPatchCAMData(wsi_id: string, task_id?: string, fold_key?: string): Promise<PatchCAMData> {
  let url = `${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/patch_cam?format=json`
  if (task_id) {
    url += `&task_id=${encodeURIComponent(task_id)}`
  }
  if (fold_key) {
    url += `&fold_key=${encodeURIComponent(fold_key)}`
  }
  return apiFetch<PatchCAMData>(url, undefined, 'Failed to fetch patch CAM data')
}

/**
 * Get patch image URL for a simple patch file (not WSI)
 * This endpoint returns the entire patch image for patch classification tasks
 * @param wsi_id - The patch ID
 * @returns URL for the patch image (with auth token for <img> tags)
 */
export function getPatchFileImageUrl(wsi_id: string): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/image`)
}

/**
 * Get thumbnail image URL for a WSI or patch
 * @param wsi_id - The WSI/patch ID
 * @param size - Max thumbnail size (default 256)
 * @returns URL for the thumbnail image with auth token
 */
export function getThumbnailUrl(wsi_id: string, size: number = 256): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/thumbnail`, { size })
}

/**
 * Get thumbnail image URL optimized for recommendation card previews.
 */
export function getRecommendationThumbnailUrl(wsi_id: string, size: number = 160): string {
  return buildAuthedHeatmapUrl(`/heatmap/wsi/${encodeURIComponent(wsi_id)}/thumbnail`, {
    size,
    preset: 'recommendation',
  })
}
