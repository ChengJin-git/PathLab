/**
 * Generic Cache Utility
 *
 * Provides a reusable caching mechanism with:
 * - TTL-based expiration
 * - Request deduplication (prevents duplicate in-flight requests)
 * - Support for both single-value and keyed (Map-based) caches
 *
 * Extracted from api.ts to eliminate code duplication.
 */

// ============================================================================
// Types
// ============================================================================

interface CacheEntry<T> {
  data: T | null
  timestamp: number
  promise: Promise<T> | null
}

// ============================================================================
// Single Value Cache (for global data like allResults, recentActivity)
// ============================================================================

/**
 * Creates a single-value cache with TTL and request deduplication.
 *
 * @param ttl - Time-to-live in milliseconds
 * @returns Cache instance with get, invalidate methods
 *
 * @example
 * ```ts
 * const resultsCache = createCache<AllResultsResponse>(30000)
 *
 * async function fetchAllResults(): Promise<AllResultsResponse> {
 *   return resultsCache.get(() => apiFetch('/results'))
 * }
 *
 * function invalidateResultsCache(): void {
 *   resultsCache.invalidate()
 * }
 * ```
 */
export function createCache<T>(ttl: number) {
  let entry: CacheEntry<T> = {
    data: null,
    timestamp: 0,
    promise: null,
  }

  return {
    /**
     * Get cached data or fetch new data using the provided fetcher.
     * Handles request deduplication automatically.
     */
    async get(fetcher: () => Promise<T>, forceRefresh = false): Promise<T> {
      const now = Date.now()

      // Return cached data if still valid and not forcing refresh
      if (!forceRefresh && entry.data !== null && now - entry.timestamp < ttl) {
        return entry.data
      }

      // If a request is already in progress, wait for it
      if (entry.promise) {
        return entry.promise
      }

      // Make new request
      entry.promise = fetcher()
        .then((data) => {
          entry.data = data
          entry.timestamp = Date.now()
          entry.promise = null
          return data
        })
        .catch((err) => {
          entry.promise = null
          throw err
        })

      return entry.promise
    },

    /** Invalidate the cache, forcing next get() to fetch fresh data */
    invalidate(): void {
      entry.data = null
      entry.timestamp = 0
    },

    /** Check if cache has valid data */
    hasValidData(): boolean {
      return entry.data !== null && Date.now() - entry.timestamp < ttl
    },
  }
}

// ============================================================================
// Keyed Cache (for per-resource data like WSI list, heatmaps)
// ============================================================================

/**
 * Creates a keyed cache (Map-based) with TTL and request deduplication.
 * Useful for caching data by ID (e.g., per-WSI, per-dataset).
 *
 * @param ttl - Time-to-live in milliseconds
 * @returns Cache instance with get, invalidate, invalidateAll methods
 *
 * @example
 * ```ts
 * const wsiListCache = createKeyedCache<WSIListResponse>(30000)
 *
 * async function fetchWSIList(datasetId?: string): Promise<WSIListResponse> {
 *   const cacheKey = datasetId || '__all__'
 *   return wsiListCache.get(cacheKey, () => apiFetch(`/wsi?dataset=${datasetId}`))
 * }
 *
 * function invalidateWSIListCache(): void {
 *   wsiListCache.invalidateAll()
 * }
 * ```
 */
export function createKeyedCache<T>(ttl: number) {
  const cache = new Map<string, CacheEntry<T>>()

  return {
    /**
     * Get cached data for a key or fetch new data using the provided fetcher.
     * Handles request deduplication automatically.
     */
    async get(key: string, fetcher: () => Promise<T>, forceRefresh = false): Promise<T> {
      const now = Date.now()
      const entry = cache.get(key)

      // Return cached data if still valid and not forcing refresh
      if (!forceRefresh && entry?.data !== null && entry?.data !== undefined && now - entry.timestamp < ttl) {
        return entry.data
      }

      // If a request is already in progress, wait for it
      if (entry?.promise) {
        return entry.promise
      }

      // Make new request
      const promise = fetcher()
        .then((data) => {
          cache.set(key, { data, timestamp: Date.now(), promise: null })
          return data
        })
        .catch((err) => {
          const currentEntry = cache.get(key)
          if (currentEntry) {
            currentEntry.promise = null
          }
          throw err
        })

      // Store promise while request is in flight
      cache.set(key, {
        data: entry?.data ?? null,
        timestamp: entry?.timestamp ?? 0,
        promise,
      })

      return promise
    },

    /** Invalidate cache for a specific key */
    invalidate(key: string): void {
      cache.delete(key)
    },

    /** Invalidate entire cache */
    invalidateAll(): void {
      cache.clear()
    },

    /** Check if cache has valid data for a key */
    hasValidData(key: string): boolean {
      const entry = cache.get(key)
      return entry?.data !== null && entry?.data !== undefined && Date.now() - entry.timestamp < ttl
    },
  }
}

// ============================================================================
// Default TTL Constants
// ============================================================================

/** Default TTL for frequently changing data (30 seconds) */
export const DEFAULT_CACHE_TTL = 30000

/** TTL for less frequently changing data (60 seconds) */
export const LONG_CACHE_TTL = 60000

/** TTL for user activity data (5 minutes) */
export const ACTIVITY_CACHE_TTL = 300000

