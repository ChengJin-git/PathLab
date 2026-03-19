import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  saveAnnotation,
  listAnnotations,
  getAnnotation,
  deleteAnnotation,
  getDatasetGroundTruth,
  getWSIGroundTruth,
  getGroundTruthThumbnailUrl,
  getDatasetAnnotationSummary,
  deleteDatasetAnnotationsByLabels,
  extractRegions,
  getExtractProgressSSEUrl,
  type SegmentationAnnotation,
  type AnnotationsMap,
} from '@renderer/api/annotation'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_ANNOTATIONS_MAP: AnnotationsMap = {
  wsi_001: [
    {
      id: 'region_1',
      type: 'rect',
      x: 100, y: 200, width: 300, height: 400,
      label: 'tumor',
      color: '#ff0000',
    },
  ],
}

const MOCK_ANNOTATION: SegmentationAnnotation = {
  annotation_id: 'ann_001',
  user_id: 'user_1',
  source_dataset_id: 'ds_1',
  annotations: MOCK_ANNOTATIONS_MAP,
  status: 'draft',
  source: 'user',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('saveAnnotation', () => {
  it('sends POST to /annotation/drafts', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANNOTATION))
    await saveAnnotation({ annotation_id: 'ann_001', annotations: MOCK_ANNOTATIONS_MAP })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/drafts')
    expect(opts?.method).toBe('POST')
  })

  it('includes annotation_id and annotations in body', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANNOTATION))
    await saveAnnotation({ annotation_id: 'ann_001', source_dataset_id: 'ds_1', annotations: MOCK_ANNOTATIONS_MAP })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.annotation_id).toBe('ann_001')
    expect(body.source_dataset_id).toBe('ds_1')
    expect(body.annotations).toEqual(MOCK_ANNOTATIONS_MAP)
  })

  it('returns saved annotation', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANNOTATION))
    const result = await saveAnnotation({ annotation_id: 'ann_001', annotations: MOCK_ANNOTATIONS_MAP })
    expect(result.annotation_id).toBe('ann_001')
    expect(result.status).toBe('draft')
  })
})

describe('listAnnotations', () => {
  it('fetches from GET /annotation/drafts', async () => {
    mockFetch.mockResolvedValueOnce(ok([MOCK_ANNOTATION]))
    const result = await listAnnotations()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/drafts')
    expect(result).toHaveLength(1)
    expect(result[0].annotation_id).toBe('ann_001')
  })
})

describe('getAnnotation', () => {
  it('fetches a specific annotation by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANNOTATION))
    const result = await getAnnotation('ann_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/drafts/ann_001')
    expect(result.annotation_id).toBe('ann_001')
  })

  it('URL-encodes the annotation ID', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANNOTATION))
    await getAnnotation('ann/special id')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('ann%2Fspecial%20id')
  })
})

describe('deleteAnnotation', () => {
  it('sends DELETE to /annotation/drafts/:id', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ok: true }))
    const result = await deleteAnnotation('ann_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/drafts/ann_001')
    expect(opts?.method).toBe('DELETE')
    expect(result.ok).toBe(true)
  })
})

describe('getDatasetGroundTruth', () => {
  it('fetches from /annotation/datasets/:id/ground-truth', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      dataset_id: 'ds_1',
      annotations: MOCK_ANNOTATIONS_MAP,
      record_count: 1,
      source: 'ground_truth',
    }))
    const result = await getDatasetGroundTruth('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/ground-truth')
    expect(result.dataset_id).toBe('ds_1')
    expect(result.source).toBe('ground_truth')
  })
})

describe('getWSIGroundTruth', () => {
  it('fetches from /annotation/wsi/:wsiId/ground-truth', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      dataset_id: 'ds_1',
      annotations: MOCK_ANNOTATIONS_MAP,
      record_count: 1,
      source: 'ground_truth',
    }))
    await getWSIGroundTruth('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/wsi/wsi_001/ground-truth')
  })
})

describe('getGroundTruthThumbnailUrl', () => {
  it('builds URL with wsiId and size params', () => {
    setAuthToken('test_token')
    const url = getGroundTruthThumbnailUrl('wsi_001', 320)
    expect(url).toContain('/annotation/wsi/wsi_001/ground-truth-thumbnail')
    expect(url).toContain('size=320')
    expect(url).toContain('token=test_token')
  })

  it('defaults to size 160', () => {
    const url = getGroundTruthThumbnailUrl('wsi_001')
    expect(url).toContain('size=160')
  })
})

describe('getDatasetAnnotationSummary', () => {
  it('fetches from /annotation/datasets/:id/summary', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      dataset_id: 'ds_1',
      total_regions: 5,
      total_slides: 2,
      labels: { tumor: { total_regions: 3, total_slides: 2 } },
      has_wsi_sources: true,
      source: 'effective_dataset',
    }))
    const result = await getDatasetAnnotationSummary('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/summary')
    expect(result.total_regions).toBe(5)
    expect(result.labels.tumor.total_regions).toBe(3)
  })
})

describe('deleteDatasetAnnotationsByLabels', () => {
  it('sends POST to /annotation/datasets/:id/delete-by-labels', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      ok: true,
      annotation_id: 'ann_001',
      summary: { dataset_id: 'ds_1', total_regions: 2, total_slides: 1, labels: {}, has_wsi_sources: false, source: 'effective_dataset' },
    }))
    await deleteDatasetAnnotationsByLabels('ds_1', { labels: ['tumor'] })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/delete-by-labels')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.labels).toEqual(['tumor'])
  })
})

describe('extractRegions', () => {
  it('sends POST to /annotation/extract', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'extract_001', status: 'queued' }))
    const result = await extractRegions({
      dataset_name: 'Extracted Tumor ROIs',
      task_type: 'segmentation',
      annotations: MOCK_ANNOTATIONS_MAP,
    })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/extract')
    expect(opts?.method).toBe('POST')
    expect(result.task_id).toBe('extract_001')
    expect(result.status).toBe('queued')
  })
})

describe('getExtractProgressSSEUrl', () => {
  it('returns null when not authenticated', () => {
    localStorage.removeItem('pathlab_auth_token')
    const url = getExtractProgressSSEUrl('extract_001')
    expect(url).toBeNull()
  })

  it('returns authed URL when token is set', () => {
    setAuthToken('test_token')
    const url = getExtractProgressSSEUrl('extract_001')
    expect(url).not.toBeNull()
    expect(url).toContain('/annotation/extract/extract_001/stream')
    expect(url).toContain('token=test_token')
  })
})
