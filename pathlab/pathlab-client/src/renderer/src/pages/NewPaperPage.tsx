import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowLeft, Check, FileText, Loader2, Search, X } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { ModalShell } from '../components/ui/modal-shell'
import { createPaperRun, listPaperRuns, MAX_PAPERS_PER_SOURCE_TASK, type CreatePaperRunRequest, type PaperRunSummary, type TaskRole, type TemplateId } from '../api/papers'
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
const PAPER_TITLE_CHECK_PAGE_SIZE = 200

function taskTitle(task: TrainingTask): string {
  return task.task_name || task.task_id
}

async function listAllPaperRunSummaries(): Promise<PaperRunSummary[]> {
  const firstPage = await listPaperRuns({ limit: PAPER_TITLE_CHECK_PAGE_SIZE, offset: 0 })
  const items = [...firstPage.items]
  let offset = items.length

  while (offset < firstPage.total) {
    const page = await listPaperRuns({ limit: PAPER_TITLE_CHECK_PAGE_SIZE, offset })
    if (!page.items.length) break
    items.push(...page.items)
    offset += page.items.length
  }

  return items
}

export default function NewPaperPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { addPaperGenerationTask } = useBackgroundTask()
  const routeState = location.state as { sourceTaskId?: string; sourceTaskName?: string } | null
  const initialTaskId = (searchParams.get('task_id') || routeState?.sourceTaskId || '').trim()
  const initialTaskName = (searchParams.get('task_name') || routeState?.sourceTaskName || '').trim()
  const [title, setTitle] = useState('')
  const [idea, setIdea] = useState('')
  const [template, setTemplate] = useState<TemplateId>('miccai')
  const [search, setSearch] = useState(initialTaskName || initialTaskId)
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>(initialTaskId ? [initialTaskId] : [])
  const [selectedRoles, setSelectedRoles] = useState<Record<string, TaskRole>>(initialTaskId ? { [initialTaskId]: 'main' } : {})
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const titleAutoFillRef = useRef('')
  const trimmedTitle = title.trim()

  const tasksQuery = useQuery({
    queryKey: ['paper-source-tasks', search],
    queryFn: () => getTrainingTasks({ page: 1, page_size: 50, search: search || undefined, sort_by: 'updated' }),
  })

  const paperLimitQuery = useQuery({
    queryKey: ['paper-source-task-limits', selectedTaskIds],
    queryFn: async () => {
      const entries = await Promise.all(
        selectedTaskIds.map(async (taskId) => {
          const response = await listPaperRuns({ source_task_id: taskId, limit: 1, offset: 0 })
          return [taskId, response.total] as const
        }),
      )
      return Object.fromEntries(entries) as Record<string, number>
    },
    enabled: selectedTaskIds.length > 0,
    staleTime: 15 * 1000,
  })

  const paperRunTitleQuery = useQuery({
    queryKey: ['paper-run-title-index'],
    queryFn: listAllPaperRunSummaries,
    enabled: Boolean(trimmedTitle),
    staleTime: 15 * 1000,
  })

  const tasks = tasksQuery.data?.items ?? []
  const tasksById = useMemo(() => new Map(tasks.map((task) => [task.task_id, task])), [tasks])
  const paperCountsByTaskId = paperLimitQuery.data ?? {}
  const duplicateTitleRun = trimmedTitle
    ? paperRunTitleQuery.data?.find((run) => run.title?.trim() === trimmedTitle)
    : undefined
  const hasTitleConflict = Boolean(duplicateTitleRun)
  const isCheckingTitleUniqueness = Boolean(trimmedTitle) && paperRunTitleQuery.isFetching
  const titleCheckFailed = Boolean(trimmedTitle) && paperRunTitleQuery.isError
  const selectedSourceTaskId = selectedTaskIds[selectedTaskIds.length - 1]
  const selectedSourceTaskName = selectedSourceTaskId
    ? tasksById.get(selectedSourceTaskId)?.task_name ?? (selectedSourceTaskId === initialTaskId ? initialTaskName : '')
    : ''
  const limitedTaskIds = selectedTaskIds.filter((taskId) => (paperCountsByTaskId[taskId] ?? 0) >= MAX_PAPERS_PER_SOURCE_TASK)
  const firstLimitedTaskId = limitedTaskIds[0]
  const hasPaperLimitBlock = limitedTaskIds.length > 0
  const isCheckingPaperLimit = paperLimitQuery.isFetching && selectedTaskIds.length > 0

  useEffect(() => {
    if (!selectedSourceTaskName) return
    setTitle((current) => {
      const previousAutoFill = titleAutoFillRef.current
      if (!current.trim() || current === previousAutoFill) {
        titleAutoFillRef.current = selectedSourceTaskName
        return selectedSourceTaskName
      }
      if (previousAutoFill && current.startsWith(previousAutoFill)) {
        titleAutoFillRef.current = selectedSourceTaskName
        return `${selectedSourceTaskName}${current.slice(previousAutoFill.length)}`
      }
      return current
    })
  }, [selectedSourceTaskName])

  useEffect(() => {
    if (!initialTaskId) return
    setSelectedTaskIds((current) => current.includes(initialTaskId) ? current : [initialTaskId, ...current])
    setSelectedRoles((roles) => ({ [initialTaskId]: 'main', ...roles }))
  }, [initialTaskId])

  const createMutation = useMutation({
    mutationFn: (request: CreatePaperRunRequest) => createPaperRun(request),
    onSuccess: (created) => {
      addPaperGenerationTask(created.paper_id, trimmedTitle || null)
      void qc.invalidateQueries({ queryKey: ['paper-runs'] })
      void qc.invalidateQueries({ queryKey: ['paper-run-title-index'] })
      void qc.invalidateQueries({ queryKey: ['paper-source-task-limits'] })
      navigate(`/papers/${created.paper_id}`)
    },
  })

  const firstLimitedTaskName = firstLimitedTaskId
    ? tasksById.get(firstLimitedTaskId)?.task_name ?? (firstLimitedTaskId === initialTaskId && initialTaskName ? initialTaskName : firstLimitedTaskId)
    : ''
  const firstLimitedTaskCount = firstLimitedTaskId
    ? paperCountsByTaskId[firstLimitedTaskId] ?? MAX_PAPERS_PER_SOURCE_TASK
    : 0
  const paperLimitMessage = firstLimitedTaskId
    ? t('paperAgent.new.paperLimitReached', {
        taskId: firstLimitedTaskId,
        taskName: firstLimitedTaskName,
        count: firstLimitedTaskCount,
        limit: MAX_PAPERS_PER_SOURCE_TASK,
      })
    : ''
  const createErrorCode = createMutation.error && typeof createMutation.error === 'object' && 'code' in createMutation.error
    ? String((createMutation.error as { code?: unknown }).code ?? '')
    : ''
  const createErrorMessage = createMutation.error
    ? createErrorCode === 'PAPER_LIMIT_EXCEEDED'
      ? t('paperAgent.new.paperLimitExceededServer', { limit: MAX_PAPERS_PER_SOURCE_TASK })
      : createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error)
    : ''
  const createDisabled = !selectedTaskIds.length || createMutation.isPending || isCheckingPaperLimit || hasPaperLimitBlock || isCheckingTitleUniqueness || hasTitleConflict || titleCheckFailed

  const openTaskPapers = (taskId: string) => {
    navigate(`/papers?source_task_id=${encodeURIComponent(taskId)}`, {
      state: {
        sourceTaskId: taskId,
        sourceTaskName: tasksById.get(taskId)?.task_name ?? (taskId === initialTaskId ? initialTaskName : undefined),
      },
    })
  }

  const toggleTask = (taskId: string) => {
    setSelectedTaskIds((current) => {
      if (current.includes(taskId)) return current.filter((id) => id !== taskId)
      setSelectedRoles((roles) => ({ ...roles, [taskId]: current.length === 0 ? 'main' : 'baseline' }))
      return [...current, taskId]
    })
  }

  const updateRole = (taskId: string, role: TaskRole) => {
    setSelectedRoles((roles) => ({ ...roles, [taskId]: role }))
  }

  const handleCreate = () => {
    if (createDisabled) return
    const sourceTasks = selectedTaskIds.map((taskId, index) => ({
      task_id: taskId,
      role: selectedRoles[taskId] ?? (index === 0 ? 'main' : 'baseline'),
      label: tasksById.get(taskId)?.task_name ?? null,
    }))
    createMutation.mutate({
      title: trimmedTitle || null,
      paper_type: 'research_paper',
      language: 'en',
      source_tasks: sourceTasks,
      selected_templates: [template],
      include_external_validation: true,
      user_idea: idea.trim() || null,
    })
  }

  const openConfirmModal = () => {
    if (createDisabled) return
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
                            {!task.task_id.startsWith('extval_') ? <div className={cn('mt-1 text-xs', selected ? 'text-white/60' : 'text-slate-500')}>{task.task_id}</div> : null}
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

              {isCheckingPaperLimit ? (
                <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('paperAgent.new.paperLimitChecking')}
                </div>
              ) : null}

              {paperLimitQuery.error ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  {t('paperAgent.new.paperLimitCheckFailed')}
                </div>
              ) : null}

              {firstLimitedTaskId ? (
                <div className="flex flex-col gap-3 rounded-2xl border border-red-200 bg-red-50 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                    <div className="min-w-0">
                      <div className="font-semibold text-red-900">{t('paperAgent.new.paperLimitTitle', { limit: MAX_PAPERS_PER_SOURCE_TASK })}</div>
                      <div className="mt-1 text-sm leading-6 text-red-700">{paperLimitMessage}</div>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openTaskPapers(firstLimitedTaskId)}
                    className="shrink-0 bg-white"
                  >
                    {t('paperAgent.new.manageTaskPapers')}
                  </Button>
                </div>
              ) : null}
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
                  aria-invalid={hasTitleConflict || titleCheckFailed}
                  className={cn(
                    'w-full rounded-2xl border bg-white px-3 py-2.5 text-sm outline-none transition focus:ring-4',
                    hasTitleConflict || titleCheckFailed
                      ? 'border-red-300 focus:border-red-400 focus:ring-red-500/10'
                      : 'border-slate-200 focus:border-slate-400 focus:ring-sky-500/10',
                  )}
                />
                {isCheckingTitleUniqueness ? (
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {t('paperAgent.new.paperTitleChecking')}
                  </span>
                ) : null}
                {hasTitleConflict ? <span className="text-xs text-red-600">{t('paperAgent.new.paperTitleConflict')}</span> : null}
                {titleCheckFailed ? <span className="text-xs text-red-600">{t('paperAgent.new.paperTitleCheckFailed')}</span> : null}
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
	                  disabled={createDisabled}
	                >
	                  {createMutation.isPending || isCheckingPaperLimit || isCheckingTitleUniqueness ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
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
                      <div className="truncate text-sm font-semibold text-slate-950">{tasksById.get(taskId)?.task_name ?? (taskId === initialTaskId && initialTaskName ? initialTaskName : t('paperAgent.detail.tasks'))}</div>
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

	            {paperLimitMessage ? (
	              <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-700">
	                {paperLimitMessage}
	              </div>
	            ) : null}

	            {createErrorMessage ? (
	              <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{createErrorMessage}</div>
	            ) : null}
	          </div>

	          <div className="flex justify-end border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-6">
	            <Button variant="primary" className="gap-2" onClick={handleCreate} disabled={createDisabled}>
	              {createMutation.isPending || isCheckingPaperLimit || isCheckingTitleUniqueness ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
	              {t('paperAgent.new.confirmCreate')}
	            </Button>
          </div>
        </ModalShell>
      </div>
    </div>
  )
}
