import { Beaker, Circle, FileJson, HardDrive, Layers, Loader2, Play, Radio, Square, Trash2, User } from 'lucide-react'
import { Button } from '../../ui/button'
import AutoResearchExecutionConsole from '../AutoResearchExecutionConsole'
import { useAutoResearchTranslation } from '../../../lib/useAutoResearchTranslation'
import { autoResearchStageLabel, autoResearchStatusLabel } from '../../../lib/autoresearchI18n'
import type { AutoResearchEvent, AutoResearchSessionDetail } from '../../../types/autoresearch'
import type { SessionStreamStatus } from '../useSessionStream'
import { formatFileSize } from '../../../lib/utils/utils'

interface AutoResearchDeveloperSessionViewProps {
  sessionId: string
  session: AutoResearchSessionDetail | null
  events: AutoResearchEvent[]
  streamStatus: SessionStreamStatus
  streamError?: string
  displayTitle: string
  titlePending: boolean
  latestStatus: string
  latestStage: string
  runningElapsed: string
  error: string
  isLoading: boolean
  isStopping: boolean
  isResuming: boolean
  isDeleting: boolean
  canStop: boolean
  canResume: boolean
  canDelete: boolean
  onStop: () => void
  onResume: () => void
  onDelete: () => void
}

function statusClass(status?: string) {
  switch (status) {
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

function formatWorkspaceSize(bytes?: number | null) {
  return typeof bytes === 'number' ? formatFileSize(bytes) : '—'
}

export default function AutoResearchDeveloperSessionView({
  sessionId,
  session,
  events,
  streamStatus,
  streamError,
  displayTitle,
  titlePending,
  latestStatus,
  latestStage,
  runningElapsed,
  error,
  isLoading,
  isStopping,
  isResuming,
  isDeleting,
  canStop,
  canResume,
  canDelete,
  onStop,
  onResume,
  onDelete,
}: AutoResearchDeveloperSessionViewProps) {
  const { t } = useAutoResearchTranslation()
  const consoleSession = session ? { ...session, status: latestStatus, stage: latestStage } : null

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
        <div className="flex flex-wrap items-center gap-2">
          {canDelete && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 border-red-200 bg-white text-red-700 hover:bg-red-50"
              onClick={onDelete}
              disabled={isDeleting}
            >
              {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              {t('autoResearch.sessionPage.deleteSession')}
            </Button>
          )}
          {canResume && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50"
              onClick={onResume}
              disabled={isResuming}
            >
              {isResuming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {t('autoResearch.sessionPage.resumeSession')}
            </Button>
          )}
          {canStop && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 border-red-200 bg-white text-red-700 hover:bg-red-50"
              onClick={onStop}
              disabled={isStopping}
            >
              {isStopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
              {t('autoResearch.sessionPage.stopRun')}
            </Button>
          )}
          <div
            className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ring-1 ${statusClass(latestStatus)}`}
            data-testid="autoresearch-session-status-pill"
          >
            <Circle className="h-2 w-2 fill-current" />
            <span>
              {autoResearchStatusLabel(latestStatus, t)}
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
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-blue-700 ring-1 ring-blue-100">
                <Beaker className="h-3.5 w-3.5" /> {t('autoResearch.sessionPage.sessionDetail')}
              </span>
              {session?.username && (
                <span
                  className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-bold text-gray-700 ring-1 ring-gray-200"
                  data-testid="autoresearch-session-detail-owner-chip"
                  title={session.username}
                >
                  <User className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                  <span className="truncate">{session.username}</span>
                </span>
              )}
            </div>
            <h1 className="flex min-w-0 flex-wrap items-center gap-2 break-words text-2xl font-extrabold tracking-tight text-gray-950 sm:text-3xl">
              {titlePending && <Loader2 className="h-5 w-5 animate-spin text-blue-600" />}
              <span>{displayTitle}</span>
            </h1>
            <p className="mt-2 text-sm text-gray-500">{t('autoResearch.sessionPage.description')}</p>
            {session?.question && (
              <div className="mt-4 rounded-2xl border border-gray-100 bg-gray-50 p-4">
                <p className="text-xs font-bold uppercase tracking-wider text-gray-400">{t('autoResearch.sessionPage.researchQuestion')}</p>
                <p className="mt-2 text-sm leading-6 text-gray-700">{session.question}</p>
              </div>
            )}
          </div>
        </div>

        <div className="relative mt-6 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Layers className="h-3.5 w-3.5" /> {t('autoResearch.labels.stage')}</span>
            <strong className="mt-2 block truncate text-gray-950">{autoResearchStageLabel(latestStage, t)}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Beaker className="h-3.5 w-3.5" /> {t('autoResearch.labels.model')}</span>
            <strong className="mt-2 block text-gray-950">{session?.model || 'gpt-5.5'}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><Radio className="h-3.5 w-3.5" /> {t('autoResearch.labels.events')}</span>
            <strong className="mt-2 block text-gray-950">{events.length}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4" title={session?.workspace_path || undefined}>
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><HardDrive className="h-3.5 w-3.5" /> {t('autoResearch.labels.workspace')}</span>
            <strong className="mt-2 block text-gray-950">{formatWorkspaceSize(session?.workspace_size_bytes)}</strong>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
            <span className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-gray-400"><FileJson className="h-3.5 w-3.5" /> ID</span>
            <strong className="mt-2 block break-all text-gray-950">{sessionId}</strong>
          </div>
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-6 text-sm text-gray-500 shadow-sm">{t('autoResearch.sessionPage.loading')}</div>
      ) : (
        <AutoResearchExecutionConsole
          session={consoleSession}
          events={events}
          streamStatus={streamStatus}
          streamError={streamError}
        />
      )}
    </div>
  )
}
