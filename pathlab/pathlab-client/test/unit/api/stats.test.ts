import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  fetchStats,
  invalidateStatsCache,
  hasValidStatsCache,
  fetchRecentActivity,
  invalidateRecentActivityCache,
  hasValidRecentActivityCache,
  fetchUserUsageStats,
} from '@renderer/api/stats'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

function ok(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response
}

function errResp(data: unknown, status: number): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response
}

const MOCK_STATS = {
  wsi_count: 500,
  task_count: 30,
  completed_count: 25,
  results_count: 450,
  labels: { LUAD: 200, LUSC: 150, normal: 150 },
  event_status: { event: 180, censored: 270 },
}

const MOCK_RECENT_ACTIVITY = {
  recent_uploads: [
    {
      wsi_id: 'wsi_001',
      original_filename: 'slide1.svs',
      dataset_id: 'ds_1',
      dataset_name: 'TCGA-BRCA',
      label: 'LUAD',
      created_at: '2024-01-01T00:00:00Z',
    },
  ],
  recent_tasks: [
    {
      task_id: 'task_001',
      task_name: 'BRCA Classification',
      task_type: 'classification',
      task_category: 'training' as const,
      status: 'completed',
      progress: 100,
      created_at: '2024-01-01T00:00:00Z',
    },
  ],
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateStatsCache()
  invalidateRecentActivityCache()
})

describe('fetchStats', () => {
  it('fetches system statistics', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_STATS))
    const result = await fetchStats()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/stats')
    expect(result.wsi_count).toBe(500)
    expect(result.task_count).toBe(30)
    expect(result.labels.LUAD).toBe(200)
  })

  it('caches results within TTL', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_STATS))
    await fetchStats()
    await fetchStats()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh bypasses cache', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_STATS))
    await fetchStats()
    await fetchStats(true)
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('throws ApiError on server error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'DB error' }, 500))
    await expect(fetchStats()).rejects.toMatchObject({ status: 500 })
  })
})

describe('invalidateStatsCache', () => {
  it('clears the stats cache', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_STATS))
    await fetchStats()
    invalidateStatsCache()
    await fetchStats()
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('hasValidStatsCache', () => {
  it('returns false before first fetch', () => {
    expect(hasValidStatsCache()).toBe(false)
  })

  it('returns true after successful fetch', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_STATS))
    await fetchStats()
    expect(hasValidStatsCache()).toBe(true)
  })

  it('returns false after cache is invalidated', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_STATS))
    await fetchStats()
    invalidateStatsCache()
    expect(hasValidStatsCache()).toBe(false)
  })
})

describe('fetchRecentActivity', () => {
  it('fetches recent uploads and tasks', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_RECENT_ACTIVITY))
    const result = await fetchRecentActivity()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/stats/recent-activity')
    expect(result.recent_uploads).toHaveLength(1)
    expect(result.recent_tasks).toHaveLength(1)
    expect(result.recent_uploads[0].wsi_id).toBe('wsi_001')
    expect(result.recent_tasks[0].task_category).toBe('training')
  })

  it('sends upload_limit and task_limit as query params', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_RECENT_ACTIVITY))
    await fetchRecentActivity(10, 15)
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('upload_limit=10')
    expect(url).toContain('task_limit=15')
  })

  it('caches results within TTL', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_RECENT_ACTIVITY))
    await fetchRecentActivity()
    await fetchRecentActivity()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh bypasses cache', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_RECENT_ACTIVITY))
    await fetchRecentActivity(5, 5)
    await fetchRecentActivity(5, 5, true)
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('invalidateRecentActivityCache', () => {
  it('clears the recent activity cache', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_RECENT_ACTIVITY))
    await fetchRecentActivity()
    invalidateRecentActivityCache()
    await fetchRecentActivity()
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('hasValidRecentActivityCache', () => {
  it('returns false before first fetch', () => {
    expect(hasValidRecentActivityCache()).toBe(false)
  })

  it('returns true after successful fetch', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_RECENT_ACTIVITY))
    await fetchRecentActivity()
    expect(hasValidRecentActivityCache()).toBe(true)
  })
})

describe('fetchUserUsageStats (admin only)', () => {
  it('fetches per-user usage statistics', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      users: [
        {
          user_id: 'user_1',
          email: 'doctor@hospital.com',
          nickname: 'Dr. Smith',
          role: 'pathologist',
          wsi_count: 200,
          ai_task_count: 15,
          training_count: 5,
          conversation_count: 50,
          message_count: 500,
          annotation_count: 30,
          feedback_count: 10,
          thumbs_up: 8,
          thumbs_down: 2,
        },
      ],
    }))
    const result = await fetchUserUsageStats()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/stats/user-usage')
    expect(result.users).toHaveLength(1)
    expect(result.users[0].email).toBe('doctor@hospital.com')
    expect(result.users[0].wsi_count).toBe(200)
  })

  it('throws AUTH_ERROR when non-admin calls this endpoint', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Forbidden' }, 403))
    await expect(fetchUserUsageStats()).rejects.toMatchObject({
      status: 403,
      code: 'AUTH_ERROR',
    })
  })
})
