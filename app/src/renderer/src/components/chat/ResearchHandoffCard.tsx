import { ArrowUpRight, Check, CircleAlert, Clock3, FlaskConical, Loader2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ResearchHandoff } from '../../api/chat'
import type { AutoResearchSessionSummary } from '../../types/autoresearch'
import { useResearchText } from '../autoresearch/researchText'
import { useWorkbenchText } from './workbenchText'

/** A durable execution receipt, distinct from an assistant's proposed navigation. */
export default function ResearchHandoffCard({ handoff, streaming, session }: {
  handoff: ResearchHandoff
  streaming: boolean
  session?: AutoResearchSessionSummary
}) {
  const text = useWorkbenchText()
  const { status: statusLabel } = useResearchText()
  const accepted = handoff.status === 'accepted' && !!handoff.session_id
  const confirmation = handoff.status === 'awaiting_confirmation'
  const pending = ['preparing', 'submitting'].includes(handoff.status)
  const busy = pending && streaming
  const failed = handoff.status === 'failed' || (pending && !streaming)
  const state = session?.status || handoff.session_status
  const queued = accepted && state === 'queued'
  const needsAttention = failed || (accepted && ['failed', 'blocked', 'interrupted'].includes(state || ''))
  const title = session?.title || handoff.title
  const label = confirmation ? text('briefConfirmation') : accepted ? (state ? statusLabel(state) : text('handoffAccepted'))
    : failed ? text(pending ? 'handoffInterrupted' : 'handoffFailed')
    : text(handoff.status === 'submitting' ? 'handoffSubmitting' : 'handoffPreparing')
  const hint = confirmation ? text('briefConfirmationHint') : accepted
    ? text(queued ? 'handoffQueuedHint' : ['running', 'preparing', 'waiting', 'pausing', 'stopping'].includes(state || '') ? 'handoffRunningHint' : 'handoffSavedHint')
    : failed ? text('handoffRetryHint')
    : text(handoff.status === 'submitting' ? 'handoffSubmittingHint' : 'handoffPreparingHint')
  const Icon = busy ? Loader2 : needsAttention ? CircleAlert : queued ? Clock3 : accepted ? Check : FlaskConical
  const heading = handoff.task_kind === 'analysis' ? text('analysisOnly')
    : handoff.task_kind === 'document' ? text('documentOnly') : text('handoffTitle')

  return (
    <section aria-label={heading} className={`my-3 overflow-hidden rounded-xl border bg-white ${needsAttention ? 'border-amber-200' : 'border-slate-200'}`}>
      <div className="flex items-start gap-3 p-4">
        <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${needsAttention ? 'bg-amber-50 text-amber-700' : 'bg-primary-50 text-primary-700'}`}>
          <Icon size={18} aria-hidden="true" className={busy ? 'animate-spin motion-reduce:animate-none' : ''} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-slate-500">{heading}</p>
          <p role="status" aria-live="polite" className="mt-0.5 text-sm font-semibold text-slate-900">{label}</p>
          {title && <p className="mt-1 line-clamp-2 break-words text-sm text-slate-700">{title}</p>}
          {failed && handoff.error && <p className="mt-2 whitespace-pre-wrap break-words text-sm text-amber-800">{handoff.error}</p>}
          <p className="mt-1.5 text-xs leading-5 text-slate-600">{hint}</p>
        </div>
      </div>
      {accepted && <div className="border-t border-slate-100 px-4">
        <Link to={`/autoresearch/sessions/${encodeURIComponent(handoff.session_id!)}`} className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded text-sm font-medium text-primary-700 transition-colors hover:text-primary-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
          {text('handoffView')}<ArrowUpRight size={15} aria-hidden="true" />
        </Link>
      </div>}
    </section>
  )
}
