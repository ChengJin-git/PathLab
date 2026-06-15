import { useEffect, useMemo, useState } from 'react'
<<<<<<< HEAD
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Beaker, Circle, FileJson, HardDrive, Layers, Loader2, Radio, Square, Trash2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import PathScientistExecutionConsole from '../components/pathscientist/PathScientistExecutionConsole'
import { useSessionStream } from '../components/pathscientist/useSessionStream'
import { deletePathScientistSession, getPathScientistSession, stopPathScientistSession } from '../api/pathscientist'
import type { PathScientistEvent, PathScientistSessionDetail, PathScientistSessionSummary } from '../types/pathscientist'
import { formatFileSize } from '../lib/utils/utils'
import { formatPathScientistElapsed } from '../lib/pathscientistTime'
=======
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import PathScientistClinicalSessionView from '../components/pathscientist/views/PathScientistClinicalSessionView'
import PathScientistDeveloperSessionView from '../components/pathscientist/views/PathScientistDeveloperSessionView'
import { useSessionStream } from '../components/pathscientist/useSessionStream'
import { deletePathScientistSession, getPathScientistSession, stopPathScientistSession } from '../api/pathscientist'
import type { PathScientistEvent, PathScientistSessionDetail, PathScientistSessionSummary } from '../types/pathscientist'
import { formatPathScientistElapsed } from '../lib/pathscientistTime'
import { isLiveClinicalStatus } from '../lib/pathscientistClinicalSteps'
>>>>>>> auto-frontend/main

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

<<<<<<< HEAD
function statusClass(status?: string) {
  switch (displayStatus(status)) {
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

=======
>>>>>>> auto-frontend/main
function displayStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

<<<<<<< HEAD
function isLiveSessionStatus(status?: string) {
  return status === 'queued' || status === 'running'
}

function formatWorkspaceSize(bytes?: number | null) {
  return typeof bytes === 'number' ? formatFileSize(bytes) : '—'
}

=======
>>>>>>> auto-frontend/main
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
<<<<<<< HEAD
=======
  const { isAdmin, isPathologist } = useAuth()
  const useClinicalView = isPathologist && !isAdmin
>>>>>>> auto-frontend/main
  const [session, setSession] = useState<PathScientistSessionDetail | null>(null)
  const [error, setError] = useState('')
  const [isStopping, setIsStopping] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
<<<<<<< HEAD
  const stream = useSessionStream(id, isLiveSessionStatus(session?.status))
=======
  const stream = useSessionStream(id, isLiveClinicalStatus(session?.status))
>>>>>>> auto-frontend/main

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
<<<<<<< HEAD
  const canStop = Boolean(id && isLiveSessionStatus(latestStatus))
  const canDelete = Boolean(id && session && !isLiveSessionStatus(latestStatus))
  const nowMs = useRunningClock(isLiveSessionStatus(latestStatus))
  const runningElapsed = isLiveSessionStatus(latestStatus) ? formatPathScientistElapsed(session?.created_at, nowMs) : ''
  const consoleSession = session ? { ...session, status: latestStatus, stage: latestStage } : null
=======
  const canStop = Boolean(id && isLiveClinicalStatus(latestStatus))
  const canDelete = Boolean(id && session && !isLiveClinicalStatus(latestStatus))
  const nowMs = useRunningClock(isLiveClinicalStatus(latestStatus))
  const runningElapsed = isLiveClinicalStatus(latestStatus) ? formatPathScientistElapsed(session?.created_at, nowMs) : ''
>>>>>>> auto-frontend/main

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
<<<<<<< HEAD
      navigate('/pathscientist')
=======
      navigate('/pathscientist/new')
>>>>>>> auto-frontend/main
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete session')
    } finally {
      setIsDeleting(false)
    }
  }

  if (!id) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">Missing session id.</div>
  }

<<<<<<< HEAD
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button asChild variant="ghost" className="w-fit gap-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900">
          <Link to="/pathscientist"><ArrowLeft className="h-4 w-4" /> Sessions</Link>
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          {canDelete && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 border-red-200 bg-white text-red-700 hover:bg-red-50"
              onClick={() => void handleDelete()}
              disabled={isDeleting}
            >
              {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              Delete session
            </Button>
          )}
          {canStop && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 border-red-200 bg-white text-red-700 hover:bg-red-50"
              onClick={() => void handleStop()}
              disabled={isStopping}
            >
              {isStopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
              Stop run
            </Button>
          )}
          <div
            className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ring-1 ${statusClass(latestStatus)}`}
            data-testid="pathscientist-session-status-pill"
          >
            <Circle className="h-2 w-2 fill-current" />
            <span>
              {latestStatus}
              {runningElapsed && <span className="ml-1 font-semibold opacity-80">· {runningElapsed}</span>}
            </span>
          </div>
        </div>
      </div>

      {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div>}

      <section className="relative overflow-hidden rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="pointer-events-none absolute right-0 top-0 h-48 w-48 translate-x-1/3 -translate-y-1/3 rounded-full bg-blue-100 blur-3xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-blue-700 ring-1 ring-blue-100">
              <Beaker className="h-3.5 w-3.5" /> Session detail
            </div>
            <h1 className="flex min-w-0 flex-wrap items-center gap-2 break-words text-2xl font-extrabold tracking-tight text-gray-950 sm:text-3xl">
              {titlePending && <Loader2 className="h-5 w-5 animate-spin text-blue-600" />}
              <span>{displayTitle}</span>
            </h1>
            <p className="mt-2 text-sm text-gray-500">Structured PathScientist execution console for this run.</p>
            {session?.question && (
              <div className="mt-4 rounded-2xl border border-gray-100 bg-gray-50 p-4">
                <p className="text-xs font-bold uppercase tracking-wider text-gray-400">Research question</p>
                <p className="mt-2 text-sm leading-6 text-gray-700">{session.question}</p>
              </div>
            )}
          </div>
        </div>

        <div className="relative mt-6 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Layers className="h-3.5 w-3.5" /> Stage</span>
            <strong className="mt-2 block truncate text-gray-950">{latestStage}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Beaker className="h-3.5 w-3.5" /> Model</span>
            <strong className="mt-2 block text-gray-950">{session?.model || 'gpt-5.5'}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Radio className="h-3.5 w-3.5" /> Events</span>
            <strong className="mt-2 block text-gray-950">{events.length}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4" title={session?.workspace_path || undefined}>
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><HardDrive className="h-3.5 w-3.5" /> Workspace</span>
            <strong className="mt-2 block text-gray-950">{formatWorkspaceSize(session?.workspace_size_bytes)}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><FileJson className="h-3.5 w-3.5" /> ID</span>
            <strong className="mt-2 block break-all text-gray-950">{id}</strong>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-6 text-sm text-gray-500 shadow-sm">Loading session...</div>
      ) : (
        <PathScientistExecutionConsole
          session={consoleSession}
          events={events}
          streamStatus={stream.status}
          streamError={stream.errorMessage}
        />
      )}
    </div>
=======
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
    isDeleting,
    canStop,
    canDelete,
    onStop: () => void handleStop(),
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
>>>>>>> auto-frontend/main
  )
}
