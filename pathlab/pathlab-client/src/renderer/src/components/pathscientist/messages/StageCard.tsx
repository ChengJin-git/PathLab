import { BookOpen, CheckCircle2, ChevronDown, Circle, Clock3, Database, ExternalLink, Loader2, XCircle } from 'lucide-react'
import { cn } from '../../../lib/utils'
import { usePathScientistTranslation } from '../../../lib/usePathScientistTranslation'
import {
  pathScientistCountLabel,
  pathScientistStageLabel,
  pathScientistStageStatusLabel,
  pathScientistStatusLabel,
} from '../../../lib/pathscientistI18n'
import type {
  PathScientistAcquisitionView,
  PathScientistDownloadProgressView,
  PathScientistGroundingView,
  PathScientistStageView,
} from '../../../lib/pathscientistEventSelectors'

interface StageCardProps {
  stage: PathScientistStageView
  grounding?: PathScientistGroundingView | null
  acquisition?: PathScientistAcquisitionView | null
  className?: string
}

function iconFor(stage: PathScientistStageView) {
  if (stage.status === 'complete') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (stage.status === 'error') return <XCircle className="h-4 w-4 text-red-600" />
  if (stage.status === 'current') return <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
  return <Circle className="h-4 w-4 text-gray-400" />
}

function stageDurationText(stage: PathScientistStageView): string | null {
  return stage.durationLabel && stage.durationLabel !== '--' ? stage.durationLabel : null
}

function taskProfileLabel(grounding: PathScientistGroundingView, notDetected: string): string {
  const profile = grounding.taskProfile
  const scope = profile.assetLevel ? `${profile.assetLevel}-level` : ''
  const target = profile.predictionTarget || profile.taskType || ''
  return [scope, target].filter(Boolean).join(' ') || notDetected
}

function paperMeta(source?: string, year?: string): string {
  return [source, year].filter(Boolean).join(' · ')
}

function compactMeta(...parts: string[]): string {
  return parts.map((part) => part.trim()).filter(Boolean).join(' · ')
}

function formatBytes(value: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let amount = Math.max(0, Number.isFinite(value) ? value : 0)
  for (const unit of units) {
    if (amount < 1024 || unit === units[units.length - 1]) {
      return `${amount.toFixed(1)}${unit}`
    }
    amount /= 1024
  }
  return '0.0B'
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return ''
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}

