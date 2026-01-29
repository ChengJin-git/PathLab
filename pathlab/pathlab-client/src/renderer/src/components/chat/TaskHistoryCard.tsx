import { useState, useEffect, useRef } from 'react'
import { Loader2, History, CheckCircle2, XCircle, Clock, PlayCircle, AlertCircle, RefreshCw, ChevronRight } from 'lucide-react'
import { getTrainingTasks, TrainingTask } from '../../api'
import { useNavigate } from 'react-router-dom'

// Cached task data for persistence - minimal data for display only
export interface CachedTaskData {
  task_id: string
  task_name: string
  task_type: string
  data_level: string
  status: string
  created_at: string | null
  finished_at: string | null
  num_classes?: number  // Just the count, not full class list
  split_strategy?: string  // Just the strategy name for badge display
}

export interface AgentTaskHistoryConfig {
  show_completed?: boolean
  show_running?: boolean
  show_failed?: boolean
  limit?: number
  split_strategy?: 'random' | 'k_fold' | 'manual'  // Filter by split strategy
  task_type?: string    // Filter by task type: "classification", "survival_prediction", etc.
  // Cached data for persistence (populated after first load)
  cached_tasks?: CachedTaskData[]
  cached_at?: string  // ISO timestamp when data was cached
}

interface TaskHistoryCardProps {
  config: AgentTaskHistoryConfig
  onError?: (error: string) => void
  onDataLoaded?: (tasks: CachedTaskData[]) => void  // Callback when data is loaded, for persistence
}

/**
 * Parse [TASK_HISTORY_CONFIG] block from message content
 */
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

/**
 * Remove [TASK_HISTORY_CONFIG] block from content for display
 */
export function removeTaskHistoryConfigBlock(content: string): string {
  return content.replace(/\[TASK_HISTORY_CONFIG\][\s\S]*?\[\/TASK_HISTORY_CONFIG\]/g, '').trim()
}

// Status icon and color mapping
function getStatusDisplay(status: string) {
  switch (status) {
    case 'completed':
      return { icon: <CheckCircle2 className="w-4 h-4" />, color: 'text-green-600 bg-green-50', label: 'Completed' }
    case 'running':
    case 'training':
      return { icon: <PlayCircle className="w-4 h-4" />, color: 'text-blue-600 bg-blue-50', label: 'Running' }
    case 'pending':
    case 'queued':
      return { icon: <Clock className="w-4 h-4" />, color: 'text-amber-600 bg-amber-50', label: 'Pending' }
    case 'failed':
      return { icon: <XCircle className="w-4 h-4" />, color: 'text-red-600 bg-red-50', label: 'Failed' }
    case 'cancelled':
      return { icon: <XCircle className="w-4 h-4" />, color: 'text-gray-500 bg-gray-50', label: 'Cancelled' }
    default:
      return { icon: <Clock className="w-4 h-4" />, color: 'text-gray-600 bg-gray-50', label: status }
  }
}

