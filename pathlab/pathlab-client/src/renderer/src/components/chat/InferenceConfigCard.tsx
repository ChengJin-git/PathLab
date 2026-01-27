import { useState, useEffect } from 'react'
import { Play, AlertCircle, CheckCircle, Loader2, Brain, Database, ThumbsUp, ThumbsDown } from 'lucide-react'
import {
  getTrainedModels,
  getTrainingTasks,
  startExternalValidation,
  type TrainedModel,
  type TrainingTask
} from '../../api'

// Config from Agent
export interface AgentInferenceConfig {
  model_id: string
  model_name: string
  data_task_id: string  // Required - the task whose data will be used for validation
  submitted_task_id?: string  // Set after successful submission for persistence
}

interface InferenceConfigCardProps {
  config: AgentInferenceConfig
  onSubmitSuccess?: (taskId: string) => void
  onSubmitError?: (error: string) => void
  onConfigChange?: (config: AgentInferenceConfig) => void
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

interface ValidationError {
  field: string
  message: string
}

/**
 * Parse [INFERENCE_CONFIG] block from message content
 */
export function parseInferenceConfig(content: string): AgentInferenceConfig | null {
  const match = content.match(/\[INFERENCE_CONFIG\]([\s\S]*?)\[\/INFERENCE_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [INFERENCE_CONFIG] block from content for display
 */
export function removeInferenceConfigBlock(content: string): string {
  return content.replace(/\[INFERENCE_CONFIG\][\s\S]*?\[\/INFERENCE_CONFIG\]/g, '').trim()
}

export function InferenceConfigCard({
  config: initialConfig,
  onSubmitSuccess,
  onSubmitError,
  onConfigChange,
  messageId,
  onHelpfulnessFeedback,
  savedHelpfulnessFeedback
}: InferenceConfigCardProps) {
  const [config, setConfig] = useState<AgentInferenceConfig>(initialConfig)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>(
    initialConfig.submitted_task_id ? 'success' : 'idle'
  )
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  // Helpfulness feedback state - initialize with saved feedback if available
  const [helpfulnessFeedback, setHelpfulnessFeedback] = useState<'helpful' | 'not_helpful' | null>(savedHelpfulnessFeedback || null)

  // Sync submitStatus when initialConfig.submitted_task_id changes (e.g., after reload)
  useEffect(() => {
    if (initialConfig.submitted_task_id) {
      setSubmitStatus('success')
      setConfig(initialConfig)
    }
  }, [initialConfig.submitted_task_id])

  // Sync helpfulnessFeedback when savedHelpfulnessFeedback changes (e.g., after reload)
  useEffect(() => {
    if (savedHelpfulnessFeedback) {
      setHelpfulnessFeedback(savedHelpfulnessFeedback)
    }
  }, [savedHelpfulnessFeedback])

  // Data loading states
  const [models, setModels] = useState<TrainedModel[]>([])
  const [tasks, setTasks] = useState<TrainingTask[]>([])
  const [isLoadingModels, setIsLoadingModels] = useState(true)
  const [isLoadingTasks, setIsLoadingTasks] = useState(false)

  // Selected model info
  const [selectedModel, setSelectedModel] = useState<TrainedModel | null>(null)

  // Load models on mount
  useEffect(() => {
    loadModels()
  }, [])

  // Load tasks for external validation
  useEffect(() => {
    loadTasks()
  }, [])

  // Find selected model when models are loaded
  useEffect(() => {
    if (models.length > 0 && config.model_id) {
      const found = models.find(m => m.model_id === config.model_id)
      setSelectedModel(found || null)
    }
  }, [models, config.model_id])

  const loadModels = async () => {
    setIsLoadingModels(true)
    try {
      const result = await getTrainedModels()
      setModels(result.items.filter(m => m.is_active))
    } catch (error) {
      console.error('Failed to load models:', error)
    } finally {
      setIsLoadingModels(false)
    }
  }

  const loadTasks = async () => {
    setIsLoadingTasks(true)
    try {
      const result = await getTrainingTasks()
      // Filter to completed tasks only, exclude the model's own task
      const completedTasks = result.filter(t => 
        t.status === 'completed' && 
        t.task_id !== selectedModel?.task_id
      )
      setTasks(completedTasks)
    } catch (error) {
      console.error('Failed to load tasks:', error)
    } finally {
      setIsLoadingTasks(false)
    }
  }

  const updateConfig = (field: keyof AgentInferenceConfig, value: string | null) => {
    const newConfig = { ...config, [field]: value }
    setConfig(newConfig)
    onConfigChange?.(newConfig)
    setValidationErrors(prev => prev.filter(e => e.field !== field))
  }

  const validate = (): boolean => {
    const errors: ValidationError[] = []

    if (!config.model_id) {
      errors.push({ field: 'model_id', message: 'Model is required' })
    } else if (!selectedModel) {
      errors.push({ field: 'model_id', message: 'Selected model not found or inactive' })
    }

    if (!config.data_task_id) {
      errors.push({ field: 'data_task_id', message: 'Please select a dataset for external validation' })
    }

    setValidationErrors(errors)
    return errors.length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setIsSubmitting(true)
    setSubmitStatus('idle')
    setErrorMessage('')

    try {
      const result = await startExternalValidation(config.model_id, config.data_task_id)

      setSubmitStatus('success')
      // Update config with submitted task ID for persistence
      const updatedConfig = { ...config, submitted_task_id: result.task_id }
      setConfig(updatedConfig)
      onConfigChange?.(updatedConfig)
      onSubmitSuccess?.(result.task_id)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to start external validation'
      setSubmitStatus('error')
      setErrorMessage(msg)
      onSubmitError?.(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  const getFieldError = (field: string) => validationErrors.find(e => e.field === field)?.message

  // Form is disabled after successful submission
  const isFormDisabled = submitStatus === 'success' || isSubmitting

  // Get selected task info for display
  const selectedTask = tasks.find(t => t.task_id === config.data_task_id)

  if (isLoadingModels) {
    return (
      <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm p-6 flex items-center justify-center gap-2">
        <Loader2 className="w-5 h-5 animate-spin text-primary-600" />
        <span className="text-gray-600">Loading inference configuration...</span>
      </div>
    )
  }

  // Check if model exists
  const modelNotFound = !selectedModel && config.model_id

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-purple-50 to-indigo-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-600" />
          External Validation
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          {submitStatus === 'success'
            ? 'External validation task submitted successfully'
            : 'Validate a trained model on a different dataset'}
        </p>
      </div>

      {/* Form Fields */}
      <div className="p-5 space-y-4">
        {/* Model Selection - Read Only Display */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-1.5">
            <Brain className="w-4 h-4 text-gray-500" />
            Selected Model
          </label>
          {modelNotFound ? (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">
                Model not found: {config.model_name || config.model_id}
              </p>
              <p className="text-xs text-red-600 mt-1">
                The selected model may have been deleted or deactivated.
              </p>
            </div>
          ) : selectedModel ? (
            <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="font-medium text-gray-900">{selectedModel.model_name}</div>
              <div className="text-xs text-gray-500 mt-1 flex flex-wrap gap-2">
                <span>Classes: {selectedModel.classes?.join(', ') || 'N/A'}</span>
                <span>•</span>
                <span>Encoder: {selectedModel.feature_extractor || 'N/A'}</span>
              </div>
            </div>
          ) : (
            <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
              <p className="text-sm text-yellow-700">No model specified in configuration</p>
            </div>
          )}
          {getFieldError('model_id') && (
            <p className="text-xs text-red-500 mt-1">{getFieldError('model_id')}</p>
          )}
        </div>

        {/* Validation Dataset Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-1.5">
            <Database className="w-4 h-4 text-gray-500" />
            Validation Dataset
          </label>
          <p className="text-xs text-gray-500 mb-2">
            Select a dataset to validate the model on. This must be different from the model's training dataset.
          </p>
          {isLoadingTasks ? (
            <div className="p-3 border border-gray-200 rounded-lg flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-gray-500" />
              <span className="text-sm text-gray-500">Loading datasets...</span>
            </div>
          ) : (
            <select
              value={config.data_task_id || ''}
              onChange={(e) => updateConfig('data_task_id', e.target.value || null)}
              disabled={isFormDisabled}
              className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-purple-100 focus:border-purple-400 ${
                getFieldError('data_task_id') ? 'border-red-300 bg-red-50' : 'border-gray-200'
              } ${isFormDisabled ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`}
            >
              <option value="">Select a dataset...</option>
              {tasks.map(task => (
                <option key={task.task_id} value={task.task_id}>
                  {task.task_name} ({task.task_type})
                </option>
              ))}
            </select>
          )}
          {getFieldError('data_task_id') && (
            <p className="text-xs text-red-500 mt-1">{getFieldError('data_task_id')}</p>
          )}
          {selectedTask && (
            <div className="mt-2 text-xs text-gray-500">
              Task Type: {selectedTask.task_type} | Status: {selectedTask.status}
            </div>
          )}
        </div>
      </div>

      {/* Error Message */}
      {submitStatus === 'error' && errorMessage && (
        <div className="mx-5 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">Failed to start inference</p>
            <p className="text-xs text-red-600 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Success Message */}
      {submitStatus === 'success' && (
        <div className="mx-5 mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <p className="text-sm font-medium text-green-700">Inference task submitted successfully!</p>
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
                const taskId = config.submitted_task_id || ''
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'helpful', taskId, 'inference', config.model_name || undefined)
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
                const taskId = config.submitted_task_id || ''
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'not_helpful', taskId, 'inference', config.model_name || undefined)
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
          disabled={isSubmitting || submitStatus === 'success' || !!modelNotFound}
          className="w-full py-2.5 bg-purple-600 text-white rounded-lg font-medium text-sm
                     hover:bg-purple-700 active:bg-purple-800
                     disabled:bg-gray-300 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 transition-colors"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Starting Inference...
            </>
          ) : submitStatus === 'success' ? (
            <>
              <CheckCircle className="w-4 h-4" />
              Inference Started
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Run Inference
            </>
          )}
        </button>
      </div>
    </div>
  )
}

