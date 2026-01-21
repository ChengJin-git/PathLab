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
  failed: 'Failed'
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
    default:
      return 'Task'
  }
}

// Single task card
const TaskCard: React.FC<{ task: BackgroundTask; onCancel: () => void; onRemove: () => void }> = ({
  task, onCancel, onRemove
}) => {
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
        className="flex items-center gap-2 p-3 cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(!expanded)}
      >
        <StatusIcon status={task.status} />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-x-2">
            <span className="text-xs text-gray-500 whitespace-nowrap">{typeLabel}</span>
            <span className="text-sm font-medium break-all">{task.title}</span>
          </div>
          {(task.status === 'running' || task.status === 'pending') && (
            <div className="mt-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={cn("h-full transition-all duration-300", getProgressBarColor())}
                style={{ width: `${task.totalProgress}%` }}
              />
            </div>
          )}
        </div>
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
        {/* Show progress percentage for training tasks */}
        {isServerTask && task.status === 'running' && (
          <span className="text-xs text-gray-500">{task.totalProgress}%</span>
        )}
        {/* Cancel button - only for local running tasks */}
        {!isServerTask && task.status === 'running' && (
          <button
            onClick={(e) => { e.stopPropagation(); onCancel() }}
            className="p-1 hover:bg-gray-200 rounded text-gray-500 hover:text-gray-700"
            title="Cancel"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        {/* Remove button - only for completed local tasks */}
        {!isServerTask && task.status !== 'running' && task.status !== 'pending' && (
          <button
            onClick={(e) => { e.stopPropagation(); onRemove() }}
            className="p-1 hover:bg-gray-200 rounded text-gray-500 hover:text-gray-700"
            title="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        <svg
          className={cn("w-4 h-4 text-gray-400 transition-transform", expanded && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
        </svg>
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
  const { tasks, isProcessing, isPanelExpanded, togglePanel, cancelTask, removeTask, clearCompletedTasks } = useBackgroundTask()

  // Don't render if no tasks
  if (tasks.length === 0) return null

  const runningCount = tasks.filter(t => t.status === 'running').length
  const completedCount = tasks.filter(t => t.status === 'success' || t.status === 'error').length

  return (
    <div className="fixed bottom-4 left-4 z-50 w-80">
      {/* Header bar */}
      <div 
        className={cn(
          "flex items-center gap-2 px-4 py-2 rounded-t-lg cursor-pointer",
          isProcessing ? "bg-blue-600 text-white" : "bg-gray-800 text-white"
        )}
        onClick={togglePanel}
      >
        {isProcessing && (
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )}
        <span className="flex-1 font-medium text-sm">
          {isProcessing ? `Processing ${runningCount} task${runningCount > 1 ? 's' : ''}...` : 'Tasks'}
        </span>
        <span className="text-xs opacity-80">{tasks.length} total</span>
        <svg 
          className={cn("w-4 h-4 transition-transform", isPanelExpanded && "rotate-180")} 
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 15l7-7 7 7" />
        </svg>
        {!isProcessing && (
          <div
            className="p-1 hover:bg-white/20 rounded cursor-pointer ml-1"
            onClick={(e) => {
              e.stopPropagation()
              clearCompletedTasks()
            }}
            title="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
        )}
      </div>

      {/* Expanded content */}
      {isPanelExpanded && (
        <div className="bg-gray-50 rounded-b-lg border border-t-0 border-gray-200 shadow-lg max-h-96 overflow-hidden flex flex-col">
          {/* Task list */}
          <div className="flex-1 overflow-y-auto p-2 space-y-2">
            {tasks.map(task => (
              <TaskCard 
                key={task.id} 
                task={task} 
                onCancel={() => cancelTask(task.id)}
                onRemove={() => removeTask(task.id)}
              />
            ))}
          </div>
          {/* Footer */}
          {completedCount > 0 && (
            <div className="border-t border-gray-200 p-2">
              <button
                onClick={clearCompletedTasks}
                className="w-full text-xs text-gray-500 hover:text-gray-700 py-1"
              >
                Clear {completedCount} completed task{completedCount > 1 ? 's' : ''}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

