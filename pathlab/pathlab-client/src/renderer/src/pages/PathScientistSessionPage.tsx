import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import PathScientistClinicalSessionView from '../components/pathscientist/views/PathScientistClinicalSessionView'
import PathScientistDeveloperSessionView from '../components/pathscientist/views/PathScientistDeveloperSessionView'
import { useSessionStream } from '../components/pathscientist/useSessionStream'
import { deletePathScientistSession, getPathScientistSession, resumePathScientistSession, stopPathScientistSession } from '../api/pathscientist'
import type { PathScientistEvent, PathScientistSessionDetail, PathScientistSessionSummary } from '../types/pathscientist'
import { formatPathScientistElapsed } from '../lib/pathscientistTime'
import { isLiveClinicalStatus } from '../lib/pathscientistClinicalSteps'

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

function titleEventValue(event: PathScientistEvent | undefined): string {
  return typeof event?.title === 'string' ? event.title : ''
}

export default function PathScientistSessionPage() {
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
  const stream = useSessionStream(id, isLiveClinicalStatus(session?.status))

  useEffect(() => {
    if (!id) return
    setIsLoading(true)
    setError('')
    getPathScientistSession(id)
      .then((detail) => setSession(detail))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load session'))
      .finally(() => setIsLoading(false))
  }, [id])

  const events = useMemo(() => mergeEvents(session?.events || [], stream.events), [session?.events, stream.events])

  const latestStage = useMemo(() => {
    const reversedEvents = [...events].reverse()
    const lastStageEvent = reversedEvents.find((event) => typeof event.stage === 'string')
    const lastStateStage = reversedEvents.find((event) => typeof event.state?.stage === 'string')?.state?.stage
    const latestStreamStage = stream.latestState?.stage
    const stage = lastStageEvent?.stage || (typeof lastStateStage === 'string' ? lastStateStage : '') || (typeof latestStreamStage === 'string' ? latestStreamStage : '') || session?.stage || 'unknown'
    return displayStatus(stage)
  }, [events, session, stream.latestState])

  const latestStatus = useMemo(() => {
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
  const titlePending = Boolean((latestTitleEvent ? latestTitleEvent.title_pending : session?.title_pending) && !latestTitle)
  const displayTitle = latestTitle || (titlePending ? 'Generating title...' : 'Untitled PathScientist session')
  const canStop = Boolean(id && isLiveClinicalStatus(latestStatus))
  const canResume = Boolean(id && session?.resume_available && !isLiveClinicalStatus(latestStatus))
  const canDelete = Boolean(id && session && !isLiveClinicalStatus(latestStatus))
  const nowMs = useRunningClock(isLiveClinicalStatus(latestStatus))
  const runningElapsed = isLiveClinicalStatus(latestStatus) ? formatPathScientistElapsed(session?.created_at, nowMs) : ''

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
      setError(err instanceof Error ? err.message : 'Failed to stop session')
    } finally {
      setIsStopping(false)
    }
  }

  const handleDelete = async () => {
    if (!id || isDeleting) return
    const confirmed = window.confirm('Delete this PathScientist session and its backend workspace? Generated code, logs, models, and run results for this session will be removed. Shared datasets are not deleted.')
    if (!confirmed) return
    setIsDeleting(true)
    setError('')
    try {
      await deletePathScientistSession(id)
      navigate('/pathscientist/new')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete session')
    } finally {
      setIsDeleting(false)
    }
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
      setError(err instanceof Error ? err.message : 'Failed to resume session')
    } finally {
      setIsResuming(false)
    }
  }

  if (!id) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">Missing session id.</div>
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
    return <PathScientistClinicalSessionView {...sharedProps} />
  }

  return (
    <PathScientistDeveloperSessionView
      {...sharedProps}
      latestStage={latestStage}
    />
  )
}
