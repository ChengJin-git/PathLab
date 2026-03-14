import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  PREPROCESSING_BASE: 'http://localhost:6101',
  AI_BASE: 'http://localhost:6102/api/ai',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

vi.mock('@renderer/api/stats', () => ({
  invalidateRecentActivityCache: vi.fn(),
}))

import {
  loginWithCredentials,
  logout,
  getCurrentUser,
  updateCurrentUser,
  registerUser,
  uploadAvatar,
  deleteAvatar,
} from '@renderer/api/auth'
import { getAuthToken, setAuthToken, clearAuthToken } from '@renderer/api/client'
import { invalidateRecentActivityCache } from '@renderer/api/stats'

const mockFetch = vi.mocked(fetch)

function ok(data: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response
}

function err(data: unknown, status: number): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response
}

const MOCK_USER = {
  id: 'user_1',
  email: 'doctor@hospital.com',
  nickname: 'Dr. Smith',
  role: 'pathologist' as const,
  is_active: true,
  is_superuser: false,
  is_verified: true,
  agreement_accepted_at: null,
  created_at: '2024-01-01T00:00:00Z',
}

describe('loginWithCredentials', () => {
  it('sends hashed password with timestamp and APP_SALT', async () => {
    mockFetch.mockResolvedValueOnce(ok({ access_token: 'jwt_token', token_type: 'bearer' }))
    await loginWithCredentials('doctor@hospital.com', 'password123')
    const [url, opts] = mockFetch.mock.calls[0]
    const body = JSON.parse(opts?.body as string)
    expect(url).toContain('/auth/secure-login')
    expect(body.username).toBe('doctor@hospital.com')
    expect(body.hashed_password).toHaveLength(64)
    expect(body.timestamp).toBeGreaterThan(0)
    expect(body.hashed_password).not.toBe('password123')
  })

  it('stores the JWT token in localStorage on success', async () => {
    mockFetch.mockResolvedValueOnce(ok({ access_token: 'my_jwt', token_type: 'bearer' }))
    await loginWithCredentials('doc@test.com', 'pw')
    expect(getAuthToken()).toBe('my_jwt')
  })

  it('calls invalidateRecentActivityCache on success', async () => {
    mockFetch.mockResolvedValueOnce(ok({ access_token: 'tok', token_type: 'bearer' }))
    await loginWithCredentials('doc@test.com', 'pw')
    expect(invalidateRecentActivityCache).toHaveBeenCalled()
  })

  it('includes turnstile_token in request body when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ access_token: 'tok', token_type: 'bearer' }))
    await loginWithCredentials('doc@test.com', 'pw', 'turnstile_value')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.turnstile_token).toBe('turnstile_value')
  })

  it('throws ApiError on login failure', async () => {
    mockFetch.mockResolvedValueOnce(err({ detail: 'login_bad_credentials' }, 401))
    await expect(loginWithCredentials('doc@test.com', 'wrong')).rejects.toMatchObject({
      status: 401,
    })
  })

  it('returns the login response with access_token', async () => {
    mockFetch.mockResolvedValueOnce(ok({ access_token: 'tok_abc', token_type: 'bearer' }))
    const result = await loginWithCredentials('doc@test.com', 'pw')
    expect(result.access_token).toBe('tok_abc')
    expect(result.token_type).toBe('bearer')
  })
})

describe('logout', () => {
  beforeEach(() => {
    setAuthToken('active_token')
  })

  it('calls the logout endpoint', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
      json: () => Promise.reject(),
    } as unknown as Response)
    await logout()
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/jwt/logout'),
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('clears auth token after successful logout', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
    } as unknown as Response)
    await logout()
    expect(getAuthToken()).toBeNull()
  })

  it('clears token even when the API call fails', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    try { await logout() } catch { }
    expect(getAuthToken()).toBeNull()
  })

  it('calls invalidateRecentActivityCache on logout', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
    } as unknown as Response)
    await logout()
    expect(invalidateRecentActivityCache).toHaveBeenCalled()
  })
})

describe('getCurrentUser', () => {
  it('returns { is_logged_in: false } when no token is stored', async () => {
    const result = await getCurrentUser()
    expect(result).toEqual({ is_logged_in: false })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('returns user info when token is valid', async () => {
    setAuthToken('valid_token')
    mockFetch.mockResolvedValueOnce(ok(MOCK_USER))
    const result = await getCurrentUser()
    expect(result.is_logged_in).toBe(true)
    expect(result.user?.email).toBe('doctor@hospital.com')
  })

  it('returns { is_logged_in: false } on 401 response', async () => {
    setAuthToken('expired_token')
    mockFetch.mockResolvedValueOnce(err({ detail: 'Unauthorized' }, 401))
    const result = await getCurrentUser()
    expect(result.is_logged_in).toBe(false)
  })

  it('clears token and returns { is_logged_in: false } on 403 response', async () => {
    setAuthToken('bad_token')
    mockFetch.mockResolvedValueOnce(err({ detail: 'Forbidden' }, 403))
    const result = await getCurrentUser()
    expect(result.is_logged_in).toBe(false)
    expect(getAuthToken()).toBeNull()
  })

  it('returns { is_logged_in: false } on network errors', async () => {
    setAuthToken('token')
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const result = await getCurrentUser()
    expect(result.is_logged_in).toBe(false)
  })
})

describe('updateCurrentUser', () => {
  it('sends PATCH request to /auth/me with updated data', async () => {
    setAuthToken('token')
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, nickname: 'Dr. Updated' }))
    const result = await updateCurrentUser({ nickname: 'Dr. Updated' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/me')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.nickname).toBe('Dr. Updated')
    expect(result.nickname).toBe('Dr. Updated')
  })

  it('can update email and password', async () => {
    setAuthToken('token')
    mockFetch.mockResolvedValueOnce(ok(MOCK_USER))
    await updateCurrentUser({ email: 'new@test.com', password: 'newpass' })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.email).toBe('new@test.com')
    expect(body.password).toBe('newpass')
  })
})

describe('registerUser', () => {
  it('sends POST request to /auth/register with user data', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_USER, 201))
    const result = await registerUser({
      email: 'newuser@test.com',
      password: 'pass123',
      nickname: 'Newbie',
      role: 'pathologist',
    })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/register')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.email).toBe('newuser@test.com')
    expect(result).toMatchObject({ email: 'doctor@hospital.com' })
  })

  it('throws ApiError when email already exists', async () => {
    mockFetch.mockResolvedValueOnce(err({ detail: 'Email already exists' }, 409))
    await expect(registerUser({ email: 'dup@test.com', password: 'pw' })).rejects.toMatchObject({
      status: 409,
      code: 'CONFLICT',
    })
  })
})

describe('uploadAvatar', () => {
  it('sends FormData via POST to /auth/avatar', async () => {
    setAuthToken('token')
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, avatar_url: 'http://cdn/avatar.png' }))
    const file = new File(['img'], 'avatar.png', { type: 'image/png' })
    const result = await uploadAvatar(file)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/avatar')
    expect(opts?.method).toBe('POST')
    expect(opts?.body).toBeInstanceOf(FormData)
    expect(result.avatar_url).toBe('http://cdn/avatar.png')
  })
})

describe('deleteAvatar', () => {
  it('sends DELETE to /auth/avatar', async () => {
    setAuthToken('token')
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_USER, avatar_url: null }))
    const result = await deleteAvatar()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/auth/avatar')
    expect(opts?.method).toBe('DELETE')
    expect(result.avatar_url).toBeNull()
  })
})
