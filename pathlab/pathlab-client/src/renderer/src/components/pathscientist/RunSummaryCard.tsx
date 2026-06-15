import { Activity, BarChart3, Clock3, Cpu, Layers3, Trophy, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'
import type { PathScientistRunSummaryView } from '../../lib/pathscientistEventSelectors'

interface RunSummaryCardProps {
  summary: PathScientistRunSummaryView
  compactHeader?: boolean
  className?: string
}

function formatMetric(summary: PathScientistRunSummaryView) {
  const metric = summary.bestMetric
  if (!metric) return '--'
  const value = metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3)
  return `${metric.name.toUpperCase()} ${value}`
}

function SummaryTile({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className="rounded-2xl bg-white/75 p-3 ring-1 ring-slate-200">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-black uppercase tracking-wider text-slate-500">{label}</p>
        <span className="text-slate-400">{icon}</span>
      </div>
      <p className="mt-1 truncate text-sm font-extrabold text-slate-950">{value}</p>
    </div>
  )
}

function isRedundantStageBadge(status: string, stage: string) {
  const normalizedStatus = status.trim().toLowerCase()
  const normalizedStage = stage.trim().toLowerCase()
  if (!normalizedStage) return true
  if (normalizedStatus === normalizedStage) return true
  return normalizedStage === 'completed' && ['completed', 'finished'].includes(normalizedStatus)
}

export default function RunSummaryCard({ summary, compactHeader = false, className }: RunSummaryCardProps) {
  const metadata = summary.sessionMetadata
  const showStageBadge = !isRedundantStageBadge(summary.status, summary.stage)

  return (
    <section
      className={cn(
        'rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-50 via-white to-blue-50/60 p-4 shadow-sm sm:p-5',
        className,
      )}
      data-testid="pathscientist-summary-card"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Run summary</p>
          {!compactHeader && (
            <>
              <h2 className="mt-1 truncate text-xl font-black tracking-tight text-slate-950">{summary.title}</h2>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-500">{summary.narrative.brief}</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-bold text-white">{summary.status}</span>
          {showStageBadge && (
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-600 ring-1 ring-slate-200">{summary.stage}</span>
          )}
          {!compactHeader && summary.narrative.source === 'llm' && (
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
              LLM summary
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <NarrativeBlock label="User request" value={summary.narrative.userRequest} />
        <NarrativeBlock label="Agent work" value={summary.narrative.agentActions} />
        <NarrativeBlock label="Result" value={summary.narrative.result} />
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryTile icon={<Clock3 className="h-4 w-4" />} label="Duration" value={summary.totalDurationLabel} />
        <SummaryTile icon={<Activity className="h-4 w-4" />} label="Events" value={`${summary.eventCount} events`} />
        <SummaryTile icon={<Wrench className="h-4 w-4" />} label="Tools" value={`${summary.toolCallCount} tools`} />
        <SummaryTile icon={<Layers3 className="h-4 w-4" />} label="Iterations" value={`${summary.iterationCount} iterations`} />
        <SummaryTile icon={<Trophy className="h-4 w-4" />} label="Best metric" value={formatMetric(summary)} />
        <SummaryTile icon={<BarChart3 className="h-4 w-4" />} label="Task" value={metadata.taskType} />
        <SummaryTile icon={<Cpu className="h-4 w-4" />} label="Foundation" value={metadata.foundationModel} />
        {metadata.milMethod && (
          <SummaryTile icon={<Layers3 className="h-4 w-4" />} label="MIL" value={metadata.milMethod} />
        )}
      </div>
    </section>
  )
}

function NarrativeBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white/80 p-3 ring-1 ring-slate-200">
      <p className="text-[11px] font-black uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-2 line-clamp-4 text-sm leading-6 text-slate-700">{value}</p>
    </div>
  )
}
