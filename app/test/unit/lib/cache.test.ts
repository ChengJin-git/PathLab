import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createCache,
  createKeyedCache,
  createPersistentCache,
  DEFAULT_CACHE_TTL,
  LONG_CACHE_TTL,
  ACTIVITY_CACHE_TTL,
  PERSISTENT_CACHE_TTL,
} from '@renderer/lib/utils/cache'

describe('cache invalidation races', () => {
  it.each(['single', 'keyed', 'persistent'] as const)('%s separates accounts and abandons late responses', async kind => {
    localStorage.setItem('pathlab_auth_token', 'owner-a')
    const single = createCache<string>(5000)
    const keyed = createKeyedCache<string>(5000)
    const persistent = createPersistentCache<string>('account-fixture', 5000)
    const get = (fetcher: () => Promise<string>) => kind === 'keyed' ? keyed.get('image', fetcher) : kind === 'single' ? single.get(fetcher) : persistent.get(fetcher)
    let finish!: (value: string) => void
    const old = get(() => new Promise(resolve => { finish = resolve }))
    localStorage.setItem('pathlab_auth_token', 'owner-b')
    expect(await get(async () => 'b')).toBe('b')
    finish('private-a'); await old
    expect(await get(async () => 'unused')).toBe('b')
    localStorage.removeItem('pathlab_auth_token')
    expect(await get(async () => 'anonymous')).toBe('anonymous')
    localStorage.removeItem('account-fixture')
  })
  it.each(['single', 'keyed', 'persistent'] as const)('%s ignores an old read that finishes after a mutation', async kind => {
    const single = createCache<number>(5000)
    const keyed = createKeyedCache<number>(5000)
    const persistent = createPersistentCache<number>('race-fixture', 5000)
    const get = (fetcher: () => Promise<number>) => kind === 'keyed' ? keyed.get('dataset', fetcher) : kind === 'single' ? single.get(fetcher) : persistent.get(fetcher)
    const invalidate = () => kind === 'keyed' ? keyed.invalidateAll() : kind === 'single' ? single.invalidate() : persistent.invalidate()
    let finishOld!: (value: number) => void
    const oldRead = get(() => new Promise(resolve => { finishOld = resolve }))
    invalidate()
    expect(await get(async () => 2)).toBe(2)
    finishOld(1)
    await oldRead
    expect(await get(async () => 3)).toBe(2)
  })
})

