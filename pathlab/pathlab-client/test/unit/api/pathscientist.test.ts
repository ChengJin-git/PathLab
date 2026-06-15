import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok } from '../../helpers/apiHelpers'
import { setAuthToken } from '@renderer/api/client'

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
} from '@renderer/api/pathscientist'

const mockFetch = vi.mocked(fetch)

beforeEach(() => {
  mockFetch.mockReset()
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
    mockFetch.mockResolvedValueOnce(ok({ items: [{ session_id: 'abc' }] }))

    await listPathScientistSessions()

    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:6100/pathscientist/sessions')

    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', events: [] }))

    await getPathScientistSession('abc')

    expect(mockFetch.mock.calls[1][0]).toBe('http://localhost:6100/pathscientist/sessions/abc')
  })

  it('builds an EventSource URL', () => {
    expect(getPathScientistEventsUrl('abc')).toBe('http://localhost:6100/pathscientist/sessions/abc/events')
  })

  it('stops a running session', async () => {
    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', status: 'interrupted' }))

    await stopPathScientistSession('abc')

    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:6100/pathscientist/sessions/abc/stop')
    expect(opts?.method).toBe('POST')
  })

  it('deletes a session', async () => {
    mockFetch.mockResolvedValueOnce(ok({ session_id: 'abc', deleted: true }))

    await deletePathScientistSession('abc')

    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:6100/pathscientist/sessions/abc')
    expect(opts?.method).toBe('DELETE')
  })

  it('builds session download and share URLs', () => {
    expect(getPathScientistSessionDownloadUrl('abc')).toBe(
      'http://localhost:6100/pathscientist/sessions/abc/download',
    )
    expect(getPathScientistSessionShareUrl('abc')).toContain('/pathscientist/sessions/abc')
  })
})
