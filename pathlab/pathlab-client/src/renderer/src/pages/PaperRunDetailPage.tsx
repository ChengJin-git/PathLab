import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { RunWorkspaceLayout } from '../components/paper/RunWorkspaceLayout'
import { StageChecklist } from '../components/paper/StageChecklist'
import { WorkspaceTabs, coerceWorkspaceTab, type WorkspaceTabValue } from '../components/paper/WorkspaceTabs'
import { RightSidePanel } from '../components/paper/RightSidePanel'
import { getPaperRun } from '../api/papers'

const ACTIVE_STATUSES = new Set(['pending', 'running'])

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
  const activeTab = coerceWorkspaceTab(searchParams.get('tab'))

  const runQuery = useQuery({
    queryKey: ['paper-run', paperId],
    queryFn: () => getPaperRun(paperId || ''),
    enabled: Boolean(paperId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? 2000 : false
    },
  })

  const setActiveTab = (tab: WorkspaceTabValue | string) => {
    const next = new URLSearchParams(searchParams)
    next.set('tab', coerceWorkspaceTab(tab))
    setSearchParams(next)
  }

  const run = runQuery.data

  return (
    <div className="w-full px-4 py-4 sm:px-6 sm:py-8">
      <div className="mx-auto flex max-w-[1800px] flex-col gap-6">
        <PageHeader title={run?.title || paperId || 'Paper run'} description="Three-column PathLab paper workspace. Read-only v1.5 surface.">
          <div className="flex flex-wrap gap-2">
            {run ? <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge> : null}
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Runs
            </Button>
            <Button variant="outline" size="sm" onClick={() => runQuery.refetch()} className="gap-2">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
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
          <RunWorkspaceLayout
            left={<StageChecklist run={run} activeTab={activeTab} onSelectTab={setActiveTab} />}
            main={<WorkspaceTabs paperId={paperId} run={run} value={activeTab} onValueChange={setActiveTab} />}
            right={<RightSidePanel run={run} onDeleted={() => navigate('/papers')} />}
          />
        ) : null}
      </div>
    </div>
  )
}
