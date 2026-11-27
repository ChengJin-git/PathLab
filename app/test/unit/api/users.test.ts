import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  listUsers,
  listUsersPaged,
  getUserById,
  createUser,
  updateUser,
  deleteUser,
  batchActivateUsers,
  batchDeactivateUsers,
  batchDeleteUsers,
  getMaintenanceMode,
  setMaintenanceMode,
  acceptAgreement,
  revokeUserAgreement,
} from '@renderer/api/users'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_USER = {
  id: 'user_1',
  email: 'doctor@hospital.com',
  nickname: 'Dr. Smith',
  role: 'pathologist' as const,
  is_active: true,
  is_superuser: false,
  is_verified: true,
  agreement_accepted_at: '2024-01-01T00:00:00Z',
  agreement_ip: '192.168.1.1',
  notice_acknowledged_at: null,
  created_at: '2024-01-01T00:00:00Z',
}

beforeEach(() => {
  setAuthToken('admin_token')
})

describe('listUsers', () => {
  it('fetches all users list', async () => {
    mockFetch.mockResolvedValueOnce(ok([MOCK_USER]))
    const result = await listUsers()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users')
    expect(result).toHaveLength(1)
    expect(result[0].email).toBe('doctor@hospital.com')
  })

  it('throws AUTH_ERROR when not admin', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Forbidden' }, 403))
    await expect(listUsers()).rejects.toMatchObject({ status: 403, code: 'AUTH_ERROR' })
  })
})

describe('listUsersPaged', () => {
  it('fetches users with pagination', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_USER], total: 1, page: 1, page_size: 20 }))
    const result = await listUsersPaged({ page: 1, page_size: 20 })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/paged')
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=20')
    expect(result.items).toHaveLength(1)
  })

  it('sends search query', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20 }))
    await listUsersPaged({ search: 'smith' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('search=smith')
  })

  it('excludes whitespace-only search', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20 }))
    await listUsersPaged({ search: '   ' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).not.toContain('search=')
  })

  it('sends exclude_admin param when set to true', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20 }))
    await listUsersPaged({ exclude_admin: true })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('exclude_admin=true')
  })
})

describe('getUserById', () => {
  it('fetches a user by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_USER))
    const result = await getUserById('user_1')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/user_1')
    expect(result.email).toBe('doctor@hospital.com')
  })
})

describe('createUser', () => {
  it('sends POST to /auth/users with full admin create payload', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, id: 'new_user_1' }))
    const result = await createUser({
      username: 'newpath',
      password: 'secure123',
      nickname: 'New Pathologist',
      role: 'pathologist',
      registration_email: 'newpath@hospital.com',
    })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.username).toBe('newpath')
    expect(body.password).toBe('secure123')
    expect(body.nickname).toBe('New Pathologist')
    expect(body.role).toBe('pathologist')
    expect(body.registration_email).toBe('newpath@hospital.com')
    expect(result.id).toBe('new_user_1')
  })

  it('omits optional registration_email when not provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, id: 'new_user_2' }))
    await createUser({
      username: 'bare',
      password: 'pass1234',
      nickname: '',
      role: 'guest',
    })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.registration_email).toBeUndefined()
  })
})

describe('updateUser', () => {
  it('sends PATCH request with admin update data', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, is_active: false }))
    const result = await updateUser('user_1', { is_active: false, role: 'guest' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/user_1')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.is_active).toBe(false)
    expect(body.role).toBe('guest')
    expect(result.is_active).toBe(false)
  })
})

describe('deleteUser', () => {
  it('sends DELETE request for a user', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
    } as unknown as Response)
    await deleteUser('user_1')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/user_1')
    expect(opts?.method).toBe('DELETE')
  })
})

describe('batchActivateUsers', () => {
  it('sends POST with user_ids to batch activate endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ updated: 3 }))
    const result = await batchActivateUsers(['user_1', 'user_2', 'user_3'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/batch/activate')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_1', 'user_2', 'user_3'])
    expect(result.updated).toBe(3)
  })
})

describe('batchDeactivateUsers', () => {
  it('sends POST with user_ids to batch deactivate endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ updated: 2 }))
    const result = await batchDeactivateUsers(['user_1', 'user_2'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/batch/deactivate')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_1', 'user_2'])
    expect(result.updated).toBe(2)
  })
})

describe('batchDeleteUsers', () => {
  it('sends POST with user_ids to batch delete endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ deleted: 1 }))
    const result = await batchDeleteUsers(['user_1'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/batch/delete')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.user_ids).toEqual(['user_1'])
    expect(result.deleted).toBe(1)
  })
})

describe('getMaintenanceMode', () => {
  it('fetches maintenance mode status', async () => {
    mockFetch.mockResolvedValueOnce(ok({ enabled: false }))
    const result = await getMaintenanceMode()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/maintenance-mode')
    expect(result.enabled).toBe(false)
  })
})

describe('setMaintenanceMode', () => {
  it('enables maintenance mode', async () => {
    mockFetch.mockResolvedValueOnce(ok({ enabled: true, affected_users: 5 }))
    const result = await setMaintenanceMode(true)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/maintenance-mode')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.enabled).toBe(true)
    expect(result.affected_users).toBe(5)
  })

  it('disables maintenance mode', async () => {
    mockFetch.mockResolvedValueOnce(ok({ enabled: false, affected_users: 5 }))
    await setMaintenanceMode(false)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.enabled).toBe(false)
  })
})

describe('acceptAgreement', () => {
  it('accepts without a browser-provided IP address', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, agreement_accepted_at: '2024-01-01T00:00:00Z' }))
    const result = await acceptAgreement()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/accept-agreement')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body).toEqual({})
    expect(result.agreement_accepted_at).toBe('2024-01-01T00:00:00Z')
  })

  it('sends null IP when not provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_USER))
    await acceptAgreement()
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.ip).toBeUndefined()
  })
})

describe('revokeUserAgreement', () => {
  it('sends POST to revoke-agreement endpoint for a specific user', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, agreement_accepted_at: null }))
    const result = await revokeUserAgreement('user_1')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/users/user_1/revoke-agreement')
    expect(opts?.method).toBe('POST')
    expect(result.agreement_accepted_at).toBeNull()
  })
})
