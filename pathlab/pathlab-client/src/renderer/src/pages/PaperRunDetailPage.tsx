import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ClipboardList, Info, Loader2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { WorkspaceTabs, coerceWorkspaceTab, type WorkspaceTabValue } from '../components/paper/WorkspaceTabs'
import { DeleteRunButton } from '../components/paper/DeleteRunButton'
import { getPaperRun } from '../api/papers'
import { paperStatusLabel } from '../lib/paperI18n'

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
  const { t } = useTranslation()
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

  return (
    <div className="w-full px-3 py-4 sm:px-4 lg:px-6 sm:py-6">
      <div className="flex w-full flex-col gap-5">
        <PageHeader
          title={run?.title || t('paperAgent.detail.fallbackTitle')}
          description={t('paperAgent.detail.description')}
        >
          <div className="flex flex-wrap items-center gap-2">
            {run ? <Badge variant={statusBadgeVariant(run.status)}>{paperStatusLabel(t, run.status)}</Badge> : null}
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              {t('paperAgent.common.runs')}
            </Button>
            {paperId ? <DeleteRunButton paperId={paperId} onDeleted={() => navigate('/papers')} /> : null}
          </div>
        </PageHeader>

        {runQuery.isLoading ? (
          <Card className="rounded-2xl border-slate-200 shadow-sm">
            <CardContent className="flex items-center gap-2 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.detail.loading')}
            </CardContent>
          </Card>
        ) : runQuery.error ? (
          <Card className="rounded-2xl border-red-200 bg-red-50 shadow-sm">
            <CardContent className="py-6 text-sm text-red-700">
              {runQuery.error instanceof Error ? runQuery.error.message : String(runQuery.error)}
            </CardContent>
          </Card>
        ) : run && paperId ? (
          <WorkspaceTabs
            paperId={paperId}
            run={run}
            value={activeTab}
            onValueChange={setActiveTab}
            pdfRefreshKey={pdfRefreshKey}
            onPdfRefreshNeeded={bumpPdfRefreshKey}
          />
        ) : null}
      </div>
    </div>
  )
}
