import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react'
import { Fragment } from 'react'
import { cn } from '../../lib/utils'
import type { PaperRunDetail, PaperRunStage, PaperStageLogEntry } from '../../api/papers'

interface StageChecklistProps {
  run: PaperRunDetail
  activeTab: string
  onSelectTab: (tab: string) => void
}

type RowState = 'completed' | 'running' | 'failed' | 'pending'

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

function stageOrderIndex(stage: string | null | undefined): number {
  return STAGE_ROWS.findIndex((row) => row.stages.includes(stage as PaperRunStage))
}

function latestForRow(logs: PaperStageLogEntry[], row: StageRowDefinition): PaperStageLogEntry | undefined {
  return [...logs].reverse().find((entry) => row.stages.includes(entry.stage as PaperRunStage))
}

function stateForRow(run: PaperRunDetail, row: StageRowDefinition, index: number, latest?: PaperStageLogEntry): RowState {
  const currentInRow = row.stages.includes(run.current_stage)
  if (run.status === 'failed' && currentInRow) return 'failed'
  if (latest?.status === 'failed') return 'failed'
  if (currentInRow && ACTIVE_RUN_STATUSES.has(run.status)) return 'running'
  if (latest?.status === 'running' || latest?.status === 'pending') return 'running'
  if (latest?.status === 'completed') return 'completed'
  const currentIndex = stageOrderIndex(run.current_stage)
  if (currentIndex > index || run.status === 'completed') return 'completed'
  return 'pending'
}

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ''
  if (ms < 1000) return `${ms} ms`
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}m ${rest}s`
}

function statusIcon(state: RowState) {
  if (state === 'completed') return <CheckCircle2 className="h-3.5 w-3.5" />
  if (state === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin" />
  if (state === 'failed') return <XCircle className="h-3.5 w-3.5" />
  return <Circle className="h-3.5 w-3.5" />
}

function pillClass(state: RowState, selected: boolean): string {
  if (selected) return 'border-slate-900 bg-slate-900 text-white shadow-sm'
  switch (state) {
    case 'completed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'running':
      return 'border-sky-200 bg-sky-50 text-sky-700'
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-700'
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
    case 'failed':
      return 'bg-red-200'
    default:
      return 'bg-slate-200'
  }
}

export function StageChecklist({ run, activeTab, onSelectTab }: StageChecklistProps) {
  const logs = run.stage_log ?? []
  const states = STAGE_ROWS.map((row, index) => stateForRow(run, row, index, latestForRow(logs, row)))
  const totalMs = logs.reduce<number>((sum, entry) => sum + (entry.duration_ms ?? 0), 0)
  const totalLabel = totalMs > 0 ? formatDuration(totalMs) : ''

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/90 px-3 py-2.5 shadow-sm">
      <div className="flex items-center gap-3">
        <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">
          Pipeline
        </span>
        <div className="flex flex-1 items-center gap-1 overflow-x-auto pb-0.5">
          {STAGE_ROWS.map((row, i) => {
            const state = states[i]
            const latest = latestForRow(logs, row)
            const duration = formatDuration(latest?.duration_ms)
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
          {totalLabel ? <span className="font-semibold text-slate-600 tabular-nums">{totalLabel}</span> : null}
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-semibold text-slate-600">
            {run.current_stage}
          </span>
        </div>
      </div>
    </div>
  )
}
