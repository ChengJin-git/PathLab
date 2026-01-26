import { useState, useEffect } from 'react'
import { Play, AlertCircle, CheckCircle, Loader2, BarChart3, FileText, ThumbsUp, ThumbsDown } from 'lucide-react'
import { runTaskAnalysis, getTrainingTasks, type TrainingTask } from '../../api'

// Config from Agent - AI decides the metrics and charts based on user's request
export interface AgentInternalAnalysisConfig {
  task_id: string           // Training task to analyze
  task_name: string         // Task name for display
  metrics: string[]         // AI-determined metrics (e.g., ["accuracy", "precision", "f1", "auc"])
  charts: string[]          // AI-determined charts (e.g., ["confusion_matrix", "roc_curve"])
  description?: string      // Optional analysis description
  submitted_analysis_id?: string  // Set after successful submission for persistence
}

interface InternalAnalysisConfigCardProps {
  config: AgentInternalAnalysisConfig
  onSubmitSuccess?: (taskId: string, analysisId: string) => void
  onSubmitError?: (error: string) => void
  onConfigChange?: (config: AgentInternalAnalysisConfig) => void
  messageId?: string  // Message ID for helpfulness feedback
  onHelpfulnessFeedback?: (
    messageId: string,
    helpfulness: 'helpful' | 'not_helpful',
    relatedTaskId: string,
    taskType?: 'training' | 'inference' | 'analysis',
    taskTitle?: string
  ) => void
  savedHelpfulnessFeedback?: 'helpful' | 'not_helpful' | null  // Previously saved feedback to restore UI state
}

/**
 * Parse [INTERNAL_ANALYSIS_CONFIG] block from message content
 */
