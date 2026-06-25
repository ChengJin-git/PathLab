import { API_BASE } from '../config'
import { apiFetch, downloadApiFile } from './client'
import type {
  DeleteAutoResearchSessionResponse,
  AutoResearchSessionDetail,
  AutoResearchSessionListResponse,
  AutoResearchSessionSummary,
  AutoResearchSkillListResponse,
  StartAutoResearchSessionRequest,
} from '../types/autoresearch'

const DEFAULT_MODEL = 'gpt-5.5'

interface AutoResearchAccessTokenResponse {
  token: string
  token_type: 'autoresearch_access'
  purpose: 'events' | 'session_download' | 'run_download'
  session_id: string
  run_id: string
  expires_in: number
}

function autoResearchBase(): string {
  return `${API_BASE}/autoresearch`
}

export function listAutoResearchSkills(): Promise<AutoResearchSkillListResponse> {
  return apiFetch(
    `${autoResearchBase()}/skills`,
    undefined,
    'List AutoResearch skills',
    true
  )
}

export function startAutoResearchSession(
  input: StartAutoResearchSessionRequest
): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...input, model: input.model || DEFAULT_MODEL }),
    },
    'Start AutoResearch session'
  )
}

export function listAutoResearchSessions(): Promise<AutoResearchSessionListResponse> {
  return apiFetch(
    `${autoResearchBase()}/sessions`,
    undefined,
    'List AutoResearch sessions'
  )
}

export function getAutoResearchSession(sessionId: string): Promise<AutoResearchSessionDetail> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    'Get AutoResearch session'
  )
}

export function stopAutoResearchSession(sessionId: string): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/stop`,
    { method: 'POST' },
    'Stop AutoResearch session'
  )
}

export function resumeAutoResearchSession(sessionId: string): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/resume`,
    { method: 'POST' },
    'Resume AutoResearch session'
  )
}

export function deleteAutoResearchSession(sessionId: string): Promise<DeleteAutoResearchSessionResponse> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
    'Delete AutoResearch session'
  )
}

function appendAutoResearchAccessToken(url: string, token: string): string {
  const params = new URLSearchParams({ token })
  return `${url}?${params.toString()}`
}

export function mintAutoResearchAccessToken(
  sessionId: string,
  input: { purpose: 'events' | 'session_download' | 'run_download'; runId?: string }
): Promise<AutoResearchAccessTokenResponse> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/access-token`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ purpose: input.purpose, run_id: input.runId || '' }),
    },
    'Mint AutoResearch access token'
  )
}

export async function getAutoResearchEventsUrl(sessionId: string): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, { purpose: 'events' })
  return appendAutoResearchAccessToken(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/events`,
    access.token
  )
}

export async function getAutoResearchRunDownloadUrl(sessionId: string, runId: string): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'run_download',
    runId,
  })
  return appendAutoResearchAccessToken(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
    access.token
  )
}

export async function downloadAutoResearchRun(
  sessionId: string,
  runId: string,
): Promise<{ filename: string }> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'run_download',
    runId,
  })
  return downloadApiFile(
    appendAutoResearchAccessToken(
      `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
      access.token,
    ),
    `autoresearch-${sessionId}-${runId}.zip`,
    undefined,
    'Download AutoResearch run',
    true,
  )
}

export async function getAutoResearchSessionDownloadUrl(sessionId: string): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, { purpose: 'session_download' })
  return appendAutoResearchAccessToken(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
    access.token
  )
}

export function downloadAutoResearchSession(sessionId: string): Promise<{ filename: string }> {
  return downloadApiFile(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
    `autoresearch-${sessionId}.zip`,
    undefined,
    'Download AutoResearch session',
  )
}

export function getAutoResearchSessionShareUrl(sessionId: string): string {
  const path = `/autoresearch/sessions/${encodeURIComponent(sessionId)}`
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}${path}`
  }
  return path
}

export async function shareAutoResearchSession(sessionId: string): Promise<'clipboard' | 'share'> {
  const url = getAutoResearchSessionShareUrl(sessionId)
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
