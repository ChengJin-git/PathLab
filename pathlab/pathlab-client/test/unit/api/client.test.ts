import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  ApiError,
  ApiErrorCode,
  getErrorCodeFromStatus,
  parseErrorResponse,
  getAuthToken,
  setAuthToken,
  clearAuthToken,
  buildSearchParams,
  appendSearchParams,
  buildAuthHeaders,
  buildAuthRequestInit,
  withAuthTokenQuery,
  apiFetch,
  apiFetchBlob,
  SESSION_EXPIRED_EVENT,
  downloadBlobFile,
} from '@renderer/api/client'

function makeJsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    blob: () => Promise.resolve(new Blob([JSON.stringify(data)])),
  } as unknown as Response
}

function makeTextResponse(text: string, status = 400): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'Bad Request',
    headers: new Headers({ 'content-type': 'text/plain' }),
    json: () => Promise.reject(new Error('not json')),
    text: () => Promise.resolve(text),
    blob: () => Promise.resolve(new Blob([text])),
  } as unknown as Response
}

function makeHtmlResponse(status = 502): Response {
  return {
    ok: false,
    status,
    statusText: 'Bad Gateway',
    headers: new Headers({ 'content-type': 'text/html' }),
    json: () => Promise.reject(new Error('not json')),
    text: () => Promise.resolve('<html>Error</html>'),
    blob: () => Promise.resolve(new Blob(['<html>Error</html>'])),
  } as unknown as Response
}

describe('ApiError', () => {
  it('sets message, status, code, details from constructor', () => {
    const err = new ApiError('not found', 404, 'NOT_FOUND', 'resource missing')
    expect(err.message).toBe('not found')
    expect(err.status).toBe(404)
    expect(err.code).toBe('NOT_FOUND')
    expect(err.details).toBe('resource missing')
    expect(err.name).toBe('ApiError')
  })

  it('is() matches error code', () => {
    const err = new ApiError('err', 400, 'VALIDATION_ERROR')
    expect(err.is('VALIDATION_ERROR')).toBe(true)
    expect(err.is('NOT_FOUND')).toBe(false)
  })

  it('isNotFound() returns true for 404 status', () => {
    expect(new ApiError('', 404, 'NOT_FOUND').isNotFound()).toBe(true)
  })

  it('isNotFound() returns true for NOT_FOUND code regardless of status', () => {
    expect(new ApiError('', 0, 'NOT_FOUND').isNotFound()).toBe(true)
  })

  it('isAuthError() returns true for 401', () => {
    expect(new ApiError('', 401, 'AUTH_ERROR').isAuthError()).toBe(true)
  })

  it('isAuthError() returns true for 403', () => {
    expect(new ApiError('', 403, 'AUTH_ERROR').isAuthError()).toBe(true)
  })

  it('isValidationError() returns true for 400', () => {
    expect(new ApiError('', 400, 'VALIDATION_ERROR').isValidationError()).toBe(true)
  })

  it('isValidationError() returns true for 422', () => {
    expect(new ApiError('', 422, 'VALIDATION_ERROR').isValidationError()).toBe(true)
  })

  it('isServerError() returns true for 500+', () => {
    expect(new ApiError('', 500, 'SERVER_ERROR').isServerError()).toBe(true)
    expect(new ApiError('', 503, 'SERVER_ERROR').isServerError()).toBe(true)
    expect(new ApiError('', 404, 'NOT_FOUND').isServerError()).toBe(false)
  })

  it('isNetworkError() returns true only for NETWORK_ERROR code', () => {
    expect(new ApiError('', 0, 'NETWORK_ERROR').isNetworkError()).toBe(true)
    expect(new ApiError('', 0, 'UNKNOWN').isNetworkError()).toBe(false)
  })

  it('defaults code to API_ERROR', () => {
    const err = new ApiError('msg', 500)
    expect(err.code).toBe('API_ERROR')
  })
})