function DownloadProgressDetails({ progress }: { progress: PathScientistDownloadProgressView }) {
  const { t } = usePathScientistTranslation()
  const hasTotal = progress.bytesTotal > 0
  const bytesLabel = hasTotal
    ? `${formatBytes(progress.downloadedBytes)} / ${formatBytes(progress.bytesTotal)}`
    : t('pathScientist.download.downloaded', { value: formatBytes(progress.downloadedBytes) })
  const speedLabel = progress.speedBps > 0 ? `${formatBytes(progress.speedBps)}/s` : ''
  const etaLabel = progress.etaSeconds !== null ? t('pathScientist.download.eta', { duration: formatDuration(progress.etaSeconds) }) : ''
  const percent = progress.percent ?? 0

  return (
    <div
      className="rounded-2xl border border-emerald-100 bg-white p-3 ring-1 ring-emerald-50"
      data-testid="pathscientist-download-progress"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-black uppercase tracking-wider text-emerald-700">{t('pathScientist.download.title')}</p>
          <p className="mt-1 text-sm font-extrabold text-gray-950">
            {progress.datasetId || progress.provider || t('pathScientist.download.datasetDownload')}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-black uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-100">
          {progress.status === 'downloading' && <Loader2 className="h-3 w-3 animate-spin" />}
          {pathScientistStatusLabel(progress.status || 'download', t)}
        </span>
      </div>

      <div className="mt-3">
        <div className="mb-1.5 flex items-center justify-between gap-3 text-xs font-extrabold text-gray-700">
          <span>{bytesLabel}</span>
          <span>{hasTotal ? `${percent}%` : t('pathScientist.download.totalSizeUnknown')}</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-emerald-100">
          {hasTotal ? (
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${percent}%` }}
            />
          ) : (
            <div className="h-full w-1/2 animate-pulse rounded-full bg-emerald-500" />
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs font-bold">
        {speedLabel && (
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-800 ring-1 ring-emerald-100">
            {speedLabel}
          </span>
        )}
        {etaLabel && (
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-800 ring-1 ring-emerald-100">
            {etaLabel}
          </span>
        )}
        {progress.currentFile && (
          <span className="rounded-full bg-gray-50 px-2.5 py-1 text-gray-700 ring-1 ring-gray-100">
            {progress.currentFile}
          </span>
        )}
      </div>

      {progress.reason && (
        <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800 ring-1 ring-amber-100">
          {progress.reason}
        </p>
      )}
    </div>
  )
}

function DownloadProgressMini({ progress }: { progress: PathScientistDownloadProgressView }) {
  const { t } = usePathScientistTranslation()
  const hasTotal = progress.bytesTotal > 0
  const percent = progress.percent ?? 0
  const speedLabel = progress.speedBps > 0 ? `${formatBytes(progress.speedBps)}/s` : ''
  const primary = hasTotal
    ? `${percent}% · ${formatBytes(progress.downloadedBytes)} / ${formatBytes(progress.bytesTotal)}`
    : t('pathScientist.download.downloaded', { value: formatBytes(progress.downloadedBytes) })
  const secondary = hasTotal ? speedLabel : [t('pathScientist.download.totalSizeUnknownLower'), speedLabel].filter(Boolean).join(' · ')

  return (
    <div
      className="mt-3 rounded-2xl border border-emerald-100 bg-emerald-50/70 p-3"
      data-testid="pathscientist-download-progress-mini"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs font-extrabold">
        <span className="text-emerald-800">{primary}</span>
        {secondary && <span className="text-emerald-700">{secondary}</span>}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white ring-1 ring-emerald-100">
        {hasTotal ? (
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="h-full w-1/2 animate-pulse rounded-full bg-emerald-500" />
        )}
      </div>
    </div>
  )
}

function GroundingDetails({ grounding }: { grounding: PathScientistGroundingView }) {
  const { t } = usePathScientistTranslation()
  const paperCount = grounding.literatureCount
  const visiblePapers = grounding.papers.slice(0, 5)
  return (
    <details
      className="group mt-4 rounded-2xl border border-blue-100 bg-blue-50/60 p-3"
      data-testid="pathscientist-grounding-disclosure"
    >
      <summary
        className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 [&::-webkit-details-marker]:hidden"
        data-testid="pathscientist-grounding-summary"
      >
        <div className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-wider text-blue-700">
          <BookOpen className="h-3.5 w-3.5" />
          <span>{t('pathScientist.grounding.title')}</span>
        </div>
        <span className="inline-flex items-center gap-2">
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-extrabold text-blue-700 ring-1 ring-blue-100">
            {pathScientistCountLabel(
              paperCount,
              'pathScientist.grounding.paperFound',
              'pathScientist.grounding.papersFound',
              t,
              'paper found',
              'papers found',
            )}
          </span>
          <ChevronDown className="h-4 w-4 text-blue-600 transition group-open:rotate-180" />
        </span>
      </summary>

      <div className="mt-3 space-y-3">
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <div className="rounded-xl bg-white/80 p-2 ring-1 ring-blue-100">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.grounding.taskProfile')}</p>
            <p className="mt-1 font-extrabold text-gray-900">{taskProfileLabel(grounding, t('pathScientist.common.notDetected'))}</p>
          </div>
          <div className="rounded-xl bg-white/80 p-2 ring-1 ring-blue-100">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.grounding.selectedSkill')}</p>
            <p className="mt-1 font-extrabold text-gray-900">{grounding.selectedSkill || t('pathScientist.common.notDetected')}</p>
          </div>
        </div>

        {(grounding.providers.length > 0 || grounding.sotaStatusLabel) && (
          <div className="flex flex-wrap gap-2 text-xs font-bold">
            {grounding.providers.length > 0 && (
              <span className="rounded-full bg-white px-2.5 py-1 text-gray-600 ring-1 ring-blue-100">
                {grounding.providers.join(', ')}
              </span>
            )}
            {grounding.sotaStatusLabel && (
              <span className="rounded-full bg-white px-2.5 py-1 text-gray-600 ring-1 ring-blue-100">
                {grounding.sotaStatusLabel}
              </span>
            )}
          </div>
        )}

        {visiblePapers.length > 0 ? (
          <div className="space-y-2">
            {visiblePapers.map((paper) => {
              const meta = paperMeta(paper.source || paper.provider, paper.year)
              return (
                <div key={`${paper.id}:${paper.title}`} className="rounded-xl bg-white p-3 ring-1 ring-blue-100">
                  {paper.url ? (
                    <a
                      href={paper.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-start gap-1.5 text-sm font-extrabold leading-5 text-gray-950 hover:text-blue-700"
                    >
                      <span>{paper.title}</span>
                      <ExternalLink className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                    </a>
                  ) : (
                    <p className="text-sm font-extrabold leading-5 text-gray-950">{paper.title}</p>
                  )}
                  {meta && <p className="mt-1 text-xs font-semibold text-gray-500">{meta}</p>}
                </div>
              )
            })}
          </div>
        ) : (
          <p className="rounded-xl bg-white p-3 text-sm font-semibold text-gray-500 ring-1 ring-blue-100">
            {t('pathScientist.grounding.noPapers')}
          </p>
        )}
      </div>
    </details>
  )
}

function AcquisitionDetails({ acquisition }: { acquisition: PathScientistAcquisitionView }) {
  const { t } = usePathScientistTranslation()
  const datasetMeta = acquisition.selectedDataset
    ? compactMeta(acquisition.selectedDataset.provider, acquisition.selectedDataset.access)
    : ''
  return (
    <details
      className="group mt-4 rounded-2xl border border-emerald-100 bg-emerald-50/60 p-3"
      data-testid="pathscientist-acquisition-disclosure"
    >
      <summary
        className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 [&::-webkit-details-marker]:hidden"
        data-testid="pathscientist-acquisition-summary"
      >
        <div className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-wider text-emerald-700">
          <Database className="h-3.5 w-3.5" />
          <span>{t('pathScientist.acquisition.title')}</span>
        </div>
        <span className="inline-flex items-center gap-2">
          <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-extrabold text-emerald-700 ring-1 ring-emerald-100">
            {acquisition.readinessStatus || acquisition.status || acquisition.planStatus || t('pathScientist.acquisition.dataStatus')}
          </span>
          <ChevronDown className="h-4 w-4 text-emerald-600 transition group-open:rotate-180" />
        </span>
      </summary>

      <div className="mt-3 space-y-3">
        {acquisition.downloadProgress && (
          <DownloadProgressDetails progress={acquisition.downloadProgress} />
        )}

        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <div className="rounded-xl bg-white/80 p-2 ring-1 ring-emerald-100">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.acquisition.dataset')}</p>
            <p className="mt-1 font-extrabold text-gray-900">
              {acquisition.selectedDataset?.name || t('pathScientist.common.notDetected')}
            </p>
            {datasetMeta && <p className="mt-1 font-semibold text-gray-500">{datasetMeta}</p>}
          </div>
          <div className="rounded-xl bg-white/80 p-2 ring-1 ring-emerald-100">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.acquisition.readiness')}</p>
            <p className="mt-1 font-extrabold text-gray-900">{acquisition.readinessStatus || t('pathScientist.common.notDetected')}</p>
            {acquisition.datasetCandidateCount > 0 && (
              <p className="mt-1 font-semibold text-gray-500">{t('pathScientist.acquisition.candidatesChecked', { count: acquisition.datasetCandidateCount })}</p>
            )}
          </div>
        </div>

        {(acquisition.status || acquisition.planStatus || acquisition.notes) && (
          <div className="flex flex-wrap gap-2 text-xs font-bold">
            {acquisition.status && (
              <span className="rounded-full bg-white px-2.5 py-1 text-gray-600 ring-1 ring-emerald-100">
                {t('pathScientist.acquisition.acquisitionStatus', { status: acquisition.status })}
              </span>
            )}
            {acquisition.planStatus && (
              <span className="rounded-full bg-white px-2.5 py-1 text-gray-600 ring-1 ring-emerald-100">
                {t('pathScientist.acquisition.planStatus', { status: acquisition.planStatus })}
              </span>
            )}
            {acquisition.notes && (
              <span className="rounded-full bg-white px-2.5 py-1 text-gray-600 ring-1 ring-emerald-100">
                {acquisition.notes}
              </span>
            )}
          </div>
        )}

        {acquisition.missing.length > 0 && (
          <p className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs font-bold text-amber-800">
            {t('pathScientist.acquisition.missing', { items: acquisition.missing.join(', ') })}
          </p>
        )}

        {acquisition.paths.length > 0 && (
          <div className="space-y-2">
            {acquisition.paths.map((path) => (
              <div key={`${path.label}:${path.value}`} className="rounded-xl bg-white p-3 ring-1 ring-emerald-100">
                <p className="text-[11px] font-black uppercase tracking-wider text-gray-400">{path.label}</p>
                <p className="mt-1 break-all text-xs font-bold leading-5 text-gray-800">{path.value}</p>
              </div>
            ))}
          </div>
        )}

        {acquisition.manifestPath && (
          <div className="rounded-xl bg-white p-3 ring-1 ring-emerald-100">
            <p className="text-[11px] font-black uppercase tracking-wider text-gray-400">{t('pathScientist.acquisition.manifest')}</p>
            <p className="mt-1 break-all text-xs font-bold leading-5 text-gray-800">{acquisition.manifestPath}</p>
          </div>
        )}

        {acquisition.planSteps.length > 0 && (
          <div className="space-y-2">
            {acquisition.planSteps.map((step, index) => (
              <div key={step.id} className="rounded-xl bg-white p-3 ring-1 ring-emerald-100">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-extrabold leading-5 text-gray-950">{step.title}</p>
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-black uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-100">
                    {step.isCurrent ? t('pathScientist.acquisition.currentStep') : t('pathScientist.acquisition.stepNumber', { step: index + 1 })}
                  </span>
                </div>
                {step.skill && <p className="mt-1 text-xs font-semibold text-gray-500">{step.skill}</p>}
              </div>
            ))}
          </div>
        )}

        {acquisition.planNotes.length > 0 && (
          <div className="space-y-1.5">
            {acquisition.planNotes.map((note) => (
              <p key={note} className="rounded-xl bg-white/80 px-3 py-2 text-xs font-semibold leading-5 text-gray-600 ring-1 ring-emerald-100">
                {note}
              </p>
            ))}
          </div>
        )}
      </div>
    </details>
  )
}

export default function StageCard({ stage, grounding, acquisition, className }: StageCardProps) {
  const { t } = usePathScientistTranslation()
  const showGroundingDetails = stage.id === 'grounding' && grounding !== null && grounding !== undefined
  const showAcquisitionDetails = stage.id === 'acquisition' && acquisition !== null && acquisition !== undefined
  const duration = stageDurationText(stage)
  const isPending = stage.status === 'pending'
  return (
    <div
      className={cn(
        'rounded-2xl border border-gray-200 bg-white p-4 shadow-sm',
        isPending && 'border-gray-100 bg-gray-50/60',
        className,
      )}
      data-testid={`pathscientist-stage-card-${stage.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={cn(
            'mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl ring-1',
            stage.status === 'complete' ? 'bg-emerald-50 ring-emerald-100' : 'bg-gray-50 ring-gray-100',
          )}
          >
            {iconFor(stage)}
          </span>
          <div className="min-w-0">
            <p className={cn('text-sm font-extrabold', isPending ? 'text-gray-500' : 'text-gray-950')}>{pathScientistStageLabel(stage.id, t)}</p>
            <p className="mt-1 truncate text-xs leading-5 text-gray-500">{stage.summary || t('pathScientist.count.events', { count: stage.eventCount })}</p>
            {duration && (
              <p
                className="mt-1.5 inline-flex items-center gap-1 text-xs font-bold text-gray-500"
                data-testid={`pathscientist-stage-duration-${stage.id}`}
              >
                <Clock3 className="h-3 w-3" />
                <span>{duration}</span>
              </p>
            )}
          </div>
        </div>
        <span className={cn(
          'rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider ring-1',
          stage.status === 'complete' && 'bg-emerald-50 text-emerald-700 ring-emerald-100',
          stage.status === 'current' && 'bg-gray-100 text-gray-500 ring-gray-200',
          stage.status === 'error' && 'bg-red-50 text-red-700 ring-red-100',
          isPending && 'bg-gray-100 text-gray-400 ring-gray-200',
        )}
        >
          {pathScientistStageStatusLabel(stage.status, t)}
        </span>
      </div>
      {stage.id === 'acquisition' && acquisition?.downloadProgress && (
        <DownloadProgressMini progress={acquisition.downloadProgress} />
      )}
      {showGroundingDetails && <GroundingDetails grounding={grounding} />}
      {showAcquisitionDetails && <AcquisitionDetails acquisition={acquisition} />}
    </div>
  )
}
