import React, { useState, useEffect } from 'react'
import { useAsyncAction } from '../lib/useAsyncAction'
import { flushSync } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getTrainingTaskStorageInfo, TrainingTaskStorageInfo, cancelQueueTask, deleteTrainingTask, updateTrainingTaskName, getTrainingTasks, prefetchTrainingTasks, TrainingTaskListStats } from '../api'
import { ClipboardList, BarChart3, Microscope, Brain, Clock, Loader2, CheckCircle2, XCircle, AlertCircle, Trash2, Copy, Timer, ArrowLeft, X, Sparkles, User, Edit2, ChevronLeft, ChevronRight, FileText } from 'lucide-react'
import { TASK_LIST_STATUS_BADGES, isActiveStatus, TRAINING_CANCELLABLE_STATUSES, VALIDATION_CANCELLABLE_STATUSES } from '../constants/status'
import { isSegFmEncoder, isSegmentationTask } from '../constants/training'
import { PageHeader } from '../components/PageHeader'
import { Tooltip } from '../components/ui/tooltip'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'
import { Input } from '../components/ui/input'
import { Select } from '../components/ui/select'
import { EmptyStatePanel, SearchField, SegmentedControl, WorkspaceStatCard } from '../components/ui/workspace-primitives'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { formatFileSize } from '../lib/utils'
import {
  clearTrainingSubmissionRecord,
  isTrainingSubmissionPendingTimedOut,
  listTrainingSubmissionRecords,
  markTrainingSubmissionCancelled,
} from '../lib/trainingSubmissionTracker'

interface Task {
  task_id: string
  task_name: string
  task_type: string
  data_type: string
  status: string
  progress: number
  created_at: string | null
  updated_at: string | null
  wsi_count?: number
  preprocessing_config?: any
  model_config?: any
  user_id?: string | null  // User ID of task creator
  username?: string | null  // Username of task creator (only for admin users)
}

function isExternalValidationTask(task: Pick<Task, 'task_id'>): boolean {
  return task.task_id.startsWith('extval_')
}

function isTaskCancellable(task: Task): boolean {
  const cancellableStatuses = isExternalValidationTask(task)
    ? VALIDATION_CANCELLABLE_STATUSES
    : TRAINING_CANCELLABLE_STATUSES

  return (cancellableStatuses as readonly string[]).includes(task.status)
}

function isPaperSourceTask(task: Pick<Task, 'status' | 'task_type'>): boolean {
  return task.status === 'completed' && task.task_type !== 'batch_inference'
}

