import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, FileText, Loader2, Plus, Search } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { createPaperRun, type CreatePaperRunRequest, type TaskRole, type TemplateId } from '../api/papers'
import { getTrainingTasks, type TrainingTask } from '../api/training'
import { cn, formatDateTime } from '../lib/utils'

const TASK_ROLES: TaskRole[] = ['main', 'baseline', 'ablation', 'external_validation']
const TEMPLATES: Array<{ id: TemplateId; title: string; description: string }> = [
  { id: 'miccai', title: 'MICCAI', description: 'LNCS proceedings, compact conference format.' },
  { id: 'nature_scientific_reports', title: 'Nature Scientific Reports', description: 'Scientific Reports article template.' },
]

function taskTitle(task: TrainingTask): string {
  return task.task_name || task.task_id
}

export default function NewPaperPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [idea, setIdea] = useState('')
  const [template, setTemplate] = useState<TemplateId>('miccai')
  const [search, setSearch] = useState('')
  const [manualTaskId, setManualTaskId] = useState('')
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([])
  const [selectedRoles, setSelectedRoles] = useState<Record<string, TaskRole>>({})

  const tasksQuery = useQuery({
    queryKey: ['paper-source-tasks', search],
    queryFn: () => getTrainingTasks({ page: 1, page_size: 50, search: search || undefined, sort_by: 'updated' }),
  })

  const tasks = tasksQuery.data?.items ?? []
  const tasksById = useMemo(() => new Map(tasks.map((task) => [task.task_id, task])), [tasks])

  const createMutation = useMutation({
    mutationFn: (request: CreatePaperRunRequest) => createPaperRun(request),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['paper-runs'] })
      navigate(`/papers/${created.paper_id}`)
    },
  })

  const toggleTask = (taskId: string) => {
    setSelectedTaskIds((current) => {
      if (current.includes(taskId)) return current.filter((id) => id !== taskId)
      setSelectedRoles((roles) => ({ ...roles, [taskId]: current.length === 0 ? 'main' : 'baseline' }))
      return [...current, taskId]
    })
  }

  const addManualTask = () => {
    const taskId = manualTaskId.trim()
    if (!taskId || selectedTaskIds.includes(taskId)) return
    setSelectedTaskIds((current) => [...current, taskId])
    setSelectedRoles((roles) => ({ ...roles, [taskId]: selectedTaskIds.length === 0 ? 'main' : 'baseline' }))
    setManualTaskId('')
  }

  const updateRole = (taskId: string, role: TaskRole) => {
    setSelectedRoles((roles) => ({ ...roles, [taskId]: role }))
  }

  const handleCreate = () => {
    if (!selectedTaskIds.length) return
    const sourceTasks = selectedTaskIds.map((taskId, index) => ({
      task_id: taskId,
      role: selectedRoles[taskId] ?? (index === 0 ? 'main' : 'baseline'),
      label: tasksById.get(taskId)?.task_name ?? null,
    }))
    createMutation.mutate({
      title: title.trim() || null,
      paper_type: 'research_paper',
      language: 'en',
      source_tasks: sourceTasks,
      selected_templates: [template],
      include_external_validation: true,
      user_idea: idea.trim() || null,
    })
  }

  return (
    <div className="w-full px-4 py-4 sm:px-6 sm:py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <PageHeader title="New paper run" description="Create a single-template PathLab paper-generation workspace.">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Runs
            </Button>
          </div>
        </PageHeader>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-6">
            <Card className="border-slate-200 bg-white/95 shadow-sm">
              <CardHeader>
                <CardTitle>1. Source tasks</CardTitle>
                <CardDescription>Select one or more training runs. Assign roles for downstream evidence organization.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search source tasks"
                    className="w-full rounded-2xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                  />
                </div>

                {tasksQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading tasks...</div>
                ) : tasksQuery.error ? (
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{tasksQuery.error instanceof Error ? tasksQuery.error.message : String(tasksQuery.error)}</div>
                ) : tasks.length ? (
                  <div className="grid gap-3 lg:grid-cols-2">
                    {tasks.map((task) => {
                      const selected = selectedTaskIds.includes(task.task_id)
                      return (
                        <button
                          key={task.task_id}
                          type="button"
                          onClick={() => toggleTask(task.task_id)}
                          className={cn(
                            'rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm',
                            selected ? 'border-slate-950 bg-slate-950 text-white' : 'border-slate-200 bg-white text-slate-900 hover:border-slate-300'
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="truncate font-semibold">{taskTitle(task)}</div>
                              <div className={cn('mt-1 text-xs', selected ? 'text-white/60' : 'text-slate-500')}>{task.task_id}</div>
                            </div>
                            <span className={cn('inline-flex h-6 w-6 items-center justify-center rounded-full border', selected ? 'border-white/20 bg-white text-slate-950' : 'border-slate-200 bg-slate-50 text-transparent')}>
                              <Check className="h-3.5 w-3.5" />
                            </span>
                          </div>
                          <div className={cn('mt-3 flex flex-wrap gap-2 text-xs', selected ? 'text-white/70' : 'text-slate-500')}>
                            <span>{task.status}</span>
                            <span>{task.task_type}</span>
                            <span>{formatDateTime(task.updated_at || task.created_at, '-')}</span>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">No tasks matched. Add a task ID manually if it exists in the backend.</div>
                )}

                <div className="flex gap-2">
                  <input
                    value={manualTaskId}
                    onChange={(event) => setManualTaskId(event.target.value)}
                    placeholder="Manual task ID"
                    className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                  />
                  <Button variant="outline" className="gap-2" onClick={addManualTask} disabled={!manualTaskId.trim()}>
                    <Plus className="h-4 w-4" /> Add
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card className="border-slate-200 bg-white/95 shadow-sm">
              <CardHeader>
                <CardTitle>2. Template</CardTitle>
                <CardDescription>Phase 1 backend accepts exactly one template.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2">
                {TEMPLATES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setTemplate(item.id)}
                    className={cn(
                      'rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm',
                      template === item.id ? 'border-sky-400 bg-sky-50 text-slate-950' : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300'
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold">{item.title}</div>
                      {template === item.id ? <Badge variant="default">selected</Badge> : null}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-500">{item.description}</p>
                  </button>
                ))}
              </CardContent>
            </Card>

            <Card className="border-slate-200 bg-white/95 shadow-sm">
              <CardHeader>
                <CardTitle>3. Paper brief</CardTitle>
                <CardDescription>Optional title and idea content passed to the paper agent.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <label className="block space-y-1.5">
                  <span className="text-sm font-semibold text-slate-700">Title</span>
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Optional manuscript title"
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                  />
                </label>
                <label className="block space-y-1.5">
                  <span className="text-sm font-semibold text-slate-700">User idea</span>
                  <textarea
                    value={idea}
                    onChange={(event) => setIdea(event.target.value)}
                    rows={7}
                    placeholder="Optional paper idea, claim direction, or writing constraints."
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                  />
                </label>
              </CardContent>
            </Card>
          </div>

          <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
            <Card className="border-slate-200 bg-slate-950 text-white shadow-lg">
              <CardHeader>
                <CardTitle className="text-white">Run package</CardTitle>
                <CardDescription className="text-slate-300">Review before sending POST /papers.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Template</div>
                  <div className="mt-1 font-semibold">{template}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Source tasks</div>
                  {selectedTaskIds.length ? (
                    <div className="mt-2 space-y-2">
                      {selectedTaskIds.map((taskId) => (
                        <div key={taskId} className="rounded-2xl border border-white/10 bg-white/5 p-3">
                          <div className="truncate text-sm font-semibold">{taskId}</div>
                          <select
                            value={selectedRoles[taskId] ?? 'baseline'}
                            onChange={(event) => updateRole(taskId, event.target.value as TaskRole)}
                            className="mt-2 w-full rounded-xl border border-white/10 bg-slate-900 px-2 py-1.5 text-xs text-white outline-none"
                          >
                            {TASK_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
                          </select>
                        </div>
                      ))}
                    </div>
                  ) : <div className="mt-2 text-sm text-slate-400">No tasks selected.</div>}
                </div>
                {createMutation.error ? (
                  <div className="rounded-2xl border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-100">{createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error)}</div>
                ) : null}
                <Button variant="primary" className="w-full gap-2" onClick={handleCreate} disabled={!selectedTaskIds.length || createMutation.isPending}>
                  {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                  Create paper run
                </Button>
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </div>
  )
}