describe('createCache', () => {
  it('fetches data on first call', async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 42 })
    const cache = createCache<{ value: number }>(5000)
    const result = await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledOnce()
    expect(result).toEqual({ value: 42 })
  })

  it('returns cached data within TTL without calling fetcher again', async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 })
    const cache = createCache<{ value: number }>(5000)
    await cache.get(fetcher)
    await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('fetches fresh data after TTL expires', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockResolvedValue({ value: 1 })
    const cache = createCache<{ value: number }>(100)
    await cache.get(fetcher)
    vi.advanceTimersByTime(200)
    await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('deduplicates concurrent requests', async () => {
    let resolve!: (v: number) => void
    const promise = new Promise<number>((r) => { resolve = r })
    const fetcher = vi.fn().mockReturnValue(promise)
    const cache = createCache<number>(5000)
    const all = Promise.all([cache.get(fetcher), cache.get(fetcher)])
    resolve(99)
    const [r1, r2] = await all
    expect(fetcher).toHaveBeenCalledOnce()
    expect(r1).toBe(99)
    expect(r2).toBe(99)
  })

  it('forceRefresh bypasses the cache', async () => {
    const fetcher = vi.fn().mockResolvedValue(1)
    const cache = createCache<number>(5000)
    await cache.get(fetcher)
    await cache.get(fetcher, true)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('invalidate clears cached data', async () => {
    const fetcher = vi.fn().mockResolvedValue(1)
    const cache = createCache<number>(5000)
    await cache.get(fetcher)
    cache.invalidate()
    await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('hasValidData returns false before first fetch', () => {
    const cache = createCache<number>(5000)
    expect(cache.hasValidData()).toBe(false)
  })

  it('hasValidData returns true after successful fetch', async () => {
    const cache = createCache<number>(5000)
    await cache.get(vi.fn().mockResolvedValue(1))
    expect(cache.hasValidData()).toBe(true)
  })

  it('hasValidData returns false after invalidate', async () => {
    const cache = createCache<number>(5000)
    await cache.get(vi.fn().mockResolvedValue(1))
    cache.invalidate()
    expect(cache.hasValidData()).toBe(false)
  })

  it('re-throws error and allows retries', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error('network fail'))
      .mockResolvedValue(42)
    const cache = createCache<number>(5000)
    await expect(cache.get(fetcher)).rejects.toThrow('network fail')
    const result = await cache.get(fetcher)
    expect(result).toBe(42)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})

describe('createKeyedCache', () => {
  it('caches independently per key', async () => {
    const fetcher = vi.fn().mockImplementation(async (key: string) => key + '_data')
    const cache = createKeyedCache<string>(5000)
    const r1 = await cache.get('key1', () => fetcher('key1'))
    const r2 = await cache.get('key2', () => fetcher('key2'))
    expect(r1).toBe('key1_data')
    expect(r2).toBe('key2_data')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('returns cached value for same key within TTL', async () => {
    const fetcher = vi.fn().mockResolvedValue('data')
    const cache = createKeyedCache<string>(5000)
    await cache.get('k', () => fetcher())
    await cache.get('k', () => fetcher())
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('invalidate removes only the specific key', async () => {
    const fetcher = vi.fn().mockResolvedValue('x')
    const cache = createKeyedCache<string>(5000)
    await cache.get('a', () => fetcher())
    await cache.get('b', () => fetcher())
    cache.invalidate('a')
    await cache.get('a', () => fetcher())
    await cache.get('b', () => fetcher())
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('invalidateAll clears all keys', async () => {
    const fetcher = vi.fn().mockResolvedValue('x')
    const cache = createKeyedCache<string>(5000)
    await cache.get('a', () => fetcher())
    await cache.get('b', () => fetcher())
    cache.invalidateAll()
    await cache.get('a', () => fetcher())
    await cache.get('b', () => fetcher())
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('forceRefresh fetches fresh data for that key', async () => {
    const fetcher = vi.fn().mockResolvedValue(1)
    const cache = createKeyedCache<number>(5000)
    await cache.get('k', () => fetcher())
    await cache.get('k', () => fetcher(), true)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('hasValidData returns false for unknown key', () => {
    const cache = createKeyedCache<string>(5000)
    expect(cache.hasValidData('missing')).toBe(false)
  })

  it('hasValidData returns true after fetch for key', async () => {
    const cache = createKeyedCache<string>(5000)
    await cache.get('k', vi.fn().mockResolvedValue('v'))
    expect(cache.hasValidData('k')).toBe(true)
  })

  it('deduplicates concurrent fetches for the same key', async () => {
    let resolve!: (v: string) => void
    const p = new Promise<string>((r) => { resolve = r })
    const fetcher = vi.fn().mockReturnValue(p)
    const cache = createKeyedCache<string>(5000)
    const all = Promise.all([
      cache.get('k', () => fetcher()),
      cache.get('k', () => fetcher()),
    ])
    resolve('ok')
    const [r1, r2] = await all
    expect(fetcher).toHaveBeenCalledOnce()
    expect(r1).toBe('ok')
    expect(r2).toBe('ok')
  })
})

describe('createPersistentCache', () => {
  const KEY = 'test-persistent-cache'

  beforeEach(() => {
    localStorage.removeItem(KEY)
  })

  it('stores fetched data in localStorage', async () => {
    const cache = createPersistentCache<string>(KEY, 5000)
    await cache.get(vi.fn().mockResolvedValue('hello'))
    const raw = localStorage.getItem(KEY)
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!)
    expect(parsed.data).toBe('hello')
  })

  it('reads from localStorage on subsequent calls within TTL', async () => {
    const fetcher = vi.fn().mockResolvedValue('data')
    const cache = createPersistentCache<string>(KEY, 5000)
    await cache.get(fetcher)
    const cache2 = createPersistentCache<string>(KEY, 5000)
    await cache2.get(fetcher)
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('fetches fresh data after TTL expires', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockResolvedValue('old')
    const cache = createPersistentCache<string>(KEY, 100)
    await cache.get(fetcher)
    vi.advanceTimersByTime(200)
    await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('forceRefresh bypasses localStorage', async () => {
    const fetcher = vi.fn().mockResolvedValue('v')
    const cache = createPersistentCache<string>(KEY, 5000)
    await cache.get(fetcher)
    await cache.get(fetcher, true)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('invalidate removes data from localStorage', async () => {
    const fetcher = vi.fn().mockResolvedValue('v')
    const cache = createPersistentCache<string>(KEY, 5000)
    await cache.get(fetcher)
    cache.invalidate()
    expect(localStorage.getItem(KEY)).toBeNull()
    await cache.get(fetcher)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('getCachedSync returns null when no cached data', () => {
    const cache = createPersistentCache<string>(KEY, 5000)
    expect(cache.getCachedSync()).toBeNull()
  })

  it('getCachedSync returns data when cached within TTL', async () => {
    const cache = createPersistentCache<string>(KEY, 5000)
    await cache.get(vi.fn().mockResolvedValue('synced'))
    expect(cache.getCachedSync()).toBe('synced')
  })
})

describe('TTL constants', () => {
  it('DEFAULT_CACHE_TTL is 30 seconds', () => {
    expect(DEFAULT_CACHE_TTL).toBe(30000)
  })

  it('LONG_CACHE_TTL is 60 seconds', () => {
    expect(LONG_CACHE_TTL).toBe(60000)
  })

  it('ACTIVITY_CACHE_TTL is 5 minutes', () => {
    expect(ACTIVITY_CACHE_TTL).toBe(300000)
  })

  it('PERSISTENT_CACHE_TTL is 1 hour', () => {
    expect(PERSISTENT_CACHE_TTL).toBe(3600000)
  })
})
