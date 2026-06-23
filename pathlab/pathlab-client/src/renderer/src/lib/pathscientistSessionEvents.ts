import type { PathScientistSessionSummary } from '../types/pathscientist'

export const PATHSCIENTIST_SESSION_CREATED_EVENT = 'pathscientist:session-created'

interface PathScientistSessionCreatedDetail {
  session?: PathScientistSessionSummary
}

export function notifyPathScientistSessionCreated(session: PathScientistSessionSummary) {
  window.dispatchEvent(new CustomEvent<PathScientistSessionCreatedDetail>(
    PATHSCIENTIST_SESSION_CREATED_EVENT,
    { detail: { session } },
  ))
}

export function sessionFromPathScientistSessionCreatedEvent(event: Event) {
  const detail = (event as CustomEvent<PathScientistSessionCreatedDetail>).detail
  const session = detail?.session
  if (!session?.session_id) return null
  return session
}
