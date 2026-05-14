import { AlertCircle, CheckCircle2, Circle, Clock3, Loader2, XCircle } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { cn } from '../../lib/utils'
import type { PaperRunDetail, PaperRunStage, PaperStageLogEntry } from '../../api/papers'

interface StageChecklistProps {
  run: PaperRunDetail
  activeTab: string
  onSelectTab: (tab: string) => void
}

type RowState = 'completed' | 'running' | 'waiting' | 'failed' | 'warning' | 'pending'

interface StageRowDefinition {
  id: string
  label: string
  short: string
  stages: PaperRunStage[]
  tab: string
}

const STAGE_ROWS: StageRowDefinition[] = [
  { id: 'collecting', label: 'Collect evidence', short: 'Collect', stages: ['collecting'], tab: 'tables' },
  { id: 'building_evidence', label: 'Lock tables', short: 'Tables', stages: ['building_evidence'], tab: 'tables' },
  { id: 'outlining', label: 'Outline', short: 'Outline', stages: ['outlining'], tab: 'outline' },
  { id: 'plotting', label: 'Figures', short: 'Figures', stages: ['plotting'], tab: 'figures' },
  { id: 'literature_review', label: 'Citations', short: 'Cites', stages: ['literature_review'], tab: 'citations' },
  { id: 'section_writing', label: 'Sections', short: 'Sections', stages: ['section_writing'], tab: 'sections' },
  { id: 'validating', label: 'Validation', short: 'Validate', stages: ['validating'], tab: 'validation' },
  { id: 'refining', label: 'Refinement', short: 'Refine', stages: ['refining'], tab: 'sections' },
  { id: 'rendering_exporting', label: 'PDF export', short: 'PDF', stages: ['rendering', 'exporting'], tab: 'pdf' },
]

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running'])
const WAITING_STATUSES = new Set(['awaiting_outline_approval'])
const LIVE_DURATION_DISPLAY_DELAY_MS = 1500

function stageOrderIndex(stage: string | null | undefined): number {
  return STAGE_ROWS.findIndex((row) => row.stages.includes(stage as PaperRunStage))
}

function latestForRow(logs: PaperStageLogEntry[], row: StageRowDefinition): PaperStageLogEntry | undefined {
  return [...logs].reverse().find((entry) => row.stages.includes(entry.stage as PaperRunStage))
}

function hasValidationGuardFailures(run: PaperRunDetail): boolean {
  return (run.validation_summary?.m10_guards ?? []).some(
    (guard) => guard.status.toLowerCase() === 'fail' || guard.error_count > 0,
  )
}

function timeMs(value: string | null | undefined): number | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  // Backend stage logs may serialize naive UTC datetimes. Treat missing timezone
  // as UTC so Hong Kong browsers do not add an artificial +8h offset.
  const normalized = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(trimmed) ? trimmed : `${trimmed}Z`
  const parsed = Date.parse(normalized)
  return Number.isNaN(parsed) ? null : parsed
}

