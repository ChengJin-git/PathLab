import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  getMyDatasetPermissions,
  grantDatasetPermission,
  revokeDatasetPermission,
  getUserDatasetPermissions,
  listDatasetPermissions,
  batchGrantDatasetPermissions,
  batchRevokeDatasetPermissions,
  type DatasetPermission,
} from '@renderer/api/permissions'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_PERMISSION: DatasetPermission = {
  id: 1,
  dataset_id: 'ds_1',
  dataset_name: 'TCGA-BRCA',
  user_id: 'user_2',
  user_email: 'guest@hospital.com',
  user_nickname: 'Guest User',
  user_role: 'guest',
  user_is_active: true,
  granted_by: 'user_1',
  permission_level: 'read',
  expires_at: null,
  created_at: '2024-01-01T00:00:00Z',
  is_expired: false,
  is_valid: true,
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('getMyDatasetPermissions', () => {
  it('fetches from GET /wsi/my-permissions', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      user_id: 'user_2',
      permissions: [MOCK_PERMISSION],
      elevated_dataset_ids: ['ds_1'],
    }))
    const result = await getMyDatasetPermissions()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/my-permissions')
    expect(result.elevated_dataset_ids).toContain('ds_1')
    expect(result.permissions).toHaveLength(1)
  })
})

describe('grantDatasetPermission', () => {
  it('sends POST with FormData to /wsi/datasets/:id/permissions', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Permission granted', permission: MOCK_PERMISSION }))
    await grantDatasetPermission('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/permissions')
    expect(opts?.method).toBe('POST')
    expect(opts?.body).toBeInstanceOf(FormData)
  })

  it('includes user_id in FormData', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Permission granted', permission: MOCK_PERMISSION }))
    await grantDatasetPermission('ds_1', 'user_2')
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('user_id')).toBe('user_2')
  })

  it('includes expires_in_hours when provided and > 0', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Permission granted', permission: MOCK_PERMISSION }))
    await grantDatasetPermission('ds_1', 'user_2', 48)
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('expires_in_hours')).toBe('48')
  })

  it('does not include expires_in_hours when 0', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Permission granted', permission: MOCK_PERMISSION }))
    await grantDatasetPermission('ds_1', 'user_2', 0)
    const formData = mockFetch.mock.calls[0][1]?.body as FormData
    expect(formData.get('expires_in_hours')).toBeNull()
  })
})

describe('revokeDatasetPermission', () => {
  it('sends DELETE to /wsi/datasets/:datasetId/permissions/:userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Permission revoked' }))
    const result = await revokeDatasetPermission('ds_1', 'user_2')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/permissions/user_2')
    expect(opts?.method).toBe('DELETE')
    expect(result.message).toBe('Permission revoked')
  })
})

describe('getUserDatasetPermissions', () => {
  it('fetches from GET /wsi/user-permissions/:userId', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      user_id: 'user_2',
      permissions: [MOCK_PERMISSION],
      valid_permissions: [MOCK_PERMISSION],
    }))
    const result = await getUserDatasetPermissions('user_2')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/user-permissions/user_2')
    expect(result.valid_permissions).toHaveLength(1)
  })
})

describe('listDatasetPermissions', () => {
  it('fetches from GET /wsi/datasets/:datasetId/permissions', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', permissions: [MOCK_PERMISSION] }))
    const result = await listDatasetPermissions('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/permissions')
    expect(result.permissions).toHaveLength(1)
  })

  it('throws NOT_FOUND for unknown dataset', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Dataset not found' }, 404))
    await expect(listDatasetPermissions('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})

describe('batchGrantDatasetPermissions', () => {
  it('sends POST to /wsi/datasets/:id/permissions/batch-grant', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', granted: 2, failed: 0, results: [] }))
    await batchGrantDatasetPermissions('ds_1', ['user_2', 'user_3'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/permissions/batch-grant')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_2', 'user_3'])
  })

  it('includes expires_in_hours when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', granted: 1, failed: 0, results: [] }))
    await batchGrantDatasetPermissions('ds_1', ['user_2'], 24)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.expires_in_hours).toBe(24)
  })
})

describe('batchRevokeDatasetPermissions', () => {
  it('sends POST to /wsi/datasets/:id/permissions/batch-revoke', async () => {
    mockFetch.mockResolvedValueOnce(ok({ dataset_id: 'ds_1', revoked: 2, failed: 0, results: [] }))
    await batchRevokeDatasetPermissions('ds_1', ['user_2', 'user_3'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/wsi/datasets/ds_1/permissions/batch-revoke')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_2', 'user_3'])
  })
})
