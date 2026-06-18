import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Beaker, Clock, HardDrive, Loader2, Plus, RefreshCw, Square, Trash2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import PathScientistBackButton from '../components/pathscientist/PathScientistBackButton'
import { deletePathScientistSession, listPathScientistSessions, stopPathScientistSession } from '../api/pathscientist'
import type { PathScientistSessionSummary } from '../types/pathscientist'
import { formatFileSize } from '../lib/utils/utils'
import { formatPathScientistElapsed } from '../lib/pathscientistTime'
import { sessionTrainingProgressLabel } from '../lib/pathscientistSessions'

function formatTime(value: number | undefined, unknownLabel: string) {
  if (!value) return unknownLabel
  return new Date(value * 1000).toLocaleString()
}

function displayStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

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

function isLiveSessionStatus(status?: string) {
  return status === 'queued' || status === 'running'
}

function formatWorkspaceSize(bytes?: number | null) {
  return typeof bytes === 'number' ? formatFileSize(bytes) : '—'
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

function dedupeSessions(sessions: PathScientistSessionSummary[]) {
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

export default function PathScientistSessionsPage() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<PathScientistSessionSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [stoppingIds, setStoppingIds] = useState<Set<string>>(() => new Set())
  const [deletingIds, setDeletingIds] = useState<Set<string>>(() => new Set())

  const loadSessions = async (silent = false) => {
    if (!silent) setIsLoading(true)
    setError('')
    try {
      const result = await listPathScientistSessions()
      setSessions(result.items || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.loadSessionsFailed'))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void loadSessions()
  }, [t])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSessions(true)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const handleStopSession = async (event: React.MouseEvent, sessionId: string) => {
    event.preventDefault()
    event.stopPropagation()
    if (stoppingIds.has(sessionId)) return
    setStoppingIds((current) => new Set(current).add(sessionId))
    setError('')
    try {
      const stopped = await stopPathScientistSession(sessionId)
      setSessions((current) => current.map((session) => (
        session.session_id === sessionId ? { ...session, ...stopped } : session
      )))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.sessionsPage.stopFailed'))
    } finally {
      setStoppingIds((current) => {
        const next = new Set(current)
        next.delete(sessionId)
        return next
      })
    }
  }

  const handleDeleteSession = async (event: React.MouseEvent, sessionId: string) => {
    event.preventDefault()
    event.stopPropagation()
    if (deletingIds.has(sessionId)) return
    const confirmed = window.confirm(t('pathScientist.sessionsPage.deleteConfirm'))
    if (!confirmed) return
    setDeletingIds((current) => new Set(current).add(sessionId))
    setError('')
    try {
      await deletePathScientistSession(sessionId)
      setSessions((current) => current.filter((session) => session.session_id !== sessionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.sessionsPage.deleteFailed'))
    } finally {
      setDeletingIds((current) => {
        const next = new Set(current)
        next.delete(sessionId)
        return next
      })
    }
  }
  const visibleSessions = useMemo(() => dedupeSessions(sessions), [sessions])
  const nowMs = useRunningClock(visibleSessions.some((session) => isLiveSessionStatus(session.status)))

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <PathScientistBackButton />
      <section className="relative overflow-hidden rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="pointer-events-none absolute right-0 top-0 h-56 w-56 translate-x-1/3 -translate-y-1/3 rounded-full bg-blue-100 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 left-10 h-40 w-40 translate-y-1/2 rounded-full bg-cyan-100 blur-3xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-blue-600 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-white shadow-sm shadow-blue-200">
              <Beaker className="h-3.5 w-3.5" /> PathScientist
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-gray-950 sm:text-4xl">{t('pathScientist.sessionsPage.title')}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-gray-500 sm:text-base">
              {t('pathScientist.sessionsPage.description')}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="outline" className="gap-2 border-gray-200 bg-white text-gray-700 hover:bg-gray-50" onClick={() => void loadSessions()}>
              <RefreshCw className="h-4 w-4" /> {t('pathScientist.sessionsPage.refresh')}
            </Button>
            <Button asChild className="gap-2 bg-gray-900 text-white shadow-sm hover:bg-gray-800">
              <Link to="/pathscientist/new"><Plus className="h-4 w-4" /> {t('pathScientist.sessionsPage.newSession')}</Link>
            </Button>
          </div>
        </div>
      </section>

      {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div>}

      {isLoading ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-6 text-sm text-gray-500 shadow-sm">{t('pathScientist.sessionsPage.loading')}</div>
      ) : visibleSessions.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-gray-300 bg-white p-10 text-center shadow-sm">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
            <Beaker className="h-6 w-6" />
          </div>
          <h2 className="mt-4 text-lg font-bold text-gray-950">{t('pathScientist.sessionsPage.emptyTitle')}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-gray-500">{t('pathScientist.sessionsPage.emptyDescription')}</p>
          <Button asChild className="mt-6 bg-blue-600 text-white hover:bg-blue-700">
            <Link to="/pathscientist/new">{t('pathScientist.sessionsPage.startOne')}</Link>
          </Button>
        </div>
      ) : (
        <div className="grid gap-3">
          {visibleSessions.map((session) => {
            const titlePending = Boolean(session.title_pending && !session.title)
            const title = titlePending ? t('pathScientist.generatingTitle') : session.title || t('pathScientist.sessionsPage.untitledSession')
            const showQuestionPreview = Boolean(session.question && (titlePending || !session.title || session.title !== session.question))
            const sessionStatus = displayStatus(session.status)
            const sessionStage = displayStatus(session.stage)
            const showStage = sessionStage && sessionStage !== 'unknown' && sessionStage !== sessionStatus
            const canStop = isLiveSessionStatus(session.status)
            const canDelete = !canStop
            const isStopping = stoppingIds.has(session.session_id)
            const isDeleting = deletingIds.has(session.session_id)
            const runningElapsed = canStop ? formatPathScientistElapsed(session.created_at, nowMs) : ''
            const trainingProgressLabel = sessionTrainingProgressLabel(session)
            return (
              <Link
                key={session.session_id}
                to={`/pathscientist/sessions/${session.session_id}`}
                className="group rounded-2xl border border-gray-200 bg-white p-4 shadow-sm transition-all duration-200 hover:border-blue-200 hover:shadow-lg hover:shadow-blue-500/5"
                data-testid={`pathscientist-session-card-${session.session_id}`}
              >
                <div className="flex items-start justify-between gap-4" data-testid={`pathscientist-session-main-row-${session.session_id}`}>
                  <div className="min-w-0 flex-1">
                    <h2 className="flex min-w-0 items-center gap-2 truncate text-base font-bold text-gray-950 group-hover:text-blue-700">
                      {titlePending && <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin text-blue-600" />}
                      <span className="truncate">{title}</span>
                    </h2>
                    {showQuestionPreview && <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{session.question}</p>}
                    {session.error && <p className="mt-2 text-xs font-medium text-red-600">{session.error}</p>}
                  </div>
                  <ArrowRight className="mt-2 h-5 w-5 flex-shrink-0 text-gray-300 transition group-hover:translate-x-1 group-hover:text-blue-600" />
                </div>
                <div
                  className="mt-2 flex flex-wrap items-end justify-between gap-3"
                  data-testid={`pathscientist-session-footer-${session.session_id}`}
                >
                  <p className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-gray-500">
                    <span>{session.session_id}</span>
                    <span className="h-1 w-1 rounded-full bg-gray-300" />
                    <span>{session.model || 'gpt-5.5'}</span>
                    <span className="h-1 w-1 rounded-full bg-gray-300" />
                    <span className="inline-flex items-center gap-1" title={session.workspace_path || undefined}>
                      <HardDrive className="h-3 w-3" />
                      <span>{t('pathScientist.sessionsPage.workspace')}</span>
                      <span className="font-semibold text-gray-700">{formatWorkspaceSize(session.workspace_size_bytes)}</span>
                    </span>
                    <span className="h-1 w-1 rounded-full bg-gray-300" />
                    <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {formatTime(session.created_at, t('pathScientist.sessionsPage.unknownTime'))}</span>
                  </p>
                  <div
                    className="ml-auto flex flex-wrap justify-end gap-2"
                    data-testid={`pathscientist-session-badges-${session.session_id}`}
                  >
                    {canStop && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1.5 border-red-200 bg-white px-2.5 text-xs font-bold text-red-700 hover:bg-red-50"
                        onClick={(event) => void handleStopSession(event, session.session_id)}
                        disabled={isStopping}
                      >
                        {isStopping ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />}
                        {t('pathScientist.sessionsPage.stopRun')}
                      </Button>
                    )}
                    {canDelete && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-label={t('pathScientist.sessionsPage.deleteSession')}
                        className="h-7 gap-1.5 border-red-200 bg-white px-2.5 text-xs font-bold text-red-700 hover:bg-red-50"
                        onClick={(event) => void handleDeleteSession(event, session.session_id)}
                        disabled={isDeleting}
                      >
                        {isDeleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                        {t('pathScientist.sessionsPage.delete')}
                      </Button>
                    )}
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ring-1 ${statusClass(session.status)}`}>
                      {sessionStatus}
                      {runningElapsed && <span className="ml-1 font-semibold opacity-80">· {runningElapsed}</span>}
                    </span>
                    {trainingProgressLabel && (
                      <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-bold text-sky-700 ring-1 ring-sky-100">
                        {trainingProgressLabel}
                      </span>
                    )}
                    {showStage && <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-500">{sessionStage}</span>}
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
