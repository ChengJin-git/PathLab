import { Activity, BarChart3, Download, Loader2, Trophy, Wrench } from 'lucide-react'
import { downloadAutoResearchRun } from '../../api/autoresearch'
import { cn } from '../../lib/utils'
import { useAutoResearchTranslation } from '../../lib/useAutoResearchTranslation'
import {
  autoResearchIterationLabel,
  autoResearchIterationStatusLabel,
  autoResearchRunningIterationLabel,
} from '../../lib/autoresearchI18n'
import { trainingProgressEpochLabel, trainingProgressMetricLabels } from '../../lib/autoresearchSessions'
import type {
  AutoResearchIterationView,
  AutoResearchMetricView,
  AutoResearchSessionMetadataView,
  AutoResearchToolView,
} from '../../lib/autoresearchEventSelectors'
import type { AutoResearchTrainingProgress } from '../../types/autoresearch'

const MAX_VISIBLE_TOOLS = 4

interface IterationLadderProps {
  iterations: AutoResearchIterationView[]
  bestMetric: AutoResearchMetricView | null
  sessionMetadata: AutoResearchSessionMetadataView
  toolCards: AutoResearchToolView[]
  sessionId?: string
  currentIteration?: number | null
  maxIterations?: number | null
  isRunning?: boolean
  trainingProgress?: AutoResearchTrainingProgress | null
  variant?: 'default' | 'clinical'
  className?: string
}

function formatMetric(metric: AutoResearchMetricView | null) {
  if (!metric || typeof metric.value !== 'number') return '--'
  return metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3)
}

function formatMetricName(metric: AutoResearchMetricView | null) {
  return metric?.name ? metric.name.toUpperCase() : 'METRIC'
}

function iterationTone(status: string) {
  if (status === 'success') return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  if (status === 'error') return 'bg-red-50 text-red-700 ring-red-100'
  if (status === 'running') return 'bg-blue-50 text-blue-700 ring-blue-100'
  return 'bg-gray-50 text-gray-600 ring-gray-100'
}

function iterationStatusLabel(iteration: AutoResearchIterationView) {
  if (iteration.committed) return 'committed'
  if (iteration.runId || typeof iteration.metricValue === 'number') return 'not committed'
  return iteration.status
}

function countTools(toolCards: AutoResearchToolView[]) {
  return toolCards.reduce<Record<string, number>>((acc, tool) => {
    acc[tool.tool] = (acc[tool.tool] || 0) + 1
    return acc
  }, {})
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white/75 p-3 ring-1 ring-blue-100">
      <p className="text-[11px] font-black uppercase tracking-wider text-blue-700">{label}</p>
      <p className="mt-1 text-sm font-extrabold text-gray-950">{value}</p>
    </div>
  )
}