describe('ApiErrorCode', () => {
  it('has all expected codes', () => {
    expect(ApiErrorCode.NETWORK_ERROR).toBe('NETWORK_ERROR')
    expect(ApiErrorCode.NOT_FOUND).toBe('NOT_FOUND')
    expect(ApiErrorCode.AUTH_ERROR).toBe('AUTH_ERROR')
    expect(ApiErrorCode.VALIDATION_ERROR).toBe('VALIDATION_ERROR')
    expect(ApiErrorCode.SERVER_ERROR).toBe('SERVER_ERROR')
    expect(ApiErrorCode.TIMEOUT).toBe('TIMEOUT')
    expect(ApiErrorCode.CONFLICT).toBe('CONFLICT')
    expect(ApiErrorCode.UNKNOWN).toBe('UNKNOWN')
  })
})

describe('getErrorCodeFromStatus', () => {
  it('maps 404 → NOT_FOUND', () => {
    expect(getErrorCodeFromStatus(404)).toBe('NOT_FOUND')
  })

  it('maps 401 → AUTH_ERROR', () => {
    expect(getErrorCodeFromStatus(401)).toBe('AUTH_ERROR')
  })

  it('maps 403 → AUTH_ERROR', () => {
    expect(getErrorCodeFromStatus(403)).toBe('AUTH_ERROR')
  })

  it('maps 400 → VALIDATION_ERROR', () => {
    expect(getErrorCodeFromStatus(400)).toBe('VALIDATION_ERROR')
  })

  it('maps 422 → VALIDATION_ERROR', () => {
    expect(getErrorCodeFromStatus(422)).toBe('VALIDATION_ERROR')
  })

  it('maps 409 → CONFLICT', () => {
    expect(getErrorCodeFromStatus(409)).toBe('CONFLICT')
  })

  it('maps 500+ → SERVER_ERROR', () => {
    expect(getErrorCodeFromStatus(500)).toBe('SERVER_ERROR')
    expect(getErrorCodeFromStatus(503)).toBe('SERVER_ERROR')
  })

  it('maps unknown codes → UNKNOWN', () => {
    expect(getErrorCodeFromStatus(418)).toBe('UNKNOWN')
    expect(getErrorCodeFromStatus(301)).toBe('UNKNOWN')
  })
})

describe('parseErrorResponse', () => {
  it('extracts message from JSON response with detail field', async () => {
    const resp = makeJsonResponse({ detail: 'Item not found' }, 404)
    const result = await parseErrorResponse(resp)
    expect(result.message).toBe('Item not found')
  })

  it('extracts message from JSON response with message field', async () => {
    const resp = {
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ message: 'Invalid input' }),
    } as unknown as Response
    const result = await parseErrorResponse(resp)
    expect(result.message).toBe('Invalid input')
  })

  it('uses statusText for HTML error responses', async () => {
    const resp = makeHtmlResponse(502)
    const result = await parseErrorResponse(resp)
    expect(result.message).toBe('Bad Gateway')
  })

  it('uses text body for plain-text error responses', async () => {
    const resp = makeTextResponse('Unauthorized', 401)
    const result = await parseErrorResponse(resp)
    expect(result.message).toBe('Unauthorized')
  })
})

describe('auth token management', () => {
  it('getAuthToken returns null when no token stored', () => {
    expect(getAuthToken()).toBeNull()
  })

  it('setAuthToken stores token in localStorage', () => {
    setAuthToken('my_jwt_token')
    expect(localStorage.getItem('pathlab_auth_token')).toBe('my_jwt_token')
  })

  it('getAuthToken retrieves stored token', () => {
    setAuthToken('abc123')
    expect(getAuthToken()).toBe('abc123')
  })

  it('clearAuthToken removes the stored token', () => {
    setAuthToken('to_clear')
    clearAuthToken()
    expect(getAuthToken()).toBeNull()
  })
})

