import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  fetchAvailableHeatmaps,
  invalidateHeatmapAvailabilityCache,
  fetchHeatmapData,
  getPatchImageUrl,
  getThumbnailUrl,
  getHeatmapThumbnailUrl,
  getPatchCAMImageUrl,
  getSegMaskImageUrl,
  getRecommendationThumbnailUrl,
  SEGMENTATION_MASK_COLORS,
} from '@renderer/api/heatmap'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_HEATMAPS = [
  {
    task_id: 'task_001',
    task_type: 'wsi_classification',
    task_name: 'BRCA Classifier',
    prediction: 'LUAD',
    probs: { LUAD: 0.85, LUSC: 0.15 },
    classes: ['LUAD', 'LUSC'],
    feature_extractor: 'uni',
    aggregator: 'abmil',
    created_at: 1704067200,
    attention_file: '/data/attention/task_001.pt',
    patch_size: 512,
    data_type: 'wsi' as const,
    is_best_fold: true,
    is_kfold: false,
    attention_type: 'single' as const,
  },
]

const MOCK_HEATMAP_DATA = {
  wsi_id: 'wsi_001',
  task_id: 'task_001',
  task_name: 'BRCA Classifier',
  patch_size: 512,
  slide_width: 50000,
  slide_height: 40000,
  num_patches: 1500,
  attention_min: 0.001,
  attention_max: 0.95,
  prediction: 'LUAD',
  probs: { LUAD: 0.85, LUSC: 0.15 },
  heatmap: [{ index: 0, x: 0, y: 0, weight: 0.5, raw_weight: 0.5 }],
  top_patches: [{ index: 100, x: 5120, y: 4096, weight: 0.95, raw_weight: 0.95 }],
  bottom_patches: [{ index: 200, x: 0, y: 0, weight: 0.001, raw_weight: 0.001 }],
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateHeatmapAvailabilityCache()
})

describe('fetchAvailableHeatmaps', () => {
  it('fetches available heatmaps for a WSI', async () => {
    mockFetch.mockResolvedValueOnce(ok({ heatmaps: MOCK_HEATMAPS }))
    const result = await fetchAvailableHeatmaps('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/heatmap/wsi/wsi_001/available')
    expect(result).toHaveLength(1)
    expect(result[0].task_id).toBe('task_001')
    expect(result[0].prediction).toBe('LUAD')
  })

  it('returns empty array when no heatmaps available', async () => {
    mockFetch.mockResolvedValueOnce(ok({ heatmaps: [] }))
    const result = await fetchAvailableHeatmaps('wsi_001')
    expect(result).toEqual([])
  })

  it('returns empty array when heatmaps field is missing from response', async () => {
    mockFetch.mockResolvedValueOnce(ok({}))
    const result = await fetchAvailableHeatmaps('wsi_001')
    expect(result).toEqual([])
  })

  it('does not reuse another user\'s result catalog for the same slide', async () => {
    mockFetch.mockResolvedValueOnce(ok({ heatmaps: MOCK_HEATMAPS }))
    expect(await fetchAvailableHeatmaps('wsi_001')).toHaveLength(1)
    setAuthToken('another_user_token')
    mockFetch.mockResolvedValueOnce(ok({ heatmaps: [] }))
    expect(await fetchAvailableHeatmaps('wsi_001')).toEqual([])
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('caches independently for different WSI IDs', async () => {
    mockFetch.mockResolvedValue(ok({ heatmaps: MOCK_HEATMAPS }))
    await fetchAvailableHeatmaps('wsi_001')
    await fetchAvailableHeatmaps('wsi_002')
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('invalidateHeatmapAvailabilityCache', () => {
  it('clears cache for a specific WSI', async () => {
    mockFetch.mockResolvedValue(ok({ heatmaps: MOCK_HEATMAPS }))
    await fetchAvailableHeatmaps('wsi_001')
    invalidateHeatmapAvailabilityCache('wsi_001')
    await fetchAvailableHeatmaps('wsi_001')
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('reads the latest authorized catalog for other slides after invalidation', async () => {
    mockFetch.mockResolvedValue(ok({ heatmaps: MOCK_HEATMAPS }))
    await fetchAvailableHeatmaps('wsi_001')
    await fetchAvailableHeatmaps('wsi_002')
    invalidateHeatmapAvailabilityCache('wsi_001')
    mockFetch.mockResolvedValueOnce(ok({ heatmaps: [] }))
    expect(await fetchAvailableHeatmaps('wsi_002')).toEqual([])
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })

  it('clears all WSI caches when called without arguments', async () => {
    mockFetch.mockResolvedValue(ok({ heatmaps: MOCK_HEATMAPS }))
    await fetchAvailableHeatmaps('wsi_001')
    await fetchAvailableHeatmaps('wsi_002')
    invalidateHeatmapAvailabilityCache()
    await fetchAvailableHeatmaps('wsi_001')
    await fetchAvailableHeatmaps('wsi_002')
    expect(mockFetch).toHaveBeenCalledTimes(4)
  })
})

describe('fetchHeatmapData', () => {
  it('fetches heatmap data for a WSI', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_HEATMAP_DATA))
    const result = await fetchHeatmapData('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/heatmap/wsi/wsi_001/data')
    expect(url).toContain('patch_size=512')
    expect(result.wsi_id).toBe('wsi_001')
    expect(result.prediction).toBe('LUAD')
    expect(result.top_patches).toHaveLength(1)
  })

  it('includes task_id param when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_HEATMAP_DATA))
    await fetchHeatmapData('wsi_001', 'task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_id=task_001')
  })

  it('includes fold_key param when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_HEATMAP_DATA))
    await fetchHeatmapData('wsi_001', undefined, 512, 'fold_0')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('fold_key=fold_0')
  })

  it('uses custom patch_size', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_HEATMAP_DATA))
    await fetchHeatmapData('wsi_001', undefined, 256)
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('patch_size=256')
  })
})

