import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { TFunction } from 'i18next'
import { Loader2, History, CheckCircle2, XCircle, Clock, PlayCircle, AlertCircle, RefreshCw, ChevronRight, Edit2 } from 'lucide-react'
import { getTrainingTasks, TrainingTask, updateTrainingTaskName } from '../../api'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

export interface CachedTaskData {
  task_id: string
  task_name: string
  task_type: string
  data_type: string
  status: string
  created_at: string | null
  finished_at: string | null
  num_classes?: number
  split_strategy?: string
}

export interface AgentTaskHistoryConfig {
  show_completed?: boolean
  show_running?: boolean
  show_failed?: boolean
  limit?: number
  split_strategy?: 'random' | 'k_fold' | 'manual'
  task_type?: string
  cached_tasks?: CachedTaskData[]
  cached_at?: string
}

interface TaskHistoryCardProps {
  config: AgentTaskHistoryConfig
  onError?: (error: string) => void
  onDataLoaded?: (tasks: CachedTaskData[]) => void
}

export function parseTaskHistoryConfig(content: string): AgentTaskHistoryConfig | null {
  const match = content.match(/\[TASK_HISTORY_CONFIG\]([\s\S]*?)\[\/TASK_HISTORY_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

export function removeTaskHistoryConfigBlock(content: string): string {
  return content.replace(/\[TASK_HISTORY_CONFIG\][\s\S]*?\[\/TASK_HISTORY_CONFIG\]/g, '').trim()
}

function getStatusDisplay(status: string, t: TFunction) {
  switch (status) {
    case 'completed':
      return { icon: <CheckCircle2 className="w-4 h-4" />, color: 'text-green-600 bg-green-50', label: t('chatComponents.taskHistory.statusCompleted') }
    case 'running':
    case 'training':
    case 'preprocessing':
    case 'extracting':
      return { icon: <PlayCircle className="w-4 h-4" />, color: 'text-blue-600 bg-blue-50', label: t('chatComponents.taskHistory.statusRunning') }
    case 'pending':
    case 'queued':
      return { icon: <Clock className="w-4 h-4" />, color: 'text-amber-600 bg-amber-50', label: t('chatComponents.taskHistory.statusPending') }
    case 'failed':
      return { icon: <XCircle className="w-4 h-4" />, color: 'text-red-600 bg-red-50', label: t('chatComponents.taskHistory.statusFailed') }
    case 'cancelled':
      return { icon: <XCircle className="w-4 h-4" />, color: 'text-gray-500 bg-gray-50', label: t('chatComponents.taskHistory.statusCancelled') }
    default:
      return { icon: <Clock className="w-4 h-4" />, color: 'text-gray-600 bg-gray-50', label: status }
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export function TaskHistoryCard({ config, onError, onDataLoaded }: TaskHistoryCardProps) {
  const { t } = useTranslation()
  const hasCachedData = config.cached_tasks && config.cached_tasks.length > 0

  const [isLoading, setIsLoading] = useState(!hasCachedData)
  const [error, setError] = useState<string>('')
  const [tasks, setTasks] = useState<TrainingTask[]>(
    hasCachedData ? (config.cached_tasks as unknown as TrainingTask[]) : []
  )
  const navigate = useNavigate()
  const { user } = useAuth()

  const [showEditModal, setShowEditModal] = useState(false)
  const [taskToEdit, setTaskToEdit] = useState<TrainingTask | null>(null)
  const [editedTaskName, setEditedTaskName] = useState('')
  const [isEditingSaving, setIsEditingSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const onDataLoadedRef = useRef(onDataLoaded)
  onDataLoadedRef.current = onDataLoaded

  const showCompleted = config.show_completed ?? true
  const showRunning = config.show_running ?? true
  const showFailed = config.show_failed ?? false
  const limit = config.limit ?? 10
  const splitStrategyFilter = config.split_strategy
  const taskTypeFilter = config.task_type

  const getTaskSplitStrategy = (task: TrainingTask | CachedTaskData): string => {
    if ('split_strategy' in task && task.split_strategy) {
      return task.split_strategy
    }
    if ('preprocessing_config' in task && task.preprocessing_config) {
      const splitConfig = task.preprocessing_config?.split_config as { strategy?: string } | undefined
      return splitConfig?.strategy || 'random'
    }
    return 'random'
  }

  const toCachedData = (task: TrainingTask): CachedTaskData => ({
    task_id: task.task_id,
    task_name: task.task_name,
    task_type: task.task_type,
    data_type: task.data_type,
    status: task.status,
    created_at: task.created_at,
    finished_at: task.finished_at,
    num_classes: task.classes?.length,
    split_strategy: getTaskSplitStrategy(task)
  })

  const getNumClasses = (task: TrainingTask | CachedTaskData): number => {
    if ('classes' in task && task.classes) {
      return task.classes.length
    }
    if ('num_classes' in task && typeof task.num_classes === 'number') {
      return task.num_classes
    }
    return 0
  }

  useEffect(() => {
    if (hasCachedData) {
      return
    }

    const fetchData = async () => {
      setIsLoading(true)
      setError('')

      try {
        const allTasks = await getTrainingTasks()

        const inProgressStatuses = ['running', 'training', 'pending', 'queued', 'preprocessing', 'extracting']

        const filteredTasks = allTasks.filter(task => {
          let statusMatch = false
          if (task.status === 'completed' && showCompleted) statusMatch = true
          if (inProgressStatuses.includes(task.status) && showRunning) statusMatch = true
          if (task.status === 'failed' && showFailed) statusMatch = true
          if (!statusMatch) return false

          if (splitStrategyFilter && getTaskSplitStrategy(task) !== splitStrategyFilter) return false

          if (taskTypeFilter && task.task_type !== taskTypeFilter) return false

          return true
        })

        const sortedTasks = filteredTasks
          .sort((a, b) => {
            const dateA = a.created_at ? new Date(a.created_at).getTime() : 0
            const dateB = b.created_at ? new Date(b.created_at).getTime() : 0
            return dateB - dateA
          })
          .slice(0, limit)

        setTasks(sortedTasks)

        if (onDataLoadedRef.current) {
          onDataLoadedRef.current(sortedTasks.map(toCachedData))
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : t('chatComponents.taskHistory.errors.failedToFetch')
        setError(msg)
        onErrorRef.current?.(msg)
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [showCompleted, showRunning, showFailed, limit, splitStrategyFilter, taskTypeFilter, hasCachedData])

  const handleRefresh = async () => {
    setIsLoading(true)
    setError('')
    try {
      const allTasks = await getTrainingTasks()
      const inProgressStatuses = ['running', 'training', 'pending', 'queued', 'preprocessing', 'extracting']
      const filteredTasks = allTasks.filter(task => {
        let statusMatch = false
        if (task.status === 'completed' && showCompleted) statusMatch = true
        if (inProgressStatuses.includes(task.status) && showRunning) statusMatch = true
        if (task.status === 'failed' && showFailed) statusMatch = true
        if (!statusMatch) return false

        if (splitStrategyFilter && getTaskSplitStrategy(task) !== splitStrategyFilter) return false

        if (taskTypeFilter && task.task_type !== taskTypeFilter) return false

        return true
      })
      const sortedTasks = filteredTasks
        .sort((a, b) => {
          const dateA = a.created_at ? new Date(a.created_at).getTime() : 0
          const dateB = b.created_at ? new Date(b.created_at).getTime() : 0
          return dateB - dateA
        })
        .slice(0, limit)
      setTasks(sortedTasks)

      if (onDataLoadedRef.current) {
        onDataLoadedRef.current(sortedTasks.map(toCachedData))
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('chatComponents.taskHistory.errors.failedToFetch')
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleEditTask = (task: TrainingTask, e: React.MouseEvent) => {
    e.stopPropagation()
    setTaskToEdit(task)
    setEditedTaskName(task.task_name)
    setEditError(null)
    setShowEditModal(true)
  }

  const handleSaveTaskName = async () => {
    if (!taskToEdit || !editedTaskName.trim()) {
      setEditError(t('chatComponents.taskHistory.errors.taskNameEmpty'))
      return
    }

    setIsEditingSaving(true)
    setEditError(null)

    try {
      const updatedTask = await updateTrainingTaskName(taskToEdit.task_id, editedTaskName.trim())

      setTasks(prevTasks =>
        prevTasks.map(taskItem =>
          taskItem.task_id === taskToEdit.task_id
            ? { ...taskItem, task_name: updatedTask.task_name, updated_at: updatedTask.updated_at }
            : taskItem
        )
      )

      setShowEditModal(false)
      setTaskToEdit(null)
    } catch (err: any) {
      console.error('Failed to update task name:', err)
      setEditError(err.message || t('chatComponents.taskHistory.errors.failedToUpdateName'))
    } finally {
      setIsEditingSaving(false)
    }
  }

  const handleTaskClick = (taskId: string) => {
    const messagesContainer = document.querySelector('[data-chat-messages-container]')
    if (messagesContainer) {
      sessionStorage.setItem('ai-chat-scroll-position', String(messagesContainer.scrollTop))
    }
    const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
    if (conversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', conversationId)
    }
    navigate(`/results?task=${taskId}`, { state: { fromAIChat: true } })
  }

  if (isLoading) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
        <div className="flex items-center justify-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-purple-600" />
          <span className="text-gray-600 text-sm sm:text-base">{t('chatComponents.taskHistory.loadingHistory')}</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-4 sm:px-5 py-3 sm:py-4 bg-red-50 border-b border-red-100">
          <h3 className="font-semibold text-red-800 flex items-center gap-2 text-sm sm:text-base">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {t('chatComponents.taskHistory.failedToLoadHistory')}
          </h3>
        </div>
        <div className="p-4 sm:p-5">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-gradient-to-r from-purple-50 to-indigo-50 border-b border-gray-100 flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 text-sm sm:text-base">
            <History className="w-4 h-4 text-purple-600 flex-shrink-0" />
            <span className="truncate">{t('chatComponents.taskHistory.title')}</span>
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            {t('chatComponents.taskHistory.tasksFound', { count: tasks.length })}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-white rounded-lg transition-colors flex-shrink-0"
          title={t('chatComponents.taskHistory.refresh')}
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Task List */}
      <div className="divide-y divide-gray-100">
        {tasks.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <History className="w-8 h-8 mx-auto mb-2 text-gray-300" />
            <p>{t('chatComponents.taskHistory.noTasksFound')}</p>
          </div>
        ) : (
          tasks.map(task => {
            const statusDisplay = getStatusDisplay(task.status, t)
            const splitStrategy = getTaskSplitStrategy(task)
            const splitConfig = task.preprocessing_config?.split_config as { n_splits?: number; ratios?: { train: number; val: number; test: number } } | undefined

            const getSplitLabel = (): { label: string; color: string } | null => {
              if (splitStrategy === 'k_fold') {
                const numFolds = splitConfig?.n_splits
                return { label: numFolds ? `${numFolds}-Fold` : 'K-Fold', color: 'text-purple-600 bg-purple-50' }
              } else if (splitStrategy === 'manual') {
                return { label: t('chatComponents.taskHistory.manualSplit'), color: 'text-amber-600 bg-amber-50' }
              } else if (splitStrategy === 'random') {
                const ratios = splitConfig?.ratios
                if (ratios) {
                  const train = Math.round(ratios.train * 10)
                  const val = Math.round(ratios.val * 10)
                  const test = Math.round(ratios.test * 10)
                  return { label: `${train}:${val}:${test}`, color: 'text-blue-600 bg-blue-50' }
                }
                return { label: '7:1:2', color: 'text-blue-600 bg-blue-50' }
              }
              return null
            }
            const splitLabel = getSplitLabel()

            return (
              <div
                key={task.task_id}
                onClick={() => handleTaskClick(task.task_id)}
                className="px-4 sm:px-5 py-3 sm:py-4 hover:bg-gray-50 cursor-pointer transition-colors group"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                      <h4 className="font-medium text-gray-900 truncate max-w-full sm:max-w-none text-sm sm:text-base">{task.task_name}</h4>
                      <span className={`inline-flex items-center gap-1 px-1.5 sm:px-2 py-0.5 rounded-full text-xs font-medium ${statusDisplay.color}`}>
                        {statusDisplay.icon}
                        <span className="hidden xs:inline">{statusDisplay.label}</span>
                      </span>
                      {splitLabel && (
                        <span className={`inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-full text-xs font-medium ${splitLabel.color}`}>
                          {splitLabel.label}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 sm:gap-3 text-xs text-gray-500">
                      <span className="capitalize">{task.task_type.replace('_', ' ')}</span>
                      <span className="hidden sm:inline">•</span>
                      <span className="uppercase">{task.data_type}</span>
                      {getNumClasses(task) > 0 && (
                        <>
                          <span className="hidden sm:inline">•</span>
                          <span>{t('chatComponents.taskHistory.classesCount', { count: getNumClasses(task) })}</span>
                        </>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-gray-400 truncate">
                      {t('chatComponents.taskHistory.created')}: {formatDate(task.created_at)}
                      {task.finished_at && <span className="hidden sm:inline"> • {t('chatComponents.taskHistory.finished')}: {formatDate(task.finished_at)}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {user && task.user_id === user.id && (
                      <button
                        onClick={(e) => handleEditTask(task, e)}
                        className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-colors"
                        title={t('chatComponents.taskHistory.editTaskName')}
                      >
                        <Edit2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                      </button>
                    )}
                    <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-purple-500 transition-colors" />
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Edit Task Name Modal */}
      {showEditModal && taskToEdit && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setShowEditModal(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-indigo-50 rounded-lg">
                  <Edit2 className="w-5 h-5 text-indigo-600" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{t('chatComponents.taskHistory.editTaskNameTitle')}</h3>
                  <p className="text-sm text-gray-500 mt-0.5">{t('chatComponents.taskHistory.editTaskNameDesc')}</p>
                </div>
              </div>
            </div>

            <div className="px-6 py-5">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('chatComponents.taskHistory.taskNameLabel')}
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
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
                    placeholder={t('chatComponents.taskHistory.taskNamePlaceholder')}
                    autoFocus
                  />
                </div>

                {editError && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                    <p className="text-sm text-red-700">{editError}</p>
                  </div>
                )}
              </div>
            </div>

            <div className="px-6 py-4 bg-gray-50 rounded-b-2xl flex items-center justify-end gap-3">
              <button
                onClick={() => setShowEditModal(false)}
                disabled={isEditingSaving}
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50"
              >
                {t('chatComponents.taskHistory.cancel')}
              </button>
              <button
                onClick={handleSaveTaskName}
                disabled={isEditingSaving || !editedTaskName.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isEditingSaving && <Loader2 className="w-4 h-4 animate-spin" />}
                {isEditingSaving ? t('chatComponents.taskHistory.saving') : t('chatComponents.taskHistory.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
