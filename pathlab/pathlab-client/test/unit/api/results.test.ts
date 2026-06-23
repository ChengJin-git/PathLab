import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

vi.mock('@renderer/api/heatmap', () => ({
  invalidateHeatmapAvailabilityCache: vi.fn(),
}))

import {
  fetchResults,
  fetchAllResults,
  deleteWSIResults,
  invalidateResultsCache,
} from '@renderer/api/results'
import { invalidateHeatmapAvailabilityCache } from '@renderer/api/heatmap'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_RESULT = {
  wsi_id: 'wsi_001',
  task_id: 'task_001',
  pred: 'LUAD',
  probs: { LUAD: 0.85, LUSC: 0.15 },
  metadata: null,
  created_at: '2024-01-01T00:00:00Z',
}

const MOCK_RESULT_WITH_WSI = {
  wsi_id: 'wsi_001',
  task_id: 'task_001',
  pred: 'LUAD',
  probs: { LUAD: 0.85, LUSC: 0.15 },
  label: 'LUAD',
  case_id: 'case_001',
  original_filename: 'slide.svs',
  created_at: '2024-01-01T00:00:00Z',
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateResultsCache()
})

describe('fetchResults', () => {
  it('returns AI result when prediction is available', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_RESULT))
    const result = await fetchResults('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/results/wsi/wsi_001')
    expect(result).not.toBeNull()
    expect(result?.pred).toBe('LUAD')
    expect(result?.probs?.LUAD).toBeCloseTo(0.85)
  })

  it('returns null when pred is null (no prediction yet)', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_RESULT, pred: null }))
    const result = await fetchResults('wsi_001')
    expect(result).toBeNull()
  })

  it('returns null when pred is empty string', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_RESULT, pred: '' }))
    const result = await fetchResults('wsi_001')
    expect(result).toBeNull()
  })

  it('throws ApiError with NOT_FOUND code for missing WSI', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'WSI not found' }, 404))
    await expect(fetchResults('missing_wsi')).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' })
  })

  it('throws ApiError on server error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Server error' }, 500))
    await expect(fetchResults('wsi_001')).rejects.toMatchObject({ status: 500, code: 'SERVER_ERROR' })
  })
})

describe('fetchAllResults', () => {
  it('fetches all results with WSI info', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_RESULT_WITH_WSI], total: 1 }))
    const result = await fetchAllResults()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/results')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].pred).toBe('LUAD')
    expect(result.total).toBe(1)
  })

  it('caches results within TTL', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0 }))
    await fetchAllResults()
    await fetchAllResults()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('fetches fresh data after cache is invalidated', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0 }))
    await fetchAllResults()
    invalidateResultsCache()
    await fetchAllResults()
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('deleteWSIResults', () => {
  it('sends DELETE request to /results/wsi/:id', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      task_id: 'task_001',
      database_deleted: 1,
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSIResults('wsi_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/results/wsi/wsi_001')
    expect(opts?.method).toBe('DELETE')
  })

  it('includes task_id query param when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      task_id: 'task_001',
      database_deleted: 1,
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSIResults('wsi_001', 'task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_id=task_001')
  })

  it('does not include task_id param when not provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      task_id: null,
      database_deleted: 1,
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSIResults('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).not.toContain('task_id=')
  })

  it('invalidates results cache after deletion', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0 }))
    await fetchAllResults()
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      task_id: null,
      database_deleted: 1,
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSIResults('wsi_001')
    await fetchAllResults()
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })

  it('invalidates heatmap availability cache after deletion', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      task_id: null,
      database_deleted: 1,
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSIResults('wsi_001')
    expect(invalidateHeatmapAvailabilityCache).toHaveBeenCalledWith('wsi_001')
  })

  it('returns deletion result with cleanup info', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'Results deleted',
      wsi_id: 'wsi_001',
      task_id: 'task_001',
      database_deleted: 2,
      storage_cleanup: {
        deleted_files: ['/data/results/wsi_001/pred.json'],
        deleted_dirs: [],
        failed: [],
        total_size: 1024,
        summary: '1 file deleted',
      },
    }))
    const result = await deleteWSIResults('wsi_001', 'task_001')
    expect(result.database_deleted).toBe(2)
    expect(result.storage_cleanup.deleted_files).toHaveLength(1)
  })
})
