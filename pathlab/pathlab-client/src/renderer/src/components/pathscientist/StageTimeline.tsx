import { Check, Circle, Clock3, Loader2, XCircle } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PathScientistStageStatus, PathScientistStageView } from '../../lib/pathscientistEventSelectors'

interface StageTimelineProps {
  stages: PathScientistStageView[]
  currentIteration?: number | null
  maxIterations?: number | null
  className?: string
<<<<<<< HEAD
=======
  embedded?: boolean
>>>>>>> auto-frontend/main
}

function statusIcon(status: PathScientistStageStatus) {
  if (status === 'complete') return <Check className="h-3.5 w-3.5" />
  if (status === 'error') return <XCircle className="h-3.5 w-3.5" />
  if (status === 'current') return <Loader2 className="h-3.5 w-3.5 animate-spin" />
  return <Circle className="h-3.5 w-3.5" />
}

function statusLabel(status: PathScientistStageStatus) {
  if (status === 'complete') return 'done'
  if (status === 'error') return 'needs attention'
  if (status === 'current') return 'running'
  return 'pending'
}

function statusClasses(status: PathScientistStageStatus) {
  switch (status) {
    case 'complete':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700 ring-emerald-100'
    case 'error':
      return 'border-red-200 bg-red-50 text-red-700 ring-red-100'
    case 'current':
      return 'border-blue-200 bg-blue-50 text-blue-700 ring-blue-100 shadow-sm shadow-blue-500/10'
    default:
      return 'border-gray-200 bg-white text-gray-400 ring-gray-100'
  }
}

<<<<<<< HEAD
export default function StageTimeline({ stages, currentIteration, maxIterations, className }: StageTimelineProps) {
=======
export default function StageTimeline({
  stages,
  currentIteration,
  maxIterations,
  className,
  embedded = false,
}: StageTimelineProps) {
>>>>>>> auto-frontend/main
  const showIteration = typeof currentIteration === 'number' && currentIteration > 0
  const iterLabel = showIteration
    ? maxIterations && maxIterations > 0
      ? `iter ${currentIteration}/${maxIterations}`
      : `iter ${currentIteration}`
    : ''

<<<<<<< HEAD
  return (
    <section aria-label="Stage timeline" className={cn('rounded-3xl border border-gray-200 bg-white p-4 shadow-sm', className)}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">Stage timeline</p>
          <p className="mt-1 text-sm text-gray-500">Compressed view of the PathScientist research pipeline.</p>
        </div>
        {iterLabel && <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-bold text-white shadow-sm">{iterLabel}</span>}
      </div>

      <ol className="flex gap-2 overflow-x-auto pb-1" role="list">
=======
  const timeline = (
    <ol className="flex gap-2 overflow-x-auto pb-1" role="list">
>>>>>>> auto-frontend/main
        {stages.map((stage, index) => (
          <li key={stage.id} className="min-w-[128px] flex-1">
            <div
              aria-current={stage.status === 'current' ? 'step' : undefined}
              className={cn('h-full rounded-2xl border px-3 py-3 ring-1 transition', statusClasses(stage.status))}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/80 ring-1 ring-current/10">
                  {statusIcon(stage.status)}
                </span>
                <span className="text-[10px] font-black uppercase tracking-wider opacity-70">{String(index + 1).padStart(2, '0')}</span>
              </div>
              <p className="mt-3 truncate text-sm font-extrabold text-gray-950">{stage.label}</p>
              <div className="mt-2 flex items-center justify-between gap-2 text-[11px] font-semibold">
                <span className="truncate">{statusLabel(stage.status)}</span>
                {stage.eventCount > 0 && <span className="rounded-full bg-white/75 px-2 py-0.5 text-gray-500 ring-1 ring-black/5">{stage.eventCount}</span>}
              </div>
              <div className="mt-2 flex items-center gap-1.5 text-[11px] font-bold text-gray-500">
                <Clock3 className="h-3 w-3" />
                <span>{stage.durationLabel}</span>
              </div>
            </div>
          </li>
        ))}
<<<<<<< HEAD
      </ol>
=======
    </ol>
  )

  if (embedded) {
    return (
      <div aria-label="Stage timeline" className={cn('border-b border-gray-100 pb-4', className)} data-testid="pathscientist-stage-timeline-embedded">
        {iterLabel && (
          <div className="mb-3 flex justify-end">
            <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-bold text-white shadow-sm">{iterLabel}</span>
          </div>
        )}
        {timeline}
      </div>
    )
  }

  return (
    <section aria-label="Stage timeline" className={cn('rounded-3xl border border-gray-200 bg-white p-4 shadow-sm', className)}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">Stage timeline</p>
          <p className="mt-1 text-sm text-gray-500">Compressed view of the PathScientist research pipeline.</p>
        </div>
        {iterLabel && <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-bold text-white shadow-sm">{iterLabel}</span>}
      </div>
      {timeline}
>>>>>>> auto-frontend/main
    </section>
  )
}
