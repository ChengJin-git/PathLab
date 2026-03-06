import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getTrainingTaskStorageInfo, TrainingTaskStorageInfo, cancelQueueTask, deleteTrainingTask, updateTrainingTaskName } from '../api'
import { ClipboardList, BarChart3, Microscope, Brain, Search, Clock, Loader2, CheckCircle2, XCircle, AlertCircle, Trash2, Copy, Layers, Timer, Activity, ArrowLeft, X, Sparkles, User, Edit2 } from 'lucide-react'
import { TASK_LIST_STATUS_BADGES, isActiveStatus, TRAINING_CANCELLABLE_STATUSES, VALIDATION_CANCELLABLE_STATUSES, CancellableStatus } from '../constants/status'
import { isSegFmEncoder } from '../constants/training'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { formatBytes } from '../lib/utils'

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

function isTaskCancellable(task: Task): boolean {
  const cancellableStatuses = task.task_type === 'external_validation'
    ? VALIDATION_CANCELLABLE_STATUSES
    : TRAINING_CANCELLABLE_STATUSES

  return cancellableStatuses.includes(task.status as CancellableStatus)
}

export default function TaskListPage() {
  const navigate = useNavigate()
  const { isAdmin, user } = useAuth()
  const { t } = useTranslation()

  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed' | 'cancelled'>('all')
  const [sortBy, setSortBy] = useState<'created' | 'updated' | 'name'>('updated')
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null)
  const [deleteMode, setDeleteMode] = useState<'standard' | 'complete'>('standard')
  const [taskStorageInfo, setTaskStorageInfo] = useState<TrainingTaskStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
  const [selectedTasks, setSelectedTasks] = useState<string[]>([])
  const [isBatchDelete, setIsBatchDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null)
  const [deletedTaskIds, setDeletedTaskIds] = useState<Set<string>>(new Set())

  // Edit task name modal states
  const [showEditModal, setShowEditModal] = useState(false)
  const [taskToEdit, setTaskToEdit] = useState<Task | null>(null)
  const [editedTaskName, setEditedTaskName] = useState('')
  const [isEditingSaving, setIsEditingSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const { rawTrainingTasks, subscribeTrainingSSE } = useBackgroundTask()

  // Subscribe to training SSE when this page is mounted
  useEffect(() => {
    const unsubscribe = subscribeTrainingSSE()
    return () => unsubscribe()
  }, [subscribeTrainingSSE])

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

  // Sync training tasks from BackgroundTaskContext SSE (avoids duplicate SSE connection)
  // Filter out tasks that have been deleted locally
  useEffect(() => {
    if (rawTrainingTasks !== null) {
      const filteredTasks = rawTrainingTasks.filter(t => !deletedTaskIds.has(t.task_id))
      setTasks(filteredTasks)
      setLoading(false)
    }
  }, [rawTrainingTasks, deletedTaskIds])

  const handleDeleteTask = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click
    setTaskToDelete(taskId)
    setTaskStorageInfo(null)
    setDeleteError(null)
    setDeleteMode('standard')
    setShowDeleteModal(true)

    // Load storage info
    setLoadingStorageInfo(true)
    try {
      const info = await getTrainingTaskStorageInfo(taskId)
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
  const handleSaveTaskName = async () => {
    if (!taskToEdit || !editedTaskName.trim()) {
      setEditError(t('taskList.editTaskNameEmpty'))
      return
    }

    setIsEditingSaving(true)
    setEditError(null)

    try {
      const updatedTask = await updateTrainingTaskName(taskToEdit.task_id, editedTaskName.trim())

      // Update local state immediately
      setTasks(prevTasks =>
        prevTasks.map(t =>
          t.task_id === taskToEdit.task_id
            ? { ...t, task_name: updatedTask.task_name, updated_at: updatedTask.updated_at }
            : t
        )
      )

      // Close modal
      setShowEditModal(false)
      setTaskToEdit(null)
    } catch (err: any) {
      console.error('Failed to update task name:', err)
      setEditError(err.message || t('taskList.editTaskNameFailed'))
    } finally {
      setIsEditingSaving(false)
    }
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedTasks(filteredTasks.map(t => t.task_id))
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

  const confirmDelete = async () => {
    if (!taskToDelete && !isBatchDelete) return

    // Determine which task IDs are being deleted
    const taskIdsToDelete = isBatchDelete ? selectedTasks : (taskToDelete ? [taskToDelete] : [])
    if (taskIdsToDelete.length === 0) return

    setIsDeleting(true)
    setDeleteError(null)

    try {
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

      // All deletions successful - update local state immediately
      setTasks(prev => prev.filter(t => !taskIdsToDelete.includes(t.task_id)))

      // Mark these tasks as deleted so they won't reappear from SSE updates
      setDeletedTaskIds(prev => {
        const newSet = new Set(prev)
        taskIdsToDelete.forEach(id => newSet.add(id))
        return newSet
      })

      // Clean up state
      if (isBatchDelete) {
        setSelectedTasks([])
        setIsBatchDelete(false)
      } else {
        setTaskToDelete(null)
      }

      setShowDeleteModal(false)
      setTaskStorageInfo(null)
      setDeleteMode('standard')
    } catch (error) {
      console.error('Failed to delete task:', error)
      setDeleteError(error instanceof Error ? error.message : t('taskList.deleteTaskFailed'))
    } finally {
      setIsDeleting(false)
    }
  }

  const getStatusBadge = (status: Task['status'], taskType?: string) => {
    const badge = TASK_LIST_STATUS_BADGES[status] ?? TASK_LIST_STATUS_BADGES.pending

    // Use the same taskList.progress keys that the progress section uses for active statuses,
    // so the badge label stays consistent with the progress label beneath it.
    let label: string
    if (taskType === 'external_validation') {
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
      if (status === 'pending' || status === 'queued') return <Clock className="w-3.5 h-3.5 mr-1" />
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

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-'
    // Fix case where both +00:00 and Z might be present from backend
    const sanitizedDate = dateStr.replace(/\+00:00Z$/, 'Z')
    // Ensure the date string is treated as UTC if no timezone is specified
    const normalizedDate = (!sanitizedDate.endsWith('Z') && !sanitizedDate.includes('+'))
      ? `${sanitizedDate}Z`
      : sanitizedDate
    const date = new Date(normalizedDate)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const filteredTasks = tasks.filter(task => {
    // Filter by status
    let statusMatch = true
    if (filter === 'running') statusMatch = isActiveStatus(task.status)
    else if (filter === 'completed') statusMatch = task.status === 'completed'
    else if (filter === 'failed') statusMatch = task.status === 'failed'
    else if (filter === 'cancelled') statusMatch = task.status === 'cancelled'

    // Filter by search query (task name or task ID)
    let searchMatch = true
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase().trim()
      searchMatch =
        task.task_name.toLowerCase().includes(query) ||
        task.task_id.toLowerCase().includes(query)
    }

    return statusMatch && searchMatch
  })

  const calculateDuration = (start: string | null, end: string | null, status: Task['status']) => {
    if (!start || !end) return t('taskList.na')
    if (isActiveStatus(status) || status === 'pending') return t('taskList.inProgress')
    const duration = new Date(end).getTime() - new Date(start).getTime()
    const hours = Math.floor(duration / (1000 * 60 * 60))
    const minutes = Math.floor((duration % (1000 * 60 * 60)) / (1000 * 60))
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m ${Math.floor((duration % (1000 * 60)) / 1000)}s`
  }

  const sortedTasks = [...filteredTasks].sort((a, b) => {
    if (sortBy === 'created') return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
    if (sortBy === 'updated') return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
    if (sortBy === 'name') return a.task_name.localeCompare(b.task_name)
    return 0
  })

  const stats = {
    total: tasks.length,
    running: tasks.filter(t => isActiveStatus(t.status)).length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length,
    cancelled: tasks.filter(t => t.status === 'cancelled').length
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
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 sm:gap-6 mb-4 sm:mb-8">
        <Card className="p-3 sm:p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-[10px] sm:text-xs md:text-sm font-medium text-gray-500 mb-0.5 sm:mb-2 uppercase tracking-tight sm:tracking-normal">{t('taskList.stats.totalTasks')}</div>
          <div className="text-xl sm:text-3xl font-semibold text-gray-900">{stats.total}</div>
        </Card>
        <Card className="p-3 sm:p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-[10px] sm:text-xs md:text-sm font-medium text-gray-500 mb-0.5 sm:mb-2 uppercase tracking-tight sm:tracking-normal">{t('taskList.stats.running')}</div>
          <div className="text-xl sm:text-3xl font-semibold text-purple-600">{stats.running}</div>
        </Card>
        <Card className="p-3 sm:p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-[10px] sm:text-xs md:text-sm font-medium text-gray-500 mb-0.5 sm:mb-2 uppercase tracking-tight sm:tracking-normal">{t('taskList.stats.completed')}</div>
          <div className="text-xl sm:text-3xl font-semibold text-green-600">{stats.completed}</div>
        </Card>
        <Card className="p-3 sm:p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-[10px] sm:text-xs md:text-sm font-medium text-gray-500 mb-0.5 sm:mb-2 uppercase tracking-tight sm:tracking-normal">{t('taskList.stats.failed')}</div>
          <div className="text-xl sm:text-3xl font-semibold text-red-600">{stats.failed}</div>
        </Card>
        <Card className="p-3 sm:p-6 overflow-visible shadow-sm border-gray-100 col-span-2 md:col-span-1">
          <div className="text-[10px] sm:text-xs md:text-sm font-medium text-gray-500 mb-0.5 sm:mb-2 text-center md:text-left uppercase tracking-tight sm:tracking-normal">{t('taskList.stats.cancelled')}</div>
          <div className="text-xl sm:text-3xl font-semibold text-gray-500 text-center md:text-left">{stats.cancelled}</div>
        </Card>
      </div>

      {/* Search Bar */}
      <div className="mb-4 sm:mb-6">
        <div className="relative w-full max-w-2xl mx-auto">
          <Search className="absolute left-3 sm:left-4 top-1/2 transform -translate-y-1/2 w-4 h-4 sm:w-5 sm:h-5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('taskList.searchPlaceholder')}
            className="w-full pl-9 sm:pl-12 pr-4 py-2 sm:py-3 bg-white border border-gray-200 rounded-xl shadow-sm focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-sm sm:text-base transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-3 sm:right-4 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title={t('taskList.clearSearch')}
            >
              <XCircle className="w-4 h-4 sm:w-5 sm:h-5" />
            </button>
          )}
        </div>
      </div>

      {/* Filters and Sort */}
      <div className="mb-4 sm:mb-6 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 sm:gap-4 sticky top-0 z-40 bg-gray-50/95 backdrop-blur py-2">
        <div className="flex items-center space-x-1 sm:space-x-2 bg-white/50 p-1 rounded-xl border border-gray-100 shadow-sm overflow-x-auto no-scrollbar">
          {(['all', 'running', 'completed', 'failed', 'cancelled'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 sm:px-4 py-1 sm:py-1.5 text-[11px] sm:text-sm font-semibold rounded-lg transition-all whitespace-nowrap ${filter === f
                ? 'bg-gray-900 text-white shadow-md'
                : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
                }`}
            >
              {t(`taskList.filters.${f}`)}
            </button>
          ))}
        </div>

        <div className="flex items-center justify-between sm:justify-end gap-3 sm:gap-6 bg-white sm:bg-transparent px-3 py-2 sm:p-0 rounded-xl border border-gray-100 sm:border-transparent">
          <div className="flex items-center gap-2 group cursor-pointer" onClick={() => toggleSelectAll(!(filteredTasks.length > 0 && selectedTasks.length === filteredTasks.length))}>
            <Checkbox
              checked={filteredTasks.length > 0 && selectedTasks.length === filteredTasks.length}
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
            <span className="text-[11px] sm:text-sm font-medium text-gray-400">{t('taskList.sort')}:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
              className="pl-1 pr-6 py-1 text-[11px] sm:text-sm font-bold border-none bg-transparent focus:ring-0 text-gray-700 cursor-pointer hover:bg-gray-100 rounded-md transition-colors"
              style={{ backgroundImage: 'none' }}
            >
              <option value="updated">{t('taskList.sortOptions.updated')}</option>
              <option value="created">{t('taskList.sortOptions.created')}</option>
              <option value="name">{t('taskList.sortOptions.name')}</option>
            </select>
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
      {loading ? (
        <Card className="p-12 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{t('taskList.loadingTasks')}</p>
        </Card>
      ) : sortedTasks.length === 0 ? (
        <Card className="p-12 text-center">
          <ClipboardList className="w-16 h-16 mx-auto mb-4 text-gray-400" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('taskList.noTasksFound')}</h3>
          <p className="text-gray-600 mb-6">
            {filter === 'all'
              ? t('taskList.createFirstTask')
              : t('taskList.noFilteredTasks', { filter: t(`taskList.filters.${filter}`) })}
          </p>
          <button
            onClick={() => navigate('/dashboard')}
            className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            {t('taskList.createNewTask')}
          </button>
        </Card>
      ) : (
        <div className="space-y-3 pb-8">
          {sortedTasks.map(task => (
            <Card
              key={task.task_id}
              className={`group p-4 sm:p-6 hover:shadow-lg transition-all cursor-pointer overflow-visible border-gray-100 ${selectedTasks.includes(task.task_id) ? 'ring-2 ring-gray-900 bg-gray-50' : 'bg-white'
                }`}
              onClick={() => navigate(`/task/${task.task_id}`)}
              style={{ borderRadius: '16px' }}
            >
              <div className="flex flex-col xl:flex-row xl:items-center gap-4 sm:gap-6">
                <div className="flex items-start gap-3 sm:gap-4 xl:w-1/4">
                  <div className="flex-shrink-0 pt-1" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedTasks.includes(task.task_id)}
                      onCheckedChange={(checked) => toggleSelectTask(task.task_id, checked as boolean)}
                      className="h-4 w-4 sm:h-5 sm:w-5 data-[state=checked]:bg-gray-900 data-[state=checked]:border-gray-900"
                    />
                  </div>

                  <div className="flex flex-col gap-1 sm:gap-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm sm:text-base font-bold text-gray-900 truncate max-w-[200px] sm:max-w-none" title={task.task_name}>{task.task_name}</h3>
                      <div className="sm:scale-90 origin-left">
                        {getStatusBadge(task.status, task.task_type)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] sm:text-xs text-gray-400 group/id">
                      <span className="font-mono truncate hover:text-gray-600 transition-colors max-w-[120px] sm:max-w-none" title={task.task_id}>
                        {task.task_id}
                      </span>
                      <div className="relative">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            if (navigator.clipboard && navigator.clipboard.writeText) {
                              navigator.clipboard.writeText(task.task_id)
                            } else {
                              // Fallback for Electron or non-secure contexts
                              const textArea = document.createElement('textarea')
                              textArea.value = task.task_id
                              textArea.style.position = 'fixed'
                              textArea.style.opacity = '0'
                              document.body.appendChild(textArea)
                              textArea.select()
                              document.execCommand('copy')
                              document.body.removeChild(textArea)
                            }
                            setCopiedId(task.task_id)
                            setTimeout(() => setCopiedId(null), 2000)
                          }}
                          className="sm:opacity-0 group-hover/id:opacity-100 p-1 hover:bg-gray-100 rounded transition-opacity"
                          title={t('taskList.copyId')}
                        >
                          <Copy className="w-3 h-3" />
                        </button>
                        {copiedId === task.task_id && (
                          <div className="absolute left-1/2 -translate-x-1/2 -top-8 px-2 py-1 bg-gray-900 text-white text-[10px] rounded shadow-lg animate-in fade-in slide-in-from-bottom-1 duration-200 z-10">
                            {t('taskList.copied')}
                          </div>
                        )}
                      </div>
                    </div>
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

                    {(() => {
                      const segBackbone = task.task_type === 'segmentation' ? (task.model_config as Record<string, unknown>)?.backbone as string : undefined
                      const segIsFm = isSegFmEncoder(segBackbone)
                      const col1Label = task.task_type === 'segmentation'
                        ? (segIsFm ? t('taskList.columns.featureExtractorSeg') : t('taskList.columns.backbone'))
                        : t('taskList.columns.extractor')
                      const col2Label = task.task_type === 'segmentation'
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
                                {task.task_type === 'segmentation'
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
                                {task.task_type === 'segmentation'
                                  ? (segIsFm
                                    ? t('taskDetail.configuration.convDecoder')
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
                          {task.task_type === 'external_validation'
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
                                width: `${task.data_type === 'patch' && task.task_type !== 'external_validation' && task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled'
                                  ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
                                  : task.progress}%`
                              }}
                            />
                          </div>
                          <span className="text-[11px] sm:text-sm font-bold text-gray-900 w-8 sm:w-10 text-right">
                            {task.data_type === 'patch' && task.task_type !== 'external_validation' && task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled'
                              ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
                              : task.progress}%
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
                    {user && (isAdmin || task.user_id === user.id) && (
                      <button
                        onClick={(e) => handleEditTask(task, e)}
                        className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-colors"
                        title={t('taskList.editTaskNameTitle')}
                      >
                        <Edit2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                      </button>
                    )}

                    {/* Cancel button - only for running/pending tasks */}
                    {isTaskCancellable(task) && (
                      <button
                        onClick={(e) => handleCancelTask(task.task_id, e)}
                        disabled={cancellingTaskId === task.task_id}
                        className="p-2 text-gray-400 hover:text-orange-600 hover:bg-orange-50 rounded-full transition-colors disabled:opacity-50"
                        title={t('taskList.cancelTask')}
                      >
                        {cancellingTaskId === task.task_id ? (
                          <Loader2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 animate-spin" />
                        ) : (
                          <X className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                        )}
                      </button>
                    )}

                    <button
                      onClick={(e) => handleDeleteTask(task.task_id, e)}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full transition-colors group/delete"
                      title={t('taskList.deleteTask')}
                    >
                      <Trash2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="text-center mb-4 sm:mb-6">
              <div className="w-12 h-12 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-3 sm:mb-4">
                <AlertCircle className="w-7 h-7 sm:w-10 sm:h-10 text-red-600" />
              </div>
              <h2 className="text-lg sm:text-2xl font-bold text-gray-900 leading-tight">
                {isBatchDelete ? t('taskList.deleteModal.batchTitle', { count: selectedTasks.length }) : t('taskList.deleteModal.singleTitle')}
              </h2>
              <p className="text-xs sm:text-sm text-gray-500 mt-1">{t('taskList.deleteModal.cannotBeUndone')}</p>
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
                      {formatBytes(displaySize)}
                    </span>
                  </div>
                  <details className="text-[11px] sm:text-sm">
                    <summary className="cursor-pointer text-blue-800 hover:text-blue-900 font-bold">
                      {t('taskList.deleteModal.files', { count: displayFiles })}
                    </summary>
                    <ul className="mt-2 space-y-1 text-blue-700/80 ml-4 border-l border-blue-100 pl-3">
                      {taskStorageInfo.training_dir.exists && (
                        <li>• {t('taskList.deleteModal.trainingData', { size: formatBytes(taskStorageInfo.training_dir.size) })}</li>
                      )}
                      {taskStorageInfo.training_logs.exists && (
                        <li>• {t('taskList.deleteModal.logs', { size: formatBytes(taskStorageInfo.training_logs.size) })}</li>
                      )}
                      {deleteMode === 'complete' && taskStorageInfo.models.length > 0 && (
                        <li>• {t('taskList.deleteModal.models', { size: formatBytes(modelsSize) })}</li>
                      )}
                    </ul>
                  </details>
                </div>
              )
            })()}

            {/* Delete Mode Selection */}
            <div className="mb-4">
              <label className="block text-[11px] sm:text-sm font-bold text-gray-700 mb-2">
                {t('taskList.deleteModal.deletionMode')}
              </label>
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
              <label className="block text-xs sm:text-sm font-medium text-gray-700 mb-2">
                {t('taskList.editModal.taskName')}
              </label>
              <input
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
                autoFocus
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
