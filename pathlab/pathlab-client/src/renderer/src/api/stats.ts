import { API_BASE } from '../config'
import { createCache, DEFAULT_CACHE_TTL, ACTIVITY_CACHE_TTL } from '../lib/cache'
import { apiFetch, buildSearchParams } from './client'

// ============================================================================
// Statistics & Recent Activity APIs
// ============================================================================

/**
 * System statistics
 */
export interface SystemStats {
  wsi_count: number
  task_count: number
  completed_count: number
  results_count: number
  labels: Record<string, number>
  event_status: Record<string, number>  // For survival prediction: 'event' and 'censored' counts
}

// Cache for fetchStats (30 seconds TTL - lightweight DB query, cache prevents repeated calls on page revisits)
const statsCache = createCache<SystemStats>(DEFAULT_CACHE_TTL)

/**
 * Fetch system statistics from Gateway.
 * Returns WSI count, task count, completed count, results count, and label distribution.
 * Uses caching to prevent repeated API calls on page revisits.
 * @param forceRefresh - If true, bypass cache and fetch fresh data
 * @throws {ApiError} If the request fails
 */
export async function fetchStats(forceRefresh = false): Promise<SystemStats> {
  return statsCache.get(
    () => apiFetch<SystemStats>(`${API_BASE}/stats`, undefined, 'Failed to get stats'),
    forceRefresh
  )
}

/**
 * Invalidate the stats cache (call after mutations that affect stats)
 */
export function invalidateStatsCache(): void {
  statsCache.invalidate()
}

/**
 * Check if stats cache has valid (non-expired) data
 */
export function hasValidStatsCache(): boolean {
  return statsCache.hasValidData()
}

/**
 * Recent upload item (WSI slide)
 */
export interface RecentUpload {
  wsi_id: string
  original_filename: string | null
  dataset_id: string | null
  dataset_name: string | null
  label: string | null
  created_at: string | null
}

/**
 * Recent task item (AI inference or training task)
 */
export interface RecentTask {
  task_id: string
  task_name?: string  // For training tasks
  task_type: string
  task_category: 'inference' | 'training'
  status: string
  progress: number
  created_at: string | null
}

/**
 * Recent activity response
 */
export interface RecentActivityResponse {
  recent_uploads: RecentUpload[]
  recent_tasks: RecentTask[]
}

// Cache for fetchRecentActivity (5 minutes TTL)
const recentActivityCache = createCache<RecentActivityResponse>(ACTIVITY_CACHE_TTL)

/**
 * Fetch recent activity from Gateway.
 * Returns recent uploads and recent tasks for the current user.
 * Uses caching to prevent repeated API calls.
 * @param uploadLimit - Number of recent uploads to fetch
 * @param taskLimit - Number of recent tasks to fetch
 * @param forceRefresh - If true, bypass cache and fetch fresh data
 * @throws {ApiError} If the request fails
 */
export async function fetchRecentActivity(
  uploadLimit: number = 5,
  taskLimit: number = 5,
  forceRefresh: boolean = false
): Promise<RecentActivityResponse> {
  const params = buildSearchParams({
    upload_limit: uploadLimit,
    task_limit: taskLimit,
  })

  return recentActivityCache.get(
    () => apiFetch<RecentActivityResponse>(
      `${API_BASE}/stats/recent-activity?${params.toString()}`,
      undefined,
      'Failed to get recent activity'
    ),
    forceRefresh
  )
}

/**
 * Invalidate the recent activity cache (call after mutations like new uploads or tasks)
 */
export function invalidateRecentActivityCache(): void {
  recentActivityCache.invalidate()
}

/**
 * Check if recent activity cache has valid (non-expired) data
 */
export function hasValidRecentActivityCache(): boolean {
  return recentActivityCache.hasValidData()
}


// ============================================================================
// Admin: Per-User Usage Statistics
// ============================================================================

/**
 * Per-user usage statistics (admin only)
 */
export interface UserUsageItem {
  user_id: string
  username: string
  nickname: string | null
  role: string
  wsi_count: number
  ai_task_count: number
  analysis_count: number
  training_count: number
  conversation_count: number
  message_count: number
  annotation_count: number
  feedback_count: number
  thumbs_up: number
  thumbs_down: number
}

export interface UserUsageResponse {
  users: UserUsageItem[]
}

/**
 * Fetch per-user usage statistics (admin only).
 * Returns aggregated counts for all non-admin users.
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function fetchUserUsageStats(): Promise<UserUsageResponse> {
  return apiFetch<UserUsageResponse>(
    `${API_BASE}/stats/user-usage`,
    undefined,
    'Failed to get user usage statistics'
  )
}