import { useCallback, useEffect, useRef, useState } from 'react'
import { getAutoResearchEventsUrl } from '../../api/autoresearch'
import type { AutoResearchEvent } from '../../types/autoresearch'
import { mergeResearchEvents } from './researchActivity'

export type SessionStreamStatus = 'idle' | 'open' | 'reconnecting' | 'closed' | 'error'

interface UseSessionStreamResult {
  events: AutoResearchEvent[]
  latestState: Record<string, unknown> | null
  status: SessionStreamStatus
  /** Last error message — set only when status === 'error'. Clean close
   * after the agent finishes is NOT an error and yields status='closed'. */
  errorMessage: string
}

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 15000
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'interrupted', 'paused', 'blocked'])

/**
 * Subscribe to a AutoResearch session SSE stream with deterministic dedup
 * (by ``seq``) and exponential-backoff reconnection.
 *
 * Critically, this hook distinguishes a *clean close* (the backend
 * finished streaming and ended the connection after emitting a terminal
 * ``state`` event) from a *network error*. The previous inline-in-page
 * implementation flagged every clean close as an error because
 * EventSource transitions to CLOSED in both cases.
 */
export function useSessionStream(sessionId: string | undefined, enabled = true, initialSequence = 0): UseSessionStreamResult {
  const [events, setEvents] = useState<AutoResearchEvent[]>([])
  const [latestState, setLatestState] = useState<Record<string, unknown> | null>(null)
  const [status, setStatus] = useState<SessionStreamStatus>('idle')
  const [errorMessage, setErrorMessage] = useState('')

  // Refs so the reconnection loop can read latest seq + see-if-finished
  // without re-subscribing on every event.
  const lastSeqRef = useRef(0)
  const finishedRef = useRef(false)
  const reconnectAttemptsRef = useRef(0)
  const currentSessionRef = useRef<string>()

  const ingest = useCallback((event: AutoResearchEvent) => {
    const seq = typeof event.seq === 'number' ? event.seq : 0
    if (seq > 0 && seq <= lastSeqRef.current) {
      return // duplicate
    }
    if (seq > 0) {
      lastSeqRef.current = seq
    }
    if (event.kind !== 'heartbeat' && event.kind !== 'internal') setEvents((current) => {
      return mergeResearchEvents(current, [event]).slice(-500)
    })

    // Terminal markers — used by the close handler to decide
    // clean-vs-error.
    const status = typeof event.status === 'string' ? event.status : ''
    if (event.kind === 'state' && TERMINAL_STATUSES.has(status)) {
      finishedRef.current = true
    } else if (event.kind === 'state' && status) {
      finishedRef.current = false
    }
    if (event.kind === 'error') {
      finishedRef.current = true
    }

    if (event.state && typeof event.state === 'object') {
      setLatestState(event.state as Record<string, unknown>)
    }
  }, [])

  useEffect(() => {
    if (currentSessionRef.current !== sessionId) {
      currentSessionRef.current = sessionId
      lastSeqRef.current = initialSequence
      setEvents([])
      setLatestState(null)
    }
    if (!sessionId) {
      setStatus('idle')
      return
    }
    if (!enabled) {
      finishedRef.current = false
      reconnectAttemptsRef.current = 0
      setErrorMessage('')
      setStatus('closed')
      return
    }

    // Reset on session change. lastSeqRef is intentionally kept across
    // reconnects within the same session.
    lastSeqRef.current = Math.max(lastSeqRef.current, initialSequence)
    finishedRef.current = false
    reconnectAttemptsRef.current = 0
    setErrorMessage('')

    let cancelled = false
    let source: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = async () => {
      if (cancelled) return
      setStatus(reconnectAttemptsRef.current === 0 ? 'open' : 'reconnecting')
      let streamUrl: string
      try {
        streamUrl = await getAutoResearchEventsUrl(sessionId, lastSeqRef.current)
      } catch (err) {
        if (!cancelled) {
          setStatus('error')
          setErrorMessage(err instanceof Error ? err.message : 'Unable to open stream')
          scheduleReconnect()
        }
        return
      }
      if (cancelled) return
      source = new EventSource(streamUrl)

      const onMessage = (raw: MessageEvent) => {
        if (cancelled) return
        try {
          const parsed = JSON.parse(raw.data) as AutoResearchEvent
          ingest(parsed)
          if (!cancelled) { setStatus('open'); setErrorMessage('') }
          reconnectAttemptsRef.current = 0
        } catch (err) {
          // Malformed payload is not fatal — log + keep streaming.
          console.error('AutoResearch SSE parse error:', err)
        }
      }

      source.onmessage = onMessage

      source.onerror = () => {
        if (cancelled || !source) return
        const readyState = source.readyState
        source.close()
        source = null

        if (finishedRef.current) {
          // Server completed the stream after a terminal state — clean close.
          setStatus('closed')
          return
        }

        if (readyState === EventSource.CLOSED) {
          // Server-side close without a terminal state — treat as error
          // unless the user navigated away.
          scheduleReconnect()
          return
        }

        // Transient error — retry.
        scheduleReconnect()
      }
    }

    const scheduleReconnect = () => {
      if (cancelled) return
      reconnectAttemptsRef.current += 1
      const attempt = reconnectAttemptsRef.current
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_MAX_MS)
      setStatus('reconnecting')
      setErrorMessage(`Stream interrupted; retrying in ${Math.round(delay / 1000)}s (attempt ${attempt})`)
      reconnectTimer = setTimeout(() => {
        void connect()
      }, delay)
    }

    void connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (source) source.close()
    }
  }, [sessionId, enabled, ingest])

  return { events, latestState, status, errorMessage }
}
