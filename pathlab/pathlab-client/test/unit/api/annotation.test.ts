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
  getDatasetLabels,
  getWSILabels,
  getLabelThumbnailUrl,
  getDatasetAnnotationSummary,
  deleteDatasetAnnotationsByLabels,
  extractRegions,
  getExtractProgressSSEUrl,
  getSharedAnnotation,
  saveSharedAnnotation,
  deleteSharedAnnotation,
  finalizeSharedAnnotation,
  bulkDeleteSharedRegionsByCreator,
  getSharedAnnotationSSEUrl,
  listCollaborators,
  addCollaborator,
  removeCollaborator,
  getMyAnnotationAccess,
  deleteDatasetLabels,
  listAnnotationAudit,
  exportAnnotationAuditUrl,
  getPresenceWSUrl,
  type SegmentationAnnotation,
  type AnnotationsMap,
  type SharedAnnotationResponse,
  type CollaboratorMember,
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

describe('getDatasetLabels', () => {
  it('fetches from /annotation/datasets/:id/labels', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      dataset_id: 'ds_1',
      annotations: MOCK_ANNOTATIONS_MAP,
      record_count: 1,
      source: 'ground_truth',
    }))
    const result = await getDatasetLabels('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/labels')
    expect(result.dataset_id).toBe('ds_1')
    expect(result.source).toBe('ground_truth')
  })
})

describe('getWSILabels', () => {
  it('fetches from /annotation/wsi/:wsiId/labels', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      dataset_id: 'ds_1',
      annotations: MOCK_ANNOTATIONS_MAP,
      record_count: 1,
      source: 'ground_truth',
    }))
    await getWSILabels('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/wsi/wsi_001/labels')
  })
})

describe('getLabelThumbnailUrl', () => {
  it('builds URL with wsiId and size params', () => {
    setAuthToken('test_token')
    const url = getLabelThumbnailUrl('wsi_001', 320)
    expect(url).toContain('/annotation/wsi/wsi_001/label-thumbnail')
    expect(url).toContain('size=320')
    expect(url).toContain('token=test_token')
  })

  it('defaults to size 160', () => {
    const url = getLabelThumbnailUrl('wsi_001')
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
      task_type: 'patch_segmentation',
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

// ============================================================================
// Shared Annotation (Collaborative) APIs
// ============================================================================

const MOCK_SHARED_ANNOTATION: SharedAnnotationResponse = {
  annotation_id: 'shared_ann_001',
  annotations: MOCK_ANNOTATIONS_MAP,
  version: 3,
  last_edited_by: 'user_1',
  updated_at: '2024-06-01T00:00:00Z',
  is_prepopulated: false,
}

describe('getSharedAnnotation', () => {
  it('fetches from /annotation/datasets/:id/shared', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_SHARED_ANNOTATION))
    const result = await getSharedAnnotation('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/shared')
    expect(result.annotation_id).toBe('shared_ann_001')
    expect(result.version).toBe(3)
  })
})

describe('saveSharedAnnotation', () => {
  it('sends PUT to /annotation/datasets/:id/shared', async () => {
    mockFetch.mockResolvedValueOnce(ok({ annotation_id: 'shared_ann_001', version: 4, updated_at: null }))
    const result = await saveSharedAnnotation('ds_1', { annotations: MOCK_ANNOTATIONS_MAP, version: 3 })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/shared')
    expect(opts?.method).toBe('PUT')
    expect(result.version).toBe(4)
  })

  it('includes annotations and version in body', async () => {
    mockFetch.mockResolvedValueOnce(ok({ annotation_id: 'shared_ann_001', version: 4, updated_at: null }))
    await saveSharedAnnotation('ds_1', { annotations: MOCK_ANNOTATIONS_MAP, version: 3 })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.version).toBe(3)
    expect(body.annotations).toEqual(MOCK_ANNOTATIONS_MAP)
  })
})

describe('deleteSharedAnnotation', () => {
  it('sends DELETE to /annotation/datasets/:id/shared', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ok: true, deleted_regions: 5 }))
    const result = await deleteSharedAnnotation('ds_1')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/shared')
    expect(opts?.method).toBe('DELETE')
    expect(result.deleted_regions).toBe(5)
  })
})

describe('finalizeSharedAnnotation', () => {
  it('sends POST to /annotation/datasets/:id/shared/finalize with force=false by default', async () => {
    mockFetch.mockResolvedValueOnce(ok({ gt_annotation_id: 'gt_001', version: 3, region_count: 10 }))
    const result = await finalizeSharedAnnotation('ds_1')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/shared/finalize')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.force).toBe(false)
    expect(result.gt_annotation_id).toBe('gt_001')
    expect(result.region_count).toBe(10)
  })

  it('passes force=true when specified', async () => {
    mockFetch.mockResolvedValueOnce(ok({ gt_annotation_id: 'gt_001', version: 3, region_count: 10 }))
    await finalizeSharedAnnotation('ds_1', true)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.force).toBe(true)
  })
})

describe('bulkDeleteSharedRegionsByCreator', () => {
  it('sends POST to /annotation/datasets/:id/shared/regions/bulk-delete', async () => {
    mockFetch.mockResolvedValueOnce(ok({ deleted_count: 7 }))
    const result = await bulkDeleteSharedRegionsByCreator('ds_1', 'user_42')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/shared/regions/bulk-delete')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_id).toBe('user_42')
    expect(result.deleted_count).toBe(7)
  })
})

