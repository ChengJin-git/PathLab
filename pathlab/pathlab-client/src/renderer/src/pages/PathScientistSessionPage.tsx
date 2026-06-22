import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import PathScientistClinicalSessionView from '../components/pathscientist/views/PathScientistClinicalSessionView'
import PathScientistDeveloperSessionView from '../components/pathscientist/views/PathScientistDeveloperSessionView'
import { useSessionStream } from '../components/pathscientist/useSessionStream'
import { deletePathScientistSession, getPathScientistSession, resumePathScientistSession, stopPathScientistSession } from '../api/pathscientist'
import type { PathScientistEvent, PathScientistSessionDetail, PathScientistSessionSummary } from '../types/pathscientist'
import { formatPathScientistElapsed } from '../lib/pathscientistTime'
import { isLiveClinicalStatus } from '../lib/pathscientistClinicalSteps'
import { derivePathScientistDisplayStatus } from '../lib/pathscientistEventSelectors'
import { ConfirmDialog } from '../components/settings/ConfirmDialog'

const LIVE_SESSION_DETAIL_REFRESH_MS = 5000

function eventKey(event: PathScientistEvent) {
  if (typeof event.seq === 'number') return `seq:${event.seq}`
  if (event.ts) return `ts:${event.ts}:${event.kind}:${event.tool || ''}:${event.iteration ?? ''}`
  return ''
}

function mergeEvents(initialEvents: PathScientistEvent[] = [], liveEvents: PathScientistEvent[] = []) {
  const seen = new Set<string>()
  const merged: PathScientistEvent[] = []
  for (const event of [...initialEvents, ...liveEvents]) {
    const key = eventKey(event)
    if (key) {
      if (seen.has(key)) continue
      seen.add(key)
    }
    merged.push(event)
  }
  return merged
}

function displayStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

function useRunningClock(enabled: boolean) {
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return undefined
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [enabled])
  return nowMs
}

function terminalDisplayStatus(status?: string) {
  const normalized = displayStatus(status)
  return ['completed', 'failed', 'interrupted'].includes(normalized) ? normalized : ''
}

function latestMergedState(session: PathScientistSessionDetail | null, events: PathScientistEvent[]) {
  const stateEvent = [...events].reverse().find((event) => event.state)
  return {
    ...(session?.state && typeof session.state === 'object' ? session.state : {}),
    ...(stateEvent?.state && typeof stateEvent.state === 'object' ? stateEvent.state : {}),
  }
}

function titleEventValue(event: PathScientistEvent | undefined): string {
  return typeof event?.title === 'string' ? event.title : ''
}

