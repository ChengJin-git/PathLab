import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react'
import { deletePaperRun, type PaperRunDetail, type ValidationSummary } from '../../api/papers'
import { cn, formatDateTime } from '../../lib/utils'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { ModalShell } from '../ui/modal-shell'

interface RightSidePanelProps {
  run: PaperRunDetail
  onDeleted: () => void
}

function guardDotClass(status: string): string {
  const normalized = status.toLowerCase()
  if (['passed', 'pass', 'ok', 'success'].includes(normalized)) return 'bg-emerald-500'
  if (['failed', 'fail', 'error'].includes(normalized)) return 'bg-red-500'
  if (['warning', 'warnings'].includes(normalized)) return 'bg-amber-500'
  return 'bg-slate-300'
}

function ValidationMini({ summary }: { summary: ValidationSummary | null | undefined }) {
  if (!summary) return <div className="text-sm text-slate-500">Validation has not run yet.</div>
  const guards = summary.m10_guards ?? []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {guards.length ? guards.slice(0, 8).map((guard) => (
          <span key={guard.guard} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600">
            <span className={cn('h-2 w-2 rounded-full', guardDotClass(guard.status))} />
            {guard.guard.replace(/_guard$/, '')}
          </span>
        )) : <Badge variant="outline">guards not run</Badge>}
      </div>
      <div className="rounded-2xl bg-slate-50 p-3 text-sm text-slate-600">
        HybridScore <span className="font-semibold text-slate-950">{summary.hybrid_score ?? '-'}</span>
        {summary.refinement ? <span> · refinement {summary.refinement.final_status ?? 'done'}</span> : null}
      </div>
    </div>
  )
}

export function RightSidePanel({ run, onDeleted }: RightSidePanelProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const qc = useQueryClient()
  const deleteMutation = useMutation({
    mutationFn: () => deletePaperRun(run.paper_id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['paper-runs'] })
      onDeleted()
    },
  })
  const recentLog = [...(run.stage_log ?? [])].slice(-8).reverse()

  return (
    <div className="space-y-4">
      <Card className="border-slate-200 bg-white/95 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Run log</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {recentLog.length ? recentLog.map((entry, index) => (
            <div key={`${entry.stage}-${entry.ts ?? index}`} className="rounded-2xl border border-slate-100 bg-slate-50/80 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-slate-900">{entry.stage}</span>
                <span className="text-xs text-slate-400">{formatDateTime(entry.finished_at || entry.started_at || entry.ts, '')}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{entry.error_message || entry.message || entry.status}</p>
            </div>
          )) : <div className="text-sm text-slate-500">No stage log entries yet.</div>}
        </CardContent>
      </Card>

      <Card className="border-slate-200 bg-white/95 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Validation</CardTitle>
        </CardHeader>
        <CardContent>
          <ValidationMini summary={run.validation_summary ?? null} />
        </CardContent>
      </Card>

      <Card className="border-slate-200 bg-white/95 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Source tasks</CardTitle>
        </CardHeader>
        <CardContent>
          {run.source_task_ids.length ? (
            <div className="flex flex-wrap gap-2">
              {run.source_task_ids.map((taskId) => (
                <Link key={taskId} to={`/task/${encodeURIComponent(taskId)}`} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-white">
                  {taskId}
                </Link>
              ))}
            </div>
          ) : <div className="text-sm text-slate-500">No source tasks recorded.</div>}
        </CardContent>
      </Card>

      <Card className="border-red-100 bg-red-50/70 shadow-sm">
        <CardContent className="space-y-3 p-4">
          <div className="flex items-start gap-2 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Delete removes this run from the paper agent workspace. Cancel is a v2.0 backend feature.
          </div>
          <Button variant="destructive" size="sm" className="w-full gap-2" onClick={() => setConfirmOpen(true)}>
            <Trash2 className="h-4 w-4" />
            Delete run
          </Button>
        </CardContent>
      </Card>

      <ModalShell isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} title="Delete paper run">
        <div className="space-y-4 p-5">
          <div>
            <h3 className="text-lg font-semibold text-slate-950">Delete this paper run?</h3>
            <p className="mt-1 text-sm leading-6 text-slate-500">This action cannot be undone from the frontend. Run ID: {run.paper_id}</p>
          </div>
          {deleteMutation.error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {deleteMutation.error instanceof Error ? deleteMutation.error.message : String(deleteMutation.error)}
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>Keep run</Button>
            <Button variant="destructive" className="gap-2" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete
            </Button>
          </div>
        </div>
      </ModalShell>
    </div>
  )
}
