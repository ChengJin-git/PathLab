import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAutoResearchTranslation } from '../../../lib/useAutoResearchTranslation'
import { ChevronDown, Circle, Loader2, Play, Square, Trash2 } from 'lucide-react'
import { Button } from '../../ui/button'
import AutoResearchExecutionConsole from '../AutoResearchExecutionConsole'
import SimpleProgressSteps from './SimpleProgressSteps'
import { buildAutoResearchExecutionView } from '../../../lib/autoresearchEventSelectors'
import {
  buildClinicalProgressSteps,
  formatClinicalMetric,
  isLiveClinicalStatus,
} from '../../../lib/autoresearchClinicalSteps'
import type { AutoResearchEvent, AutoResearchSessionDetail } from '../../../types/autoresearch'
import type { SessionStreamStatus } from '../useSessionStream'

interface AutoResearchClinicalSessionViewProps {
  sessionId: string
  session: AutoResearchSessionDetail | null
  events: AutoResearchEvent[]
  streamStatus: SessionStreamStatus
  streamError?: string
  displayTitle: string
  titlePending: boolean
  latestStatus: string
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
    case 'interrupted':
      return 'bg-gray-100 text-gray-700 ring-gray-200'
    default:
      return 'bg-gray-100 text-gray-600 ring-gray-200'
  }
}

