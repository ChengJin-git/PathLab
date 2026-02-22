import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Play, AlertCircle, CheckCircle, Loader2, BarChart3, FileText, ThumbsUp, ThumbsDown, ArrowRight, FlaskConical } from 'lucide-react'
import { runTaskAnalysis, getTrainingTasks, startExternalValidation, getTrainedModels, fetchDatasetsForValidation } from '../../api'
import { isDatasetCompatible } from '../../lib/externalValidationUtils'

// Config from Agent - supports both internal and external analysis
export interface AgentAnalysisConfig {
  analysis_type: 'internal' | 'external'  // Type of analysis
  task_id: string           // Training task to analyze (internal) or set after external validation
  task_name: string         // Task name for display
  metrics: string[]         // AI-determined metrics
  charts: string[]          // AI-determined charts
  description?: string      // Optional analysis description
  submitted_analysis_id?: string  // Set after successful submission
  compute_bootstrap_ci?: boolean  // Whether to compute 95% CI (set by user checkbox)
  bootstrap_ci_metrics?: string[] // Metrics for 95% CI (set by AI when user asks for CI)
  // External validation specific fields
  model_id?: string         // TrainedModel ID for external validation
  data_task_id?: string     // Target dataset task ID for external validation
  source_name?: string      // Source model name for display
  target_name?: string      // Target dataset name for display
  external_validation_task_id?: string  // Set after external validation starts
  // Auto-submit: when true, automatically submit without user clicking (for voice commands)
  auto_submit?: boolean
}

interface AnalysisConfigCardProps {
  config: AgentAnalysisConfig
  onSubmitSuccess?: (taskId: string, analysisId: string) => void
  onSubmitError?: (error: string) => void
  onConfigChange?: (config: AgentAnalysisConfig) => void
  messageId?: string
  onHelpfulnessFeedback?: (
    messageId: string,
    helpfulness: 'helpful' | 'not_helpful',
    relatedTaskId: string,
    taskType?: 'training' | 'inference' | 'analysis',
    taskTitle?: string
  ) => void
  savedHelpfulnessFeedback?: 'helpful' | 'not_helpful' | null
}

/**
 * Parse [ANALYSIS_CONFIG] block from AI response
 */
