import type { AutoResearchSessionSummary } from '../types/autoresearch'

export const AUTORESEARCH_SESSION_CREATED_EVENT = 'autoresearch:session-created'

interface AutoResearchSessionCreatedDetail {
  session?: AutoResearchSessionSummary
}

export function notifyAutoResearchSessionCreated(session: AutoResearchSessionSummary) {
  window.dispatchEvent(new CustomEvent<AutoResearchSessionCreatedDetail>(
    AUTORESEARCH_SESSION_CREATED_EVENT,
    { detail: { session } },
  ))
}

export function sessionFromAutoResearchSessionCreatedEvent(event: Event) {
  const detail = (event as CustomEvent<AutoResearchSessionCreatedDetail>).detail
  const session = detail?.session
  if (!session?.session_id) return null
  return session
}