describe('getPatchImageUrl', () => {
  it('builds correct URL with x, y, size and auth token', () => {
    const url = getPatchImageUrl('wsi_001', 1024, 2048, 256)
    expect(url).toContain('/heatmap/wsi/wsi_001/patch_image')
    expect(url).toContain('x=1024')
    expect(url).toContain('y=2048')
    expect(url).toContain('size=256')
    expect(url).toContain('token=test_token')
  })

  it('uses default size of 256', () => {
    const url = getPatchImageUrl('wsi_001', 0, 0)
    expect(url).toContain('size=256')
  })
})

describe('getThumbnailUrl', () => {
  it('builds thumbnail URL with size and auth token', () => {
    const url = getThumbnailUrl('wsi_001', 128)
    expect(url).toContain('/heatmap/wsi/wsi_001/thumbnail')
    expect(url).toContain('size=128')
    expect(url).toContain('token=test_token')
  })

  it('uses default size of 256', () => {
    const url = getThumbnailUrl('wsi_001')
    expect(url).toContain('size=256')
  })
})

describe('getHeatmapThumbnailUrl', () => {
  it('builds heatmap thumbnail URL with all params', () => {
    const url = getHeatmapThumbnailUrl('wsi_001', 'task_001', 256, 0, 'fold_0')
    expect(url).toContain('/heatmap/wsi/wsi_001/heatmap_thumbnail')
    expect(url).toContain('task_id=task_001')
    expect(url).toContain('size=256')
    expect(url).toContain('class_idx=0')
    expect(url).toContain('fold_key=fold_0')
    expect(url).toContain('token=test_token')
  })
})

describe('getPatchCAMImageUrl', () => {
  it('builds patch CAM image URL', () => {
    const url = getPatchCAMImageUrl('wsi_001', 'task_001', 'fold_0', 256)
    expect(url).toContain('/heatmap/wsi/wsi_001/patch_cam')
    expect(url).toContain('format=image')
    expect(url).toContain('task_id=task_001')
    expect(url).toContain('fold_key=fold_0')
    expect(url).toContain('token=test_token')
  })
})

describe('getSegMaskImageUrl', () => {
  it('builds segmentation mask image URL', () => {
    const url = getSegMaskImageUrl('wsi_001', 'task_001')
    expect(url).toContain('/heatmap/wsi/wsi_001/seg_mask')
    expect(url).toContain('task_id=task_001')
    expect(url).toContain('token=test_token')
  })
})

describe('getRecommendationThumbnailUrl', () => {
  it('builds recommendation thumbnail URL with preset=recommendation', () => {
    const url = getRecommendationThumbnailUrl('wsi_001', 160)
    expect(url).toContain('/heatmap/wsi/wsi_001/thumbnail')
    expect(url).toContain('preset=recommendation')
    expect(url).toContain('size=160')
    expect(url).toContain('token=test_token')
  })
})

describe('SEGMENTATION_MASK_COLORS', () => {
  it('has at least 10 distinct colors', () => {
    expect(SEGMENTATION_MASK_COLORS.length).toBeGreaterThanOrEqual(10)
  })

  it('all colors are valid hex strings', () => {
    for (const color of SEGMENTATION_MASK_COLORS) {
      expect(color).toMatch(/^#[0-9a-fA-F]{6}$/)
    }
  })
})
