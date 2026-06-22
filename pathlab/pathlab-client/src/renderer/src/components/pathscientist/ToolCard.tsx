import { AlertCircle, CheckCircle2, ChevronDown, Clock3, Info, Wrench } from 'lucide-react'
import { cn } from '../../lib/utils'
import { usePathScientistTranslation } from '../../lib/usePathScientistTranslation'
import {
  pathScientistIterationLabel,
  pathScientistStageLabel,
  pathScientistToolStatusLabel,
} from '../../lib/pathscientistI18n'
import type { PathScientistToolStatus, PathScientistToolView } from '../../lib/pathscientistEventSelectors'

interface ToolCardProps {
  tool: PathScientistToolView
  defaultOpen?: boolean
  className?: string
}

function statusIcon(status: PathScientistToolStatus) {
  if (status === 'success') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (status === 'error') return <AlertCircle className="h-4 w-4 text-red-600" />
  if (status === 'running') return <Clock3 className="h-4 w-4 text-blue-600" />
  return <Info className="h-4 w-4 text-gray-500" />
}

function statusClasses(status: PathScientistToolStatus) {
  switch (status) {
    case 'success':
      return 'border-emerald-100 bg-emerald-50/70'
    case 'error':
      return 'border-red-200 bg-red-50/80'
    case 'running':
      return 'border-blue-200 bg-blue-50/70'
    default:
      return 'border-gray-200 bg-white'
  }
}

export default function ToolCard({ tool, defaultOpen, className }: ToolCardProps) {
  const { t } = usePathScientistTranslation()
  const open = defaultOpen ?? tool.status !== 'success'
  const detailEvents = tool.events.filter((event) => typeof event.summary === 'string' && event.summary.trim())

  return (
    <details className={cn('group rounded-2xl border shadow-sm', statusClasses(tool.status), className)} open={open}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-white text-gray-700 ring-1 ring-black/5">
            {tool.status === 'info' ? <Wrench className="h-4 w-4" /> : statusIcon(tool.status)}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-extrabold text-gray-950">{tool.tool}</span>
            <span className="mt-0.5 block truncate text-xs font-medium text-gray-500">{tool.summary}</span>
          </span>
        </span>
        <span className="flex flex-shrink-0 items-center gap-2">
          <span className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-gray-600 ring-1 ring-black/5">
            {pathScientistToolStatusLabel(tool.status, t)}
          </span>
          <ChevronDown className="h-4 w-4 text-gray-400 transition group-open:rotate-180" />
        </span>
      </summary>

      <div className="border-t border-black/5 px-4 py-3">
        <div className="grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
          <div className="rounded-xl bg-white/75 p-3 ring-1 ring-black/5">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.labels.stage')}</p>
            <p className="mt-1 font-semibold text-gray-800">{pathScientistStageLabel(tool.stage, t)}</p>
          </div>
          <div className="rounded-xl bg-white/75 p-3 ring-1 ring-black/5">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.labels.iteration')}</p>
            <p className="mt-1 font-semibold text-gray-800">{tool.iteration === null ? t('pathScientist.iteration.preRun') : pathScientistIterationLabel(tool.iteration, t)}</p>
          </div>
          <div className="rounded-xl bg-white/75 p-3 ring-1 ring-black/5">
            <p className="font-bold uppercase tracking-wider text-gray-400">{t('pathScientist.labels.events')}</p>
            <p className="mt-1 font-semibold text-gray-800">{tool.events.length}</p>
          </div>
        </div>

        {detailEvents.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {detailEvents.map((event, index) => (
              <p key={`${event.kind}-${index}`} className="rounded-xl bg-white/75 px-3 py-2 text-xs leading-5 text-gray-700 ring-1 ring-black/5">
                {event.summary}
              </p>
            ))}
          </div>
        )}
      </div>
    </details>
  )
}
