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
// Persistent Cache (localStorage-backed)
// ============================================================================

interface PersistentCacheData<T> {
  data: T
  timestamp: number
}

/**
 * Creates a persistent cache backed by localStorage.
 * Data persists across page refreshes and browser sessions.
 *
 * @param key - localStorage key for this cache
 * @param ttl - Time-to-live in milliseconds
 * @returns Cache instance with get, invalidate methods
 *
 * @example
 * ```ts
 * const externalDatasetsCache = createPersistentCache<ExternalDatasetsResponse>(
 *   'external-datasets-cache',
 *   LONG_CACHE_TTL
 * )
 *
 * async function getExternalDatasets(): Promise<ExternalDatasetsResponse> {
 *   return externalDatasetsCache.get(() => apiFetch('/storage/external-datasets-summary'))
 * }
 * ```
 */
export function createPersistentCache<T>(key: string, ttl: number) {
  // In-memory promise for request deduplication
  let promise: Promise<T> | null = null

  /**
   * Load cached data from localStorage
   */
  function loadFromStorage(): PersistentCacheData<T> | null {
    try {
      const stored = localStorage.getItem(key)
      if (stored) {
        return JSON.parse(stored) as PersistentCacheData<T>
      }
    } catch (err) {
      console.warn(`Failed to load cache from localStorage (${key}):`, err)
    }
    return null
  }

  /**
   * Save data to localStorage
   */
  function saveToStorage(data: T): void {
    try {
      const cacheData: PersistentCacheData<T> = {
        data,
        timestamp: Date.now(),
      }
      localStorage.setItem(key, JSON.stringify(cacheData))
    } catch (err) {
      console.warn(`Failed to save cache to localStorage (${key}):`, err)
    }
  }

  return {
    /**
     * Get cached data or fetch new data using the provided fetcher.
     * First tries localStorage, then falls back to fetcher.
     */
    async get(fetcher: () => Promise<T>, forceRefresh = false): Promise<T> {
      const now = Date.now()

      // Try to load from localStorage first
      if (!forceRefresh) {
        const cached = loadFromStorage()
        if (cached && now - cached.timestamp < ttl) {
          return cached.data
        }
      }

      // If a request is already in progress, wait for it
      if (promise) {
        return promise
      }

      // Make new request
      promise = fetcher()
        .then((data) => {
          saveToStorage(data)
          promise = null
          return data
        })
        .catch((err) => {
          promise = null
          throw err
        })

      return promise
    },

    /** Invalidate the cache */
    invalidate(): void {
      try {
        localStorage.removeItem(key)
      } catch (err) {
        console.warn(`Failed to invalidate cache (${key}):`, err)
      }
    },

    /** Check if cache has valid data */
    hasValidData(): boolean {
      const cached = loadFromStorage()
      return cached !== null && Date.now() - cached.timestamp < ttl
    },

    /** Get cached data synchronously (returns null if no valid cache) */
    getCachedSync(): T | null {
      const cached = loadFromStorage()
      if (cached && Date.now() - cached.timestamp < ttl) {
        return cached.data
      }
      return null
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

/** TTL for persistent cache data (1 hour - aggressive caching for expensive operations) */
export const PERSISTENT_CACHE_TTL = 3600000

