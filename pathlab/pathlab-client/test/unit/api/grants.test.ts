import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  getMyDatasetGrants,
  grantDatasetGrant,
  revokeDatasetGrant,
  getUserDatasetGrants,
  listDatasetGrants,
  batchGrantDatasetGrants,
  batchRevokeDatasetGrants,
  type DatasetGrant,
} from '@renderer/api/grants'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_GRANT: DatasetGrant = {
  id: 1,
  dataset_id: 'ds_1',
  dataset_name: 'TCGA-BRCA',
  user_id: 'user_2',
  user_email: 'guest@hospital.com',
  user_nickname: 'Guest User',
  user_role: 'guest',
  user_is_active: true,
  granted_by: 'user_1',
  can_collaborate: false,
  can_use_gpu: true,
  expires_at: null,
  created_at: '2024-01-01T00:00:00Z',
  is_expired: false,
  is_valid: true,
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('getMyDatasetGrants', () => {
  it('fetches from GET /wsi/my-grants', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      user_id: 'user_2',
      grants: [MOCK_GRANT],
      elevated_dataset_ids: ['ds_1'],
    }))
    const result = await getMyDatasetGrants()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/my-grants')
    expect(result.elevated_dataset_ids).toContain('ds_1')
    expect(result.grants).toHaveLength(1)
  })
})

describe('grantDatasetGrant', () => {
  it('sends POST with FormData to /wsi/datasets/:id/grants', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Grant created', grant: MOCK_GRANT }))
    await grantDatasetGrant('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/grants')
    expect(opts?.method).toBe('POST')
    expect(opts?.body).toBeInstanceOf(FormData)
  })

  it('includes user_id in FormData', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Grant created', grant: MOCK_GRANT }))
    await grantDatasetGrant('ds_1', 'user_2')
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('user_id')).toBe('user_2')
  })

  it('includes expires_in_hours when provided and > 0', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Grant created', grant: MOCK_GRANT }))
    await grantDatasetGrant('ds_1', 'user_2', 48)
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('expires_in_hours')).toBe('48')
  })

  it('does not include expires_in_hours when 0', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Grant created', grant: MOCK_GRANT }))
    await grantDatasetGrant('ds_1', 'user_2', 0)
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('expires_in_hours')).toBeNull()
  })
})

describe('revokeDatasetGrant', () => {
  it('sends DELETE to /wsi/datasets/:datasetId/grants/:userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Grant revoked' }))
    const result = await revokeDatasetGrant('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/grants/user_2')
    expect(opts?.method).toBe('DELETE')
    expect(result.message).toBe('Grant revoked')
  })
})

describe('getUserDatasetGrants', () => {
  it('fetches from GET /wsi/user-grants/:userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      user_id: 'user_2',
      grants: [MOCK_GRANT],
      valid_grants: [MOCK_GRANT],
    }))
    const result = await getUserDatasetGrants('user_2')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/user-grants/user_2')
    expect(result.valid_grants).toHaveLength(1)
  })
})

describe('listDatasetGrants', () => {
  it('fetches from GET /wsi/datasets/:datasetId/grants', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', grants: [MOCK_GRANT] }))
    const result = await listDatasetGrants('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/grants')
    expect(result.grants).toHaveLength(1)
  })

  it('throws NOT_FOUND for unknown dataset', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Dataset not found' }, 404))
    await expect(listDatasetGrants('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})

describe('batchGrantDatasetGrants', () => {
  it('sends POST to /wsi/datasets/:id/grants/batch-grant', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', granted: 2, failed: 0, results: [] }))
    await batchGrantDatasetGrants('ds_1', ['user_2', 'user_3'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/grants/batch-grant')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_2', 'user_3'])
  })

  it('includes expires_in_hours when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', granted: 1, failed: 0, results: [] }))
    await batchGrantDatasetGrants('ds_1', ['user_2'], 24)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.expires_in_hours).toBe(24)
  })
})

describe('batchRevokeDatasetGrants', () => {
  it('sends POST to /wsi/datasets/:id/grants/batch-revoke', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', revoked: 2, failed: 0, results: [] }))
    await batchRevokeDatasetGrants('ds_1', ['user_2', 'user_3'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/grants/batch-revoke')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_2', 'user_3'])
  })
})
