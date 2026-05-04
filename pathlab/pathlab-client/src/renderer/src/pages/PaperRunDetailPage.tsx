import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Download, FileText, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { PageHeader } from '../components/PageHeader'
import { downloadPaperFile, getPaperRun } from '../api/papers'

const ACTIVE_STATUSES = new Set(['pending', 'running'])

export default function PaperRunDetailPage() {
  const navigate = useNavigate()
  const { paper_id: paperId } = useParams()

  const runQuery = useQuery({
    queryKey: ['paper-run', paperId],
    queryFn: () => getPaperRun(paperId || ''),
    enabled: Boolean(paperId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? 2000 : false
    },
  })

  const run = runQuery.data

  return (
    <div className="w-full py-4 sm:py-8 px-4 sm:px-6 max-w-7xl mx-auto flex flex-col gap-6">
      <PageHeader title={run?.title || paperId || 'Paper run'} description="Paper-generation run detail and public artifacts.">
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            Runs
          </Button>
          <Button variant="outline" size="sm" onClick={() => runQuery.refetch()} className="gap-2">
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </PageHeader>

      {runQuery.isLoading ? (
        <Card className="rounded-2xl border-gray-200 shadow-sm">
          <CardContent className="flex items-center gap-2 py-10 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading paper run...
          </CardContent>
        </Card>
      ) : runQuery.error ? (
        <Card className="rounded-2xl border-red-200 bg-red-50 shadow-sm">
          <CardContent className="py-6 text-sm text-red-700">
            {runQuery.error instanceof Error ? runQuery.error.message : String(runQuery.error)}
          </CardContent>
        </Card>
      ) : run ? (
        <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-6">
          <Card className="rounded-2xl border-gray-200 shadow-sm">
            <CardHeader>
              <CardTitle>Status</CardTitle>
              <CardDescription>{run.paper_id}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between"><span className="text-gray-500">Status</span><span className="font-semibold text-gray-900">{run.status}</span></div>
              <div className="flex items-center justify-between"><span className="text-gray-500">Stage</span><span className="font-semibold text-gray-900">{run.current_stage}</span></div>
              <div className="flex items-center justify-between"><span className="text-gray-500">Templates</span><span className="font-semibold text-gray-900">{run.selected_templates.join(', ')}</span></div>
              <div className="flex items-center justify-between"><span className="text-gray-500">Tasks</span><span className="font-semibold text-gray-900">{run.source_task_ids.join(', ') || '-'}</span></div>
              {run.error_message ? <div className="rounded-xl bg-red-50 p-3 text-red-700">{run.error_message}</div> : null}
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card className="rounded-2xl border-gray-200 shadow-sm">
              <CardHeader>
                <CardTitle>Public artifacts</CardTitle>
                <CardDescription>Private evidence and raw prompts are never shown here.</CardDescription>
              </CardHeader>
              <CardContent>
                {run.artifacts.length ? (
                  <div className="space-y-3">
                    {run.artifacts.map((artifact) => (
                      <div key={artifact.path} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 px-4 py-3">
                        <div>
                          <div className="flex items-center gap-2 font-semibold text-gray-900">
                            <FileText className="w-4 h-4 text-primary-600" />
                            {artifact.label || artifact.path}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">{artifact.path} · {artifact.status}</div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-2"
                          disabled={!artifact.downloadable}
                          onClick={() => paperId && downloadPaperFile(paperId, artifact.path)}
                        >
                          <Download className="w-4 h-4" /> Download
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">
                    No public artifacts registered yet.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="rounded-2xl border-gray-200 shadow-sm">
              <CardHeader>
                <CardTitle>Stage log</CardTitle>
                <CardDescription>Latest manifest stage history.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {run.stage_log.map((entry, index) => (
                    <div key={index} className="rounded-xl bg-gray-50 px-3 py-2 text-sm text-gray-700">
                      <span className="font-semibold">{String(entry.stage || 'stage')}</span>
                      <span className="text-gray-500"> · {String(entry.message || '')}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  )
}