describe('buildSearchParams', () => {
  it('builds params from plain object', () => {
    const params = buildSearchParams({ page: 1, size: 20 })
    expect(params.get('page')).toBe('1')
    expect(params.get('size')).toBe('20')
  })

  it('filters out null and undefined values', () => {
    const params = buildSearchParams({ a: null, b: undefined, c: 'keep' })
    expect(params.has('a')).toBe(false)
    expect(params.has('b')).toBe(false)
    expect(params.get('c')).toBe('keep')
  })

  it('handles boolean values', () => {
    const params = buildSearchParams({ active: true, deleted: false })
    expect(params.get('active')).toBe('true')
    expect(params.get('deleted')).toBe('false')
  })

  it('handles array values as repeated params', () => {
    const params = buildSearchParams({ ids: ['a', 'b', 'c'] })
    expect(params.getAll('ids')).toEqual(['a', 'b', 'c'])
  })

  it('filters null items inside arrays', () => {
    const params = buildSearchParams({ ids: ['a', null, 'b'] })
    expect(params.getAll('ids')).toEqual(['a', 'b'])
  })

  it('returns empty params for undefined input', () => {
    const params = buildSearchParams(undefined)
    expect(params.toString()).toBe('')
  })
})

describe('appendSearchParams', () => {
  it('appends to existing params', () => {
    const existing = new URLSearchParams('x=1')
    const result = appendSearchParams(existing, { y: 2 })
    expect(result.get('x')).toBe('1')
    expect(result.get('y')).toBe('2')
  })

  it('returns params unchanged when entries is undefined', () => {
    const p = new URLSearchParams('a=1')
    const result = appendSearchParams(p, undefined)
    expect(result.toString()).toBe('a=1')
  })
})

describe('buildAuthHeaders', () => {
  it('adds Authorization header when token is present', () => {
    setAuthToken('jwt_token')
    const headers = buildAuthHeaders()
    expect(headers.get('Authorization')).toBe('Bearer jwt_token')
  })

  it('does not add Authorization when no token', () => {
    const headers = buildAuthHeaders()
    expect(headers.has('Authorization')).toBe(false)
  })

  it('does not add Authorization when skipAuth is true', () => {
    setAuthToken('token')
    const headers = buildAuthHeaders(undefined, true)
    expect(headers.has('Authorization')).toBe(false)
  })

  it('does not override an existing Authorization header', () => {
    setAuthToken('token')
    const headers = buildAuthHeaders({ Authorization: 'Basic dXNlcjpwYXNz' })
    expect(headers.get('Authorization')).toBe('Basic dXNlcjpwYXNz')
  })
})

describe('buildAuthRequestInit', () => {
  it('merges headers and injects Authorization', () => {
    setAuthToken('mytoken')
    const init = buildAuthRequestInit({ method: 'POST' })
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer mytoken')
    expect(init.method).toBe('POST')
  })
})

describe('withAuthTokenQuery', () => {
  it('appends token to URL without existing query string', () => {
    setAuthToken('tok123')
    const url = withAuthTokenQuery('http://api.local/image')
    expect(url).toBe('http://api.local/image?token=tok123')
  })

  it('appends token to URL with existing query string', () => {
    setAuthToken('tok123')
    const url = withAuthTokenQuery('http://api.local/image?size=256')
    expect(url).toContain('token=tok123')
    expect(url).toContain('size=256')
  })

  it('preserves hash fragment', () => {
    setAuthToken('tok123')
    const url = withAuthTokenQuery('http://api.local/path#section')
    expect(url).toContain('token=tok123')
    expect(url).toContain('#section')
  })

  it('returns URL unchanged when no token is stored', () => {
    const url = withAuthTokenQuery('http://api.local/image')
    expect(url).toBe('http://api.local/image')
  })

  it('does not duplicate token if already present', () => {
    setAuthToken('tok123')
    const url = withAuthTokenQuery('http://api.local/image?token=existing')
    const params = new URL(url).searchParams
    expect(params.getAll('token')).toHaveLength(1)
    expect(params.get('token')).toBe('existing')
  })

  it('uses custom token parameter name', () => {
    setAuthToken('tok123')
    const url = withAuthTokenQuery('http://api.local/img', 'auth')
    expect(url).toContain('auth=tok123')
  })
})

