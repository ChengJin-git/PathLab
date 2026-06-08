import { API_BASE } from '../config'
import { apiFetch } from './client'
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
