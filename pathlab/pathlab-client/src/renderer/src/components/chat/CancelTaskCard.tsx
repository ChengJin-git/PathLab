import { useState } from 'react'
import { Loader2, XCircle, CheckCircle2, AlertCircle, StopCircle } from 'lucide-react'
import { cancelQueueTask } from '../../api'

export interface AgentCancelTaskConfig {
  task_id: string
  task_name?: string
  reason?: string
}

interface CancelTaskCardProps {
  config: AgentCancelTaskConfig
  onSuccess?: (taskId: string) => void
  onError?: (error: string) => void
}

/**
 * Parse [CANCEL_TASK] block from message content
 */
export function parseCancelTaskConfig(content: string): AgentCancelTaskConfig | null {
  const match = content.match(/\[CANCEL_TASK\]([\s\S]*?)\[\/CANCEL_TASK\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [CANCEL_TASK] block from content for display
 */
export function removeCancelTaskBlock(content: string): string {
  return content.replace(/\[CANCEL_TASK\][\s\S]*?\[\/CANCEL_TASK\]/g, '').trim()
}

export function CancelTaskCard({ config, onSuccess, onError }: CancelTaskCardProps) {
  const [isCancelling, setIsCancelling] = useState(false)
  const [isCancelled, setIsCancelled] = useState(false)
  const [error, setError] = useState<string>('')

  const handleCancel = async () => {
    if (isCancelling || isCancelled) return

    setIsCancelling(true)
    setError('')

    try {
      const result = await cancelQueueTask(config.task_id)
      if (result.cancelled) {
        setIsCancelled(true)
        onSuccess?.(config.task_id)
      } else {
        const errorMsg = result.message || 'Failed to cancel task'
        setError(errorMsg)
        onError?.(errorMsg)
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to cancel task'
      setError(errorMsg)
      onError?.(errorMsg)
    } finally {
      setIsCancelling(false)
    }
  }

  if (isCancelled) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-green-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-4 sm:px-5 py-3 sm:py-4 bg-green-50 border-b border-green-100">
          <h3 className="font-semibold text-green-800 flex items-center gap-1.5 sm:gap-2 text-sm sm:text-base">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span className="truncate">Task Cancelled Successfully</span>
          </h3>
        </div>
        <div className="px-4 sm:px-5 py-3 sm:py-4">
          <p className="text-gray-600 text-sm sm:text-base">
            Task <span className="font-medium truncate">{config.task_name || config.task_id}</span> has been cancelled.
          </p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-4 sm:px-5 py-3 sm:py-4 bg-red-50 border-b border-red-100">
          <h3 className="font-semibold text-red-800 flex items-center gap-1.5 sm:gap-2 text-sm sm:text-base">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="truncate">Failed to Cancel Task</span>
          </h3>
        </div>
        <div className="px-4 sm:px-5 py-3 sm:py-4">
          <p className="text-red-700 text-sm break-words">{error}</p>
          <button
            onClick={handleCancel}
            className="mt-3 w-full sm:w-auto px-3 sm:px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm flex items-center justify-center gap-1.5 sm:gap-2"
          >
            <XCircle className="w-4 h-4 flex-shrink-0" />
            <span>Retry</span>
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-gradient-to-r from-red-50 to-orange-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2 text-sm sm:text-base">
          <StopCircle className="w-4 h-4 text-red-600 flex-shrink-0" />
          <span className="truncate">Cancel Training Task</span>
        </h3>
        {config.reason && (
          <p className="text-xs text-gray-500 mt-1">{config.reason}</p>
        )}
      </div>

      {/* Content */}
      <div className="px-4 sm:px-5 py-3 sm:py-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 sm:gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-gray-700 text-sm sm:text-base truncate">
              Task: <span className="font-medium">{config.task_name || config.task_id}</span>
            </p>
            <p className="text-xs text-gray-500 mt-1 truncate">
              ID: <span className="font-mono">{config.task_id}</span>
            </p>
          </div>
          <button
            onClick={handleCancel}
            disabled={isCancelling}
            className="w-full sm:w-auto px-3 sm:px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm flex items-center justify-center gap-1.5 sm:gap-2 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          >
            {isCancelling ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
                <span>Cancelling...</span>
              </>
            ) : (
              <>
                <XCircle className="w-4 h-4 flex-shrink-0" />
                <span>Cancel Task</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