describe('apiFetch', () => {
  const mockFetch = vi.mocked(fetch)

  it('returns parsed JSON on successful response', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ id: 1, name: 'test' }))
    const result = await apiFetch<{ id: number; name: string }>('http://api.local/test')
    expect(result).toEqual({ id: 1, name: 'test' })
  })

  it('includes Authorization header when token is set', async () => {
    setAuthToken('bearer_token')
    mockFetch.mockResolvedValue(makeJsonResponse({ ok: true }))
    await apiFetch('http://api.local/test')
    const [, opts] = mockFetch.mock.calls[0]
    const headers = new Headers(opts?.headers)
    expect(headers.get('Authorization')).toBe('Bearer bearer_token')
  })

  it('throws ApiError with NOT_FOUND code on 404', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'Not found' }, 404))
    await expect(apiFetch('http://api.local/missing')).rejects.toMatchObject({
      status: 404,
      code: 'NOT_FOUND',
    })
  })

  it('throws ApiError with SERVER_ERROR code on 500', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'Internal error' }, 500))
    await expect(apiFetch('http://api.local/broken')).rejects.toMatchObject({
      status: 500,
      code: 'SERVER_ERROR',
    })
  })

  it('throws ApiError with NETWORK_ERROR on fetch failure', async () => {
    mockFetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(apiFetch('http://api.local/unreachable')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    })
  })

  it('clears token and dispatches SESSION_EXPIRED_EVENT on 401 while authenticated', async () => {
    setAuthToken('expired_token')
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'Unauthorized' }, 401))
    const events: Event[] = []
    window.addEventListener(SESSION_EXPIRED_EVENT, (e) => events.push(e))
    await expect(apiFetch('http://api.local/protected')).rejects.toMatchObject({ status: 401 })
    expect(getAuthToken()).toBeNull()
    expect(events).toHaveLength(1)
    window.removeEventListener(SESSION_EXPIRED_EVENT, (e) => events.push(e))
  })

  it('does not dispatch SESSION_EXPIRED_EVENT on 401 without a token', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'Unauthorized' }, 401))
    const events: Event[] = []
    window.addEventListener(SESSION_EXPIRED_EVENT, (e) => events.push(e))
    await expect(apiFetch('http://api.local/protected')).rejects.toMatchObject({ status: 401 })
    expect(events).toHaveLength(0)
    window.removeEventListener(SESSION_EXPIRED_EVENT, (e) => events.push(e))
  })

  it('handles 204 No Content as undefined', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
      json: () => Promise.reject(new Error('no body')),
    } as unknown as Response)
    const result = await apiFetch('http://api.local/delete')
    expect(result).toBeUndefined()
  })

  it('prepends context to error message when context is provided', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'resource missing' }, 404))
    await expect(apiFetch('http://api.local/x', undefined, 'Load item')).rejects.toMatchObject({
      message: expect.stringContaining('Load item'),
    })
  })
})

describe('apiFetchBlob', () => {
  const mockFetch = vi.mocked(fetch)

  it('returns a Blob on success', async () => {
    const blob = new Blob(['binary data'], { type: 'application/octet-stream' })
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/octet-stream' }),
      blob: () => Promise.resolve(blob),
    } as unknown as Response)
    const result = await apiFetchBlob('http://api.local/file')
    expect(result).toBeInstanceOf(Blob)
  })

  it('throws ApiError on non-2xx status', async () => {
    mockFetch.mockResolvedValue(makeJsonResponse({ detail: 'not found' }, 404))
    const { apiFetchBlob: fetchBlob } = await import('@renderer/api/client')
    await expect(fetchBlob('http://api.local/missing')).rejects.toMatchObject({ status: 404 })
  })
})

describe('downloadBlobFile', () => {
  it('creates and clicks a download link', () => {
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn().mockReturnValue('blob:url'),
      revokeObjectURL: vi.fn(),
    })
    const blob = new Blob(['data'])
    downloadBlobFile(blob, 'test.csv')
    expect(appendSpy).toHaveBeenCalled()
    expect(removeSpy).toHaveBeenCalled()
    appendSpy.mockRestore()
    removeSpy.mockRestore()
    vi.unstubAllGlobals()
  })
})
