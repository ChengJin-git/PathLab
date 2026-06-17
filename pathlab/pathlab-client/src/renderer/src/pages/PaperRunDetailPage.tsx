import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { StageChecklist } from '../components/paper/StageChecklist'
import { WorkspaceTabs, coerceWorkspaceTab, type WorkspaceTabValue } from '../components/paper/WorkspaceTabs'
import { DeleteRunButton } from '../components/paper/DeleteRunButton'
import { getPaperRun } from '../api/papers'

const ACTIVE_STATUSES = new Set(['pending', 'running'])
const ACTIVE_RUN_REFETCH_INTERVAL_MS = 500

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'secondary'
  if (status === 'failed' || status === 'cancelled') return 'destructive'
  if (status === 'running') return 'default'
  return 'outline'
}

export default function PaperRunDetailPage() {
  const navigate = useNavigate()
  const { paper_id: paperId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [pdfRefreshKey, setPdfRefreshKey] = useState(0)
  const activeTab = coerceWorkspaceTab(searchParams.get('tab'))

  const runQuery = useQuery({
    queryKey: ['paper-run', paperId],
    queryFn: () => getPaperRun(paperId || ''),
    enabled: Boolean(paperId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? ACTIVE_RUN_REFETCH_INTERVAL_MS : false
    },
  })

  const setActiveTab = (tab: WorkspaceTabValue | string) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', coerceWorkspaceTab(tab))
    setSearchParams(next)
  }

  const bumpPdfRefreshKey = () => {
    setPdfRefreshKey((key) => key + 1)
  }

  const run = runQuery.data
  const sourceTaskIds = run?.source_task_ids ?? []

  return (
    <div className="w-full px-3 py-4 sm:px-4 lg:px-6 sm:py-6">
      <div className="flex w-full flex-col gap-5">
        <PageHeader
          title={run?.title || paperId || 'Paper run'}
          description="PathLab paper workspace. Review, edit sections, and inspect generated artifacts."
        >
          <div className="flex flex-wrap items-center gap-2">
            {run ? <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge> : null}
            {sourceTaskIds.length ? (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Tasks</span>
                {sourceTaskIds.map((taskId) => (
                  <Link
                    key={taskId}
                    to={`/task/${encodeURIComponent(taskId)}`}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-white"
                  >
                    {taskId}
                  </Link>
                ))}
              </div>
            ) : null}
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Runs
            </Button>
            <Button variant="outline" size="sm" onClick={() => runQuery.refetch()} className="gap-2">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            {paperId ? <DeleteRunButton paperId={paperId} onDeleted={() => navigate('/papers')} /> : null}
          </div>
        </PageHeader>

        {runQuery.isLoading ? (
          <Card className="rounded-2xl border-slate-200 shadow-sm">
            <CardContent className="flex items-center gap-2 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading paper run...
            </CardContent>
          </Card>
        ) : runQuery.error ? (
          <Card className="rounded-2xl border-red-200 bg-red-50 shadow-sm">
            <CardContent className="py-6 text-sm text-red-700">
              {runQuery.error instanceof Error ? runQuery.error.message : String(runQuery.error)}
            </CardContent>
          </Card>
        ) : run && paperId ? (
          <div className="flex flex-col gap-4">
            <StageChecklist run={run} activeTab={activeTab} onSelectTab={setActiveTab} />
            <WorkspaceTabs
              paperId={paperId}
              run={run}
              value={activeTab}
              onValueChange={setActiveTab}
              pdfRefreshKey={pdfRefreshKey}
              onPdfRefreshNeeded={bumpPdfRefreshKey}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}
