import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Bug, ChevronDown, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'
import { useAutoResearchTranslation } from '../../lib/useAutoResearchTranslation'
import {
  autoResearchRunningIterationLabel,
  autoResearchVisibleEventsLabel,
} from '../../lib/autoresearchI18n'
import { Button } from '../ui/button'
import { buildAutoResearchExecutionView } from '../../lib/autoresearchEventSelectors'
import { trainingProgressConsoleLabel } from '../../lib/autoresearchSessions'
import type { AutoResearchEvent, AutoResearchSessionDetail } from '../../types/autoresearch'
import type { SessionStreamStatus } from './useSessionStream'
import StageTimeline from './StageTimeline'
import IterationLadder from './IterationLadder'
import RunSummaryCard from './RunSummaryCard'
import StageCard from './messages/StageCard'
import IterationCard from './messages/IterationCard'

interface AutoResearchExecutionConsoleProps {
  session: AutoResearchSessionDetail | null
  events: AutoResearchEvent[]
  streamStatus: SessionStreamStatus
  streamError?: string
  variant?: 'default' | 'clinical'
}

function renderJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value)
}

function cleanFailureText(value: unknown): string {
  return asString(value).replace(/\s+/g, ' ').trim()
}

function firstFailureText(...values: unknown[]): string {
  for (const value of values) {
    const text = cleanFailureText(value)
    if (text) return text
  }
  return ''
}

function latestState(session: AutoResearchSessionDetail | null, events: AutoResearchEvent[]) {
  const stateEvent = [...events].reverse().find((event) => event.state)
  return { ...asRecord(session?.state), ...asRecord(stateEvent?.state) }
}

function isLiveStatus(status?: string) {
  return status === 'queued' || status === 'running'
}

function isTerminalStatus(value: unknown) {
  const status = asString(value).toLowerCase()
  return ['completed', 'finished', 'failed', 'interrupted'].includes(status)
}

function isFailureStatus(value: unknown) {
  const status = asString(value).toLowerCase()
  return status === 'failed' || status === 'interrupted'
}

function latestFailureEvent(events: AutoResearchEvent[]): AutoResearchEvent | undefined {
  return [...events].reverse().find((event) => (
    event.kind === 'error'
    || event.kind === 'emit_error'
    || event.severity === 'error'
    || isFailureStatus(event.status)
    || isFailureStatus(event.stage)
  ))
}

function latestFailedRun(state: Record<string, unknown>): Record<string, unknown> {
  const history = Array.isArray(state.run_history) ? state.run_history.map(asRecord) : []
  return [...history].reverse().find((entry) => {
    const metrics = asRecord(entry.metrics)
    return Boolean(
      cleanFailureText(entry.error)
      || cleanFailureText(entry.error_type)
      || cleanFailureText(metrics.error)
      || cleanFailureText(metrics.status).toLowerCase() === 'failed'
    )
  }) || {}
}

function failureReason(
  session: AutoResearchSessionDetail | null,
  state: Record<string, unknown>,
  events: AutoResearchEvent[],
): string {
  const event = latestFailureEvent(events)
  const eventState = asRecord(event?.state)
  const failedRun = latestFailedRun(state)
  const failedRunMetrics = asRecord(failedRun.metrics)
  const latestReview = asRecord(state.latest_review)

  return firstFailureText(
    session?.error,
    state.error,
    state.interrupted_reason,
    eventState.error,
    eventState.interrupted_reason,
    event?.message,
    event?.summary,
    failedRun.error,
    failedRunMetrics.error,
    failedRun.error_type,
    latestReview.summary,
    latestReview.reason,
  )
}

function rawIterationValues(state: Record<string, unknown>, events: AutoResearchEvent[]): number[] {
  const values = events
    .map((event) => asNumber(event.iteration))
    .filter((value): value is number => typeof value === 'number')
  const history = Array.isArray(state.run_history) ? state.run_history.map(asRecord) : []
  history.forEach((record) => {
    const value = asNumber(record.iteration)
    if (typeof value === 'number') values.push(value)
  })
  return values
}

function displayIteration(index: number | null, state: Record<string, unknown>, events: AutoResearchEvent[]): number | null {
  if (typeof index !== 'number') return null
  const zeroBased = rawIterationValues(state, events).some((value) => value === 0)
  let display = zeroBased ? index + 1 : index
  if (display <= 0) display = 1
  const maxIterations = asNumber(state.max_iterations)
  if (typeof maxIterations === 'number' && maxIterations > 0 && display > maxIterations) {
    display = maxIterations
  }
  return display
}

