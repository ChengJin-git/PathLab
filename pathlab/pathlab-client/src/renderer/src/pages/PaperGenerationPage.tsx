import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, Loader2, Plus, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { PageHeader } from '../components/PageHeader'
import { createPaperRun, listPaperRuns, type CreatePaperRunRequest } from '../api/papers'

const ACTIVE_STATUSES = new Set(['pending', 'running'])

export default function PaperGenerationPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [taskId, setTaskId] = useState('')
  const [idea, setIdea] = useState('')

  const runsQuery = useQuery({
    queryKey: ['paper-runs'],
    queryFn: () => listPaperRuns({ limit: 50 }),
    refetchInterval: (query) => {
      const hasActive = query.state.data?.items?.some((run) => ACTIVE_STATUSES.has(run.status))
      return hasActive ? 2000 : false
    },
  })

  const createMutation = useMutation({
    mutationFn: (request: CreatePaperRunRequest) => createPaperRun(request),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['paper-runs'] })
      navigate(`/papers/${created.paper_id}`)
    },
  })

  const handleCreate = () => {
    const trimmedTaskId = taskId.trim()
    if (!trimmedTaskId) return
    createMutation.mutate({
      title: title.trim() || null,
      source_tasks: [{ task_id: trimmedTaskId, role: 'main' }],
      selected_templates: ['miccai', 'nature_scientific_reports'],
      include_external_validation: true,
      user_idea: idea.trim() || null,
    })
  }

  return (
    <div className="w-full py-4 sm:py-8 px-4 sm:px-6 max-w-7xl mx-auto flex flex-col gap-6">
      <PageHeader title="Paper Generator" description="Create and monitor PathLab paper-generation runs.">
        <Button variant="outline" size="sm" onClick={() => navigate('/tools')} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Tools
        </Button>
      </PageHeader>

      <div className="grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6">
        <Card className="border-gray-200 rounded-2xl shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <Plus className="w-5 h-5 text-emerald-600" />
              New paper run
            </CardTitle>
            <CardDescription>Phase 01 creates the run scaffold and worker descriptor.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-1.5">
              <span className="text-sm font-semibold text-gray-700">Title</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Optional manuscript title"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-semibold text-gray-700">Main task ID</span>
              <input
                value={taskId}
                onChange={(event) => setTaskId(event.target.value)}
                placeholder="training task id"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-sm font-semibold text-gray-700">Idea / notes</span>
              <textarea
                value={idea}
                onChange={(event) => setIdea(event.target.value)}
                rows={5}
                placeholder="Optional user idea for the future agents"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
              />
            </label>
            {createMutation.error ? (
              <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">
                {createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error)}
              </div>
            ) : null}
            <Button onClick={handleCreate} disabled={!taskId.trim() || createMutation.isPending} className="w-full gap-2">
              {createMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
              Create paper run
            </Button>
          </CardContent>
        </Card>

        <Card className="border-gray-200 rounded-2xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-xl">Runs</CardTitle>
              <CardDescription>Polling every 2s while a run is active.</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => runsQuery.refetch()} className="gap-2">
              <RefreshCw className="w-4 h-4" />
              Refresh
            </Button>
          </CardHeader>
          <CardContent>
            {runsQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading runs...
              </div>
            ) : runsQuery.data?.items.length ? (
              <div className="space-y-3">
                {runsQuery.data.items.map((run) => (
                  <button
                    key={run.paper_id}
                    onClick={() => navigate(`/papers/${run.paper_id}`)}
                    className="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-left transition hover:border-primary-200 hover:bg-primary-50/40"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-semibold text-gray-900">{run.title || run.paper_id}</div>
                      <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-700">{run.status}</span>
                    </div>
                    <div className="mt-1 text-sm text-gray-500">{run.current_stage} · {run.source_task_ids.join(', ') || 'no task'}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">
                No paper runs yet.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
