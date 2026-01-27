import { useState, useEffect, useRef } from 'react'
import { Loader2, History, CheckCircle2, XCircle, Clock, PlayCircle, AlertCircle, RefreshCw, ChevronRight } from 'lucide-react'
import { getTrainingTasks, TrainingTask } from '../../api'
import { useNavigate } from 'react-router-dom'

export interface AgentTaskHistoryConfig {
  show_completed?: boolean
  show_running?: boolean
  show_failed?: boolean
  limit?: number
  split_strategy?: 'random' | 'k_fold' | 'manual'  // Filter by split strategy
  task_type?: string    // Filter by task type: "classification", "survival_prediction", etc.
}

interface TaskHistoryCardProps {
  config: AgentTaskHistoryConfig
  onError?: (error: string) => void
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

export function TaskHistoryCard({ config, onError }: TaskHistoryCardProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [tasks, setTasks] = useState<TrainingTask[]>([])
  const navigate = useNavigate()

  // Use ref for onError to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  // Default config values
  const showCompleted = config.show_completed ?? true
  const showRunning = config.show_running ?? true
  const showFailed = config.show_failed ?? false
  const limit = config.limit ?? 10
  const splitStrategyFilter = config.split_strategy
  const taskTypeFilter = config.task_type

  // Helper to get task's split strategy
  const getTaskSplitStrategy = (task: TrainingTask): string => {
    const splitConfig = task.preprocessing_config?.split_config as { strategy?: string } | undefined
    return splitConfig?.strategy || 'random'
  }

  useEffect(() => {
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
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch tasks'
        setError(msg)
        onErrorRef.current?.(msg)
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
  }, [showCompleted, showRunning, showFailed, limit, splitStrategyFilter, taskTypeFilter])

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
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch tasks'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  const handleTaskClick = (taskId: string) => {
    navigate(`/results?task=${taskId}`)
  }

  if (isLoading) {
    return (
      <div className="mt-4 w-full min-w-[500px] bg-white border border-gray-200 rounded-2xl shadow-sm p-6">
        <div className="flex items-center justify-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-purple-600" />
          <span className="text-gray-600">Loading training history...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 w-full min-w-[500px] bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 bg-red-50 border-b border-red-100">
          <h3 className="font-semibold text-red-800 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            Failed to Load History
          </h3>
        </div>
        <div className="p-5">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 w-full min-w-[500px] bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-purple-50 to-indigo-50 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <History className="w-4 h-4 text-purple-600" />
            Training History
          </h3>
          <p className="text-xs text-gray-500 mt-1">
            {tasks.length} task{tasks.length !== 1 ? 's' : ''} found
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-white rounded-lg transition-colors"
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
                className="px-5 py-4 hover:bg-gray-50 cursor-pointer transition-colors group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium text-gray-900 truncate">{task.task_name}</h4>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${statusDisplay.color}`}>
                        {statusDisplay.icon}
                        {statusDisplay.label}
                      </span>
                      {splitLabel && (
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${splitLabel.color}`}>
                          {splitLabel.label}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-xs text-gray-500">
                      <span className="capitalize">{task.task_type.replace('_', ' ')}</span>
                      <span>•</span>
                      <span className="uppercase">{task.data_level}</span>
                      {task.classes && task.classes.length > 0 && (
                        <>
                          <span>•</span>
                          <span>{task.classes.length} classes</span>
                        </>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-gray-400">
                      Created: {formatDate(task.created_at)}
                      {task.finished_at && ` • Finished: ${formatDate(task.finished_at)}`}
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