// Format date for display
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
  // Check if we have cached data
  const hasCachedData = config.cached_tasks && config.cached_tasks.length > 0

  const [isLoading, setIsLoading] = useState(!hasCachedData)
  const [error, setError] = useState<string>('')
  const [tasks, setTasks] = useState<TrainingTask[]>(
    // Initialize with cached data if available
    hasCachedData ? (config.cached_tasks as unknown as TrainingTask[]) : []
  )
  const navigate = useNavigate()

  // Use ref for callbacks to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const onDataLoadedRef = useRef(onDataLoaded)
  onDataLoadedRef.current = onDataLoaded

  // Default config values
  const showCompleted = config.show_completed ?? true
  const showRunning = config.show_running ?? true
  const showFailed = config.show_failed ?? false
  const limit = config.limit ?? 10
  const splitStrategyFilter = config.split_strategy
  const taskTypeFilter = config.task_type

  // Helper to get task's split strategy
  const getTaskSplitStrategy = (task: TrainingTask | CachedTaskData): string => {
    // For CachedTaskData, use the cached split_strategy field
    if ('split_strategy' in task && task.split_strategy) {
      return task.split_strategy
    }
    // For TrainingTask, extract from preprocessing_config
    if ('preprocessing_config' in task && task.preprocessing_config) {
      const splitConfig = task.preprocessing_config?.split_config as { strategy?: string } | undefined
      return splitConfig?.strategy || 'random'
    }
    return 'random'
  }

  // Convert TrainingTask to CachedTaskData for persistence - minimal data only
  const toCachedData = (task: TrainingTask): CachedTaskData => ({
    task_id: task.task_id,
    task_name: task.task_name,
    task_type: task.task_type,
    data_level: task.data_level,
    status: task.status,
    created_at: task.created_at,
    finished_at: task.finished_at,
    num_classes: task.classes?.length,
    split_strategy: getTaskSplitStrategy(task)
  })

  // Helper to get number of classes from either TrainingTask or CachedTaskData
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
    // Skip fetching if we have cached data
    if (hasCachedData) {
      return
    }

    const fetchData = async () => {
      setIsLoading(true)
      setError('')

      try {
        const allTasks = await getTrainingTasks()

        // Filter tasks based on config
        const filteredTasks = allTasks.filter(task => {
          // Status filter
          let statusMatch = false
          if (task.status === 'completed' && showCompleted) statusMatch = true
          if (['running', 'training', 'pending', 'queued'].includes(task.status) && showRunning) statusMatch = true
          if (task.status === 'failed' && showFailed) statusMatch = true
          if (!statusMatch) return false

          // Split strategy filter
          if (splitStrategyFilter && getTaskSplitStrategy(task) !== splitStrategyFilter) return false

          // Task type filter
          if (taskTypeFilter && task.task_type !== taskTypeFilter) return false

          return true
        })

        // Sort by created_at descending and limit
        const sortedTasks = filteredTasks
          .sort((a, b) => {
            const dateA = a.created_at ? new Date(a.created_at).getTime() : 0
            const dateB = b.created_at ? new Date(b.created_at).getTime() : 0
            return dateB - dateA
          })
          .slice(0, limit)

        setTasks(sortedTasks)

        // Notify parent to persist the data
        if (onDataLoadedRef.current) {
          onDataLoadedRef.current(sortedTasks.map(toCachedData))
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch tasks'
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
      const filteredTasks = allTasks.filter(task => {
        // Status filter
        let statusMatch = false
        if (task.status === 'completed' && showCompleted) statusMatch = true
        if (['running', 'training', 'pending', 'queued'].includes(task.status) && showRunning) statusMatch = true
        if (task.status === 'failed' && showFailed) statusMatch = true
        if (!statusMatch) return false

        // Split strategy filter
        if (splitStrategyFilter && getTaskSplitStrategy(task) !== splitStrategyFilter) return false

        // Task type filter
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

      // Notify parent to persist the refreshed data
      if (onDataLoadedRef.current) {
        onDataLoadedRef.current(sortedTasks.map(toCachedData))
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch tasks'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleTaskClick = (taskId: string) => {
    // Save scroll position and conversation ID before navigating
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
          <span className="text-gray-600 text-sm sm:text-base">Loading training history...</span>
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
            Failed to Load History
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
            <span className="truncate">Training History</span>
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            {tasks.length} task{tasks.length !== 1 ? 's' : ''} found
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-white rounded-lg transition-colors flex-shrink-0"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Task List */}
      <div className="divide-y divide-gray-100">
        {tasks.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <History className="w-8 h-8 mx-auto mb-2 text-gray-300" />
            <p>No training tasks found</p>
          </div>
        ) : (
          tasks.map(task => {
            const statusDisplay = getStatusDisplay(task.status)
            const splitStrategy = getTaskSplitStrategy(task)
            const splitConfig = task.preprocessing_config?.split_config as { n_splits?: number; ratios?: { train: number; val: number; test: number } } | undefined

            // Get split strategy display label
            const getSplitLabel = (): { label: string; color: string } | null => {
              if (splitStrategy === 'k_fold') {
                const numFolds = splitConfig?.n_splits
                return { label: numFolds ? `${numFolds}-Fold` : 'K-Fold', color: 'text-purple-600 bg-purple-50' }
              } else if (splitStrategy === 'manual') {
                return { label: 'Manual Split', color: 'text-amber-600 bg-amber-50' }
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
                      <span className="uppercase">{task.data_level}</span>
                      {getNumClasses(task) > 0 && (
                        <>
                          <span className="hidden sm:inline">•</span>
                          <span>{getNumClasses(task)} classes</span>
                        </>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-gray-400 truncate">
                      Created: {formatDate(task.created_at)}
                      {task.finished_at && <span className="hidden sm:inline"> • Finished: {formatDate(task.finished_at)}</span>}
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-purple-500 transition-colors flex-shrink-0 mt-1" />
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