export function parseInternalAnalysisConfig(content: string): AgentInternalAnalysisConfig | null {
  const match = content.match(/\[INTERNAL_ANALYSIS_CONFIG\]([\s\S]*?)\[\/INTERNAL_ANALYSIS_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [INTERNAL_ANALYSIS_CONFIG] block from content for display
 */
export function removeInternalAnalysisConfigBlock(content: string): string {
  return content.replace(/\[INTERNAL_ANALYSIS_CONFIG\][\s\S]*?\[\/INTERNAL_ANALYSIS_CONFIG\]/g, '').trim()
}

export function InternalAnalysisConfigCard({
  config: initialConfig,
  onSubmitSuccess,
  onSubmitError,
  onConfigChange,
  messageId,
  onHelpfulnessFeedback,
  savedHelpfulnessFeedback
}: InternalAnalysisConfigCardProps) {
  const [config, setConfig] = useState<AgentInternalAnalysisConfig>(initialConfig)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>(
    initialConfig.submitted_analysis_id ? 'success' : 'idle'
  )
  const [errorMessage, setErrorMessage] = useState<string>('')
  // Helpfulness feedback state - initialize with saved feedback if available
  const [helpfulnessFeedback, setHelpfulnessFeedback] = useState<'helpful' | 'not_helpful' | null>(savedHelpfulnessFeedback || null)

  // Task validation
  const [isLoadingTask, setIsLoadingTask] = useState(true)
  const [taskExists, setTaskExists] = useState(true)

  // Validate task exists on mount
  useEffect(() => {
    const checkTask = async () => {
      setIsLoadingTask(true)
      try {
        const tasks = await getTrainingTasks()
        const found = tasks.some(t => t.task_id === config.task_id && t.status === 'completed')
        setTaskExists(found)
      } catch (error) {
        console.error('Failed to check task:', error)
        setTaskExists(false)
      } finally {
        setIsLoadingTask(false)
      }
    }
    checkTask()
  }, [config.task_id])

  const handleSubmit = async () => {
    setIsSubmitting(true)
    setSubmitStatus('idle')
    setErrorMessage('')

    try {
      const result = await runTaskAnalysis(
        config.task_id,
        config.metrics,
        config.charts,
        config.description
      )

      setSubmitStatus('success')
      // Update config with submitted analysis ID for persistence
      const updatedConfig = { ...config, submitted_analysis_id: result.analysis_id }
      setConfig(updatedConfig)
      onConfigChange?.(updatedConfig)
      onSubmitSuccess?.(result.task_id, result.analysis_id)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to run analysis'
      setSubmitStatus('error')
      setErrorMessage(msg)
      onSubmitError?.(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoadingTask) {
    return (
      <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm p-6 flex items-center justify-center gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-primary-600" />
        <span className="text-gray-600">Loading analysis configuration...</span>
      </div>
    )
  }

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-blue-50 to-cyan-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-blue-600" />
          Internal Analysis
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          {submitStatus === 'success'
            ? 'Analysis completed successfully'
            : 'Analyze model performance on the held-out test set'}
        </p>
      </div>

      {/* Config Display */}
      <div className="p-5 space-y-4">
        {/* Task Info */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-1.5">
            <FileText className="w-4 h-4 text-gray-500" />
            Training Task
          </label>
          {!taskExists ? (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">Task not found: {config.task_name || config.task_id}</p>
              <p className="text-xs text-red-600 mt-1">The task may have been deleted or not completed.</p>
            </div>
          ) : (
            <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="font-medium text-gray-900">{config.task_name}</div>
              <div className="text-xs text-gray-500 mt-1">ID: {config.task_id}</div>
            </div>
          )}
        </div>

        {/* Metrics */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Metrics to Calculate</label>
          <div className="flex flex-wrap gap-2">
            {config.metrics.map(metric => (
              <span key={metric} className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded-full">
                {metric}
              </span>
            ))}
          </div>
        </div>

        {/* Charts */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Charts to Generate</label>
          <div className="flex flex-wrap gap-2">
            {config.charts.map(chart => (
              <span key={chart} className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded-full">
                {chart.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Error Message */}
      {submitStatus === 'error' && errorMessage && (
        <div className="mx-5 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">Failed to run analysis</p>
            <p className="text-xs text-red-600 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Success Message */}
      {submitStatus === 'success' && (
        <div className="mx-5 mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <p className="text-sm font-medium text-green-700">Analysis completed successfully!</p>
        </div>
      )}

      {/* Helpfulness Feedback */}
      {submitStatus === 'success' && !helpfulnessFeedback && (
        <div className="mx-5 mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-800 mb-2">Do you find AI helpful for this task?</p>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setHelpfulnessFeedback('helpful')
                const taskId = config.submitted_analysis_id || config.task_id
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'helpful', taskId, 'analysis', config.task_name || undefined)
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-100 hover:bg-green-200 text-green-700 rounded-md text-sm font-medium transition-colors"
            >
              <ThumbsUp className="w-3.5 h-3.5" />
              Yes
            </button>
            <button
              onClick={() => {
                setHelpfulnessFeedback('not_helpful')
                const taskId = config.submitted_analysis_id || config.task_id
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'not_helpful', taskId, 'analysis', config.task_name || undefined)
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-100 hover:bg-red-200 text-red-700 rounded-md text-sm font-medium transition-colors"
            >
              <ThumbsDown className="w-3.5 h-3.5" />
              No
            </button>
          </div>
        </div>
      )}

      {/* Helpfulness Feedback Submitted */}
      {submitStatus === 'success' && helpfulnessFeedback && (
        <div className="mx-5 mb-4 p-3 bg-gray-50 border border-gray-200 rounded-lg flex items-center gap-2">
          {helpfulnessFeedback === 'helpful' ? (
            <ThumbsUp className="w-4 h-4 text-green-500" />
          ) : (
            <ThumbsDown className="w-4 h-4 text-red-500" />
          )}
          <p className="text-sm text-gray-600">
            Thank you for your feedback!
          </p>
        </div>
      )}

      {/* Submit Button */}
      <div className="px-5 py-4 bg-gray-50 border-t border-gray-100">
        <button
          onClick={handleSubmit}
          disabled={isSubmitting || submitStatus === 'success' || !taskExists}
          className="w-full py-2.5 bg-blue-600 text-white rounded-lg font-medium text-sm
                     hover:bg-blue-700 active:bg-blue-800
                     disabled:bg-gray-300 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 transition-colors"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Running Analysis...
            </>
          ) : submitStatus === 'success' ? (
            <>
              <CheckCircle className="w-4 h-4" />
              Analysis Complete
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Run Analysis
            </>
          )}
        </button>
      </div>
    </div>
  )
}

