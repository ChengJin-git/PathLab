import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok } from '../../helpers/apiHelpers'
import { clearAuthToken, setAuthToken } from '@renderer/api/client'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
}))

import {
  deletePathScientistSession,
  getPathScientistEventsUrl,
  getPathScientistSession,
  getPathScientistSessionDownloadUrl,
  getPathScientistSessionShareUrl,
  listPathScientistSessions,
  listPathScientistSkills,
  startPathScientistSession,
  stopPathScientistSession,
  downloadPathScientistSession,
  downloadPathScientistRun,
  sharePathScientistSession,
} from '@renderer/api/pathscientist'

const mockFetch = vi.mocked(fetch)

beforeEach(() => {
  mockFetch.mockReset()
  clearAuthToken()
})

describe('pathscientist api', () => {
  it('lists skills', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [{ id: 'mil_classification', name: 'MIL' }] }))

    const result = await listPathScientistSkills()

    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:6100/pathscientist/skills')
    expect(result.items[0].id).toBe('mil_classification')
  })

  it('starts a session with gpt-5.5 default when model is omitted', async () => {
    setAuthToken('session-token')
    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', conversation_id: '', model: 'gpt-5.5', status: 'queued' }))

    await startPathScientistSession({ question: 'hello' })

    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:6100/pathscientist/sessions')
    expect(opts?.method).toBe('POST')
    expect(new Headers(opts?.headers).get('Authorization')).toBe('Bearer session-token')
    expect(JSON.parse(opts?.body as string).model).toBe('gpt-5.5')
  })

  it('lists and fetches sessions', async () => {
    setAuthToken('session-token')
    mockFetch.mockResolvedValueOnce(ok({ items: [{ session_id: 'abc' }] }))

    await listPathScientistSessions()

    const [listUrl, listOpts] = mockFetch.mock.calls[0]
    expect(listUrl).toBe('http://localhost:6100/pathscientist/sessions')
    expect(new Headers(listOpts?.headers).get('Authorization')).toBe('Bearer session-token')

    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', events: [] }))

    await getPathScientistSession('abc')

    const [detailUrl, detailOpts] = mockFetch.mock.calls[1]
    expect(detailUrl).toBe('http://localhost:6100/pathscientist/sessions/abc')
    expect(new Headers(detailOpts?.headers).get('Authorization')).toBe('Bearer session-token')
  })

  it('builds an EventSource URL with a scoped access token', async () => {
    setAuthToken('stream-token')
    mockFetch.mockResolvedValueOnce(ok({
      token: 'scoped-stream-token',
      token_type: 'pathscientist_access',
      purpose: 'events',
      session_id: 'abc',
      run_id: '',
      expires_in: 300,
    }))

    await expect(getPathScientistEventsUrl('abc')).resolves.toBe(
      'http://localhost:6100/pathscientist/sessions/abc/events?token=scoped-stream-token',
    )
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:6100/pathscientist/sessions/abc/access-token')
    expect(JSON.parse(mockFetch.mock.calls[0][1]?.body as string)).toEqual({
      purpose: 'events',
      run_id: '',
    })
  })

  it('stops a running session', async () => {
    setAuthToken('session-token')
    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', status: 'interrupted' }))

    await stopPathScientistSession('abc')

    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:6100/pathscientist/sessions/abc/stop')
    expect(opts?.method).toBe('POST')
    expect(new Headers(opts?.headers).get('Authorization')).toBe('Bearer session-token')
  })

  it('deletes a session', async () => {
    setAuthToken('session-token')
    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', deleted: true }))

    await deletePathScientistSession('abc')

    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:6100/pathscientist/sessions/abc')
    expect(opts?.method).toBe('DELETE')
    expect(new Headers(opts?.headers).get('Authorization')).toBe('Bearer session-token')
  })

  it('builds session download URL with a scoped access token and share URL', async () => {
    setAuthToken('download-token')
    mockFetch.mockResolvedValueOnce(ok({
      token: 'scoped-download-token',
      token_type: 'pathscientist_access',
      purpose: 'session_download',
      session_id: 'abc',
      run_id: '',
      expires_in: 300,
    }))

    await expect(getPathScientistSessionDownloadUrl('abc')).resolves.toBe(
      'http://localhost:6100/pathscientist/sessions/abc/download?token=scoped-download-token',
    )
    expect(getPathScientistSessionShareUrl('abc')).toContain('/pathscientist/sessions/abc')
  })

  it('downloads a run with a scoped access token through fetch instead of page navigation', async () => {
    setAuthToken('download-token')
    const originalURL = globalThis.URL
    const originalClick = HTMLAnchorElement.prototype.click
    try {
      vi.stubGlobal('URL', {
        createObjectURL: vi.fn(() => 'blob:run-zip'),
        revokeObjectURL: vi.fn(),
      })
      HTMLAnchorElement.prototype.click = vi.fn()
      mockFetch
        .mockResolvedValueOnce(ok({
          token: 'scoped-run-token',
          token_type: 'pathscientist_access',
          purpose: 'run_download',
          session_id: 'abc',
          run_id: 'run_1',
          expires_in: 300,
        }))
        .mockResolvedValueOnce(new Response(new Blob(['zip-content']), {
          status: 200,
          headers: new Headers({
            'Content-Disposition': 'attachment; filename="pathscientist-abc-run_1.zip"',
          }),
        }))

      const result = await downloadPathScientistRun('abc', 'run_1')

      expect(result.filename).toBe('pathscientist-abc-run_1.zip')
      expect(mockFetch).toHaveBeenCalledTimes(2)
      expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:6100/pathscientist/sessions/abc/access-token')
      expect(JSON.parse(mockFetch.mock.calls[0][1]?.body as string)).toEqual({
        purpose: 'run_download',
        run_id: 'run_1',
      })
      expect(mockFetch.mock.calls[1][0]).toBe(
        'http://localhost:6100/pathscientist/sessions/abc/runs/run_1/download?token=scoped-run-token',
      )
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    } finally {
      vi.stubGlobal('URL', originalURL)
      HTMLAnchorElement.prototype.click = originalClick
    }
  })

  describe('user-visible branding', () => {
    it('uses AutoResearch in apiFetch context for start session', async () => {
      setAuthToken('session-token')
      mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', conversation_id: '', model: 'gpt-5.5', status: 'queued' }))

      await startPathScientistSession({ question: 'hello' })

      mockFetch.mockReset()
      mockFetch.mockRejectedValueOnce(new TypeError('Network error'))

      await expect(startPathScientistSession({ question: 'hello' })).rejects.toThrow('AutoResearch')
    })

    it('uses AutoResearch in apiFetch context for delete session', async () => {
      setAuthToken('session-token')
      mockFetch.mockRejectedValueOnce(new TypeError('Network error'))

      await expect(deletePathScientistSession('abc')).rejects.toThrow('AutoResearch')
    })

    it('uses AutoResearch in apiFetch context for list sessions', async () => {
      setAuthToken('session-token')
      mockFetch.mockRejectedValueOnce(new TypeError('Network error'))

      await expect(listPathScientistSessions()).rejects.toThrow('AutoResearch')
    })

    it('uses AutoResearch in downloadApiFile context on network error', async () => {
      setAuthToken('download-token')
      mockFetch.mockRejectedValueOnce(new TypeError('Network error'))

      await expect(downloadPathScientistSession('abc')).rejects.toThrow('AutoResearch')
    })

    it('returns autoresearch fallback filename on successful download without Content-Disposition', async () => {
      setAuthToken('download-token')
      const originalURL = globalThis.URL
      const originalClick = HTMLAnchorElement.prototype.click
      try {
        vi.stubGlobal('URL', {
          createObjectURL: vi.fn(() => 'blob:mock-url'),
          revokeObjectURL: vi.fn(),
        })
        HTMLAnchorElement.prototype.click = vi.fn()
        mockFetch.mockResolvedValueOnce(new Response(new Blob(['zip-content']), {
          status: 200,
          headers: new Headers(),
        }))

        const result = await downloadPathScientistSession('abc')

        expect(result.filename).toBe('autoresearch-abc.zip')
      } finally {
        vi.stubGlobal('URL', originalURL)
        HTMLAnchorElement.prototype.click = originalClick
      }
    })

    it('uses AutoResearch in navigator.share title', async () => {
      const originalNavigator = window.navigator
      const shareMock = vi.fn()
      try {
        Object.defineProperty(window, 'navigator', {
          value: { ...originalNavigator, share: shareMock, clipboard: undefined },
          writable: true,
          configurable: true,
        })
        shareMock.mockResolvedValue(undefined)

        await sharePathScientistSession('abc')

        expect(shareMock).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'AutoResearch session',
          }),
        )
      } finally {
        Object.defineProperty(window, 'navigator', {
          value: originalNavigator,
          writable: true,
          configurable: true,
        })
      }
    })
  })
})
