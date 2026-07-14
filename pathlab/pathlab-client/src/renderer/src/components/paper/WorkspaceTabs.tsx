import * as Tabs from '@radix-ui/react-tabs'
import { useTranslation } from 'react-i18next'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Circle,
  Clock3,
  FileCode2,
  FileJson,
  Image,
  Library,
  Loader2,
  ShieldCheck,
  Table2,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PaperRunDetail, PaperRunStage, PaperStageLogEntry } from '../../api/papers'
import { CitationsTab } from './CitationsTab'
import { FiguresTab } from './FiguresTab'
import { OutlineTab } from './OutlineTab'
import { PdfPreviewTab } from './PdfPreviewTab'
import { SectionsTab } from './SectionsTab'
import { TablesTab } from './TablesTab'
import { ValidationTab } from './ValidationTab'

export const WORKSPACE_TAB_VALUES = [
  'outline',
  'sections',
  'figures',
  'tables',
  'citations',
  'validation',
  'pdf',
] as const
export type WorkspaceTabValue = (typeof WORKSPACE_TAB_VALUES)[number]

interface WorkspaceTabsProps {
  paperId: string
  run: PaperRunDetail
  value: WorkspaceTabValue
  onValueChange: (value: WorkspaceTabValue) => void
  pdfRefreshKey: number
  onPdfRefreshNeeded: () => void
}

interface TabDefinition {
  value: WorkspaceTabValue
  icon: LucideIcon
}

type TabState = 'completed' | 'running' | 'waiting' | 'failed' | 'warning' | 'pending'

interface StageRowDefinition {
  id: string
  stages: PaperRunStage[]
  tab: WorkspaceTabValue
}

const TABS: TabDefinition[] = [
  { value: 'outline', icon: FileJson },
  { value: 'sections', icon: FileCode2 },
  { value: 'figures', icon: Image },
  { value: 'tables', icon: Table2 },
  { value: 'citations', icon: Library },
  { value: 'validation', icon: ShieldCheck },
  { value: 'pdf', icon: BookOpen },
]

const STAGE_ROWS: StageRowDefinition[] = [
  { id: 'collecting', stages: ['collecting'], tab: 'tables' },
  { id: 'building_evidence', stages: ['building_evidence'], tab: 'tables' },
  { id: 'outlining', stages: ['outlining'], tab: 'outline' },
  { id: 'plotting', stages: ['plotting'], tab: 'figures' },
  { id: 'literature_review', stages: ['literature_review'], tab: 'citations' },
  { id: 'section_writing', stages: ['section_writing'], tab: 'sections' },
  { id: 'validating', stages: ['validating'], tab: 'validation' },
  { id: 'refining', stages: ['refining'], tab: 'sections' },
  { id: 'rendering_exporting', stages: ['rendering', 'exporting'], tab: 'pdf' },
]

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running'])
const WAITING_STATUSES = new Set(['awaiting_outline_approval'])

function isWorkspaceTabValue(value: string): value is WorkspaceTabValue {
  return (WORKSPACE_TAB_VALUES as readonly string[]).includes(value)
}

export function coerceWorkspaceTab(value: string | null | undefined): WorkspaceTabValue {
  if (value === 'pdf_preview' || value === 'pdf-preview') return 'pdf'
  return value && isWorkspaceTabValue(value) ? value : 'outline'
}

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