export default function PathScientistSessionPage() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isAdmin, isPathologist } = useAuth()
  const useClinicalView = isPathologist && !isAdmin
  const [session, setSession] = useState<PathScientistSessionDetail | null>(null)
  const [error, setError] = useState('')
  const [isStopping, setIsStopping] = useState(false)
  const [isResuming, setIsResuming] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [dialogState, setDialogState] = useState({ isOpen: false, title: '', message: '', onConfirm: () => {} })

  const showConfirmDialog = (config: { title: string; message: string; onConfirm: () => void }) => {
    setDialogState({ isOpen: true, ...config })
  }

  const closeConfirmDialog = () => {
    setDialogState({ isOpen: false, title: '', message: '', onConfirm: () => {} })
  }

  const stream = useSessionStream(id, isLiveClinicalStatus(session?.status))
  const streamEventsRef = useRef<PathScientistEvent[]>([])

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setIsLoading(true)
    setError('')
    setSession(null)
    getPathScientistSession(id)
      .then((detail) => {
        if (!cancelled) setSession(detail)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : t('pathScientist.sessionPage.loadFailed'))
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const events = useMemo(() => mergeEvents(session?.events || [], stream.events), [session?.events, stream.events])

  useEffect(() => {
    streamEventsRef.current = stream.events
  }, [stream.events])

  const latestStage = useMemo(() => {
    const reversedEvents = [...events].reverse()
    const lastStageEvent = reversedEvents.find((event) => typeof event.stage === 'string')
    const lastStateStage = reversedEvents.find((event) => typeof event.state?.stage === 'string')?.state?.stage
    const latestStreamStage = stream.latestState?.stage
    const stage = lastStageEvent?.stage || (typeof lastStateStage === 'string' ? lastStateStage : '') || (typeof latestStreamStage === 'string' ? latestStreamStage : '') || session?.stage || 'unknown'
    return displayStatus(stage)
  }, [events, session, stream.latestState])

  const latestStatus = useMemo(() => {
    const derivedStatus = terminalDisplayStatus(
      derivePathScientistDisplayStatus(session, latestMergedState(session, events)),
    )
    if (derivedStatus) return derivedStatus

    const sessionTerminalStatus = terminalDisplayStatus(session?.status)
    if (sessionTerminalStatus) return sessionTerminalStatus

    const reversedEvents = [...events].reverse()
    for (const event of reversedEvents) {
      const eventTerminalStatus = terminalDisplayStatus(event.status)
      if (eventTerminalStatus) return eventTerminalStatus
      const stateStage = typeof event.state?.stage === 'string' ? event.state.stage : ''
      const stageTerminalStatus = terminalDisplayStatus(event.stage || stateStage)
      if (stageTerminalStatus) return stageTerminalStatus
    }

    const lastStatusEvent = reversedEvents.find((event) => typeof event.status === 'string')
    return displayStatus(lastStatusEvent?.status || session?.status || 'loading')
  }, [events, session])

  const latestTitleEvent = useMemo(() => [...events].reverse().find((event) => event.kind === 'session_title'), [events])
  const latestTitle = titleEventValue(latestTitleEvent) || session?.title || ''
  const titlePending = Boolean(
    (latestTitleEvent ? latestTitleEvent.title_pending : session?.title_pending)
    && !latestTitle
    && isLiveClinicalStatus(latestStatus),
  )
  const displayTitle = latestTitle || (titlePending ? t('pathScientist.generatingTitle') : t('pathScientist.sessionsPage.untitledSession'))
  const canStop = Boolean(id && isLiveClinicalStatus(latestStatus))
  const canResume = Boolean(id && session?.resume_available && !isLiveClinicalStatus(latestStatus))
  const canDelete = Boolean(id && session && !isLiveClinicalStatus(latestStatus))
  const nowMs = useRunningClock(isLiveClinicalStatus(latestStatus))
  const runningElapsed = isLiveClinicalStatus(latestStatus) ? formatPathScientistElapsed(session?.created_at, nowMs) : ''

  useEffect(() => {
    if (!id || !isLiveClinicalStatus(latestStatus)) return undefined
    let cancelled = false
    const refreshSession = async () => {
      try {
        const detail = await getPathScientistSession(id)
        if (cancelled) return
        setSession((current) => {
          if (!current || current.session_id !== detail.session_id) return detail
          return {
            ...current,
            ...detail,
            events: mergeEvents(detail.events || [], streamEventsRef.current),
          }
        })
      } catch {
        // Keep the live stream UI stable; the primary loader/error path handles
        // the initial detail request and SSE handles transient runtime updates.
      }
    }
    const timer = window.setInterval(() => {
      void refreshSession()
    }, LIVE_SESSION_DETAIL_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [id, latestStatus])

  const handleStop = async () => {
    if (!id || isStopping) return
    setIsStopping(true)
    setError('')
    try {
      const stopped: PathScientistSessionSummary = await stopPathScientistSession(id)
      const stopEvent: PathScientistEvent = {
        kind: 'state',
        status: stopped.status,
        stage: stopped.stage || stopped.status,
        state: { stage: stopped.stage || stopped.status, stop_reason: 'user_cancelled' },
        summary: 'Stopped by user from PathLab.',
      }
      setSession((current) => current
        ? { ...current, ...stopped, events: [...(current.events || []), stopEvent] }
        : { ...stopped, events: [stopEvent] })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.sessionPage.stopFailed'))
    } finally {
      setIsStopping(false)
    }
  }

  const handleDelete = async () => {
    if (!id || isDeleting) return
    showConfirmDialog({
      title: t('pathScientist.sessionsPage.deleteConfirmTitle'),
      message: t('pathScientist.sessionsPage.deleteConfirm'),
      onConfirm: async () => {
        closeConfirmDialog()
        setIsDeleting(true)
        setError('')
        try {
          await deletePathScientistSession(id)
          navigate('/pathscientist/new')
        } catch (err) {
          setError(err instanceof Error ? err.message : t('pathScientist.sessionPage.deleteFailed'))
        } finally {
          setIsDeleting(false)
        }
      },
    })
  }

  const handleResume = async () => {
    if (!id || isResuming) return
    setIsResuming(true)
    setError('')
    try {
      const resumed: PathScientistSessionSummary = await resumePathScientistSession(id)
      const resumeEvent: PathScientistEvent = {
        kind: 'session',
        status: resumed.status,
        stage: resumed.stage || 'resuming',
        summary: 'Resuming persisted PathScientist conversation.',
      }
      setSession((current) => current
        ? { ...current, ...resumed, events: [...(current.events || []), resumeEvent] }
        : { ...resumed, events: [resumeEvent] })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.sessionPage.resumeFailed'))
    } finally {
      setIsResuming(false)
    }
  }

  if (!id) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{t('pathScientist.sessionPage.missingSessionId')}</div>
  }

  const sharedProps = {
    sessionId: id,
    session,
    events,
    streamStatus: stream.status,
    streamError: stream.errorMessage,
    displayTitle,
    titlePending,
    latestStatus,
    runningElapsed,
    error,
    isLoading,
    isStopping,
    isResuming,
    isDeleting,
    canStop,
    canResume,
    canDelete,
    onStop: () => void handleStop(),
    onResume: () => void handleResume(),
    onDelete: () => void handleDelete(),
  }

  if (useClinicalView) {
    return (
      <>
        <PathScientistClinicalSessionView {...sharedProps} />
        <ConfirmDialog dialog={dialogState} onClose={closeConfirmDialog} />
      </>
    )
  }

  return (
    <>
      <PathScientistDeveloperSessionView
        {...sharedProps}
        latestStage={latestStage}
      />
      <ConfirmDialog dialog={dialogState} onClose={closeConfirmDialog} />
    </>
  )
}
