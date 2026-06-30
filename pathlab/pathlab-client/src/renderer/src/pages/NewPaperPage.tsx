import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Check, FileText, Loader2, Plus, Search, X } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { ModalShell } from '../components/ui/modal-shell'
import { createPaperRun, listPaperRuns, type CreatePaperRunRequest, type TaskRole, type TemplateId } from '../api/papers'
import { getTrainingTasks, type TrainingTask } from '../api/training'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { cn, formatDateTime } from '../lib/utils'
import {
  paperTaskRoleLabel,
  paperTemplateDescription,
  paperTemplateTitle,
} from '../lib/paperI18n'

const TASK_ROLES: TaskRole[] = ['main', 'baseline', 'ablation', 'external_validation']
const TEMPLATES: TemplateId[] = ['miccai', 'nature_scientific_reports']

function taskTitle(task: TrainingTask): string {
  return task.task_name || task.task_id
}

export default function NewPaperPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { addPaperGenerationTask } = useBackgroundTask()
  const initialSourceTaskId = searchParams.get('source_task_id')?.trim() || ''
  const initialSourceTaskName = searchParams.get('source_task_name')?.trim() || ''
  const [title, setTitle] = useState('')
  const [idea, setIdea] = useState('')
  const [template, setTemplate] = useState<TemplateId>('miccai')
  const [search, setSearch] = useState('')
  const [manualTaskId, setManualTaskId] = useState('')
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>(() => initialSourceTaskId ? [initialSourceTaskId] : [])
  const [selectedRoles, setSelectedRoles] = useState<Record<string, TaskRole>>(() => initialSourceTaskId ? { [initialSourceTaskId]: 'main' } : {})
  const [manualTaskIds, setManualTaskIds] = useState<Set<string>>(() => new Set())
  const [showConfirmModal, setShowConfirmModal] = useState(false)

  const tasksQuery = useQuery({
    queryKey: ['paper-source-tasks', search],
    queryFn: () => getTrainingTasks({ page: 1, page_size: 50, search: search || undefined, sort_by: 'updated' }),
  })

  const existingRunsQuery = useQuery({
    queryKey: ['paper-runs', 'new-manual-source-task-conflicts'],
    queryFn: () => listPaperRuns({ limit: 200 }),
  })

  const tasks = tasksQuery.data?.items ?? []
  const tasksById = useMemo(() => {
    const map = new Map(tasks.map((task) => [task.task_id, task]))
    if (initialSourceTaskId && initialSourceTaskName && !map.has(initialSourceTaskId)) {
      map.set(initialSourceTaskId, {
        task_id: initialSourceTaskId,
        task_name: initialSourceTaskName,
      } as TrainingTask)
    }
    return map
  }, [initialSourceTaskId, initialSourceTaskName, tasks])
  const existingSourceTaskIds = useMemo(() => {
    const ids = new Set<string>()
    for (const run of existingRunsQuery.data?.items ?? []) {
      for (const taskId of run.source_task_ids ?? []) {
        ids.add(taskId)
      }
    }
    return ids
  }, [existingRunsQuery.data?.items])
  const manualTaskIdValue = manualTaskId.trim()
  const manualTaskIdError = manualTaskIdValue && existingSourceTaskIds.has(manualTaskIdValue)
    ? t('paperAgent.new.manualTaskConflict', { taskId: manualTaskIdValue })
    : ''

  const createMutation = useMutation({
    mutationFn: (request: CreatePaperRunRequest) => createPaperRun(request),
    onSuccess: (created) => {
      addPaperGenerationTask(created.paper_id, title)
      void qc.invalidateQueries({ queryKey: ['paper-runs'] })
      navigate(`/papers/${created.paper_id}`)
    },
  })

  const toggleTask = (taskId: string) => {
    setSelectedTaskIds((current) => {
      if (current.includes(taskId)) {
        setManualTaskIds((ids) => {
          if (!ids.has(taskId)) return ids
          const next = new Set(ids)
          next.delete(taskId)
          return next
        })
        return current.filter((id) => id !== taskId)
      }
      setSelectedRoles((roles) => ({ ...roles, [taskId]: current.length === 0 ? 'main' : 'baseline' }))
      return [...current, taskId]
    })
  }

  const addManualTask = () => {
    const taskId = manualTaskIdValue
    if (!taskId || selectedTaskIds.includes(taskId) || manualTaskIdError) return
    setSelectedTaskIds((current) => [...current, taskId])
    setSelectedRoles((roles) => ({ ...roles, [taskId]: selectedTaskIds.length === 0 ? 'main' : 'baseline' }))
    setManualTaskIds((ids) => new Set(ids).add(taskId))
    setManualTaskId('')
  }

  const updateRole = (taskId: string, role: TaskRole) => {
    setSelectedRoles((roles) => ({ ...roles, [taskId]: role }))
  }

  const handleCreate = () => {
    if (!selectedTaskIds.length || manualTaskIdError) return
    const sourceTasks = selectedTaskIds.map((taskId, index) => ({
      task_id: taskId,
      role: selectedRoles[taskId] ?? (index === 0 ? 'main' : 'baseline'),
      label: tasksById.get(taskId)?.task_name ?? null,
      is_manual: manualTaskIds.has(taskId),
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

  const openConfirmModal = () => {
    if (!selectedTaskIds.length || manualTaskIdError || createMutation.isPending) return
    setShowConfirmModal(true)
  }

  const closeConfirmModal = () => {
    if (createMutation.isPending) return
    setShowConfirmModal(false)
  }

  return (
    <div className="w-full px-4 py-4 sm:px-6 sm:py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <PageHeader title={t('paperAgent.new.title')} description={t('paperAgent.new.description')}>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate('/papers')} className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              {t('paperAgent.common.runs')}
            </Button>
          </div>
        </PageHeader>

        <div className="space-y-6">
          <Card className="border-slate-200 bg-white/95 shadow-sm">
            <CardHeader>
              <CardTitle>{t('paperAgent.new.sourceTasksTitle')}</CardTitle>
              <CardDescription>{t('paperAgent.new.sourceTasksDescription')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t('paperAgent.new.searchTasksPlaceholder')}
                  className="w-full rounded-2xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                />
              </div>

              {tasksQuery.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.new.loadingTasks')}</div>
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
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">{t('paperAgent.new.noTasksMatched')}</div>
              )}

              <div className="flex gap-2">
                <input
                  value={manualTaskId}
                  onChange={(event) => setManualTaskId(event.target.value)}
                  placeholder={t('paperAgent.new.manualTaskPlaceholder')}
                  aria-invalid={Boolean(manualTaskIdError)}
                  className={cn(
                    'min-w-0 flex-1 rounded-2xl border bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10',
                    manualTaskIdError ? 'border-red-300 focus:border-red-400 focus:ring-red-500/10' : 'border-slate-200',
                  )}
                />
                <Button variant="outline" className="gap-2" onClick={addManualTask} disabled={!manualTaskIdValue || Boolean(manualTaskIdError)}>
                  <Plus className="h-4 w-4" /> {t('paperAgent.common.add')}
                </Button>
              </div>
              {manualTaskIdError ? <div className="text-xs font-medium text-red-600">{manualTaskIdError}</div> : null}
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white/95 shadow-sm">
            <CardHeader>
              <CardTitle>{t('paperAgent.new.templateTitle')}</CardTitle>
              <CardDescription>{t('paperAgent.new.templateDescription')}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              {TEMPLATES.map((templateId) => (
                <button
                  key={templateId}
                  type="button"
                  onClick={() => setTemplate(templateId)}
                  className={cn(
                    'rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm',
                    template === templateId ? 'border-sky-400 bg-sky-50 text-slate-950' : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300'
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-semibold">{paperTemplateTitle(t, templateId)}</div>
                    {template === templateId ? <Badge variant="default">{t('paperAgent.common.selected')}</Badge> : null}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-500">{paperTemplateDescription(t, templateId)}</p>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white/95 shadow-sm">
            <CardHeader>
              <CardTitle>{t('paperAgent.new.briefTitle')}</CardTitle>
              <CardDescription>{t('paperAgent.new.briefDescription')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block space-y-1.5">
                <span className="text-sm font-semibold text-slate-700">{t('paperAgent.new.paperTitleLabel')}</span>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t('paperAgent.new.paperTitlePlaceholder')}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm font-semibold text-slate-700">{t('paperAgent.new.userIdeaLabel')}</span>
                <textarea
                  value={idea}
                  onChange={(event) => setIdea(event.target.value)}
                  rows={7}
                  placeholder={t('paperAgent.new.userIdeaPlaceholder')}
                  className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                />
              </label>
              <div className="flex justify-end border-t border-slate-100 pt-4">
                <Button
                  variant="primary"
                  className="gap-2"
                  onClick={openConfirmModal}
                  disabled={!selectedTaskIds.length || Boolean(manualTaskIdError) || createMutation.isPending}
                >
                  <FileText className="h-4 w-4" />
                  {t('paperAgent.new.create')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        <ModalShell isOpen={showConfirmModal} onClose={closeConfirmModal} maxWidth="lg" title={t('paperAgent.new.confirmTitle')}>
          <div className="border-b border-slate-200 px-5 py-4 sm:px-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-950">{t('paperAgent.new.confirmTitle')}</h2>
                <p className="mt-1 text-sm text-slate-500">{t('paperAgent.new.confirmDescription')}</p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={closeConfirmModal}
                disabled={createMutation.isPending}
                aria-label={t('paperAgent.new.closeConfirm')}
                className="h-9 w-9 shrink-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="space-y-5 px-5 py-5 sm:px-6">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{t('paperAgent.runRow.template')}</div>
              <div className="mt-1 text-base font-semibold text-slate-950">{paperTemplateTitle(t, template)}</div>
            </div>

            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{t('paperAgent.new.sourceTasksLabel')}</div>
              {selectedTaskIds.length ? (
                <div className="mt-2 space-y-2">
                  {selectedTaskIds.map((taskId) => (
                    <div key={taskId} className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
                      <div className="truncate text-sm font-semibold text-slate-950">{taskId}</div>
                      <select
                        value={selectedRoles[taskId] ?? 'baseline'}
                        onChange={(event) => updateRole(taskId, event.target.value as TaskRole)}
                        disabled={createMutation.isPending}
                        className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-sky-500/10"
                      >
                        {TASK_ROLES.map((role) => <option key={role} value={role}>{paperTaskRoleLabel(t, role)}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              ) : <div className="mt-2 text-sm text-slate-400">{t('paperAgent.new.noTasksSelected')}</div>}
            </div>

            {createMutation.error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error)}</div>
            ) : null}
          </div>

          <div className="flex justify-end border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-6">
            <Button variant="primary" className="gap-2" onClick={handleCreate} disabled={!selectedTaskIds.length || Boolean(manualTaskIdError) || createMutation.isPending}>
              {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {t('paperAgent.new.confirmCreate')}
            </Button>
          </div>
        </ModalShell>
      </div>
    </div>
  )
}
