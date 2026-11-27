import type { AutoResearchEvent, AutoResearchSessionSummary } from '../../types/autoresearch'

export function researchStatus(session: AutoResearchSessionSummary | undefined, events: AutoResearchEvent[]): string {
  // A historical state event must never overwrite a newer database snapshot.
  const newer = events.filter(event => event.kind === 'state' && event.status && (
    session?.sequence !== undefined ? (event.seq || 0) > session.sequence : (event.ts || 0) > (session?.updated_at || Infinity)
  )).at(-1)
  return newer?.status || session?.status || 'preparing'
}

export function isPublicResearchMessage(message: { type?: string; metadata?: { pathlabInternal?: boolean } } | undefined): boolean {
  return Boolean(message && message.type === 'assistant' && !message.metadata?.pathlabInternal)
}
