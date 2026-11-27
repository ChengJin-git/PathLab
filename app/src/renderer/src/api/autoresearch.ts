import { API_BASE } from '../config'
import { apiFetch, apiFetchBlob, downloadApiFile } from './client'
import type { SupportedLanguage } from '../i18n'
import type {
  DeleteAutoResearchSessionResponse,
  AutoResearchSessionDetail,
  AutoResearchSessionListResponse,
  AutoResearchSessionSummary,
  StartAutoResearchSessionRequest,
  ContinueResearchRequest
} from '../types/autoresearch'
import type { ResearchBudget, ResearchEffort, ResearchSkillImport } from '../types/autoresearch'

interface AutoResearchAccessTokenResponse {
  token: string
  token_type: 'autoresearch_access'
  purpose: 'events' | 'session_download' | 'run_download'
  session_id: string
  run_id: string
  expires_in: number
}

function autoResearchBase(): string {
  return `${API_BASE}/research`
}

export function polishResearchGoal(input: {
  question: string
  language: SupportedLanguage
  source_conversation_id?: string
}, signal?: AbortSignal): Promise<{ question: string }> {
  return apiFetch(`${autoResearchBase()}/polish-goal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal
  })
}

export function startAutoResearchSession(
  input: StartAutoResearchSessionRequest
): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input)
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

export function getAutoResearchSession(
  sessionId: string,
  compact = false,
  signal?: AbortSignal
): Promise<AutoResearchSessionDetail> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}${compact ? '?compact=true' : ''}`,
    { signal },
    'Get AutoResearch session'
  )
}

export function getResearchRunMetrics(
  sessionId: string,
  runId: string
): Promise<{ run_id: string; metrics: Record<string, number> }> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/metrics`,
    undefined,
    'Get run metrics'
  )
}

export function stopAutoResearchSession(
  sessionId: string
): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/stop`,
    { method: 'POST' },
    'Stop AutoResearch session'
  )
}

export function resumeAutoResearchSession(
  sessionId: string
): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/resume`,
    { method: 'POST' },
    'Resume AutoResearch session'
  )
}

export function deleteAutoResearchSession(
  sessionId: string
): Promise<DeleteAutoResearchSessionResponse> {
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
  input: {
    purpose: 'events' | 'session_download' | 'run_download'
    runId?: string
  }
): Promise<AutoResearchAccessTokenResponse> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/access-token`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        purpose: input.purpose,
        run_id: input.runId || ''
      })
    },
    'Mint AutoResearch access token'
  )
}

export async function getAutoResearchEventsUrl(
  sessionId: string,
  after = 0
): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'events'
  })
  return (
    appendAutoResearchAccessToken(
      `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/events`,
      access.token
    ) + `&after=${after}`
  )
}

export function getResearchConfiguration(): Promise<{
  model: { model?: string; provider?: string }
  error: string
  can_execute: boolean
  effort_presets: Record<'standard' | 'scientific', Record<ResearchEffort, ResearchBudget>>
}> {
  return apiFetch(
    `${autoResearchBase()}/configuration`,
    undefined,
    'Research configuration'
  )
}

export function importResearchSkill(url: string, signal?: AbortSignal): Promise<ResearchSkillImport> {
  return apiFetch(`${autoResearchBase()}/skills/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }), signal
  })
}

export function uploadResearchSkills(files: File[], signal?: AbortSignal): Promise<ResearchSkillImport> {
  const data = new FormData()
  for (const file of files) data.append('files', file, file.webkitRelativePath || file.name)
  return apiFetch(`${autoResearchBase()}/skills/upload`, { method: 'POST', body: data, signal })
}

export function getResearchDatasets(
  query = '',
  workspaceId?: string
): Promise<{ items: import('../types/autoresearch').ResearchDataset[] }> {
  return apiFetch(
    `${autoResearchBase()}/datasets?query=${encodeURIComponent(query)}${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''}`,
    undefined,
    'Research datasets'
  )
}

export function sendResearchMessage(
  id: string,
  text: string,
  references?: import('./workbench').ResourceReference[]
): Promise<{ command_id: string }> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, ...(references ? { references } : {}) })
    },
    'Send research instruction'
  )
}

export function pauseResearch(id: string): Promise<AutoResearchSessionSummary> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/pause`,
    { method: 'POST' },
    'Pause research'
  )
}