function stateForRow(run: PaperRunDetail, row: StageRowDefinition, index: number, latest?: PaperStageLogEntry): TabState {
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

function tabState(run: PaperRunDetail, tab: WorkspaceTabValue): TabState {
  const rows = STAGE_ROWS
    .map((row, index) => ({ row, index, latest: latestForRow(run.stage_log ?? [], row) }))
    .filter(({ row }) => row.tab === tab)
  const states = rows.map(({ row, index, latest }) => stateForRow(run, row, index, latest))
  if (states.includes('failed')) return 'failed'
  if (states.includes('warning')) return 'warning'
  if (states.includes('running')) return 'running'
  if (states.includes('waiting')) return 'waiting'
  if (states.length > 0 && states.every((state) => state === 'completed')) return 'completed'
  if (states.includes('completed')) return 'completed'
  return 'pending'
}

function tabStateMessage(run: PaperRunDetail, tab: WorkspaceTabValue): string | undefined {
  const logs = run.stage_log ?? []
  const rows = STAGE_ROWS.filter((row) => row.tab === tab)
  return [...logs].reverse().find((entry) => rows.some((row) => row.stages.includes(entry.stage as PaperRunStage)))?.message
}

function stateIcon(state: TabState) {
  if (state === 'completed') return <CheckCircle2 className="h-4 w-4" />
  if (state === 'running') return <Loader2 className="h-4 w-4 animate-spin" />
  if (state === 'waiting') return <Clock3 className="h-4 w-4" />
  if (state === 'failed') return <XCircle className="h-4 w-4" />
  if (state === 'warning') return <AlertCircle className="h-4 w-4" />
  return <Circle className="h-4 w-4" />
}

function tabButtonClass(state: TabState, selected: boolean): string {
  if (selected) {
    switch (state) {
      case 'failed':
        return 'border-red-500 bg-red-600 text-white shadow-md shadow-red-200'
      case 'warning':
      case 'waiting':
        return 'border-amber-400 bg-amber-500 text-white shadow-md shadow-amber-200'
      case 'running':
        return 'border-sky-500 bg-sky-600 text-white shadow-md shadow-sky-200'
      default:
        return 'border-slate-950 bg-slate-950 text-white shadow-md shadow-slate-200'
    }
  }

  switch (state) {
    case 'completed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:border-emerald-300 hover:bg-emerald-100'
    case 'running':
      return 'border-sky-200 bg-sky-50 text-sky-800 hover:border-sky-300 hover:bg-sky-100'
    case 'waiting':
      return 'border-amber-200 bg-amber-50 text-amber-800 hover:border-amber-300 hover:bg-amber-100'
    case 'warning':
      return 'border-orange-200 bg-orange-50 text-orange-800 hover:border-orange-300 hover:bg-orange-100'
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-800 hover:border-red-300 hover:bg-red-100'
    default:
      return 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
  }
}

function statusPillClass(state: TabState, selected: boolean): string {
  if (selected) return 'bg-white/15 text-white'
  switch (state) {
    case 'completed':
      return 'bg-emerald-100 text-emerald-800'
    case 'running':
      return 'bg-sky-100 text-sky-800'
    case 'waiting':
      return 'bg-amber-100 text-amber-800'
    case 'warning':
      return 'bg-orange-100 text-orange-800'
    case 'failed':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-slate-100 text-slate-500'
  }
}

export function WorkspaceTabs({
  paperId,
  run,
  value,
  onValueChange,
  pdfRefreshKey,
  onPdfRefreshNeeded,
}: WorkspaceTabsProps) {
  const { t } = useTranslation()
  const templateId = run.selected_templates[0]

  return (
    <Tabs.Root
      value={value}
      onValueChange={(next) => {
        if (isWorkspaceTabValue(next)) onValueChange(next)
      }}
      className="overflow-hidden rounded-[1.75rem] border border-slate-200 bg-white shadow-sm"
    >
      <div className="overflow-x-auto border-b border-slate-100 bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.12),_transparent_34%),linear-gradient(180deg,_#ffffff,_#f8fafc)] p-3">
        <Tabs.List
          className="grid min-w-[900px] grid-cols-7 gap-2 rounded-[1.4rem] bg-white/75 p-2 shadow-inner shadow-slate-200/60"
          aria-label={t('paperAgent.tabs.ariaLabel')}
        >
          {TABS.map((tab) => {
            const Icon = tab.icon
            const state = tabState(run, tab.value)
            const selected = value === tab.value
            const latestMessage = tabStateMessage(run, tab.value)
            const tabLabel = t(`paperAgent.tabs.${tab.value}`)
            const statusLabel = t(`paperAgent.tabs.status.${state}`)
            return (
              <Tabs.Trigger
                key={tab.value}
                value={tab.value}
                title={latestMessage ? `${tabLabel} · ${statusLabel} · ${latestMessage}` : `${tabLabel} · ${statusLabel}`}
                className={cn(
                  'flex min-h-[4.8rem] min-w-0 flex-col items-start justify-between rounded-2xl border px-3 py-3 text-left transition hover:-translate-y-0.5 hover:shadow-sm',
                  'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-sky-500/20',
                  tabButtonClass(state, selected),
                )}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <Icon className="h-5 w-5 shrink-0" />
                    <span className="truncate text-base font-semibold">{tabLabel}</span>
                  </span>
                  <span className="shrink-0">{stateIcon(state)}</span>
                </span>
                <span className={cn('max-w-full truncate rounded-full px-2 py-0.5 text-[11px] font-semibold', statusPillClass(state, selected))}>
                  {statusLabel}
                </span>
              </Tabs.Trigger>
            )
          })}
        </Tabs.List>
      </div>

      <Tabs.Content value="outline" className="p-4 focus:outline-none sm:p-5">
        <OutlineTab paperId={paperId} run={run} />
      </Tabs.Content>
      <Tabs.Content value="sections" className="p-4 focus:outline-none sm:p-5">
        <SectionsTab paperId={paperId} templateId={templateId} onPdfRefreshNeeded={onPdfRefreshNeeded} />
      </Tabs.Content>
      <Tabs.Content value="figures" className="p-4 focus:outline-none sm:p-5">
        <FiguresTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="tables" className="p-4 focus:outline-none sm:p-5">
        <TablesTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="citations" className="p-4 focus:outline-none sm:p-5">
        <CitationsTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="validation" className="p-4 focus:outline-none sm:p-5">
        <ValidationTab paperId={paperId} run={run} validationSummary={run.validation_summary ?? null} />
      </Tabs.Content>
      <Tabs.Content value="pdf" className="p-4 focus:outline-none sm:p-5">
        <PdfPreviewTab
          paperId={paperId}
          run={run}
          pdfRefreshKey={pdfRefreshKey}
          onPdfRefreshNeeded={onPdfRefreshNeeded}
        />
      </Tabs.Content>
    </Tabs.Root>
  )
}
