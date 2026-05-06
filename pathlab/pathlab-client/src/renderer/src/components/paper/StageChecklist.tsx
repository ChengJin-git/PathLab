import { CheckCircle2, Circle, FileJson, FileText, Image, Loader2, ShieldCheck, Table2, XCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
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
  stages: PaperRunStage[]
  tab: string
  icon: LucideIcon
}

const STAGE_ROWS: StageRowDefinition[] = [
  { id: 'collecting', label: 'Collect evidence', stages: ['collecting'], tab: 'tables', icon: Table2 },
  { id: 'building_evidence', label: 'Lock tables', stages: ['building_evidence'], tab: 'tables', icon: Table2 },
  { id: 'outlining', label: 'Outline', stages: ['outlining'], tab: 'outline', icon: FileJson },
  { id: 'plotting', label: 'Figures', stages: ['plotting'], tab: 'figures', icon: Image },
  { id: 'literature_review', label: 'Citations', stages: ['literature_review'], tab: 'citations', icon: FileText },
  { id: 'section_writing', label: 'Sections', stages: ['section_writing'], tab: 'sections', icon: FileText },
  { id: 'validating', label: 'Validation', stages: ['validating'], tab: 'validation', icon: ShieldCheck },
  { id: 'refining', label: 'Refinement', stages: ['refining'], tab: 'sections', icon: FileText },
  { id: 'rendering_exporting', label: 'PDF export', stages: ['rendering', 'exporting'], tab: 'pdf', icon: FileText },
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
  if (state === 'completed') return <CheckCircle2 className="h-4 w-4" />
  if (state === 'running') return <Loader2 className="h-4 w-4 animate-spin" />
  if (state === 'failed') return <XCircle className="h-4 w-4" />
  return <Circle className="h-4 w-4" />
}

function stateClass(state: RowState): string {
  switch (state) {
    case 'completed':
      return 'border-emerald-200 bg-emerald-50/80 text-emerald-700'
    case 'running':
      return 'border-sky-200 bg-sky-50/80 text-sky-700'
    case 'failed':
      return 'border-red-200 bg-red-50/80 text-red-700'
    default:
      return 'border-slate-200 bg-white text-slate-400'
  }
}

export function StageChecklist({ run, activeTab, onSelectTab }: StageChecklistProps) {
  const logs = run.stage_log ?? []

  return (
    <Card className="overflow-hidden border-slate-200 bg-white/90 shadow-sm">
      <CardHeader className="border-b border-slate-100 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">todo.md</div>
            <CardTitle className="text-lg">Stage checklist</CardTitle>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">
            {run.current_stage}
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-3">
        <div className="space-y-2">
          {STAGE_ROWS.map((row, index) => {
            const Icon = row.icon
            const latest = latestForRow(logs, row)
            const state = stateForRow(run, row, index, latest)
            const duration = formatDuration(latest?.duration_ms)
            const selected = activeTab === row.tab
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => onSelectTab(row.tab)}
                className={cn(
                  'group w-full rounded-2xl border px-3 py-3 text-left transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-sm',
                  selected ? 'border-slate-900 bg-slate-950 text-white shadow-sm' : 'border-slate-100 bg-slate-50/60 text-slate-700'
                )}
              >
                <div className="flex items-start gap-3">
                  <span className={cn('mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full border', selected ? 'border-white/20 bg-white/10 text-white' : stateClass(state))}>
                    {statusIcon(state)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2 font-semibold">
                        <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
                        <span className="truncate">{row.label}</span>
                      </span>
                      <span className={cn('shrink-0 text-[11px] font-semibold uppercase tracking-[0.14em]', selected ? 'text-white/70' : 'text-slate-400')}>
                        {duration || state}
                      </span>
                    </span>
                    <span className={cn('mt-1 line-clamp-2 block text-xs leading-5', selected ? 'text-white/70' : 'text-slate-500')}>
                      {latest?.error_message || latest?.message || 'Waiting for this artifact.'}
                    </span>
                  </span>
                </div>
              </button>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