export default function TaskListPage() {
  const navigate = useNavigate()
  const { isAdmin, user } = useAuth()
  const { t } = useTranslation()
  const qc = useQueryClient()

  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed' | 'cancelled'>('all')
  const [sortBy, setSortBy] = useState<'created' | 'updated' | 'name'>('updated')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  const [currentPage, setCurrentPage] = useState(() => {
    const stored = sessionStorage.getItem('pathlab.taskList.page')
    return stored ? Math.max(1, parseInt(stored, 10)) : 1
  })
  const [pageInput, setPageInput] = useState(() => sessionStorage.getItem('pathlab.taskList.page') || '1')
  const [itemsPerPage, setItemsPerPage] = useState(() => {
    const stored = sessionStorage.getItem('pathlab.taskList.pageSize')
    return stored ? parseInt(stored, 10) : 5
  })
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null)
  const [deleteMode, setDeleteMode] = useState<'standard' | 'complete'>('standard')
  const [taskStorageInfo, setTaskStorageInfo] = useState<TrainingTaskStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
  const [selectedTasks, setSelectedTasks] = useState<string[]>([])
  const [isBatchDelete, setIsBatchDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isDeleting, runDeleting] = useAsyncAction({
    onError: (err) => setDeleteError(err instanceof Error ? err.message : t('taskList.deleteTaskFailed'))
  })
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null)
  const [submissionTaskRecords, setSubmissionTaskRecords] = useState(() => listTrainingSubmissionRecords(['pending', 'failed', 'cancelled']))
  const trainingTasksQuery = useQuery({
    queryKey: ['training-tasks', { page: currentPage, pageSize: itemsPerPage, search: debouncedSearchQuery, filter, sort: sortBy }],
    queryFn: async () => {
      const query = {
        page: currentPage,
        page_size: itemsPerPage,
        search: debouncedSearchQuery || undefined,
        status_filter: filter,
        sort_by: sortBy,
      } as const
      const response = await getTrainingTasks(query)
      const totalPages = Math.max(1, Math.ceil((response.total || 0) / itemsPerPage))
      if (currentPage > 1) {
        void prefetchTrainingTasks({ ...query, page: currentPage - 1, forceRefresh: false })
      }
      if (currentPage < totalPages) {
        void prefetchTrainingTasks({ ...query, page: currentPage + 1, forceRefresh: false })
      }
      return response
    },
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  })

  const tasks: Task[] = trainingTasksQuery.data?.items ?? []
  const totalCount: number = trainingTasksQuery.data?.total ?? 0
  const stats: TrainingTaskListStats = trainingTasksQuery.data?.stats ?? { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 }
  const loading = trainingTasksQuery.isLoading
  const isFetchingInBackground = trainingTasksQuery.isFetching && !trainingTasksQuery.isLoading

  const refreshTasks = React.useCallback(async ({ showLoadingSpinner: _show = true, forceRefresh = false }: { showLoadingSpinner?: boolean; forceRefresh?: boolean } = {}) => {
    if (forceRefresh) {
      await qc.invalidateQueries({ queryKey: ['training-tasks'] })
    }
  }, [qc])

  const [showEditModal, setShowEditModal] = useState(false)
  const [taskToEdit, setTaskToEdit] = useState<Task | null>(null)
  const [editedTaskName, setEditedTaskName] = useState('')
  const [isEditingSaving, runEditingSaving] = useAsyncAction({
    onError: (err: unknown) => setEditError((err as Error)?.message || t('taskList.editTaskNameFailed'))
  })
  const [editError, setEditError] = useState<string | null>(null)

  const { rawTrainingTasks, subscribeTrainingSSE } = useBackgroundTask()

  // Subscribe to training SSE when this page is mounted
  useEffect(() => {
    const unsubscribe = subscribeTrainingSSE()
    return () => unsubscribe()
  }, [subscribeTrainingSSE])

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery.trim())
    }, 300)

    return () => clearTimeout(timer)
  }, [searchQuery])

  // Handle cancel task
  const handleCancelTask = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setCancellingTaskId(taskId)
    try {
      await cancelQueueTask(taskId)
    } catch (error) {
      console.error('Failed to cancel task:', error)
    } finally {
      setCancellingTaskId(null)
    }
  }

  const handleNewPaperTask = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation()
    navigate(`/papers/new?task_id=${encodeURIComponent(task.task_id)}`, {
      state: {
        sourceTaskId: task.task_id,
        sourceTaskName: task.task_name,
      },
    })
  }

  useEffect(() => {
    if (rawTrainingTasks === null) return
    void qc.invalidateQueries({ queryKey: ['training-tasks'] })
  }, [rawTrainingTasks, qc])

  useEffect(() => {
    const refresh = () => {
      setSubmissionTaskRecords(listTrainingSubmissionRecords(['pending', 'failed', 'cancelled']))
    }

    refresh()
    window.addEventListener('focus', refresh)
    const intervalId = window.setInterval(refresh, 2000)
    return () => {
      window.removeEventListener('focus', refresh)
      window.clearInterval(intervalId)
    }
  }, [])

  const syntheticSubmissionTasks: Task[] = submissionTaskRecords
    .filter(record => {
      if (record.state !== 'pending') return true
      const timedOut = isTrainingSubmissionPendingTimedOut(record)
      if (timedOut) {
        clearTrainingSubmissionRecord(record.taskId)
      }
      return !timedOut
    })
    .map(record => ({
      task_id: record.taskId,
      task_name: record.taskName || record.taskId,
      task_type: 'wsi_classification',
      data_type: 'wsi',
      status: record.state === 'failed' ? 'failed' : record.state === 'cancelled' ? 'cancelled' : 'creating',
      progress: 0,
      created_at: new Date(record.createdAt).toISOString(),
      updated_at: new Date(record.updatedAt).toISOString(),
      wsi_count: 0,
    }))
    .filter(pendingTask => !tasks.some(task => task.task_id === pendingTask.task_id))

  const syntheticTaskIdSet = new Set(syntheticSubmissionTasks.map(task => task.task_id))
  const displayTasks = [...syntheticSubmissionTasks, ...tasks]

  const syntheticStats = syntheticSubmissionTasks.reduce(
    (acc, task) => {
      acc.total += 1
      if (task.status === 'failed') acc.failed += 1
      else if (task.status === 'cancelled') acc.cancelled += 1
      else acc.running += 1
      return acc
    },
    { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 }
  )

  const uiStats: TrainingTaskListStats = {
    total: stats.total + syntheticStats.total,
    running: stats.running + syntheticStats.running,
    completed: stats.completed + syntheticStats.completed,
    failed: stats.failed + syntheticStats.failed,
    cancelled: stats.cancelled + syntheticStats.cancelled,
  }
  const uiTotalCount = totalCount + syntheticStats.total

  useEffect(() => {
    sessionStorage.setItem('pathlab.taskList.page', String(currentPage))
  }, [currentPage])

  useEffect(() => {
    sessionStorage.setItem('pathlab.taskList.pageSize', String(itemsPerPage))
  }, [itemsPerPage])

  useEffect(() => {
    setSelectedTasks([])
  }, [currentPage, itemsPerPage, debouncedSearchQuery, filter, sortBy])

  const handleDeleteTask = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click

    // flushSync: React 18 automatic batching would defer setShowDeleteModal until
    // after the await below resolves, making the dialog appear frozen. Force flush
    // so the modal renders immediately before the network request starts.
    flushSync(() => {
      setTaskToDelete(taskId)
      setTaskStorageInfo(null)
      setDeleteError(null)
      setDeleteMode('standard')
      setShowDeleteModal(true)
      setLoadingStorageInfo(true)
    })

    try {
      const info = await getTrainingTaskStorageInfo(taskId, { quick: true })
      setTaskStorageInfo(info)
    } catch (err) {
      console.error('Failed to load storage info:', err)
    } finally {
      setLoadingStorageInfo(false)
    }
  }

  // Handle edit task name
  const handleEditTask = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click
    setTaskToEdit(task)
    setEditedTaskName(task.task_name)
    setEditError(null)
    setShowEditModal(true)
  }

  // Save edited task name
  const handleSaveTaskName = () => {
    if (!taskToEdit || !editedTaskName.trim()) {
      setEditError(t('taskList.editTaskNameEmpty'))
      return
    }
    setEditError(null)
    return runEditingSaving(async () => {
      await updateTrainingTaskName(taskToEdit.task_id, editedTaskName.trim())
      await qc.invalidateQueries({ queryKey: ['training-tasks'] })
      setShowEditModal(false)
      setTaskToEdit(null)
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedTasks(tasks.map(t => t.task_id))
    } else {
      setSelectedTasks([])
    }
  }

  const toggleSelectTask = (taskId: string, checked: boolean) => {
    if (checked) {
      setSelectedTasks(prev => [...prev, taskId])
    } else {
      setSelectedTasks(prev => prev.filter(id => id !== taskId))
    }
  }

  const handleBatchDeleteClick = () => {
    if (selectedTasks.length === 0) return
    setIsBatchDelete(true)
    setTaskToDelete(null)
    setTaskStorageInfo(null)
    setDeleteError(null)
    setDeleteMode('standard')
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (!taskToDelete && !isBatchDelete) return

    // Determine which task IDs are being deleted
    const taskIdsToDelete = isBatchDelete ? selectedTasks : (taskToDelete ? [taskToDelete] : [])
    if (taskIdsToDelete.length === 0) return

    setDeleteError(null)
    return runDeleting(async () => {
      // Delete tasks synchronously - cancel active tasks first, then delete
      for (const taskId of taskIdsToDelete) {
        const task = tasks.find(t => t.task_id === taskId)
        if (task && isTaskCancellable(task)) {
          try {
            await cancelQueueTask(taskId)
          } catch (cancelError) {
            console.warn(`Failed to cancel task ${taskId} before delete, continuing with delete`, cancelError)
          }
        }
        await deleteTrainingTask(taskId, deleteMode)
      }

      await refreshTasks({ showLoadingSpinner: false, forceRefresh: true })
      setSelectedTasks([])

      // Clean up state
      if (isBatchDelete) {
        setIsBatchDelete(false)
      } else {
        setTaskToDelete(null)
      }

      setShowDeleteModal(false)
      setTaskStorageInfo(null)
      setDeleteMode('standard')
    })
  }

  const getStatusBadge = (status: Task['status'], taskType?: string, isSyntheticTask?: boolean, isExternalValidation?: boolean) => {
    const badge = TASK_LIST_STATUS_BADGES[status] ?? TASK_LIST_STATUS_BADGES.pending

    // Use the same taskList.progress keys that the progress section uses for active statuses,
    // so the badge label stays consistent with the progress label beneath it.
    let label: string
    if (isSyntheticTask && status === 'creating') {
      label = t('taskList.progress.creatingTask')
    } else if (isExternalValidation) {
      // For validation tasks, 'training' status means "Running Inference"
      if (status === 'patching') label = t('taskList.progress.patching') 
      else if (status === 'extracting') label = t('taskList.progress.extracting')
      else if (status === 'training') label = t('taskList.progress.testing')
      else label = t(`backgroundTask.serverStatus.validation.${status}`, { defaultValue: badge.label })
    } else {
      if (status === 'patching') label = t('taskList.progress.patching')
      else if (status === 'extracting') label = t('taskList.progress.extracting')
      else if (status === 'training') label = t('taskList.progress.training')
      else label = t(`backgroundTask.serverStatus.training.${status}`, { defaultValue: badge.label })
    }

    // Determine icon based on status
    const getIcon = () => {
      if (status === 'pending' || status === 'queued' || status === 'creating') return <Clock className="w-3.5 h-3.5 mr-1" />
      if (isActiveStatus(status)) return <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
      if (status === 'completed') return <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
      return <XCircle className="w-3.5 h-3.5 mr-1" />
    }

    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.color}`}>
        {getIcon()}
        {label}
      </span>
    )
  }

  const calculateDuration = (start: string | null, end: string | null, status: Task['status']) => {
    if (!start || !end) return t('taskList.na')
    if (isActiveStatus(status) || status === 'pending') return t('taskList.inProgress')
    const duration = new Date(end).getTime() - new Date(start).getTime()
    const hours = Math.floor(duration / (1000 * 60 * 60))
    const minutes = Math.floor((duration % (1000 * 60 * 60)) / (1000 * 60))
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m ${Math.floor((duration % (1000 * 60)) / 1000)}s`
  }

  const totalPages = Math.max(1, Math.ceil(uiTotalCount / itemsPerPage))
  const paginationStart = uiTotalCount === 0 ? 0 : (currentPage - 1) * itemsPerPage + 1
  const paginationEnd = Math.min(currentPage * itemsPerPage, uiTotalCount)
  const allFilteredSelected = tasks.length > 0 && tasks.every(task => selectedTasks.includes(task.task_id))

  useEffect(() => {
    setCurrentPage(prev => Math.min(prev, totalPages))
  }, [totalPages])

  useEffect(() => {
    setPageInput(String(currentPage))
  }, [currentPage])

  const commitPageInput = (rawValue: string) => {
    const trimmed = rawValue.trim()
    if (!trimmed) { setPageInput(String(currentPage)); return }
    const parsed = Number.parseInt(trimmed, 10)
    if (Number.isNaN(parsed)) { setPageInput(String(currentPage)); return }
    const nextPage = Math.min(Math.max(parsed, 1), totalPages)
    setCurrentPage(nextPage)
    setPageInput(String(nextPage))
  }

  return (
    <div className="w-full">
      {/* Header */}
      <PageHeader
        title={t('taskList.title')}
        description={t('taskList.description')}
      >
        <Button
          variant="outline"
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('taskList.backToDashboard')}
        </Button>
        <Button
          onClick={() => navigate('/dashboard')}
          className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          <Sparkles className="w-4 h-4" />
          {t('taskList.newTask')}
        </Button>
      </PageHeader>

      {/* Statistics Cards */}
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5 sm:gap-6 sm:mb-8">
        <WorkspaceStatCard label={t('taskList.stats.totalTasks')} value={uiStats.total} accent="neutral" />
        <WorkspaceStatCard label={t('taskList.stats.running')} value={uiStats.running} accent="pathology" />
        <WorkspaceStatCard label={t('taskList.stats.completed')} value={uiStats.completed} accent="success" />
        <WorkspaceStatCard label={t('taskList.stats.failed')} value={uiStats.failed} accent="danger" />
        <WorkspaceStatCard label={t('taskList.stats.cancelled')} value={uiStats.cancelled} accent="system" className="col-span-2 md:col-span-1" />
      </div>

      {/* Search Bar */}
      <div className="mb-4 sm:mb-6">
        <SearchField
          value={searchQuery}
          onChange={(value) => {
            setSearchQuery(value)
            setCurrentPage(1)
          }}
          placeholder={t('taskList.searchPlaceholder')}
          clearButton={searchQuery ? (
            <Tooltip content={t('taskList.clearSearch')}>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('')
                  setCurrentPage(1)
                }}
                className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              >
                <XCircle className="w-4 h-4 sm:w-5 sm:h-5" />
              </button>
            </Tooltip>
          ) : undefined}
        />
      </div>

      {/* Filters and Sort */}
      <div className="sticky top-0 z-40 mb-4 flex flex-col gap-3 rounded-[1.5rem] border border-[color:var(--surface-border)] bg-[color:var(--surface-work)]/95 p-3 shadow-[var(--shadow-soft)] backdrop-blur md:flex-row md:items-center md:justify-between sm:mb-6 sm:gap-4 sm:p-4">
        <div className="overflow-x-auto no-scrollbar">
          <SegmentedControl
            value={filter}
            onChange={(value) => {
              setFilter(value as typeof filter)
              setCurrentPage(1)
            }}
            options={(['all', 'running', 'completed', 'failed', 'cancelled'] as const).map((item) => ({
              value: item,
              label: t(`taskList.filters.${item}`),
            }))}
          />
        </div>

        <div className="flex items-center justify-between gap-3 rounded-[1.1rem] border border-[color:var(--surface-border)] bg-white/70 px-3 py-2 sm:gap-6 sm:border-transparent sm:bg-transparent sm:p-0 sm:justify-end">
          <div className="flex items-center gap-2 group">
            <Checkbox
              checked={allFilteredSelected}
              onCheckedChange={toggleSelectAll}
              id="select-all"
              className="h-4 w-4 data-[state=checked]:bg-gray-900 data-[state=checked]:border-gray-900"
            />
            <label htmlFor="select-all" className="text-[11px] sm:text-sm font-bold text-gray-600 cursor-pointer select-none">
              {t('taskList.selectAll')}
            </label>
          </div>

          <div className="h-4 w-px bg-gray-200"></div>

          <div className="flex items-center space-x-1 sm:space-x-2">
            <span className="text-[11px] sm:text-sm font-medium text-gray-400">{t('taskList.pagination.itemsPerPage')}:</span>
            <Select
              value={String(itemsPerPage)}
              onChange={(value) => {
                setItemsPerPage(Number(value))
                setCurrentPage(1)
              }}
              options={[
                { value: '5', label: '5' },
                { value: '10', label: '10' },
                { value: '20', label: '20' },
              ]}
              className="w-[76px]"
              triggerClassName="h-7 sm:h-8 text-[11px] sm:text-sm font-bold border-gray-200"
              dropdownClassName="min-w-[76px]"
            />
          </div>

          <div className="h-4 w-px bg-gray-200"></div>

          <div className="flex items-center space-x-1 sm:space-x-2">
            <span className="text-[11px] sm:text-sm font-medium text-gray-400">{t('taskList.sort')}:</span>
            <Select
              value={sortBy}
              onChange={(value) => {
                setSortBy(value as typeof sortBy)
                setCurrentPage(1)
              }}
              options={[
                { value: 'updated', label: t('taskList.sortOptions.updated') },
                { value: 'created', label: t('taskList.sortOptions.created') },
                { value: 'name', label: t('taskList.sortOptions.name') },
              ]}
              className="w-[128px] sm:w-[156px]"
              triggerClassName="h-7 sm:h-8 text-[11px] sm:text-sm font-bold border-gray-200"
            />
          </div>

          {selectedTasks.length > 0 && (
            <>
              <div className="h-4 w-px bg-gray-200 hidden sm:block"></div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleBatchDeleteClick}
                className="text-red-600 hover:text-red-700 hover:bg-red-50 h-7 sm:h-8 px-2 text-[11px] sm:text-sm font-bold animate-in fade-in slide-in-from-right-4"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1" />
                {t('taskList.deleteCount', { count: selectedTasks.length })}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Task List */}
      {loading && displayTasks.length === 0 && uiTotalCount === 0 ? (
        <Card surface="elevated" className="p-12 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-slate-500">{t('taskList.loadingTasks')}</p>
        </Card>
      ) : displayTasks.length === 0 ? (
        <EmptyStatePanel
          title={t('taskList.noTasksFound')}
          description={filter === 'all'
            ? t('taskList.createFirstTask')
            : t('taskList.noFilteredTasks', { filter: t(`taskList.filters.${filter}`) })}
          tone="neutral"
          icon={<ClipboardList className="h-8 w-8" />}
          action={
            <Button onClick={() => navigate('/dashboard')} variant="primary">
              {t('taskList.createNewTask')}
            </Button>
          }
        />
      ) : (
        <div className="space-y-3 pb-8">
            {displayTasks.map(task => {
              const isSyntheticTask = syntheticTaskIdSet.has(task.task_id)
              const isExternalValidation = isExternalValidationTask(task)
              return (
            <Card
              key={task.task_id}
              className={`group p-4 sm:p-6 hover:shadow-lg transition-all cursor-pointer overflow-visible border-gray-100 ${selectedTasks.includes(task.task_id) ? 'ring-2 ring-gray-900 bg-gray-50' : 'bg-white'
                }`}
              onClick={() => navigate(`/task/${task.task_id}`)}
              style={{ borderRadius: '16px' }}
            >
              <div className="flex flex-col xl:flex-row xl:items-center gap-4 sm:gap-6">
                <div className="flex items-start gap-3 sm:gap-4 xl:w-1/4">
                  <div className="flex-shrink-0 pt-1">
                    <Checkbox
                      checked={selectedTasks.includes(task.task_id)}
                      onCheckedChange={(checked) => toggleSelectTask(task.task_id, checked as boolean)}
                      disabled={isSyntheticTask}
                      className="h-4 w-4 sm:h-5 sm:w-5 data-[state=checked]:bg-gray-900 data-[state=checked]:border-gray-900"
                    />
                  </div>

                  <div className="flex flex-col gap-1 sm:gap-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm sm:text-base font-bold text-gray-900 truncate max-w-[200px] sm:max-w-none" title={task.task_name}>{task.task_name}</h3>
                      <div className="sm:scale-90 origin-left">
                        {getStatusBadge(task.status, task.task_type, isSyntheticTask, isExternalValidation)}
                      </div>
                    </div>
                    {!isExternalValidation && <div className="flex items-center gap-2 text-[10px] sm:text-xs text-gray-400 group/id">
                      <span className="font-mono truncate hover:text-gray-600 transition-colors max-w-[120px] sm:max-w-none" title={task.task_id}>
                        {task.task_id}
                      </span>
                      <div className="relative">
                        <Tooltip content={t('taskList.copyId')}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              navigator.clipboard.writeText(task.task_id).catch(() => {})
                              setCopiedId(task.task_id)
                              setTimeout(() => setCopiedId(null), 2000)
                            }}
                            className="sm:opacity-0 group-hover/id:opacity-100 p-1 hover:bg-gray-100 rounded transition-opacity"
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                        </Tooltip>
                        {copiedId === task.task_id && (
                          <div className="absolute left-1/2 -translate-x-1/2 -top-8 px-2 py-1 bg-gray-900 text-white text-[10px] rounded shadow-lg animate-in fade-in slide-in-from-bottom-1 duration-200 z-10">
                            {t('taskList.copied')}
                          </div>
                        )}
                      </div>
                    </div>}
                    {isAdmin && task.username && (
                      <div className="flex items-center gap-1 text-[10px] sm:text-xs text-gray-400">
                        <User className="w-3 h-3 text-gray-300 flex-shrink-0" />
                        <span className="text-gray-400 truncate max-w-[150px]" title={task.username}>{task.username}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex-1 min-w-0 border-l border-gray-100 pl-4 sm:pl-6 xl:ml-0 overflow-hidden">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-y-3 sm:gap-y-4 gap-x-4 sm:gap-x-8 text-sm text-gray-600">

                    <div className="flex flex-col gap-0.5" title={t('taskList.columns.data')}>
                      <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskList.columns.data')}</span>
                      <div className="flex items-center gap-1.5 sm:gap-2">
                        <BarChart3 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-400" />
                        <span className="text-sm sm:text-base font-bold text-gray-900">{task.wsi_count}</span>
                        <span className="text-[11px] sm:text-sm text-gray-500">{task.data_type === 'patch' ? t('taskList.patches') : t('taskList.slides')}</span>
                      </div>
                    </div>

                    {task.task_type === 'batch_inference' ? (
                      <>
                        <div className="flex flex-col gap-0.5" title={t('taskList.columns.batchModel')}>
                          <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskList.columns.batchModel')}</span>
                          <div className="flex items-center gap-1.5 sm:gap-2">
                            <Brain className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-purple-400" />
                            <span className="text-sm sm:text-base font-bold truncate text-gray-900">
                              {(task.model_config as Record<string, unknown>)?.model_id as string || t('taskList.na')}
                            </span>
                          </div>
                        </div>
                        <div className="flex flex-col gap-0.5" title={t('taskList.columns.batchDataset')}>
                          <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskList.columns.batchDataset')}</span>
                          <div className="flex items-center gap-1.5 sm:gap-2">
                            <Microscope className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-purple-400" />
                            <span className="text-sm sm:text-base font-bold truncate text-gray-900">
                              {(task.model_config as Record<string, unknown>)?.dataset_id as string || t('taskList.na')}
                            </span>
                          </div>
                        </div>
                      </>
                    ) : (() => {
                      const isSegmentation = isSegmentationTask(task.task_type)
                      const segBackbone = isSegmentation ? (task.model_config as Record<string, unknown>)?.backbone as string : undefined
                      const segIsFm = isSegFmEncoder(segBackbone)
                      const fmDecoderType = ((task.model_config as Record<string, unknown>)?.decoder_type as string) || 'conv'
                      const col1Label = isSegmentation
                        ? (segIsFm ? t('taskList.columns.featureExtractorSeg') : t('taskList.columns.backbone'))
                        : t('taskList.columns.extractor')
                      const col2Label = isSegmentation
                        ? (segIsFm ? t('taskList.columns.decoder') : t('taskList.columns.architecture'))
                        : t('taskList.columns.model')
                      return (
                        <>
                          <div className="flex flex-col gap-0.5" title={col1Label}>
                            <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">
                              {col1Label}
                            </span>
                            <div className="flex items-center gap-1.5 sm:gap-2">
                              <Microscope className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-400" />
                              <span className="text-sm sm:text-base font-bold truncate text-gray-900">
                                {isSegmentation
                                  ? (segBackbone || t('taskList.na'))
                                  : (task.preprocessing_config?.feature_extractor || t('taskList.na'))}
                              </span>
                            </div>
                          </div>

                          <div className="flex flex-col gap-0.5" title={col2Label}>
                            <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">
                              {col2Label}
                            </span>
                            <div className="flex items-center gap-1.5 sm:gap-2">
                              <Brain className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-400" />
                              <span className="text-sm sm:text-base font-bold truncate text-gray-900">
                                {isSegmentation
                                  ? (segIsFm
                                    ? t(`training.modelConfig.decoder.${fmDecoderType}`, fmDecoderType.toUpperCase())
                                    : ((task.model_config as Record<string, unknown>)?.architecture as string || t('taskList.na')))
                                  : task.data_type === 'patch'
                                    ? t(`taskList.classifiers.${(task.model_config as Record<string, unknown>)?.classifier || 'linear'}`, t('taskList.linearProbe'))
                                    : (task.model_config?.aggregator?.toUpperCase() || t('taskList.na'))}
                              </span>
                            </div>
                          </div>
                        </>
                      )
                    })()}

                    {(task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') ? (
                      <div className="flex flex-col gap-0.5" title={t('taskList.columns.duration')}>
                        <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskList.columns.duration')}</span>
                        <div className="flex items-center gap-1.5 sm:gap-2">
                          <Timer className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-400" />
                          <span className="text-sm sm:text-base font-bold text-gray-900">{calculateDuration(task.created_at, task.updated_at, task.status)}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-0.5 w-full col-span-2 md:col-span-1">
                        <span className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider">
                          {isSyntheticTask && task.status === 'creating'
                            ? t('taskList.progress.creatingTask')
                            : isExternalValidation
                            ? (task.status === 'patching' ? t('taskList.progress.patching') :
                              task.status === 'extracting' ? t('taskList.progress.extracting') :
                              task.status === 'training' ? t('taskList.progress.testing') : t('taskList.progress.progress'))
                            : (task.status === 'patching' ? t('taskList.progress.patching') :
                              task.status === 'extracting' ? t('taskList.progress.extracting') :
                                task.status === 'training' ? t('taskList.progress.training') : t('taskList.progress.progress'))}
                        </span>
                        <div className="flex items-center gap-2 w-full mt-1">
                          <div className="w-full bg-gray-100 rounded-full h-1.5 sm:h-2 overflow-hidden flex-1">
                            <div
                              className="bg-gray-900 h-full rounded-full transition-all duration-300"
                              style={{
                                width: `${Math.max(0, Math.min(task.progress, 100))}%`
                              }}
                            />
                          </div>
                          <span className="text-[11px] sm:text-sm font-bold text-gray-900 w-8 sm:w-10 text-right">
                            {Math.max(0, Math.min(task.progress, 100))}%
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex xl:flex-col items-center xl:items-end justify-between xl:justify-center gap-3 sm:gap-4 xl:w-32 xl:border-l xl:border-gray-100 xl:pl-6 pt-3 sm:pt-4 xl:pt-0 border-t xl:border-t-0 border-gray-50/50 mt-1 sm:mt-2 xl:mt-0">
                  <div className="flex flex-col gap-2 text-[10px] sm:text-xs text-gray-400 text-left xl:text-right">
                    <div className="flex flex-col">
                      <span className="font-medium text-gray-500">{task.updated_at ? new Date(task.updated_at).toLocaleDateString() : t('taskList.na')}</span>
                      <span className="text-[9px] sm:text-[10px] text-gray-300 uppercase tracking-wide">{t('taskList.updated')}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    {/* Edit button - only for task creator or admin */}
                    {!isSyntheticTask && user && (isAdmin || task.user_id === user.id) && (
                      <Tooltip content={t('taskList.editTaskNameTitle')}>
                        <button
                          type="button"
                          onClick={(e) => handleEditTask(task, e)}
                          className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-colors"
                        >
                          <Edit2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        </button>
                      </Tooltip>
                    )}

                    {/* Cancel button - only for running/pending tasks */}
                    {(isSyntheticTask && task.status === 'creating') && (
                      <Tooltip content={t('taskList.cancelTask')}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            markTrainingSubmissionCancelled(task.task_id)
                            setSubmissionTaskRecords(listTrainingSubmissionRecords(['pending', 'failed', 'cancelled']))
                          }}
                          className="p-2 text-gray-400 hover:text-orange-600 hover:bg-orange-50 rounded-full transition-colors"
                        >
                          <X className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        </button>
                      </Tooltip>
                    )}

                    {!isSyntheticTask && isTaskCancellable(task) && (
                      <Tooltip content={t('taskList.cancelTask')}>
                        <button
                          type="button"
                          onClick={(e) => handleCancelTask(task.task_id, e)}
                          disabled={cancellingTaskId === task.task_id}
                          className="p-2 text-gray-400 hover:text-orange-600 hover:bg-orange-50 rounded-full transition-colors disabled:opacity-50"
                        >
                          {cancellingTaskId === task.task_id ? (
                            <Loader2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 animate-spin" />
                          ) : (
                            <X className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                          )}
                        </button>
                      </Tooltip>
                    )}

                    {!isSyntheticTask && isPaperSourceTask(task) && (
                      <Tooltip content={t('taskList.newPaper')}>
                        <button
                          type="button"
                          onClick={(e) => handleNewPaperTask(task, e)}
                          className="p-2 text-gray-400 hover:text-sky-700 hover:bg-sky-50 rounded-full transition-colors"
                        >
                          <FileText className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        </button>
                      </Tooltip>
                    )}

                    {!isSyntheticTask && (
                      <Tooltip content={t('taskList.deleteTask')}>
                        <button
                          type="button"
                          onClick={(e) => handleDeleteTask(task.task_id, e)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full transition-colors group/delete"
                        >
                          <Trash2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        </button>
                      </Tooltip>
                    )}

                    {isSyntheticTask && (
                      <Tooltip content={t('taskList.deleteTask')}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            clearTrainingSubmissionRecord(task.task_id)
                            setSubmissionTaskRecords(listTrainingSubmissionRecords(['pending', 'failed', 'cancelled']))
                          }}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full transition-colors group/delete"
                        >
                          <Trash2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        </button>
                      </Tooltip>
                    )}
                  </div>
                </div>
              </div>
            </Card>
            )
          })}

            <Card surface="elevated" className="border-[color:var(--surface-border)] bg-white/90">
            <div className="px-4 sm:px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="text-xs sm:text-sm text-gray-500 font-medium text-center sm:text-left flex items-center gap-2">
                <span>{t('taskList.pagination.summary', {
                  start: paginationStart,
                  end: paginationEnd,
                  total: uiTotalCount,
                })}</span>
                {isFetchingInBackground && uiTotalCount > 0 && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />
                )}
              </div>

              <div className="flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
                {totalPages > 1 && (
                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">
                      {t('taskList.pagination.goToPage')}
                    </span>
                    <Input
                      value={pageInput}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPageInput(e.target.value.replace(/[^0-9]/g, ''))}
                      onBlur={() => commitPageInput(pageInput)}
                      onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                        if (e.key === 'Enter') { e.preventDefault(); commitPageInput(pageInput) }
                        if (e.key === 'Escape') setPageInput(String(currentPage))
                      }}
                      inputMode="numeric"
                      aria-label={t('taskList.pagination.goToPage')}
                      className="h-8 w-16 px-2 text-center text-xs sm:text-sm"
                    />
                    <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">/ {totalPages}</span>
                  </div>
                )}

                <div className="flex items-center gap-2 sm:gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                    disabled={currentPage === 1}
                    className="h-8 px-2 sm:px-3"
                  >
                    <ChevronLeft className="w-4 h-4 sm:mr-1" />
                    <span className="hidden sm:inline">{t('common.previous')}</span>
                  </Button>

                  <span className="text-xs sm:text-sm font-semibold text-gray-600 min-w-[88px] text-center">
                    {t('taskList.pagination.pageInfo', { current: currentPage, total: totalPages })}
                  </span>

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                    disabled={currentPage === totalPages}
                    className="h-8 px-2 sm:px-3"
                  >
                    <span className="hidden sm:inline">{t('common.next')}</span>
                    <ChevronRight className="w-4 h-4 sm:ml-1" />
                  </Button>
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="mb-4 flex flex-col items-center text-center sm:mb-6">
              <div className="w-12 h-12 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-3 sm:mb-4">
                <AlertCircle className="w-7 h-7 sm:w-10 sm:h-10 text-red-600" />
              </div>
              <h2 className="w-full text-center text-lg sm:text-2xl font-bold text-gray-900 leading-tight">
                {isBatchDelete ? t('taskList.deleteModal.batchTitle', { count: selectedTasks.length }) : t('taskList.deleteModal.singleTitle')}
              </h2>
              <p className="mt-1 w-full text-center text-xs sm:text-sm text-gray-500">{t('taskList.deleteModal.cannotBeUndone')}</p>
            </div>

            {/* Batch Delete Warning */}
            {isBatchDelete && (
              <div className="bg-orange-50 border border-orange-200 rounded-xl p-3 sm:p-4 mb-3 sm:mb-4">
                <p className="text-[11px] sm:text-sm text-orange-800 leading-relaxed">
                  {t('taskList.deleteModal.batchWarning', { count: selectedTasks.length })}
                </p>
              </div>
            )}

            {/* Storage Info (Single Task Only) */}
            {!isBatchDelete && loadingStorageInfo && (
              <div className="flex items-center justify-center py-4 mb-3 sm:mb-4">
                <Loader2 className="w-4 h-4 animate-spin text-blue-600 mr-2" />
                <span className="text-xs sm:text-sm text-gray-600 font-medium">{t('taskList.deleteModal.loadingStorageInfo')}</span>
              </div>
            )}

            {!isBatchDelete && taskStorageInfo && !loadingStorageInfo && (() => {
              if (taskStorageInfo.quick) {
                const quickDeleteItems = [
                  taskStorageInfo.training_dir.exists && 'trainingDataQuick',
                  taskStorageInfo.ai_results.exists && 'aiResultsQuick',
                  taskStorageInfo.training_logs.exists && 'logsQuick',
	                  taskStorageInfo.analysis_logs.exists && 'analysisLogsQuick',
	                  deleteMode === 'complete' && taskStorageInfo.models.some(model => model.exists) && 'modelsQuick',
	                  deleteMode === 'complete' && 'papersQuick',
	                ].filter(Boolean) as string[]

                return (
                  <div className="bg-sky-50/70 border border-sky-100 rounded-xl p-3 sm:p-4 mb-3 sm:mb-4">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.12)]" />
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] sm:text-xs leading-relaxed text-sky-800/80">
                          {t(deleteMode === 'complete' ? 'taskList.deleteModal.quickScopeCompleteDesc' : 'taskList.deleteModal.quickScopeStandardDesc')}
                        </p>
                        <ul className="mt-3 grid gap-1.5 text-[10px] sm:text-xs text-sky-900">
                          {quickDeleteItems.map(itemKey => (
                            <li key={itemKey} className="flex items-center gap-2">
                              <span className="h-1.5 w-1.5 rounded-full bg-sky-500" />
                              <span>{t(`taskList.deleteModal.${itemKey}`)}</span>
                            </li>
                          ))}
	                          {deleteMode === 'standard' && taskStorageInfo.models.some(model => model.exists) && (
	                            <li className="flex items-center gap-2 text-emerald-700">
	                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
	                              <span>{t('taskList.deleteModal.modelsKeptQuick')}</span>
	                            </li>
	                          )}
	                          {deleteMode === 'standard' && (
	                            <li className="flex items-center gap-2 text-emerald-700">
	                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
	                              <span>{t('taskList.deleteModal.papersKeptQuick')}</span>
	                            </li>
	                          )}
                        </ul>
                      </div>
                    </div>
                  </div>
                )
              }

              // Calculate size and file count based on delete mode
              const modelsSize = taskStorageInfo.models.reduce((sum, m) => sum + m.size, 0)
              const modelsCount = taskStorageInfo.models.reduce((sum, m) => sum + m.file_count, 0)
              const displaySize = deleteMode === 'complete' ? taskStorageInfo.total_size : taskStorageInfo.total_size - modelsSize
              const displayFiles = deleteMode === 'complete' ? taskStorageInfo.total_files : taskStorageInfo.total_files - modelsCount
              return (
                <div className="bg-blue-50/50 border border-blue-100 rounded-xl p-3 sm:p-4 mb-3 sm:mb-4">
                  <div className="flex items-center justify-between mb-2 sm:mb-3">
                    <span className="text-[11px] sm:text-sm font-semibold text-blue-900">{t('taskList.deleteModal.freesSurface')}:</span>
                    <span className="text-base sm:text-lg font-bold text-blue-900">
                      {formatFileSize(displaySize)}
                    </span>
                  </div>
                  <details className="text-[11px] sm:text-sm">
                    <summary className="cursor-pointer text-blue-800 hover:text-blue-900 font-bold">
                      {t('taskList.deleteModal.files', { count: displayFiles })}
                    </summary>
                    <ul className="mt-2 space-y-1 text-blue-700/80 ml-4 border-l border-blue-100 pl-3">
                      {taskStorageInfo.training_dir.exists && (
                        <li>• {t('taskList.deleteModal.trainingData', { size: formatFileSize(taskStorageInfo.training_dir.size) })}</li>
                      )}
                      {taskStorageInfo.ai_results.exists && (
                        <li>• {t('taskList.deleteModal.aiResults', { size: formatFileSize(taskStorageInfo.ai_results.size) })}</li>
                      )}
                      {taskStorageInfo.training_logs.exists && (
                        <li>• {t('taskList.deleteModal.logs', { size: formatFileSize(taskStorageInfo.training_logs.size) })}</li>
                      )}
                      {taskStorageInfo.analysis_logs.exists && (
                        <li>• {t('taskList.deleteModal.analysisLogs', { size: formatFileSize(taskStorageInfo.analysis_logs.size) })}</li>
                      )}
                      {deleteMode === 'complete' && taskStorageInfo.models.length > 0 && (
                        <li>• {t('taskList.deleteModal.models', { size: formatFileSize(modelsSize) })}</li>
                      )}
                    </ul>
                  </details>
                </div>
              )
            })()}

            {/* Delete Mode Selection */}
            <div className="mb-4">
              <div className="block text-[11px] sm:text-sm font-bold text-gray-700 mb-2">
                {t('taskList.deleteModal.deletionMode')}
              </div>
              <div className="space-y-2">
                <label className={`flex items-start gap-3 p-2 sm:p-3 border-2 rounded-xl cursor-pointer hover:bg-gray-50 transition-all ${deleteMode === 'standard' ? 'border-blue-500 bg-blue-50/20' : 'border-gray-100'}`}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="standard"
                    checked={deleteMode === 'standard'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-blue-600"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-gray-900 text-sm">{t('taskList.deleteModal.standardMode')}</div>
                    <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                      {t('taskList.deleteModal.standardDesc')}
                      <span className="text-blue-600 font-semibold"> {t('taskList.deleteModal.keepsModels')}</span>.
                    </div>
                  </div>
                </label>

                <label className={`flex items-start gap-3 p-2 sm:p-3 border-2 rounded-xl cursor-pointer hover:bg-gray-50 transition-all ${deleteMode === 'complete' ? 'border-red-500 bg-red-50/20' : 'border-gray-100'}`}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="complete"
                    checked={deleteMode === 'complete'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-red-600"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-gray-900 text-sm">{t('taskList.deleteModal.completeMode')}</div>
                    <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                      {t('taskList.deleteModal.completeDesc')}
                      <strong className="text-red-600"> {t('taskList.deleteModal.irreversible')}</strong>
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteModal(false)
                  setTaskToDelete(null)
                  setTaskStorageInfo(null)
                  setIsBatchDelete(false)
                  setDeleteMode('standard')
                  setDeleteError(null)
                }}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 sm:py-2.5 bg-white border border-gray-300 text-gray-700 text-xs sm:text-sm font-bold rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={isDeleting}
                className="flex-1 px-4 py-2 sm:py-2.5 bg-red-600 text-white text-xs sm:text-sm font-bold rounded-lg hover:bg-red-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('taskList.deleting')}
                  </>
                ) : (
                  t('common.delete')
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Task Name Modal */}
      {showEditModal && taskToEdit && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6">
            {/* Header */}
            <div className="mb-4 sm:mb-6">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 sm:w-12 sm:h-12 bg-indigo-100 rounded-full flex items-center justify-center">
                  <Edit2 className="w-5 h-5 sm:w-6 sm:h-6 text-indigo-600" />
                </div>
                <h2 className="text-lg sm:text-xl font-bold text-gray-900">{t('taskList.editModal.title')}</h2>
              </div>
              <p className="text-xs sm:text-sm text-gray-500 ml-13 sm:ml-15">
                {t('taskList.editModal.subtitle')}
              </p>
            </div>

            {/* Input */}
            <div className="mb-4 sm:mb-6">
              <label htmlFor="edit-task-name" className="block text-xs sm:text-sm font-medium text-gray-700 mb-2">
                {t('taskList.editModal.taskName')}
              </label>
              <input
                id="edit-task-name"
                type="text"
                value={editedTaskName}
                onChange={(e) => setEditedTaskName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !isEditingSaving) {
                    handleSaveTaskName()
                  }
                }}
                className="w-full px-3 sm:px-4 py-2 sm:py-2.5 text-sm sm:text-base border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
                placeholder={t('taskList.editModal.placeholder')}
                disabled={isEditingSaving}
              />
            </div>

            {/* Error Message */}
            {editError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-xs sm:text-sm text-red-800">{editError}</p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2 sm:gap-3">
              <button
                type="button"
                onClick={() => {
                  setShowEditModal(false)
                  setTaskToEdit(null)
                  setEditError(null)
                }}
                disabled={isEditingSaving}
                className="flex-1 px-4 py-2 sm:py-2.5 bg-gray-100 text-gray-700 text-xs sm:text-sm font-semibold rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={handleSaveTaskName}
                disabled={isEditingSaving || !editedTaskName.trim()}
                className="flex-1 px-4 py-2 sm:py-2.5 bg-indigo-600 text-white text-xs sm:text-sm font-bold rounded-lg hover:bg-indigo-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {isEditingSaving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('taskList.saving')}
                  </>
                ) : (
                  t('common.save')
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