export function parseAnalysisConfig(content: string): AgentAnalysisConfig | null {
  const match = content.match(/\[ANALYSIS_CONFIG\]([\s\S]*?)\[\/ANALYSIS_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    const config = JSON.parse(jsonStr)
    // Default to internal if not specified
    if (!config.analysis_type) config.analysis_type = 'internal'
    return config
  } catch {
    return null
  }
}

/**
 * Remove [ANALYSIS_CONFIG] block from content
 */
export function removeAnalysisConfigBlock(content: string): string {
  return content.replace(/\[ANALYSIS_CONFIG\][\s\S]*?\[\/ANALYSIS_CONFIG\]/g, '').trim()
}

export function AnalysisConfigCard({
  config: initialConfig,
  onSubmitSuccess,
  onSubmitError,
  onConfigChange,
  messageId,
  onHelpfulnessFeedback,
  savedHelpfulnessFeedback
}: AnalysisConfigCardProps) {
  const { t } = useTranslation()
  const [config, setConfig] = useState<AgentAnalysisConfig>(initialConfig)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>(
    initialConfig.submitted_analysis_id || initialConfig.external_validation_task_id ? 'success' : 'idle'
  )
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [helpfulnessFeedback, setHelpfulnessFeedback] = useState<'helpful' | 'not_helpful' | null>(savedHelpfulnessFeedback || null)
  // Initialize checkbox: true if compute_bootstrap_ci is set OR if bootstrap_ci_metrics array exists and is non-empty
  const [computeBootstrapCI, setComputeBootstrapCI] = useState<boolean>(
    initialConfig.compute_bootstrap_ci ?? (initialConfig.bootstrap_ci_metrics && initialConfig.bootstrap_ci_metrics.length > 0) ?? false
  )
  // Track if auto-submit has been triggered (to prevent multiple submissions)
  const [autoSubmitTriggered, setAutoSubmitTriggered] = useState(false)

  // Sync submitStatus when initialConfig changes (e.g., after reload)
  useEffect(() => {
    if (initialConfig.submitted_analysis_id || initialConfig.external_validation_task_id) {
      setSubmitStatus('success')
      setConfig(initialConfig)
    }
  }, [initialConfig.submitted_analysis_id, initialConfig.external_validation_task_id])

  // Sync helpfulnessFeedback when savedHelpfulnessFeedback changes (e.g., after reload)
  useEffect(() => {
    if (savedHelpfulnessFeedback) {
      setHelpfulnessFeedback(savedHelpfulnessFeedback)
    }
  }, [savedHelpfulnessFeedback])

  // Task/model validation
  const [isLoadingTask, setIsLoadingTask] = useState(true)
  const [taskExists, setTaskExists] = useState(true)
  const [validationError, setValidationError] = useState<string>('')

  const isExternal = config.analysis_type === 'external'

  // Validate task/model exists on mount
  useEffect(() => {
    const checkTask = async () => {
      setIsLoadingTask(true)
      setValidationError('')
      try {
        const tasks = await getTrainingTasks()
        if (isExternal) {
          // For external: validate model and dataset compatibility using same logic as ResultsViewerPage
          if (!config.model_id || !config.data_task_id) {
            setTaskExists(false)
            setValidationError('Missing model or dataset configuration')
            return
          }

          // Fetch model and dataset details
          const [models, datasets] = await Promise.all([
            getTrainedModels(),
            fetchDatasetsForValidation()
          ])

          const model = models.find(m => m.model_id === config.model_id)
          if (!model) {
            setTaskExists(false)
            setValidationError(`Model not found: ${config.model_id}`)
            return
          }

          const modelTask = tasks.find(task => task.task_id === model.task_id)
          if (!modelTask) {
            setTaskExists(false)
            setValidationError(`Training task not found for model: ${model.model_name}`)
            return
          }

          const dataset = datasets.items.find(ds => ds.dataset_id === config.data_task_id)
          if (!dataset) {
            setTaskExists(false)
            setValidationError(`Dataset not found: ${config.data_task_id}`)
            return
          }

          // Check compatibility using shared validation logic
          const compatible = isDatasetCompatible(model, modelTask, dataset)
          if (!compatible) {
            setTaskExists(false)
            setValidationError(
              `Dataset "${dataset.name}" is not compatible with model "${model.model_name}". ` +
              `Please check that task types, data types, and label sets match.`
            )
            return
          }

          setTaskExists(true)
        } else {
          // For internal: check if task exists and is completed
          const found = tasks.some(task => task.task_id === config.task_id && task.status === 'completed')
          setTaskExists(found)
          if (!found) {
            setValidationError(`Task not found or not completed: ${config.task_id}`)
          }
        }
      } catch (error) {
        console.error('Failed to check task:', error)
        setTaskExists(false)
        setValidationError(error instanceof Error ? error.message : 'Failed to validate configuration')
      } finally {
        setIsLoadingTask(false)
      }
    }
    checkTask()
  }, [config.task_id, config.model_id, config.data_task_id, isExternal])

  // Auto-submit effect: when auto_submit is true and data is ready, automatically submit
  useEffect(() => {
    if (
      initialConfig.auto_submit &&
      !autoSubmitTriggered &&
      submitStatus === 'idle' &&
      !isSubmitting &&
      !isLoadingTask &&
      taskExists
    ) {
      setAutoSubmitTriggered(true)
      const timer = setTimeout(() => {
        handleAutoSubmit()
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [
    initialConfig.auto_submit,
    autoSubmitTriggered,
    submitStatus,
    isSubmitting,
    isLoadingTask,
    taskExists
  ])

  const handleSubmit = async () => {
    setIsSubmitting(true)
    setSubmitStatus('idle')
    setErrorMessage('')

    try {
      if (isExternal && config.model_id && config.data_task_id) {
        // External: start external validation
        // If inference results exist, it will skip GPU and run analysis directly
        // Otherwise, it will run GPU inference first, then auto-trigger analysis
        const extValResult = await startExternalValidation(
          config.model_id,
          config.data_task_id,
          config.metrics,
          config.charts,
          computeBootstrapCI
        )
        const updatedConfig = { ...config, external_validation_task_id: extValResult.task_id, compute_bootstrap_ci: computeBootstrapCI }
        setConfig(updatedConfig)
        onConfigChange?.(updatedConfig)
        setSubmitStatus('success')
        // For external, pass the extval task_id but no analysis_id yet
        onSubmitSuccess?.(extValResult.task_id, '')
      } else {
        // Internal: run analysis directly
        const bootstrapCIMetrics = computeBootstrapCI ? config.metrics : undefined
        const result = await runTaskAnalysis(
          config.task_id,
          config.metrics,
          config.charts,
          config.description,
          bootstrapCIMetrics
        )
        const updatedConfig = { ...config, submitted_analysis_id: result.analysis_id, compute_bootstrap_ci: computeBootstrapCI }
        setConfig(updatedConfig)
        onConfigChange?.(updatedConfig)
        setSubmitStatus('success')
        onSubmitSuccess?.(result.task_id, result.analysis_id)
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : t('chatComponents.analysisConfig.failedToRunAnalysis')
      setSubmitStatus('error')
      setErrorMessage(msg)
      onSubmitError?.(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  // Auto-submit handler: similar to handleSubmit but called automatically (AI already confirmed)
  const handleAutoSubmit = async () => {
    if (isSubmitting || submitStatus === 'success') return

    setIsSubmitting(true)
    setSubmitStatus('idle')
    setErrorMessage('')

    try {
      if (isExternal && config.model_id && config.data_task_id) {
        const extValResult = await startExternalValidation(
          config.model_id,
          config.data_task_id,
          config.metrics,
          config.charts,
          computeBootstrapCI
        )
        const updatedConfig = { ...config, external_validation_task_id: extValResult.task_id, compute_bootstrap_ci: computeBootstrapCI }
        setConfig(updatedConfig)
        onConfigChange?.(updatedConfig)
        setSubmitStatus('success')
        onSubmitSuccess?.(extValResult.task_id, '')
      } else {
        const bootstrapCIMetrics = computeBootstrapCI ? config.metrics : undefined
        const result = await runTaskAnalysis(
          config.task_id,
          config.metrics,
          config.charts,
          config.description,
          bootstrapCIMetrics
        )
        const updatedConfig = { ...config, submitted_analysis_id: result.analysis_id, compute_bootstrap_ci: computeBootstrapCI }
        setConfig(updatedConfig)
        onConfigChange?.(updatedConfig)
        setSubmitStatus('success')
        onSubmitSuccess?.(result.task_id, result.analysis_id)
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : t('chatComponents.analysisConfig.failedToRunAnalysis')
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
        <span className="text-gray-600">{t('chatComponents.analysisConfig.loadingConfig')}</span>
      </div>
    )
  }

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className={`px-5 py-4 border-b border-gray-100 ${isExternal ? 'bg-gradient-to-r from-orange-50 to-amber-50' : 'bg-gradient-to-r from-indigo-50 to-blue-50'}`}>
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          {isExternal ? (
            <FlaskConical className="w-4 h-4 text-orange-600" />
          ) : (
            <BarChart3 className="w-4 h-4 text-indigo-600" />
          )}
          {isExternal ? t('chatComponents.analysisConfig.externalValidation') : t('chatComponents.analysisConfig.internalAnalysis')}
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          {submitStatus === 'success'
            ? t('chatComponents.analysisConfig.analysisSubmittedTrack')
            : isExternal
              ? t('chatComponents.analysisConfig.validateOnExternalDataset')
              : t('chatComponents.analysisConfig.analyzeOnTestSet')}
        </p>
      </div>

      {/* Config Display */}
      <div className="p-5 space-y-4">
        {/* Task/Model Info */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-1.5">
            <FileText className="w-4 h-4 text-gray-500" />
            {isExternal ? t('chatComponents.analysisConfig.validationSetup') : t('chatComponents.analysisConfig.trainingTask')}
          </label>
          {!taskExists ? (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">
                {validationError || (isExternal
                  ? `Missing model or target dataset configuration`
                  : `Task not found: ${config.task_name || config.task_id}`)}
              </p>
            </div>
          ) : isExternal ? (
            <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">{config.source_name || 'Model'}</span>
                <ArrowRight className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900">{config.target_name || 'Target Dataset'}</span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                Model: {config.model_id} → Dataset: {config.data_task_id}
              </div>
            </div>
          ) : (
            <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <div className="font-medium text-gray-900">{config.task_name}</div>
              <div className="text-xs text-gray-500 mt-1">ID: {config.task_id}</div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Metrics */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.analysisConfig.metricsToCalculate')}</label>
            <div className="flex flex-wrap gap-2">
              {config.metrics.map(metric => (
                <span key={metric} className={`px-2 py-1 text-xs rounded-full ${isExternal ? 'bg-orange-100 text-orange-700' : 'bg-indigo-100 text-indigo-700'}`}>
                  {metric}
                </span>
              ))}
            </div>
          </div>

          {/* Charts */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('chatComponents.analysisConfig.chartsToGenerate')}</label>
            <div className="flex flex-wrap gap-2">
              {config.charts.map(chart => (
                <span key={chart} className={`px-2 py-1 text-xs rounded-full ${isExternal ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                  {chart.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Bootstrap CI Option */}
        <div className="pt-2 border-t border-gray-100">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={computeBootstrapCI}
              onChange={(e) => setComputeBootstrapCI(e.target.checked)}
              disabled={submitStatus === 'success'}
              className={`w-4 h-4 border-gray-300 rounded disabled:opacity-50 ${isExternal ? 'text-orange-600 focus:ring-orange-500' : 'text-indigo-600 focus:ring-indigo-500'}`}
            />
            <span className="text-sm text-gray-700">
              {t('chatComponents.analysisConfig.computeBootstrapCI')}
            </span>
          </label>
          <p className="text-xs text-gray-500 mt-1 ml-6">
            {t('chatComponents.analysisConfig.bootstrapCIDescription')}
          </p>
        </div>
      </div>

      {/* Error Message */}
      {submitStatus === 'error' && errorMessage && (
        <div className="mx-5 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">{t('chatComponents.analysisConfig.failedToRunAnalysis')}</p>
            <p className="text-xs text-red-600 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Success Message */}
      {submitStatus === 'success' && (
        <div className="mx-5 mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <p className="text-sm font-medium text-green-700">{t('chatComponents.analysisConfig.analysisCompletedSuccess')}</p>
        </div>
      )}

      {/* Helpfulness Feedback */}
      {submitStatus === 'success' && !helpfulnessFeedback && (
        <div className="mx-5 mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm font-medium text-blue-800 mb-3">{t('chatComponents.analysisConfig.helpfulnessFeedbackQuestion')}</p>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setHelpfulnessFeedback('helpful')
                const taskId = config.submitted_analysis_id || config.task_id
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'helpful', taskId, 'analysis', config.task_name || undefined)
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-blue-200 hover:bg-green-50 hover:border-green-300 hover:text-green-700 text-blue-700 rounded-md text-sm font-medium transition-all shadow-sm"
            >
              <ThumbsUp className="w-3.5 h-3.5" />
              {t('common.yes')}
            </button>
            <button
              onClick={() => {
                setHelpfulnessFeedback('not_helpful')
                const taskId = config.submitted_analysis_id || config.task_id
                if (messageId && onHelpfulnessFeedback) {
                  onHelpfulnessFeedback(messageId, 'not_helpful', taskId, 'analysis', config.task_name || undefined)
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-blue-200 hover:bg-red-50 hover:border-red-300 hover:text-red-700 text-blue-700 rounded-md text-sm font-medium transition-all shadow-sm"
            >
              <ThumbsDown className="w-3.5 h-3.5" />
              {t('common.no')}
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
            {t('chatComponents.analysisConfig.thankYouFeedback')}
          </p>
        </div>
      )}

      {/* Submit Button */}
      <div className="px-5 py-4 bg-gray-50 border-t border-gray-100">
        <button
          onClick={handleSubmit}
          disabled={isSubmitting || submitStatus === 'success' || !taskExists}
          className={`w-full py-2.5 text-white rounded-lg font-medium text-sm
                     disabled:bg-gray-300 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 transition-colors ${
                       isExternal
                         ? 'bg-orange-600 hover:bg-orange-700 active:bg-orange-800'
                         : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800'
                     }`}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('chatComponents.analysisConfig.submitting')}
            </>
          ) : submitStatus === 'success' ? (
            <>
              <CheckCircle className="w-4 h-4" />
              {isExternal ? t('chatComponents.analysisConfig.validationStarted') : t('chatComponents.analysisConfig.analysisSubmitted')}
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              {isExternal ? t('chatComponents.analysisConfig.startExternalValidation') : t('chatComponents.analysisConfig.runAnalysis')}
            </>
          )}
        </button>
      </div>
    </div>
  )
}
