import { CheckCircle2, CircleDashed, Loader2 } from 'lucide-react'
import type { RegenerateProgress } from '../../api/papers'
import { cn } from '../../lib/utils'

const STEPS: RegenerateProgress['step'][] = [
  'queued',
  'locating',
  'drafting',
  'guarding',
  'refining',
  'compiling',
  'finalizing',
]

interface RegenerateProgressBarProps {
  progress?: RegenerateProgress | null
  status?: string
}

export function RegenerateProgressBar({ progress, status }: RegenerateProgressBarProps) {
  const activeStep = progress?.step ?? 'queued'
  const activeIndex = STEPS.indexOf(activeStep)
  const percent = Math.max(0, Math.min(100, progress?.percent ?? (status === 'completed' ? 100 : 0)))

  return (
    <div className="space-y-3 rounded-2xl border border-sky-100 bg-sky-50/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Regenerate progress</div>
          <div className="mt-0.5 text-sm text-slate-700">{progress?.detail ?? 'Waiting for backend progress...'}</div>
        </div>
        <div className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-xs font-semibold text-sky-700">
          {percent}%
        </div>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-white shadow-inner">
        <div
          className="h-full rounded-full bg-gradient-to-r from-sky-500 via-cyan-400 to-emerald-400 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="grid grid-cols-7 gap-1">
        {STEPS.map((step, index) => {
          const isDone = status === 'completed' || index < activeIndex
          const isActive = index === activeIndex && status !== 'completed'
          return (
            <div
              key={step}
              className={cn(
                'flex flex-col items-center gap-1 rounded-xl px-1 py-1.5 text-center text-[10px] font-semibold uppercase tracking-[0.08em]',
                isDone ? 'text-emerald-700' : isActive ? 'text-sky-700' : 'text-slate-400',
              )}
            >
              {isDone ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : isActive ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CircleDashed className="h-3.5 w-3.5" />
              )}
              <span className="hidden sm:inline">{step}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