function clinicalStatusLabel(status: string, t: (key: string) => string) {
  const key = `autoResearch.clinical.status.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

export default function AutoResearchClinicalSessionView({
  sessionId,
  session,
  events,
  streamStatus,
  streamError,
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
  onStop,
  onResume,
  onDelete,
}: AutoResearchClinicalSessionViewProps) {
  const { t } = useAutoResearchTranslation()
  const navigate = useNavigate()
  const [technicalOpen, setTechnicalOpen] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const isLive = isLiveClinicalStatus(latestStatus) || streamStatus === 'open' || streamStatus === 'reconnecting'
  useEffect(() => {
    if (!isLive) return undefined
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isLive])
  const view = useMemo(
    () => buildAutoResearchExecutionView(session, events, nowMs),
    [session, events, nowMs],
  )
  const progressSteps = useMemo(() => buildClinicalProgressSteps(view.stages), [view.stages])
  const consoleSession = session ? { ...session, status: latestStatus, stage: view.runSummary.stage } : null

  const stateRecord = useMemo(() => {
    const stateEvent = [...events].reverse().find((event) => event.state)
    return { ...(session?.state || {}), ...(stateEvent?.state || {}) } as Record<string, unknown>
  }, [events, session?.state])
  const rawMaxIterations = typeof stateRecord.max_iterations === 'number' ? stateRecord.max_iterations : null
  const rawIterationIndex = typeof stateRecord.iteration_index === 'number' ? stateRecord.iteration_index : null
  const currentIteration = rawIterationIndex ?? (view.iterations.at(-1)?.index ?? null)
  const maxIterations = rawMaxIterations
  const iterationLabel = currentIteration
    ? maxIterations && maxIterations > currentIteration
      ? t('autoResearch.clinical.iterationProgress', { current: currentIteration, max: maxIterations })
      : t('autoResearch.clinical.iterationCurrent', { current: currentIteration })
    : '—'

  const bestMetricLabel = formatClinicalMetric(
    view.bestMetric?.name,
    view.bestMetric?.value ?? null,
  )

  const isTerminal = ['completed', 'failed', 'interrupted'].includes(latestStatus)

  return (
    <div className="space-y-5" data-testid="autoresearch-clinical-session">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="flex min-w-0 flex-wrap items-center gap-2 text-2xl font-extrabold tracking-tight text-gray-950 sm:text-3xl">
            {titlePending && <Loader2 className="h-5 w-5 animate-spin text-blue-600" />}
            <span>{displayTitle}</span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
              {t('autoResearch.clinical.stopRun')}
            </Button>
          )}
          <div
            className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ring-1 ${statusClass(latestStatus)}`}
            data-testid="autoresearch-session-status-pill"
          >
            <Circle className="h-2 w-2 fill-current" />
            <span>
              {clinicalStatusLabel(latestStatus, t)}
              {runningElapsed && <span className="ml-1 font-semibold opacity-80">· {runningElapsed}</span>}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-700">{error}</div>
      )}

      {session?.question && (
        <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">{t('autoResearch.clinical.researchQuestion')}</p>
          <p className="mt-2 text-sm leading-6 text-gray-700">{session.question}</p>
        </section>
      )}

      <section className="rounded-3xl border border-blue-100 bg-gradient-to-br from-blue-50 to-white p-5 shadow-sm" data-testid="autoresearch-clinical-overview">
        <h2 className="text-sm font-bold text-gray-900">{t('autoResearch.clinical.overviewTitle')}</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <OverviewTile label={t('autoResearch.clinical.taskType')} value={view.sessionMetadata.taskType || '—'} />
          <OverviewTile label={t('autoResearch.clinical.foundationModel')} value={view.sessionMetadata.foundationModel || '—'} />
          <OverviewTile label={t('autoResearch.clinical.duration')} value={view.runSummary.totalDurationLabel || '—'} />
          <OverviewTile label={t('autoResearch.clinical.bestMetric')} value={bestMetricLabel} />
          <OverviewTile label={t('autoResearch.clinical.currentIteration')} value={iterationLabel} />
          <OverviewTile label={t('autoResearch.clinical.runStatus')} value={clinicalStatusLabel(latestStatus, t)} />
        </div>
      </section>

      {isLoading ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-6 text-sm text-gray-500 shadow-sm">
          {t('autoResearch.clinical.loading')}
        </div>
      ) : (
        <>
          <SimpleProgressSteps steps={progressSteps} />

          <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold text-gray-900">{t('autoResearch.clinical.roundSummaryTitle')}</h2>
            <div className="mt-4 space-y-3">
              {view.runSummary.narrative.agentActions && (
                <SummaryBlock
                  label={t('autoResearch.clinical.agentWork')}
                  value={view.runSummary.narrative.agentActions}
                />
              )}
              {view.runSummary.narrative.result && (
                <SummaryBlock
                  label={t('autoResearch.clinical.result')}
                  value={view.runSummary.narrative.result}
                />
              )}
              {!view.runSummary.narrative.agentActions && !view.runSummary.narrative.result && (
                <p className="text-sm leading-6 text-gray-500">
                  {isLive
                    ? t('autoResearch.clinical.waitingForUpdates')
                    : t('autoResearch.clinical.noSummaryYet')}
                </p>
              )}
            </div>
          </section>

          {isTerminal && (
            <section className="rounded-3xl border border-emerald-200 bg-emerald-50/70 p-5 shadow-sm">
              <h2 className="text-sm font-bold text-emerald-900">
                {latestStatus === 'completed'
                  ? t('autoResearch.clinical.completedTitle')
                  : t('autoResearch.clinical.endedTitle')}
              </h2>
              {view.runSummary.narrative.result && (
                <p className="mt-2 text-sm leading-6 text-emerald-800">{view.runSummary.narrative.result}</p>
              )}
              {bestMetricLabel !== '—' && (
                <p className="mt-2 text-sm font-semibold text-emerald-900">
                  {t('autoResearch.clinical.bestMetricResult', { metric: bestMetricLabel })}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
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
                    {t('autoResearch.clinical.deleteSession')}
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                  onClick={() => navigate('/autoresearch/new')}
                >
                  {t('autoResearch.clinical.newExperiment')}
                </Button>
              </div>
            </section>
          )}

          <section className="rounded-3xl border border-gray-200 bg-white shadow-sm">
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
              onClick={() => setTechnicalOpen((value) => !value)}
              aria-expanded={technicalOpen}
            >
              <span className="text-sm font-semibold text-gray-900">{t('autoResearch.clinical.technicalDetails')}</span>
              <ChevronDown className={`h-4 w-4 text-gray-500 transition ${technicalOpen ? 'rotate-180' : ''}`} />
            </button>
            {technicalOpen && (
              <div className="border-t border-gray-100 px-2 pb-4 sm:px-4">
                <AutoResearchExecutionConsole
                  variant="clinical"
                  session={consoleSession}
                  events={events}
                  streamStatus={streamStatus}
                  streamError={streamError}
                />
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function OverviewTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/80 bg-white/80 p-3 ring-1 ring-blue-100">
      <p className="text-[11px] font-bold uppercase tracking-wider text-blue-700">{label}</p>
      <p className="mt-1 text-sm font-extrabold text-gray-950">{value}</p>
    </div>
  )
}

function SummaryBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
      <p className="text-xs font-bold uppercase tracking-wider text-gray-400">{label}</p>
      <p className="mt-2 text-sm leading-6 text-gray-700">{value}</p>
    </div>
  )
}