export function answerResearchQuestion(
  id: string,
  formId: string,
  answer: Record<string, unknown>
): Promise<{ command_id: string }> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/answers`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ form_id: formId, answer })
    },
    'Answer research question'
  )
}

export function readResearchFile(
  id: string,
  path: string
): Promise<{ path: string; content: string; revision: string }> {
  return apiFetch(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/files?path=${encodeURIComponent(path)}`,
    undefined,
    'Read research artifact'
  )
}

export function continueResearch(id: string, input: ContinueResearchRequest): Promise<{ command_id: string; status: string }> {
  return apiFetch(`${autoResearchBase()}/sessions/${encodeURIComponent(id)}/continue`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  }, 'Continue task')
}

export function getResearchHandoff(conversationId: string): Promise<{ context: string; message_count: number; included_messages: number; workspace_id?: string }> {
  return apiFetch(`${autoResearchBase()}/handoff/${encodeURIComponent(conversationId)}`, undefined, 'Read Chat context')
}

export function listResearchSourceFiles(id: string): Promise<{ items: string[]; editable: boolean }> {
  return apiFetch(`${autoResearchBase()}/sessions/${encodeURIComponent(id)}/source-files`, undefined, 'List workspace sources')
}

export function saveResearchSource(id: string, path: string, content: string, revision: string): Promise<{ saved: boolean; revision: string }> {
  return apiFetch(`${autoResearchBase()}/sessions/${encodeURIComponent(id)}/source-files`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path, content, revision })
  }, 'Save workspace source')
}

export function downloadResearchFile(id: string, path: string) {
  return downloadApiFile(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/files?path=${encodeURIComponent(path)}&download=true`,
    path.split('/').pop() || 'artifact',
    undefined,
    'Download artifact'
  )
}

export function readResearchImage(id: string, path: string, signal?: AbortSignal): Promise<Blob> {
  return apiFetchBlob(
    `${autoResearchBase()}/sessions/${encodeURIComponent(id)}/files?path=${encodeURIComponent(path)}`,
    { signal },
    'Preview research image'
  )
}

export async function getAutoResearchRunDownloadUrl(
  sessionId: string,
  runId: string
): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'run_download',
    runId
  })
  return appendAutoResearchAccessToken(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
    access.token
  )
}

export async function downloadAutoResearchRun(
  sessionId: string,
  runId: string
): Promise<{ filename: string }> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'run_download',
    runId
  })
  return downloadApiFile(
    appendAutoResearchAccessToken(
      `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/download`,
      access.token
    ),
    `autoresearch-${sessionId}-${runId}.zip`,
    undefined,
    'Download AutoResearch run',
    true
  )
}

export async function getAutoResearchSessionDownloadUrl(
  sessionId: string
): Promise<string> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'session_download'
  })
  return appendAutoResearchAccessToken(
    `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
    access.token
  )
}

export async function downloadAutoResearchSession(
  sessionId: string
): Promise<{ filename: string }> {
  const access = await mintAutoResearchAccessToken(sessionId, {
    purpose: 'session_download'
  })
  return downloadApiFile(
    appendAutoResearchAccessToken(
      `${autoResearchBase()}/sessions/${encodeURIComponent(sessionId)}/download`,
      access.token
    ),
    `autoresearch-${sessionId}.zip`,
    undefined,
    'Download AutoResearch session',
    true
  )
}

export function getAutoResearchSessionShareUrl(sessionId: string): string {
  const path = `/autoresearch/sessions/${encodeURIComponent(sessionId)}`
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}${path}`
  }
  return path
}

export async function shareAutoResearchSession(
  sessionId: string
): Promise<'clipboard' | 'share'> {
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
