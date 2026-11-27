import { Check, ChevronDown, ChevronRight, Circle, CircleAlert, Loader2, ListTree, Clock3 } from 'lucide-react'
import { useResearchText } from './researchText'
import { Button } from '../ui/button'
import { researchPlanState, researchStepKey, researchStepStatus, type ResearchStep } from './researchPlan'
export type { ResearchStep } from './researchPlan'

export function ResearchQueueNotice({ queue }: { queue?: { limit: number; running: number; position: number; busy: boolean } }) {
  const { text } = useResearchText()
  if (!queue?.position) return null
  return <div role="status" className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
    <Clock3 size={20} className="mt-0.5 shrink-0" /><div><p className="text-sm font-semibold">{queue.busy ? text.queueBusy : text.queued}</p><p className="mt-1 text-xs leading-5 text-amber-800">{text.queueHint}</p><p className="mt-2 text-xs">{text.queuePosition} #{queue.position} · {text.queueLimit} {queue.limit}</p></div>
  </div>
}

export default function ResearchOutline({ plan, selected, onSelect, status, completedRuns, totalRuns }: {
  plan: ResearchStep[]; selected: string | null; onSelect: (key: string) => void; status: string; completedRuns: number; totalRuns: number
}) {
  const { text, status: label } = useResearchText()
  const { completed, total } = researchPlanState(plan, status)
  const active = ['running', 'waiting', 'preparing'].includes(status)
  return <aside className="min-h-0 w-full self-start overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)]" data-testid="research-outline">
    <details open className="group/plan">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-400 [&::-webkit-details-marker]:hidden">
        <ListTree size={17} className="shrink-0 text-slate-500" aria-hidden="true" />
        <h2 className="min-w-0 flex-1 text-sm font-semibold text-slate-900">{text.outline}</h2>
        {total > 0 && <span className="whitespace-nowrap text-xs tabular-nums text-slate-500">{completed}/{total}</span>}
        <ChevronDown size={15} className="shrink-0 text-slate-400 transition-transform group-open/plan:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
      </summary>
      <div className="border-t border-[color:var(--surface-border)] px-5 pb-2 pt-3">
        <p className="text-[11px] leading-5 text-slate-500">{text.planAdapts}</p>
        {total > 0 && <progress aria-label={text.planCompletion} aria-valuetext={text.planCompletedCount.replace('{done}', String(completed)).replace('{total}', String(total))} max={total} value={completed}
          className="mt-2 h-1 w-full overflow-hidden rounded-full accent-primary-600 [&::-webkit-progress-bar]:bg-slate-100 [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-primary-600 [&::-moz-progress-bar]:bg-primary-600" />}
      </div>
      <div className="max-h-[55vh] overflow-y-auto p-2 sm:max-h-[64vh]">
        {!total && <p className="px-3 py-4 text-sm leading-6 text-slate-500">{status === 'completed' ? text.noPlanCompleted : active ? text.noPlan : text.noPlanYet}</p>}
        <ol className="space-y-1">{plan.map((step, index) => {
          const key = researchStepKey(step)
          const state = researchStepStatus(step.status, status)
          const chosen = selected === key
          const current = state === 'running'
          const Icon = state === 'completed' ? Check : current ? Loader2 : state === 'failed' ? CircleAlert : Circle
          return <li key={key}>
            <Button type="button" variant="ghost" onClick={() => onSelect(key)} aria-pressed={chosen} aria-label={`${step.title}: ${label(state)}`}
              className={`h-auto w-full items-start gap-3 whitespace-normal rounded-2xl px-3 py-3 text-left ${chosen ? 'bg-primary-50 ring-1 ring-inset ring-primary-100' : current ? 'bg-[color:var(--surface-muted)]' : ''}`}>
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${state === 'completed' ? 'bg-emerald-50 text-emerald-700' : current ? 'bg-white text-primary-700' : 'text-slate-400'}`}>
                {state === 'completed' || current ? <Icon size={13} aria-hidden="true" className={current ? 'animate-spin motion-reduce:animate-none' : ''} /> : <span className="text-[11px] tabular-nums">{index + 1}</span>}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block break-words text-sm font-medium leading-6 text-slate-800">{step.title}</span>
                <span className={`mt-1 block text-[11px] font-normal ${state === 'completed' ? 'text-emerald-700' : current ? 'text-primary-700' : state === 'failed' ? 'text-red-700' : 'text-slate-500'}`}>{label(state)}</span>
                {chosen && step.summary && <span className="mt-2 block text-xs font-normal leading-6 text-slate-600">{step.summary}</span>}
              </span>
              <ChevronRight size={14} className="mt-1.5 shrink-0 text-slate-400" aria-hidden="true" />
            </Button>
            {chosen && !!step.children?.length && <ol className="mb-2 ml-9 space-y-2 border-l border-[color:var(--surface-border)] py-2 pl-4 pr-3">{step.children.map((child, i) => {
              const state = researchStepStatus(child.status, status)
              return <li key={i} className="flex items-start gap-2 text-xs leading-5 text-slate-600">
                {state === 'completed' ? <Check size={12} className="mt-1 shrink-0 text-emerald-600" /> : state === 'running' ? <Loader2 size={12} className="mt-1 shrink-0 animate-spin text-primary-600 motion-reduce:animate-none" /> : <Circle size={9} className="mt-1.5 shrink-0 text-slate-400" />}
                <span>{child.title}<span className="sr-only"> {label(state)}</span></span>
              </li>
            })}</ol>}
          </li>
        })}</ol>
      </div>
      {totalRuns > 0 && <footer className="flex items-center justify-between border-t border-[color:var(--surface-border)] px-5 py-3 text-xs text-slate-500"><span>{text.runs}</span><span className="tabular-nums">{completedRuns}/{totalRuns}</span></footer>}
    </details>
  </aside>
}
