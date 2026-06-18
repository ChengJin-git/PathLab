import { Activity, BarChart3, CheckCircle2, Clock3, Cpu, Layers3, ShieldCheck, Trophy, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'
import { usePathScientistTranslation } from '../../lib/usePathScientistTranslation'
import { pathScientistStatusLabel } from '../../lib/pathscientistI18n'
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

function formatExternalMetric(summary: PathScientistRunSummaryView) {
  const metric = summary.externalTest?.primaryMetric
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
  const { t } = usePathScientistTranslation()
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
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">{t('pathScientist.runSummary.title')}</p>
          {!compactHeader && (
            <>
              <h2 className="mt-1 truncate text-xl font-black tracking-tight text-slate-950">{summary.title}</h2>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-500">{summary.narrative.brief}</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-bold text-white">{pathScientistStatusLabel(summary.status, t)}</span>
          {showStageBadge && (
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-600 ring-1 ring-slate-200">{summary.stage}</span>
          )}
          {!compactHeader && summary.narrative.source === 'llm' && (
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
              {t('pathScientist.runSummary.llmSummary')}
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <NarrativeBlock label={t('pathScientist.runSummary.userRequest')} value={summary.narrative.userRequest} />
        <NarrativeBlock label={t('pathScientist.runSummary.agentWork')} value={summary.narrative.agentActions} />
        <NarrativeBlock label={t('pathScientist.runSummary.result')} value={summary.narrative.result} />
      </div>

      {summary.externalTest && (
        <ExternalValidationSummary summary={summary} />
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryTile icon={<Clock3 className="h-4 w-4" />} label={t('pathScientist.labels.duration')} value={summary.totalDurationLabel} />
        <SummaryTile icon={<Activity className="h-4 w-4" />} label={t('pathScientist.labels.events')} value={t('pathScientist.count.events', { count: summary.eventCount })} />
        <SummaryTile icon={<Wrench className="h-4 w-4" />} label={t('pathScientist.labels.tools')} value={t('pathScientist.count.tools', { count: summary.toolCallCount })} />
        <SummaryTile icon={<Layers3 className="h-4 w-4" />} label={t('pathScientist.labels.iterations')} value={t('pathScientist.count.iterations', { count: summary.iterationCount })} />
        <SummaryTile icon={<Trophy className="h-4 w-4" />} label={t('pathScientist.labels.bestMetric')} value={formatMetric(summary)} />
        <SummaryTile icon={<BarChart3 className="h-4 w-4" />} label={t('pathScientist.labels.task')} value={metadata.taskType} />
        <SummaryTile icon={<Cpu className="h-4 w-4" />} label={t('pathScientist.labels.foundation')} value={metadata.foundationModel} />
        {metadata.milMethod && (
          <SummaryTile icon={<Layers3 className="h-4 w-4" />} label="MIL" value={metadata.milMethod} />
        )}
      </div>
    </section>
  )
}

function ExternalValidationSummary({ summary }: { summary: PathScientistRunSummaryView }) {
  const { t } = usePathScientistTranslation()
  const external = summary.externalTest
  if (!external) return null
  const status = external.status || (external.committed ? 'completed' : 'recorded')
  const samples = external.sampleCount === null ? '--' : t('pathScientist.count.samples', { count: external.sampleCount })

  return (
    <div
      className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-3 ring-1 ring-emerald-100"
      data-testid="pathscientist-external-summary"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-emerald-700">
            <ShieldCheck className="h-3.5 w-3.5" />
            {t('pathScientist.runSummary.externalValidation')}
          </p>
          <p className="mt-1 text-lg font-black text-slate-950">{formatExternalMetric(summary)}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] font-bold">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/85 px-2.5 py-1 text-emerald-700 ring-1 ring-emerald-200">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {pathScientistStatusLabel(status, t)}
          </span>
          <span className="rounded-full bg-white/85 px-2.5 py-1 text-slate-600 ring-1 ring-emerald-100">{samples}</span>
          {external.runId && (
            <span className="rounded-full bg-white/85 px-2.5 py-1 text-slate-600 ring-1 ring-emerald-100">{external.runId}</span>
          )}
        </div>
      </div>
      {(external.modelPath || external.runDir) && (
        <div className="mt-3 grid gap-2 text-xs text-slate-600 lg:grid-cols-2">
          {external.modelPath && (
            <ExternalPath label={t('pathScientist.labels.model')} value={external.modelPath} />
          )}
          {external.runDir && (
            <ExternalPath label={t('pathScientist.labels.runDir')} value={external.runDir} />
          )}
        </div>
      )}
    </div>
  )
}

function ExternalPath({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-white/80 px-3 py-2 ring-1 ring-emerald-100">
      <p className="text-[10px] font-black uppercase tracking-wider text-emerald-700">{label}</p>
      <p className="mt-1 truncate font-semibold text-slate-700" title={value}>{value}</p>
    </div>
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
