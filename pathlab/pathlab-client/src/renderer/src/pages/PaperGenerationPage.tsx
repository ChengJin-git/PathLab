import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, Loader2, Plus, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { listPaperRuns, type PaperRunSummary } from '../api/papers'
import { formatDateTime } from '../lib/utils'

const ACTIVE_STATUSES = new Set(['pending', 'running'])

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'secondary'
  if (status === 'failed' || status === 'cancelled') return 'destructive'
  if (status === 'running') return 'default'
  return 'outline'
}

function RunRow({ run, onOpen }: { run: PaperRunSummary; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group w-full rounded-2xl border border-slate-200 bg-white px-4 py-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-semibold text-slate-950">
            <FileText className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:text-slate-700" />
            <span className="truncate">{run.title || run.paper_id}</span>
          </div>
          <div className="mt-1 text-sm text-slate-500">{run.paper_id}</div>
        </div>
        <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
      </div>
      <div className="mt-4 grid gap-2 text-sm text-slate-600 sm:grid-cols-3">
        <div className="rounded-xl bg-slate-50 px-3 py-2"><span className="text-slate-400">Stage</span><br />{run.current_stage}</div>
        <div className="rounded-xl bg-slate-50 px-3 py-2"><span className="text-slate-400">Template</span><br />{run.selected_templates.join(', ') || '-'}</div>
        <div className="rounded-xl bg-slate-50 px-3 py-2"><span className="text-slate-400">Created</span><br />{formatDateTime(run.created_at)}</div>
      </div>
      <div className="mt-3 text-xs text-slate-400">{run.source_task_ids.join(', ') || 'No source task IDs recorded'}</div>
    </button>
  )
}

export default function PaperGenerationPage() {
  const navigate = useNavigate()
  const runsQuery = useQuery({
    queryKey: ['paper-runs'],
    queryFn: () => listPaperRuns({ limit: 50 }),
    refetchInterval: (query) => {
      const hasActive = query.state.data?.items?.some((run) => ACTIVE_STATUSES.has(run.status))
      return hasActive ? 2000 : false
    },
  })

  return (
    <div className="w-full px-4 py-4 sm:px-6 sm:py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <PageHeader title="Paper runs" description="List-only view for PathLab paper-generation workspaces.">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate('/tools')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Tools
            </Button>
            <Button variant="outline" size="sm" onClick={() => runsQuery.refetch()} className="gap-2">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            <Button size="sm" onClick={() => navigate('/papers/new')} className="gap-2">
              <Plus className="h-4 w-4" />
              New paper
            </Button>
          </div>
        </PageHeader>

        <Card className="border-slate-200 bg-white/95 shadow-sm">
          <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
            <div>
              <CardTitle>Workspace index</CardTitle>
              <CardDescription>Polling every 2s while any run is pending or running.</CardDescription>
            </div>
            <Badge variant="outline">{runsQuery.data?.total ?? 0} total</Badge>
          </CardHeader>
          <CardContent>
            {runsQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading runs...
              </div>
            ) : runsQuery.error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {runsQuery.error instanceof Error ? runsQuery.error.message : String(runsQuery.error)}
              </div>
            ) : runsQuery.data?.items.length ? (
              <div className="space-y-3">
                {runsQuery.data.items.map((run) => <RunRow key={run.paper_id} run={run} onOpen={() => navigate(`/papers/${run.paper_id}`)} />)}
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-10 text-center">
                <FileText className="mx-auto h-9 w-9 text-slate-300" />
                <div className="mt-3 font-semibold text-slate-800">No paper runs yet</div>
                <p className="mt-1 text-sm text-slate-500">Create a run to start the read-only workspace.</p>
                <Button className="mt-4 gap-2" onClick={() => navigate('/papers/new')}>
                  <Plus className="h-4 w-4" /> New paper
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
