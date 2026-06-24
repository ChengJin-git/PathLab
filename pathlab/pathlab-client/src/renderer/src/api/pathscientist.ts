import { API_BASE } from '../config'
import { apiFetch, downloadApiFile } from './client'
import type {
  DeletePathScientistSessionResponse,
  PathScientistSessionDetail,
  PathScientistSessionListResponse,
  PathScientistSessionSummary,
  PathScientistSkillListResponse,
  StartPathScientistSessionRequest,
} from '../types/pathscientist'

const DEFAULT_MODEL = 'gpt-5.5'

interface PathScientistAccessTokenResponse {
  token: string
  token_type: 'pathscientist_access'
  purpose: 'events' | 'session_download' | 'run_download'
  session_id: string
  run_id: string
  expires_in: number
}

function pathScientistBase(): string {
  return `${API_BASE}/pathscientist`
}

export function listPathScientistSkills(): Promise<PathScientistSkillListResponse> {
  return apiFetch(
    `${pathScientistBase()}/skills`,
    undefined,
    'List AutoResearch skills',
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
    'Start AutoResearch session'
  )
}

export function listPathScientistSessions(): Promise<PathScientistSessionListResponse> {
  return apiFetch(
    `${pathScientistBase()}/sessions`,
    undefined,
    'List AutoResearch sessions'
  )
}

export function getPathScientistSession(sessionId: string): Promise<PathScientistSessionDetail> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    'Get AutoResearch session'
  )
}

export function stopPathScientistSession(sessionId: string): Promise<PathScientistSessionSummary> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/stop`,
    { method: 'POST' },
    'Stop AutoResearch session'
  )
}

export function resumePathScientistSession(sessionId: string): Promise<PathScientistSessionSummary> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/resume`,
    { method: 'POST' },
    'Resume AutoResearch session'
  )
}

export function deletePathScientistSession(sessionId: string): Promise<DeletePathScientistSessionResponse> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
    'Delete AutoResearch session'
  )
}

function appendPathScientistAccessToken(url: string, token: string): string {
  const params = new URLSearchParams({ token })
  return `${url}?${params.toString()}`
}

export function mintPathScientistAccessToken(
  sessionId: string,
  input: { purpose: 'events' | 'session_download' | 'run_download'; runId?: string }
): Promise<PathScientistAccessTokenResponse> {
  return apiFetch(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/access-token`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ purpose: input.purpose, run_id: input.runId || '' }),
    },
    'Mint AutoResearch access token'
  )
}

export async function getPathScientistEventsUrl(sessionId: string): Promise<string> {
  const access = await mintPathScientistAccessToken(sessionId, { purpose: 'events' })
  return appendPathScientistAccessToken(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/events`,
    access.token
  )
}

export async function getPathScientistRunDownloadUrl(sessionId: string, runId: string): Promise<string> {
  const access = await mintPathScientistAccessToken(sessionId, {
    purpose: 'run_download',
    runId,
  })
  return appendPathScientistAccessToken(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
    access.token
  )
}

export async function downloadPathScientistRun(
  sessionId: string,
  runId: string,
): Promise<{ filename: string }> {
  const access = await mintPathScientistAccessToken(sessionId, {
    purpose: 'run_download',
    runId,
  })
  return downloadApiFile(
    appendPathScientistAccessToken(
      `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
      access.token,
    ),
    `autoresearch-${sessionId}-${runId}.zip`,
    undefined,
    'Download AutoResearch run',
    true,
  )
}

export async function getPathScientistSessionDownloadUrl(sessionId: string): Promise<string> {
  const access = await mintPathScientistAccessToken(sessionId, { purpose: 'session_download' })
  return appendPathScientistAccessToken(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
    access.token
  )
}

export function downloadPathScientistSession(sessionId: string): Promise<{ filename: string }> {
  return downloadApiFile(
    `${pathScientistBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
    `autoresearch-${sessionId}.zip`,
    undefined,
    'Download AutoResearch session',
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
      await navigator.share({ url, title: 'AutoResearch session' })
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
