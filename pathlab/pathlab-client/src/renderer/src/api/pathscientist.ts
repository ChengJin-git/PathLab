import { API_BASE } from '../config'
<<<<<<< HEAD
import { apiFetch } from './client'
=======
import { apiFetch, downloadApiFile } from './client'
>>>>>>> auto-frontend/main
import type {
  DeletePathScientistSessionResponse,
  PathScientistSessionDetail,
  PathScientistSessionListResponse,
  PathScientistSessionSummary,
  PathScientistSkillListResponse,
  StartPathScientistSessionRequest,
} from '../types/pathscientist'

const DEFAULT_MODEL = 'gpt-5.5'

function pathScientistBase(): string {
  return `${API_BASE}/pathscientist`
}

export function listPathScientistSkills(): Promise<PathScientistSkillListResponse> {
  return apiFetch(
    `${pathScientistBase()}/skills`,
    undefined,
    'List PathScientist skills',
    true
  )
}

export function startPathScientistSession(
  input: StartPathScientistSessionRequest
): Promise<PathScientistSessionSummary> {
  return apiFetch(
    `${pathScientistBase()}/sessions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...input, model: input.model || DEFAULT_MODEL }),
    },
    'Start PathScientist session',
    true
  )
}

export function listPathScientistSessions(): Promise<PathScientistSessionListResponse> {
  return apiFetch(
    `${pathScientistBase()}/sessions`,
    undefined,
    'List PathScientist sessions',
    true
  )
}

export function getPathScientistSession(sessionId: string): Promise<PathScientistSessionDetail> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    'Get PathScientist session',
    true
  )
}

export function stopPathScientistSession(sessionId: string): Promise<PathScientistSessionSummary> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/stop`,
    { method: 'POST' },
    'Stop PathScientist session',
    true
  )
}

export function deletePathScientistSession(sessionId: string): Promise<DeletePathScientistSessionResponse> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
    'Delete PathScientist session',
    true
  )
}

export function getPathScientistEventsUrl(sessionId: string): string {
  return `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/events`
}

export function getPathScientistRunDownloadUrl(sessionId: string, runId: string): string {
  return `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`
}
<<<<<<< HEAD
=======

export function getPathScientistSessionDownloadUrl(sessionId: string): string {
  return `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/download`
}

export function downloadPathScientistSession(sessionId: string): Promise<{ filename: string }> {
  return downloadApiFile(
    getPathScientistSessionDownloadUrl(sessionId),
    `pathscientist-${sessionId}.zip`,
    undefined,
    'Download PathScientist session',
    true,
  )
}

export function getPathScientistSessionShareUrl(sessionId: string): string {
  const path = `/pathscientist/sessions/${encodeURIComponent(sessionId)}`
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}${path}`
  }
  return path
}

export async function sharePathScientistSession(sessionId: string): Promise<'clipboard' | 'share'> {
  const url = getPathScientistSessionShareUrl(sessionId)
  if (typeof navigator !== 'undefined' && navigator.share) {
    try {
      await navigator.share({ url, title: 'PathScientist session' })
      return 'share'
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error
      }
    }
  }
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(url)
    return 'clipboard'
  }
  throw new Error('Sharing is not supported in this browser')
}
>>>>>>> auto-frontend/main
