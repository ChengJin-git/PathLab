import type { PathScientistSessionSummary } from '../types/pathscientist'

export function displaySessionStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

export function isLiveSessionStatus(status?: string) {
  return status === 'queued' || status === 'running'
}

function sessionDedupeKey(session: PathScientistSessionSummary) {
  if (session.workspace_path) return `workspace:${session.workspace_path}`
  if (session.conversation_id) return `conversation:${session.conversation_id}`
  return `session:${session.session_id}`
}

function sessionRank(session: PathScientistSessionSummary) {
  return [
    isLiveSessionStatus(session.status) ? 1 : 0,
    session.model ? 1 : 0,
    session.conversation_id ? 1 : 0,
    session.updated_at || 0,
    session.created_at || 0,
  ]
}

function isBetterSessionCandidate(
  candidate: PathScientistSessionSummary,
  current: PathScientistSessionSummary,
) {
  const nextRank = sessionRank(candidate)
  const currentRank = sessionRank(current)
  for (let index = 0; index < nextRank.length; index += 1) {
    if (nextRank[index] !== currentRank[index]) {
      return nextRank[index] > currentRank[index]
    }
  }
  return false
}

export function dedupePathScientistSessions(sessions: PathScientistSessionSummary[]) {
  const selectedByKey = new Map<string, PathScientistSessionSummary>()
  const keyOrder: string[] = []
  for (const session of sessions) {
    const key = sessionDedupeKey(session)
    const current = selectedByKey.get(key)
    if (!current) {
      selectedByKey.set(key, session)
      keyOrder.push(key)
    } else if (isBetterSessionCandidate(session, current)) {
      selectedByKey.set(key, session)
    }
  }
  return keyOrder
    .map((key) => selectedByKey.get(key))
    .filter((session): session is PathScientistSessionSummary => Boolean(session))
}

export function sessionStatusClass(status?: string) {
  switch (displaySessionStatus(status)) {
    case 'completed':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    case 'failed':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'running':
      return 'bg-blue-50 text-blue-700 ring-blue-200'
    case 'queued':
      return 'bg-amber-50 text-amber-700 ring-amber-200'
    default:
      return 'bg-gray-100 text-gray-600 ring-gray-200'
  }
}