describe('getSharedAnnotationSSEUrl', () => {
  it('returns null when not authenticated', () => {
    localStorage.removeItem('pathlab_auth_token')
    const url = getSharedAnnotationSSEUrl('ds_1')
    expect(url).toBeNull()
  })

  it('returns authed URL when token is set', () => {
    setAuthToken('test_token')
    const url = getSharedAnnotationSSEUrl('ds_1')
    expect(url).not.toBeNull()
    expect(url).toContain('/annotation/datasets/ds_1/shared/stream')
    expect(url).toContain('token=test_token')
  })
})

// ============================================================================
// Collaborator Management APIs
// ============================================================================

const MOCK_COLLABORATOR: CollaboratorMember = {
  user_id: 'user_2',
  email: 'bob@example.com',
  nickname: 'Bob',
  role: 'collaborator',
}

describe('listCollaborators', () => {
  it('fetches from /annotation/datasets/:id/collaborators', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', members: [MOCK_COLLABORATOR] }))
    const result = await listCollaborators('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/collaborators')
    expect(result.members).toHaveLength(1)
    expect(result.members[0].user_id).toBe('user_2')
  })
})

describe('addCollaborator', () => {
  it('sends POST to /annotation/datasets/:id/collaborators', async () => {
    mockFetch.mockResolvedValueOnce(ok({ collaborator: MOCK_COLLABORATOR }))
    const result = await addCollaborator('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/collaborators')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_id).toBe('user_2')
    expect(result.collaborator.email).toBe('bob@example.com')
  })
})

describe('removeCollaborator', () => {
  it('sends DELETE to /annotation/datasets/:id/collaborators/:userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ok: true, residual_region_count: 2 }))
    const result = await removeCollaborator('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/collaborators/user_2')
    expect(opts?.method).toBe('DELETE')
    expect(result.residual_region_count).toBe(2)
  })

  it('URL-encodes the userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ok: true, residual_region_count: 0 }))
    await removeCollaborator('ds_1', 'user/special')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('user%2Fspecial')
  })
})

describe('getMyAnnotationAccess', () => {
  it('returns can_annotate true when user has access', async () => {
    mockFetch.mockResolvedValueOnce(ok({ can_annotate: true }))
    const result = await getMyAnnotationAccess('ds_1')
    expect(result.can_annotate).toBe(true)
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:6100/annotation/datasets/ds_1/my-access',
      expect.objectContaining({ headers: expect.any(Object) })
    )
  })

  it('returns can_annotate false when user has no access', async () => {
    mockFetch.mockResolvedValueOnce(ok({ can_annotate: false }))
    const result = await getMyAnnotationAccess('ds_1')
    expect(result.can_annotate).toBe(false)
  })

  it('URL-encodes dataset ID with special characters', async () => {
    mockFetch.mockResolvedValueOnce(ok({ can_annotate: true }))
    await getMyAnnotationAccess('ds/with spaces')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('ds%2Fwith%20spaces')
  })
})

describe('deleteDatasetLabels', () => {
  it('sends DELETE to /annotation/datasets/:id/labels', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ok: true }))
    const result = await deleteDatasetLabels('ds_1')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/datasets/ds_1/labels')
    expect(opts?.method).toBe('DELETE')
    expect(result.ok).toBe(true)
  })
})

// ============================================================================
// Annotation Audit Log APIs
// ============================================================================

describe('listAnnotationAudit', () => {
  it('fetches from /annotation/audit with no filters', async () => {
    mockFetch.mockResolvedValueOnce(ok({ entries: [], count: 0 }))
    await listAnnotationAudit({})
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/annotation/audit')
  })

  it('passes dataset_id and event_type as query params', async () => {
    mockFetch.mockResolvedValueOnce(ok({ entries: [], count: 0 }))
    await listAnnotationAudit({ dataset_id: 'ds_1', event_type: 'shared_write', limit: 10, offset: 0 })
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('dataset_id=ds_1')
    expect(String(url)).toContain('event_type=shared_write')
    expect(String(url)).toContain('limit=10')
    expect(String(url)).toContain('offset=0')
  })

  it('returns entries with count', async () => {
    const entry = {
      id: 1, dataset_id: 'ds_1', dataset_name: 'Test', user_id: 'user_1', user_display: 'Alice',
      event_type: 'shared_write', event_metadata: {}, created_at: '2024-01-01T00:00:00Z',
    }
    mockFetch.mockResolvedValueOnce(ok({ entries: [entry], count: 1 }))
    const result = await listAnnotationAudit({ dataset_id: 'ds_1' })
    expect(result.count).toBe(1)
    expect(result.entries[0].event_type).toBe('shared_write')
  })
})

describe('exportAnnotationAuditUrl', () => {
  it('builds URL with no filters', () => {
    const url = exportAnnotationAuditUrl({})
    expect(url).toContain('/annotation/audit/export')
  })

  it('builds URL with dataset_id filter', () => {
    const url = exportAnnotationAuditUrl({ dataset_id: 'ds_1' })
    expect(url).toContain('dataset_id=ds_1')
  })

  it('builds URL with event_type filter', () => {
    const url = exportAnnotationAuditUrl({ event_type: 'collaborator_add' })
    expect(url).toContain('event_type=collaborator_add')
  })
})

// ============================================================================
// WebSocket Presence URL
// ============================================================================

describe('getPresenceWSUrl', () => {
  it('returns null when not authenticated', () => {
    localStorage.removeItem('pathlab_auth_token')
    const url = getPresenceWSUrl('ds_1')
    expect(url).toBeNull()
  })

  it('returns ws:// URL when token is set', () => {
    setAuthToken('test_token')
    const url = getPresenceWSUrl('ds_1')
    expect(url).not.toBeNull()
    expect(url).toMatch(/^ws/)
    expect(url).toContain('/annotation/datasets/ds_1/presence')
    expect(url).toContain('token=test_token')
  })
})
