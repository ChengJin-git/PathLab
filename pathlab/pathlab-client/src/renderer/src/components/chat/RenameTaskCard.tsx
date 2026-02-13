import { useState } from 'react'
import { Loader2, Edit2, CheckCircle2, XCircle } from 'lucide-react'
import { updateTrainingTaskName } from '../../api'

// Config for renaming a task
export interface AgentRenameTaskConfig {
  task_id: string
  old_name: string
  new_name: string
}

interface RenameTaskCardProps {
  config: AgentRenameTaskConfig
  onSuccess?: (taskId: string, newName: string) => void
  onError?: (error: string) => void
}

/**
 * Parse [RENAME_TASK] block from message content
 */
export function parseRenameTaskConfig(content: string): AgentRenameTaskConfig | null {
  const match = content.match(/\[RENAME_TASK\]([\s\S]*?)\[\/RENAME_TASK\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [RENAME_TASK] block from content for display
 */
export function removeRenameTaskBlock(content: string): string {
  return content.replace(/\[RENAME_TASK\][\s\S]*?\[\/RENAME_TASK\]/g, '').trim()
}

export function RenameTaskCard({ config, onSuccess, onError }: RenameTaskCardProps) {
  const [isRenaming, setIsRenaming] = useState(false)
  const [isRenamed, setIsRenamed] = useState(false)
  const [error, setError] = useState<string>('')

  const handleRename = async () => {
    if (!config.new_name.trim()) {
      const errorMsg = 'Task name cannot be empty'
      setError(errorMsg)
      onError?.(errorMsg)
      return
    }

    setIsRenaming(true)
    setError('')

    try {
      await updateTrainingTaskName(config.task_id, config.new_name.trim())
      setIsRenamed(true)
      onSuccess?.(config.task_id, config.new_name.trim())
    } catch (err: any) {
      const errorMsg = err.message || 'Failed to rename task'
      setError(errorMsg)
      onError?.(errorMsg)
    } finally {
      setIsRenaming(false)
    }
  }

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-gradient-to-r from-indigo-50 to-purple-50 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-100 rounded-lg">
            <Edit2 className="w-4 h-4 sm:w-5 sm:h-5 text-indigo-600" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-gray-900 text-sm sm:text-base">Rename Training Task</h3>
            <p className="text-xs sm:text-sm text-gray-600 mt-0.5 truncate">
              Update task name from "{config.old_name}"
            </p>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="p-4 sm:p-5">
        <div className="space-y-4">
          {/* Old Name */}
          <div>
            <label className="block text-xs sm:text-sm font-medium text-gray-700 mb-1.5">
              Current Name
            </label>
            <div className="px-3 sm:px-4 py-2 sm:py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">
              {config.old_name}
            </div>
          </div>

          {/* New Name */}
          <div>
            <label className="block text-xs sm:text-sm font-medium text-gray-700 mb-1.5">
              New Name
            </label>
            <div className="px-3 sm:px-4 py-2 sm:py-2.5 bg-indigo-50 border border-indigo-200 rounded-lg text-sm font-medium text-indigo-900">
              {config.new_name}
            </div>
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
              <XCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Success Message */}
          {isRenamed && (
            <div className="p-3 bg-green-50 border border-green-200 rounded-lg flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-green-700">Task renamed successfully!</p>
            </div>
          )}

          {/* Rename Button */}
          {!isRenamed && (
            <button
              onClick={handleRename}
              disabled={isRenaming}
              className="w-full px-4 py-2.5 sm:py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm sm:text-base"
            >
              {isRenaming && <Loader2 className="w-4 h-4 animate-spin" />}
              {isRenaming ? 'Renaming...' : 'Rename Task'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

