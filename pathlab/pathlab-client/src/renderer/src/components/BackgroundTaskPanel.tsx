/**
 * Background Task Panel Component
 *
 * A floating panel that displays background task progress.
 * Shows in bottom-left corner with minimize/expand functionality.
 * Displays both local tasks (upload/delete) and server tasks (training).
 */

import React from 'react'
import { useBackgroundTask, BackgroundTask, TaskItem, TaskStatus, TrainingTaskStatus } from '../contexts/BackgroundTaskContext'
import { cn } from '../lib/utils'

// Training status label mapping
const trainingStatusLabels: Record<TrainingTaskStatus, string> = {
  pending: 'Queued',
  preprocessing: 'Preprocessing',
  extracting: 'Extracting Features',
  training: 'Training',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled'
}

// Status icons
const StatusIcon: React.FC<{ status: TaskStatus; className?: string }> = ({ status, className }) => {
  switch (status) {
    case 'pending':
      return (
        <svg className={cn("w-4 h-4 text-gray-400", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="12" r="10" strokeWidth="2" />
        </svg>
      )
    case 'running':
      return (
        <svg className={cn("w-4 h-4 text-blue-500 animate-spin", className)} fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )
    case 'success':
      return (
        <svg className={cn("w-4 h-4 text-green-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
        </svg>
      )
    case 'error':
      return (
        <svg className={cn("w-4 h-4 text-red-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      )
    case 'cancelled':
      return (
        <svg className={cn("w-4 h-4 text-gray-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
        </svg>
      )
  }
}

// Task item row
const TaskItemRow: React.FC<{ item: TaskItem }> = ({ item }) => (
  <div className="flex items-center gap-2 py-1 text-xs">
    <StatusIcon status={item.status} className="flex-shrink-0" />
    <span className="flex-1 truncate text-gray-600" title={item.name}>{item.name}</span>
    {item.status === 'running' && (
      <span className="text-gray-400">{item.progress}%</span>
    )}
    {item.error && (
      <span className="text-red-500 truncate max-w-[100px]" title={item.error}>Error</span>
    )}
  </div>
)

// Get type label for display
const getTypeLabel = (task: BackgroundTask): string => {
  switch (task.type) {
    case 'upload':
      return 'Upload'
    case 'delete_wsi':
      return 'Delete File(s)'
    case 'delete_task':
      return 'Delete Task(s)'
    case 'training':
      // Show training status if available
      if (task.serverTaskStatus) {
        return `${trainingStatusLabels[task.serverTaskStatus]}`
      }
      return 'Training'
    case 'migration':
      return 'Storage'
    case 'batch_import':
      return 'Batch Import'
    case 'delete_external':
      return 'Delete External'
    default:
      return 'Task'
  }
}

// Single task card
const TaskCard: React.FC<{
  task: BackgroundTask;
  onCancel: () => void;
  onCancelServer: () => Promise<boolean>;
  onRemove: () => void
}> = ({
  task, onCancel, onCancelServer, onRemove
}) => {
    const [isCancelling, setIsCancelling] = React.useState(false)
    const [expanded, setExpanded] = React.useState(task.status === 'running')
    const isServerTask = task.isServerTask === true

    const typeLabel = getTypeLabel(task)

    // For training tasks, use different progress bar colors based on stage
    const getProgressBarColor = () => {
      if (task.type === 'training') {
        switch (task.serverTaskStatus) {
          case 'preprocessing':
            return 'bg-yellow-500'
          case 'extracting':
            return 'bg-orange-500'
          case 'training':
            return 'bg-purple-500'
          default:
            return 'bg-blue-500'
        }
      }
      return 'bg-blue-500'
    }

    return (
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
        <div
          className="flex items-start gap-3 p-3 cursor-pointer hover:bg-gray-50"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="mt-1">
            <StatusIcon status={task.status} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-col gap-1 items-start w-full">
              <div className="flex items-center justify-between w-full">
                <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                  {typeLabel}
                </span>
                {isServerTask && task.status === 'running' && (
                  <span className="text-xs font-semibold text-blue-600">
                    {task.totalProgress}%
                  </span>
                )}
              </div>
              {task.title.startsWith('Relocating to ') ? (
                <div className="flex flex-col text-sm font-medium text-left w-full">
                  <span className="text-gray-500 text-xs">Relocating to</span>
                  <span className="break-words text-gray-700 leading-tight">{task.title.replace('Relocating to ', '')}</span>
                </div>
              ) : (
                <div className="text-sm font-semibold text-gray-900 break-words text-left leading-normal w-full">
                  {task.title}
                </div>
              )}
            </div>
            {(task.status === 'running' || task.status === 'pending') && (
              <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={cn("h-full transition-all duration-300", getProgressBarColor())}
                  style={{ width: `${task.totalProgress}%` }}
                />
              </div>
            )}
          </div>
          <div className="flex flex-row items-center gap-1 self-start mt-0.5">
            {/* Show success/fail counts for non-training tasks */}
            {!isServerTask && (
              <div className="flex items-center gap-1 text-xs">
                {task.successCount > 0 && (
                  <span className="text-green-600 flex items-center">
                    {task.successCount}
                    <svg className="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
                    </svg>
                  </span>
                )}
                {task.failedCount > 0 && (
                  <span className="text-red-500 flex items-center">
                    {task.failedCount}
                    <svg className="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </span>
                )}
              </div>
            )}
            {/* Cancel button - for running/pending tasks (both local and server) */}
            {(task.status === 'running' || task.status === 'pending') && (
              <button
                onClick={async (e) => {
                  e.stopPropagation()
                  if (isServerTask) {
                    setIsCancelling(true)
                    await onCancelServer()
                    setIsCancelling(false)
                  } else {
                    onCancel()
                  }
                }}
                disabled={isCancelling}
                className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-red-600 disabled:opacity-50"
                title="Cancel"
              >
                {isCancelling ? (
                  <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                )}
              </button>
            )}
            {/* Remove button - only for completed local tasks */}
            {!isServerTask && task.status !== 'running' && task.status !== 'pending' && (
              <button
                onClick={(e) => { e.stopPropagation(); onRemove() }}
                className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-gray-700"
                title="Close"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
            <svg
              className={cn("w-3.5 h-3.5 text-gray-300 transition-transform", expanded && "rotate-180")}
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
        {expanded && !isServerTask && (
          <div className="px-3 pb-3 max-h-40 overflow-y-auto border-t border-gray-100">
            {task.items.map(item => <TaskItemRow key={item.id} item={item} />)}
          </div>
        )}
      </div>
    )
  }

// Main panel component
export function BackgroundTaskPanel(): React.ReactElement | null {
  const { tasks, isProcessing, cancelTask, cancelServerTask, removeTask, clearCompletedTasks } = useBackgroundTask()
  const [isOpen, setIsOpen] = React.useState(false)
  const panelRef = React.useRef<HTMLDivElement>(null)

  // Close when clicking outside
  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [])

  const runningCount = tasks.filter(t => t.status === 'running' || t.status === 'pending').length
  const completedCount = tasks.filter(t => t.status === 'success' || t.status === 'error').length

  return (
    <div className="relative" ref={panelRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "p-2 rounded-lg transition-colors relative",
          isOpen ? "bg-gray-100 text-primary-600" : "text-gray-500 hover:text-primary-600 hover:bg-gray-100"
        )}
        title="Background Tasks"
      >
        <svg className={cn("w-5 h-5", isProcessing && "animate-pulse")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>

        {/* Badge */}
        {runningCount > 0 && (
          <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-blue-500 rounded-full border-2 border-white"></span>
        )}
        {runningCount === 0 && completedCount > 0 && (
          <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-gray-400 rounded-full border-2 border-white"></span>
        )}
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div className={cn(
          "bg-white rounded-xl shadow-xl border border-gray-200 z-50 overflow-hidden flex flex-col",
          // Mobile: Fixed positioning for better visibility and width
          "fixed top-16 left-2 right-2 mt-2 max-h-[75vh]",
          // Desktop: Absolute dropdown
          "sm:absolute sm:top-full sm:right-0 sm:left-auto sm:w-[450px] sm:max-h-[80vh] sm:mt-2 sm:mr-0"
        )}>
          {/* Header */}
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
            <div>
              <h3 className="font-semibold text-gray-900">Tasks</h3>
              <p className="text-xs text-gray-500">
                {isProcessing
                  ? `${runningCount} running, ${completedCount} completed`
                  : `${tasks.length} tasks history`}
              </p>
            </div>
            {!isProcessing && completedCount > 0 && (
              <button
                onClick={clearCompletedTasks}
                className="text-xs text-blue-600 hover:text-blue-700 hover:underline px-2 py-1"
              >
                Clear All
              </button>
            )}
          </div>

          {/* Task List */}
          {tasks.length === 0 ? (
            <div className="p-8 text-center text-gray-500 flex flex-col items-center">
              <svg className="w-12 h-12 text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm">No active tasks</p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-2 space-y-2 bg-gray-50/50">
              {tasks.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onCancel={() => cancelTask(task.id)}
                  onCancelServer={() => cancelServerTask(task.id)}
                  onRemove={() => removeTask(task.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

