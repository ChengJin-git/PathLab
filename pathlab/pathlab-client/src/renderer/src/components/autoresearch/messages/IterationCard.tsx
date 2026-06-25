import { useState } from 'react'
import { BarChart3, ChevronDown, Loader2 } from 'lucide-react'
import { cn } from '../../../lib/utils'
import { useAutoResearchTranslation } from '../../../lib/useAutoResearchTranslation'
import {
  autoResearchIterationLabel,
  autoResearchIterationStatusLabel,
} from '../../../lib/autoresearchI18n'
import type {
  AutoResearchIterationView,
  AutoResearchSessionMetadataView,
} from '../../../lib/autoresearchEventSelectors'
import ToolCard from '../ToolCard'

interface IterationCardProps {
  iteration: AutoResearchIterationView
  sessionMetadata: AutoResearchSessionMetadataView
  isCurrentRunning?: boolean
  className?: string
}

function statusTone(status: string) {
  if (status === 'success') return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  if (status === 'error') return 'bg-red-50 text-red-700 ring-red-100'
  if (status === 'running') return 'bg-blue-50 text-blue-700 ring-blue-100'
  return 'bg-gray-50 text-gray-600 ring-gray-100'
}

function statusLabel(iteration: AutoResearchIterationView) {
  if (iteration.committed) return 'committed'
  if (iteration.runId || typeof iteration.metricValue === 'number') return 'not committed'
  return iteration.status
}

function MetadataBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[11px] font-bold text-slate-600 ring-1 ring-slate-100">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-800">{value}</span>
    </span>
  )
}

export default function IterationCard({ iteration, sessionMetadata, isCurrentRunning = false, className }: IterationCardProps) {
  const { t } = useAutoResearchTranslation()
  const showRunning = isCurrentRunning || iteration.status === 'running'
  const [open, setOpen] = useState(false)
  const showMilMethod = sessionMetadata.taskType.startsWith('slide-level') && Boolean(sessionMetadata.milMethod)

  return (
    <details
      className={cn(
        'group rounded-3xl border bg-white shadow-sm',
        showRunning ? 'border-blue-200 shadow-blue-500/10 ring-1 ring-blue-100' : 'border-gray-200',
        className,
      )}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-testid={`autoresearch-iteration-${iteration.index}`}
    >
      <summary
        className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-4 py-4"
        data-testid={`autoresearch-iteration-summary-${iteration.index}`}
      >
        <div>
          <h3 className="text-base font-extrabold text-gray-950">{autoResearchIterationLabel(iteration.index, t)}</h3>
          <p className="mt-1 text-xs text-gray-500">
            {showRunning
              ? t('autoResearch.iteration.runningToolCalls', { count: iteration.tools.length })
              : t('autoResearch.iteration.toolCalls', { count: iteration.tools.length })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MetadataBadge label={t('autoResearch.labels.foundationModel')} value={sessionMetadata.foundationModel} />
          {showMilMethod && sessionMetadata.milMethod && (
            <MetadataBadge label={t('autoResearch.labels.milMethod')} value={sessionMetadata.milMethod} />
          )}
          {showRunning && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-blue-700 ring-1 ring-blue-100">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('autoResearch.iteration.runningStatus')}
            </span>
          )}
          {!showRunning && (
            <span className={cn('rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider ring-1', statusTone(iteration.status))}>
              {autoResearchIterationStatusLabel(statusLabel(iteration), t)}
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-50 px-2.5 py-1 text-[11px] font-bold text-gray-600 ring-1 ring-gray-100">
            <BarChart3 className="h-3.5 w-3.5" /> {iteration.metricName || 'metric'} {typeof iteration.metricValue === 'number' ? iteration.metricValue.toFixed(3) : '--'}
          </span>
          <ChevronDown className="h-4 w-4 text-gray-400 transition group-open:rotate-180" />
        </div>
      </summary>

      <div className="border-t border-gray-100 px-4 pb-4 pt-3">
        {iteration.tools.length === 0 ? (
          <p className={cn(
            'rounded-2xl border border-dashed p-4 text-sm',
            showRunning ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-gray-200 bg-gray-50 text-gray-500',
          )}>
            {showRunning
              ? t('autoResearch.iteration.waitingNextTool')
              : t('autoResearch.iteration.noToolCalls')}
          </p>
        ) : (
          <div className="space-y-2">
            {iteration.tools.map((tool) => (
              <ToolCard key={tool.id} tool={tool} />
            ))}
          </div>
        )}
      </div>
    </details>
  )
}