export default function IterationLadder({
  iterations,
  bestMetric,
  sessionMetadata,
  toolCards,
  sessionId,
  currentIteration,
  maxIterations,
  isRunning = false,
  trainingProgress,
  variant = 'default',
  className,
}: IterationLadderProps) {
  const { t } = useAutoResearchTranslation()
  const isClinical = variant === 'clinical'
  const toolCounts = Object.entries(countTools(toolCards)).sort((a, b) => b[1] - a[1])
  const visibleToolCounts = toolCounts.slice(0, MAX_VISIBLE_TOOLS)
  const hiddenToolCount = Math.max(0, toolCounts.length - visibleToolCounts.length)
  const showMilMethod = sessionMetadata.taskType.startsWith('slide-level')
  const showRunning = isRunning && typeof currentIteration === 'number' && currentIteration > 0
  const hasCurrentIteration = showRunning && iterations.some((iteration) => iteration.index === currentIteration)
  const showRunningPlaceholder = showRunning && !hasCurrentIteration
  const liveLabel = showRunning ? autoResearchRunningIterationLabel(currentIteration, maxIterations, t) : ''
  const trainingEpochLabel = trainingProgressEpochLabel(trainingProgress)
  const trainingMetricLabels = trainingProgressMetricLabels(trainingProgress)
  const ladderProgressLabel = [trainingEpochLabel, ...trainingMetricLabels].filter(Boolean).join(' · ')
  const downloadRun = async (runId: string) => {
    if (!sessionId) return
    try {
      await downloadAutoResearchRun(sessionId, runId)
    } catch (error) {
      console.error('AutoResearch run download failed:', error)
    }
  }

  return (
    <aside
      className={cn(
        'space-y-4 xl:flex xl:self-start xl:flex-col xl:gap-4 xl:space-y-0',
        className,
      )}
      data-testid="autoresearch-sidebar"
    >
      <section className={cn('flex-shrink-0 rounded-3xl border border-blue-100 bg-gradient-to-br from-blue-50 to-white p-5 shadow-sm', !isClinical && 'xl:flex-none')}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-bold uppercase tracking-wider text-blue-700">{t('autoResearch.iterationLadder.taskSetup')}</p>
          <Activity className="h-4 w-4 text-blue-600" />
        </div>
        <div className="mt-4 space-y-2">
          <MetadataRow label={t('autoResearch.labels.taskType')} value={sessionMetadata.taskType} />
          <MetadataRow label={t('autoResearch.labels.foundationModel')} value={sessionMetadata.foundationModel} />
          {showMilMethod && sessionMetadata.milMethod && (
            <MetadataRow label={t('autoResearch.labels.milMethod')} value={sessionMetadata.milMethod} />
          )}
        </div>
      </section>

      <section className={cn('flex-shrink-0 rounded-3xl border border-emerald-100 bg-gradient-to-br from-emerald-50 to-white p-5 shadow-sm', !isClinical && 'xl:flex-none')}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-700">{t('autoResearch.iterationLadder.bestSoFar')}</p>
          <Trophy className="h-4 w-4 text-emerald-600" />
        </div>
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-3xl font-black tracking-tight text-gray-950">{formatMetric(bestMetric)}</p>
          {sessionId && bestMetric?.runId && (() => {
            const runId = bestMetric.runId
            return (
            <button
              type="button"
              onClick={() => void downloadRun(runId)}
              aria-label={t('autoResearch.iterationLadder.downloadBestRun')}
              className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-extrabold text-emerald-700 ring-1 ring-emerald-100 transition hover:bg-emerald-50"
            >
              <Download className="h-3.5 w-3.5" />
              ZIP
            </button>
            )
          })()}
        </div>
        <p className="mt-1 truncate text-xs font-semibold text-gray-500">{formatMetricName(bestMetric)}{bestMetric?.runId ? t('autoResearch.iterationLadder.metricFromRun', { runId: bestMetric.runId }) : ''}</p>
      </section>

      <section
        className={cn(
          'flex min-h-[280px] flex-col overflow-hidden rounded-3xl border border-gray-200 bg-white p-5 shadow-sm',
          isClinical ? 'max-h-[360px]' : 'xl:min-h-[320px]',
        )}
        data-testid="autoresearch-iteration-ladder-card"
      >
        <div className="mb-4 flex flex-shrink-0 items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-extrabold text-gray-950">{t('autoResearch.iterationLadder.title')}</h2>
            <p className="mt-1 text-xs text-gray-500">{t('autoResearch.iterationLadder.description')}</p>
          </div>
          <BarChart3 className="h-4 w-4 text-gray-400" />
        </div>

        {showRunning && (
          <div
            className="mb-3 flex items-center justify-between gap-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-extrabold text-blue-700"
            data-testid="autoresearch-ladder-running-strip"
          >
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {liveLabel}
              {trainingEpochLabel && <span className="text-blue-500">· {trainingEpochLabel}</span>}
            </span>
            <span className="h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_0_4px_rgba(59,130,246,0.15)]" />
          </div>
        )}

        <div
          className={cn(
            'min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-1 custom-scrollbar',
          )}
          data-testid="autoresearch-iteration-ladder-scroll"
        >
        {iterations.length === 0 && !showRunningPlaceholder ? (
          <p className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">{t('autoResearch.iterationLadder.noIterations')}</p>
        ) : (
          <>
            {showRunningPlaceholder && (
              <div
                className="rounded-2xl border border-dashed border-blue-200 bg-blue-50/80 p-3 text-sm text-blue-700"
                data-testid="autoresearch-ladder-running-placeholder"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-extrabold">{autoResearchIterationLabel(currentIteration, t)}</span>
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
                <p className="mt-1 text-xs font-semibold text-blue-600">
                  {ladderProgressLabel || t('autoResearch.iterationLadder.waitingFirstEvent')}
                </p>
              </div>
            )}
            {iterations.map((iteration) => {
              const isCurrentRunning = showRunning && iteration.index === currentIteration
              const status = isCurrentRunning ? 'running' : iteration.status
              const statusLabel = autoResearchIterationStatusLabel(isCurrentRunning ? 'running' : iterationStatusLabel(iteration), t)

              return (
                <div
                  key={iteration.index}
                  className={cn(
                    'rounded-2xl border p-3',
                    isCurrentRunning
                      ? 'border-blue-200 bg-blue-50/70 ring-1 ring-blue-100'
                      : 'border-gray-100 bg-gray-50/70',
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-extrabold text-gray-950">{autoResearchIterationLabel(iteration.index, t)}</span>
                    <span className={cn('rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider ring-1', iterationTone(status))}>
                      {statusLabel}
                    </span>
                  </div>
                  {isCurrentRunning && (
                    <div className="mt-1 space-y-1">
                      <p className="inline-flex items-center gap-1.5 text-[11px] font-bold text-blue-700">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {t('autoResearch.iteration.runningBadge')}
                      </p>
                      {ladderProgressLabel && (
                        <p
                          className="w-fit rounded-full bg-white/85 px-2 py-0.5 text-[11px] font-extrabold text-sky-700 ring-1 ring-sky-100"
                          data-testid="autoresearch-ladder-training-progress"
                        >
                          {ladderProgressLabel}
                        </p>
                      )}
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between gap-3 text-xs text-gray-500">
                    <span>{iteration.metricName || bestMetric?.name || 'metric'}</span>
                    <strong className="font-extrabold text-gray-900">{typeof iteration.metricValue === 'number' ? iteration.metricValue.toFixed(3) : '--'}</strong>
                  </div>
                  {iteration.runId && (() => {
                    const runId = iteration.runId
                    return (
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="truncate text-[11px] font-medium text-gray-400">{runId}</p>
                      {sessionId && (
                        <button
                          type="button"
                          onClick={() => void downloadRun(runId)}
                          aria-label={t('autoResearch.iterationLadder.downloadIterationRun', { iteration: iteration.index })}
                          className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-[11px] font-extrabold text-blue-700 ring-1 ring-blue-100 transition hover:bg-blue-50"
                        >
                          <Download className="h-3 w-3" />
                          ZIP
                        </button>
                      )}
                    </div>
                    )
                  })()}
                </div>
              )
            })}
          </>
        )}
        </div>
      </section>

      <section
        className={cn(
          'flex flex-shrink-0 flex-col rounded-3xl border border-gray-200 bg-white p-5 shadow-sm',
          !isClinical && 'xl:flex-none',
        )}
        data-testid="autoresearch-tools-card"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-extrabold text-gray-950">{t('autoResearch.iterationLadder.toolsUsed')}</h2>
          <Wrench className="h-4 w-4 text-gray-400" />
        </div>
        {toolCounts.length === 0 ? (
          <p className="text-sm text-gray-500">{t('autoResearch.iterationLadder.noTools')}</p>
        ) : (
          <div className="space-y-2" data-testid="autoresearch-tools-list">
            {visibleToolCounts.map(([tool, count]) => (
              <div key={tool} className="flex items-center justify-between rounded-2xl bg-gray-50 px-3 py-2 text-sm ring-1 ring-gray-100">
                <span className="truncate font-semibold text-gray-700">{tool} x{count}</span>
                <Activity className="h-3.5 w-3.5 flex-shrink-0 text-gray-400" />
              </div>
            ))}
            {hiddenToolCount > 0 && (
              <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 px-3 py-2 text-center text-xs font-bold text-gray-500">
                {t('autoResearch.iterationLadder.moreTools', { count: hiddenToolCount })}
              </div>
            )}
          </div>
        )}
      </section>
    </aside>
  )
}
