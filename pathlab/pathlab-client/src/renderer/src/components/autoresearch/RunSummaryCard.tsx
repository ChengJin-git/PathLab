import { Activity, BarChart3, CheckCircle2, Clock3, Cpu, Layers3, ShieldCheck, Trophy, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'
import { useAutoResearchTranslation } from '../../lib/useAutoResearchTranslation'
import { autoResearchStatusLabel } from '../../lib/autoresearchI18n'
import type { AutoResearchRunSummaryView } from '../../lib/autoresearchEventSelectors'

interface RunSummaryCardProps {
  summary: AutoResearchRunSummaryView
  compactHeader?: boolean
  className?: string
}

function formatMetric(summary: AutoResearchRunSummaryView) {
  const metric = summary.bestMetric
  if (!metric) return '--'
  const value = typeof metric.value === 'number'
    ? (metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3))
    : '--'
  return `${metric.name.toUpperCase()} ${value}`
}

function formatExternalMetric(summary: AutoResearchRunSummaryView) {
  const metric = summary.externalTest?.primaryMetric
  if (!metric) return '--'
  const value = typeof metric.value === 'number'
    ? (metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3))
    : '--'
  return `${metric.name.toUpperCase()} ${value}`
}

function formatInternalMetric(summary: AutoResearchRunSummaryView) {
  const metric = summary.internalTest?.primaryMetric
  if (!metric) return '--'
  const value = typeof metric.value === 'number'
    ? (metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3))
    : '--'
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
  const { t } = useAutoResearchTranslation()
  const metadata = summary.sessionMetadata
  const showStageBadge = !isRedundantStageBadge(summary.status, summary.stage)

  return (
    <section
      className={cn(
        'rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-50 via-white to-blue-50/60 p-4 shadow-sm sm:p-5',
        className,
      )}
      data-testid="autoresearch-summary-card"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">{t('autoResearch.runSummary.title')}</p>
          {!compactHeader && (
            <>
              <h2 className="mt-1 truncate text-xl font-black tracking-tight text-slate-950">{summary.title}</h2>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-500">{summary.narrative.brief}</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-bold text-white">{autoResearchStatusLabel(summary.status, t)}</span>
          {showStageBadge && (
            <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-600 ring-1 ring-slate-200">{summary.stage}</span>
          )}
          {!compactHeader && summary.narrative.source === 'llm' && (
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
              {t('autoResearch.runSummary.llmSummary')}
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <NarrativeBlock label={t('autoResearch.runSummary.userRequest')} value={summary.narrative.userRequest} />
        <NarrativeBlock label={t('autoResearch.runSummary.agentWork')} value={summary.narrative.agentActions} />
        <NarrativeBlock label={t('autoResearch.runSummary.result')} value={summary.narrative.result} />
      </div>

      {(summary.internalTest || summary.externalTest) && (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {summary.internalTest && (
            <InternalTestSummary summary={summary} />
          )}
          {summary.externalTest && (
            <ExternalValidationSummary summary={summary} />
          )}
        </div>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryTile icon={<Clock3 className="h-4 w-4" />} label={t('autoResearch.labels.duration')} value={summary.totalDurationLabel} />
        <SummaryTile icon={<Activity className="h-4 w-4" />} label={t('autoResearch.labels.events')} value={t('autoResearch.count.events', { count: summary.eventCount })} />
        <SummaryTile icon={<Wrench className="h-4 w-4" />} label={t('autoResearch.labels.tools')} value={t('autoResearch.count.tools', { count: summary.toolCallCount })} />
        <SummaryTile icon={<Layers3 className="h-4 w-4" />} label={t('autoResearch.labels.iterations')} value={t('autoResearch.count.iterations', { count: summary.iterationCount })} />
        <SummaryTile icon={<Trophy className="h-4 w-4" />} label={t('autoResearch.labels.bestMetric')} value={formatMetric(summary)} />
        <SummaryTile icon={<BarChart3 className="h-4 w-4" />} label={t('autoResearch.labels.task')} value={metadata.taskType} />
        <SummaryTile icon={<Cpu className="h-4 w-4" />} label={t('autoResearch.labels.foundation')} value={metadata.foundationModel} />
        {metadata.milMethod && (
          <SummaryTile icon={<Layers3 className="h-4 w-4" />} label="MIL" value={metadata.milMethod} />
        )}
      </div>
    </section>
  )
}

function InternalTestSummary({ summary }: { summary: AutoResearchRunSummaryView }) {
  const { t } = useAutoResearchTranslation()
  const internal = summary.internalTest
  if (!internal) return null
  const status = internal.status || (internal.committed ? 'completed' : 'recorded')
  const samples = internal.sampleCount === null ? '--' : t('autoResearch.count.samples', { count: internal.sampleCount })

  return (
    <div
      className="rounded-2xl border border-sky-200 bg-sky-50/70 p-3 ring-1 ring-sky-100"
      data-testid="autoresearch-internal-summary"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-sky-700">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {t('autoResearch.runSummary.internalTest')}
          </p>
          <p className="mt-1 text-lg font-black text-slate-950">{formatInternalMetric(summary)}</p>
          {internal.datasetName && (
            <p className="mt-1 max-w-full truncate text-xs font-extrabold text-sky-700/80" title={internal.datasetName}>
              {internal.datasetName}
            </p>
          )}
        </div>
        <div
          className="flex flex-col items-end gap-2 text-[11px] font-bold sm:items-end"
          data-testid="autoresearch-internal-summary-badges"
        >
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/85 px-2.5 py-1 text-sky-700 ring-1 ring-sky-200">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {autoResearchStatusLabel(status, t)}
          </span>
          <span className="rounded-full bg-white/85 px-2.5 py-1 text-slate-600 ring-1 ring-sky-100">{samples}</span>
        </div>
      </div>
    </div>
  )
}

function ExternalValidationSummary({ summary }: { summary: AutoResearchRunSummaryView }) {
  const { t } = useAutoResearchTranslation()
  const external = summary.externalTest
  if (!external) return null
  const status = external.status || (external.committed ? 'completed' : 'recorded')
  const samples = external.sampleCount === null ? '--' : t('autoResearch.count.samples', { count: external.sampleCount })

  return (
    <div
      className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-3 ring-1 ring-emerald-100"
      data-testid="autoresearch-external-summary"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-emerald-700">
            <ShieldCheck className="h-3.5 w-3.5" />
            {t('autoResearch.runSummary.externalValidation')}
          </p>
          <p className="mt-1 text-lg font-black text-slate-950">{formatExternalMetric(summary)}</p>
          {external.datasetName && (
            <p className="mt-1 max-w-full truncate text-xs font-extrabold text-emerald-700/80" title={external.datasetName}>
              {external.datasetName}
            </p>
          )}
        </div>
        <div
          className="flex flex-col items-end gap-2 text-[11px] font-bold sm:items-end"
          data-testid="autoresearch-external-summary-badges"
        >
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/85 px-2.5 py-1 text-emerald-700 ring-1 ring-emerald-200">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {autoResearchStatusLabel(status, t)}
          </span>
          <span className="rounded-full bg-white/85 px-2.5 py-1 text-slate-600 ring-1 ring-emerald-100">{samples}</span>
        </div>
      </div>
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