function stateForRow(run: PaperRunDetail, row: StageRowDefinition, index: number, latest?: PaperStageLogEntry): RowState {
  const currentInRow = row.stages.includes(run.current_stage)
  const currentIndex = stageOrderIndex(run.current_stage)
  if (run.status === 'failed' && currentInRow) return 'failed'
  if (latest?.status === 'failed') return 'failed'
  if (row.id === 'validating' && latest?.status === 'completed' && hasValidationGuardFailures(run)) return 'warning'
  if (currentIndex > index || run.status === 'completed') return 'completed'
  if (latest?.status === 'running' || latest?.status === 'pending') return 'running'
  if (latest?.status && WAITING_STATUSES.has(latest.status)) return 'waiting'
  if (latest?.status === 'completed') return 'completed'
  if (currentInRow && WAITING_STATUSES.has(run.status)) return 'waiting'
  if (currentInRow && ACTIVE_RUN_STATUSES.has(run.status)) return 'running'
  return 'pending'
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ''
  const safeMs = Math.max(0, ms)
  if (safeMs < 1000) return `${safeMs} ms`
  const seconds = Math.floor(safeMs / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}m ${rest}s`
}

function durationMsForState(state: RowState, latest: PaperStageLogEntry | undefined, nowMs: number): number | null {
  if ((state === 'running' || state === 'waiting') && latest) {
    const startedMs = timeMs(latest.started_at) ?? timeMs(latest.ts)
    if (startedMs !== null) return nowMs - startedMs
  }
  return latest?.duration_ms ?? null
}

function visibleDurationMsForState(state: RowState, latest: PaperStageLogEntry | undefined, nowMs: number): number | null {
  const durationMs = durationMsForState(state, latest, nowMs)
  if (
    (state === 'running' || state === 'waiting') &&
    latest?.duration_ms == null &&
    durationMs !== null &&
    durationMs < LIVE_DURATION_DISPLAY_DELAY_MS
  ) {
    return null
  }
  return durationMs
}

function durationForState(state: RowState, latest: PaperStageLogEntry | undefined, nowMs: number): string {
  return formatDuration(visibleDurationMsForState(state, latest, nowMs))
}

function statusIcon(state: RowState) {
  if (state === 'completed') return <CheckCircle2 className="h-3.5 w-3.5" />
  if (state === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin" />
  if (state === 'waiting') return <Clock3 className="h-3.5 w-3.5" />
  if (state === 'failed') return <XCircle className="h-3.5 w-3.5" />
  if (state === 'warning') return <AlertCircle className="h-3.5 w-3.5" />
  return <Circle className="h-3.5 w-3.5" />
}

function pillClass(state: RowState, selected: boolean): string {
  if (selected) return 'border-slate-900 bg-slate-900 text-white shadow-sm'
  switch (state) {
    case 'completed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'running':
      return 'border-sky-200 bg-sky-50 text-sky-700'
    case 'waiting':
      return 'border-amber-200 bg-amber-50 text-amber-700'
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-700'
    case 'warning':
      return 'border-amber-200 bg-amber-50 text-amber-800'
    default:
      return 'border-slate-200 bg-white text-slate-400'
  }
}

function connectorClass(prevState: RowState): string {
  switch (prevState) {
    case 'completed':
      return 'bg-emerald-300'
    case 'running':
      return 'bg-sky-200'
    case 'waiting':
      return 'bg-amber-200'
    case 'failed':
      return 'bg-red-200'
    case 'warning':
      return 'bg-amber-200'
    default:
      return 'bg-slate-200'
  }
}

export function StageChecklist({ run, activeTab, onSelectTab }: StageChecklistProps) {
  const [nowMs, setNowMs] = useState(() => Date.now())
  const logs = run.stage_log ?? []
  const latestEntries = STAGE_ROWS.map((row) => latestForRow(logs, row))
  const states = STAGE_ROWS.map((row, index) => stateForRow(run, row, index, latestEntries[index]))
  const hasLiveStage = states.some((state) => state === 'running' || state === 'waiting')
  useEffect(() => {
    if (!hasLiveStage) return
    setNowMs(Date.now())
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [hasLiveStage])

  const liveIndex = states.findIndex((state) => state === 'running' || state === 'waiting' || state === 'failed')
  const liveRow = liveIndex >= 0 ? STAGE_ROWS[liveIndex] : undefined
  const liveState = liveIndex >= 0 ? states[liveIndex] : undefined
  const liveDurationMs = liveIndex >= 0 ? visibleDurationMsForState(states[liveIndex], latestEntries[liveIndex], nowMs) : null
  const liveDuration = formatDuration(liveDurationMs)
  const completedTotalMs = logs.reduce<number>((sum, entry) => sum + (entry.duration_ms ?? 0), 0)
  const liveLoggedMs = liveIndex >= 0 ? (latestEntries[liveIndex]?.duration_ms ?? 0) : 0
  const liveExtraMs =
    liveState === 'running' || liveState === 'waiting'
      ? Math.max(0, (liveDurationMs ?? 0) - liveLoggedMs)
      : 0
  const totalMs = completedTotalMs + liveExtraMs
  const totalLabel = totalMs > 0 ? formatDuration(totalMs) : ''
  const liveLabel = liveRow
    ? liveState === 'running'
      ? `Running: ${liveRow.label}`
      : liveState === 'waiting'
        ? `Waiting: ${liveRow.label}`
        : `Failed: ${liveRow.label}`
    : undefined

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/90 px-3 py-2.5 shadow-sm">
      <div className="flex items-center gap-3">
        <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">
          Pipeline
        </span>
        <div className="flex flex-1 items-center gap-1 overflow-x-auto pb-0.5">
          {STAGE_ROWS.map((row, i) => {
            const state = states[i]
            const latest = latestEntries[i]
            const duration = durationForState(state, latest, nowMs)
            const selected = activeTab === row.tab
            const tip = [
              row.label,
              duration ? `· ${duration}` : '',
              latest?.message ? `— ${latest.message}` : '',
            ]
              .filter(Boolean)
              .join(' ')
            return (
              <Fragment key={row.id}>
                {i > 0 ? (
                  <div className={cn('h-0.5 w-3 shrink-0 rounded-full sm:w-5', connectorClass(states[i - 1]))} />
                ) : null}
                <button
                  type="button"
                  onClick={() => onSelectTab(row.tab)}
                  title={tip}
                  className={cn(
                    'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition hover:-translate-y-0.5 hover:shadow-sm',
                    pillClass(state, selected)
                  )}
                >
                  {statusIcon(state)}
                  <span>{row.short}</span>
                  {duration ? (
                    <span className={cn('text-[10px] font-medium tabular-nums', selected ? 'text-white/70' : 'text-slate-400')}>
                      {duration}
                    </span>
                  ) : null}
                </button>
              </Fragment>
            )
          })}
        </div>
        <div className="shrink-0 flex items-center gap-2 text-xs">
          {liveLabel ? (
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-semibold',
                liveState === 'running' && 'border-sky-200 bg-sky-50 text-sky-700',
                liveState === 'waiting' && 'border-amber-200 bg-amber-50 text-amber-700',
                liveState === 'failed' && 'border-red-200 bg-red-50 text-red-700'
              )}
            >
              {liveState ? statusIcon(liveState) : null}
              {liveLabel}
              {liveDuration ? <span className="font-mono text-[11px]">{liveDuration}</span> : null}
            </span>
          ) : null}
          {totalLabel ? <span className="font-semibold text-slate-600 tabular-nums">Total {totalLabel}</span> : null}
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-semibold text-slate-600">
            {run.current_stage}
          </span>
        </div>
      </div>
    </div>
  )
}