function RunningIterationPlaceholder({ iteration, maxIterations }: { iteration: number; maxIterations: number | null }) {
  const { t } = useAutoResearchTranslation()
  return (
    <article
      className="rounded-3xl border border-dashed border-blue-200 bg-blue-50/80 p-4 text-blue-800 ring-1 ring-blue-100"
      data-testid="autoresearch-iteration-running-placeholder"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-extrabold">{t('autoResearch.iteration.label', { iteration })}</h3>
          <p className="mt-1 text-xs font-semibold text-blue-600">
            {autoResearchRunningIterationLabel(iteration, maxIterations, t)}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/80 px-3 py-1 text-xs font-extrabold text-blue-700 ring-1 ring-blue-100">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t('autoResearch.iteration.runningBadge')}
        </span>
      </div>
      <p className="mt-3 rounded-2xl bg-white/70 p-3 text-sm font-medium text-blue-700">
        {t('autoResearch.executionConsole.waitingNextTool')}
      </p>
    </article>
  )
}

export default function AutoResearchExecutionConsole({
  session,
  events,
  streamStatus,
  streamError,
  variant = 'default',
}: AutoResearchExecutionConsoleProps) {
  const { t } = useAutoResearchTranslation()
  const isClinical = variant === 'clinical'
  const [debugOpen, setDebugOpen] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const isLive = isLiveStatus(session?.status) || streamStatus === 'open' || streamStatus === 'reconnecting'
  useEffect(() => {
    if (!isLive) return
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isLive])
  const view = useMemo(() => buildAutoResearchExecutionView(session, events, nowMs), [session, events, nowMs])
  const state = useMemo(() => latestState(session, view.visibleEvents), [session, view.visibleEvents])
  const rawCurrentIteration = asNumber(state.iteration_index)
  const displayCurrentIteration = typeof rawCurrentIteration === 'number'
    ? displayIteration(rawCurrentIteration, state, view.visibleEvents)
    : view.iterations.at(-1)?.index ?? null
  const maxIterations = asNumber(state.max_iterations)
  const currentStage = asString(state.stage) || asString(session?.stage) || view.stages.find((stage) => stage.status === 'current')?.id || ''
  const isExecutionRunning = isLive && currentStage === 'execution'
  const runningLabel = displayCurrentIteration ? autoResearchRunningIterationLabel(displayCurrentIteration, maxIterations, t) : ''
  const isSessionEnded =
    isTerminalStatus(session?.status) ||
    isTerminalStatus(session?.stage) ||
    isTerminalStatus(state.status) ||
    isTerminalStatus(state.stage)
  const trainingProgressLabel = isSessionEnded ? '' : trainingProgressConsoleLabel(session?.training_progress)
  const isSessionFailed =
    isFailureStatus(session?.status) ||
    isFailureStatus(session?.stage) ||
    isFailureStatus(state.status) ||
    isFailureStatus(state.stage)
  const failureMessage = isSessionFailed ? failureReason(session, state, view.visibleEvents) : ''
  const hasCurrentIterationCard = displayCurrentIteration
    ? view.iterations.some((iteration) => iteration.index === displayCurrentIteration)
    : false
  const activeStages = view.stages.filter((stage) => stage.status !== 'pending' || stage.eventCount > 0)
  const nonExecutionStages = (isClinical ? view.stages : activeStages).filter((stage) => stage.id !== 'execution')

  return (
    <div className="space-y-5">
      {streamError && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-800">
          {streamError}
        </div>
      )}

      {failureMessage && (
        <section
          className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 shadow-sm"
          data-testid="autoresearch-failure-details"
          role="alert"
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-white text-red-600 ring-1 ring-red-100">
              <AlertTriangle className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-black uppercase tracking-wider text-red-700">
                {t('autoResearch.executionConsole.failureDetails')}
              </p>
              <p className="mt-1 break-words text-sm font-semibold leading-6 text-red-900">
                {failureMessage}
              </p>
            </div>
          </div>
        </section>
      )}

      {!isClinical && (
        <StageTimeline stages={view.stages} currentIteration={displayCurrentIteration} maxIterations={maxIterations} />
      )}

      <div
        className={cn(
          'grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]',
          isClinical ? 'items-start' : 'items-stretch xl:h-[calc(100vh-18rem)] xl:min-h-[920px]',
        )}
        data-testid="autoresearch-console-layout"
      >
        <div
          className={cn(
            'flex flex-col gap-5',
            !isClinical && 'h-full min-h-0 xl:overflow-hidden',
          )}
          data-testid="autoresearch-main-column"
        >
          <RunSummaryCard summary={view.runSummary} compactHeader={isClinical} className={isClinical ? 'flex-shrink-0' : undefined} />

          <section
            className={cn(
              'flex flex-col overflow-hidden rounded-3xl border border-gray-200 bg-white p-4 shadow-sm sm:p-5',
              isClinical ? 'flex-shrink-0' : 'min-h-[520px] flex-1 min-h-0 xl:min-h-0',
            )}
            data-testid="autoresearch-events-card"
          >
            <div className="mb-4 flex flex-shrink-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-gray-400">{t('autoResearch.executionConsole.title')}</p>
                {!isClinical && (
                  <>
                    <h2 className="mt-1 text-lg font-extrabold text-gray-950">{t('autoResearch.executionConsole.transcriptTitle')}</h2>
                    <p className="mt-1 text-sm text-gray-500">{t('autoResearch.executionConsole.transcriptDescription')}</p>
                  </>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {isExecutionRunning && displayCurrentIteration && (
                  <span
                    className="inline-flex w-fit items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-extrabold text-blue-700 ring-1 ring-blue-100"
                    data-testid="autoresearch-execution-running-badge"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {runningLabel}
                  </span>
                )}
                {trainingProgressLabel && (
                  <span
                    className="inline-flex w-fit items-center gap-1.5 rounded-full bg-sky-50 px-3 py-1 text-xs font-extrabold text-sky-700 ring-1 ring-sky-100"
                    data-testid="autoresearch-training-progress-badge"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {trainingProgressLabel}
                  </span>
                )}
                <span className="w-fit rounded-full bg-gray-100 px-3 py-1 text-xs font-bold text-gray-500 ring-1 ring-gray-200">
                  {autoResearchVisibleEventsLabel(view.visibleEvents.length, t)}
                </span>
              </div>
            </div>

            <div
              className={cn(
                'space-y-3 overflow-y-auto overscroll-contain pr-1 custom-scrollbar',
                isClinical ? 'autoresearch-steps-scroll' : 'min-h-0 flex-1',
              )}
              data-testid="autoresearch-events-scroll"
            >
              {nonExecutionStages.map((stage) => (
                <StageCard
                  key={stage.id}
                  stage={stage}
                  grounding={stage.id === 'grounding' ? view.grounding : null}
                  acquisition={stage.id === 'acquisition' ? view.acquisition : null}
                />
              ))}

              {isExecutionRunning && displayCurrentIteration && !hasCurrentIterationCard && (
                <RunningIterationPlaceholder iteration={displayCurrentIteration} maxIterations={maxIterations} />
              )}

              {view.iterations.map((iteration) => (
                <IterationCard
                  key={iteration.index}
                  iteration={iteration}
                  sessionMetadata={view.sessionMetadata}
                  isCurrentRunning={isExecutionRunning && iteration.index === displayCurrentIteration}
                />
              ))}

              {view.visibleEvents.length === 0 && (
                <div className="rounded-3xl border border-dashed border-gray-200 bg-gray-50 p-8 text-center">
                  <p className="text-base font-extrabold text-gray-950">{t('autoResearch.executionConsole.waitingEventsTitle')}</p>
                  <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-gray-500">{t('autoResearch.executionConsole.waitingEventsDescription')}</p>
                </div>
              )}
            </div>

            <div className="mt-4 flex-shrink-0 border-t border-gray-100 pt-4">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2 border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                onClick={() => setDebugOpen((value) => !value)}
              >
                <Bug className="h-3.5 w-3.5" /> {debugOpen ? t('autoResearch.executionConsole.hideRawEvents') : t('autoResearch.executionConsole.showRawEvents')}
                <ChevronDown className={`h-3.5 w-3.5 transition ${debugOpen ? 'rotate-180' : ''}`} />
              </Button>

              {debugOpen && (
                <pre className="mt-3 max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-gray-200 bg-gray-950 p-4 text-xs leading-5 text-gray-100">
                  {renderJson(view.debugEvents)}
                </pre>
              )}
            </div>
          </section>
        </div>

        <IterationLadder
          variant={isClinical ? 'clinical' : 'default'}
          iterations={view.iterations}
          bestMetric={view.bestMetric}
          sessionMetadata={view.sessionMetadata}
          toolCards={view.toolCards}
          sessionId={session?.session_id}
          currentIteration={displayCurrentIteration}
          maxIterations={maxIterations}
          isRunning={isExecutionRunning}
          trainingProgress={session?.training_progress}
        />
      </div>
    </div>
  )
}
