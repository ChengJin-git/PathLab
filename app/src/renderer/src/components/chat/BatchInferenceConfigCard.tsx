import { useState, useRef } from 'react'
import { useConfirmedSubmission } from '../../lib/hooks/useConfirmedSubmission'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Play, CheckCircle, Loader2, AlertCircle, ArrowRight, PlayCircle, Cpu } from 'lucide-react'
import { startBatchInference, startIndependentInference } from '../../api/batchInference'
import { dataTypeLabel } from '../../lib/dataTypeLabel'

export interface BatchInferenceConfig {
  mode?: 'dataset' | 'uploaded_wsi'
  model_task_id?: string
  model_id: string
  dataset_id?: string
  wsi_ids?: string[]
  model_name?: string
  dataset_name?: string
  task_type?: string
  data_type?: string
  submitted_task_id?: string
}

interface BatchInferenceConfigCardProps {
  config: BatchInferenceConfig
  onSubmitSuccess?: (taskId: string) => void
  onSubmitError?: (error: string) => void
  onConfigChange?: (config: BatchInferenceConfig) => void
  messageId?: string
  submitTrigger?: number
}

export function parseBatchInferenceConfig(content: string): BatchInferenceConfig | null {
  const match = content.match(/\[BATCH_INFERENCE_CONFIG\]([\s\S]*?)\[\/BATCH_INFERENCE_CONFIG\]/)
  if (!match) return null
  try {
    const config = JSON.parse(match[1].trim()) as BatchInferenceConfig
    if (config.mode === 'uploaded_wsi') {
      if (!config.model_id || !Array.isArray(config.wsi_ids) || config.wsi_ids.length === 0) return null
      return config
    }
    if (!config.model_task_id || !config.model_id || !config.dataset_id) return null
    return config
  } catch {
    return null
  }
}

export function removeBatchInferenceConfigBlock(content: string): string {
  return content.replace(/\[BATCH_INFERENCE_CONFIG\][\s\S]*?\[\/BATCH_INFERENCE_CONFIG\]/g, '').trim()
}

export function BatchInferenceConfigCard({
  config: initialConfig,
  onSubmitSuccess,
  onSubmitError,
  onConfigChange,
  submitTrigger,
}: BatchInferenceConfigCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [config, setConfig] = useState<BatchInferenceConfig>(initialConfig)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>(
    initialConfig.submitted_task_id ? 'success' : 'idle'
  )
  const [errorMessage, setErrorMessage] = useState<string>('')
  const submittingRef = useRef(false)

  const isUploadedWsiMode = config.mode === 'uploaded_wsi'
  const hasUploadedWsiConfig = Boolean(
    config.model_id && Array.isArray(config.wsi_ids) && config.wsi_ids.length > 0
  )
  const hasDatasetConfig = Boolean(config.model_task_id && config.model_id && config.dataset_id)
  const isMissingConfig = isUploadedWsiMode ? !hasUploadedWsiConfig : !hasDatasetConfig

  const handleSubmit = async () => {
    if (isMissingConfig || submittingRef.current || submitStatus === 'success') return
    submittingRef.current = true
    setIsSubmitting(true)
    setErrorMessage('')
    try {
      const result = isUploadedWsiMode
        ? await startIndependentInference({
            model_id: config.model_id,
            wsi_ids: config.wsi_ids ?? [],
          })
        : await startBatchInference({
            model_task_id: config.model_task_id ?? '',
            model_id: config.model_id,
            dataset_id: config.dataset_id ?? '',
          })
      const updatedConfig = { ...config, submitted_task_id: result.task_id }
      setConfig(updatedConfig)
      onConfigChange?.(updatedConfig)
      setSubmitStatus('success')
      onSubmitSuccess?.(result.task_id)
    } catch (error) {
      const msg = error instanceof Error ? error.message : t('chatComponents.batchInferenceConfig.failedToSubmit')
      setSubmitStatus('error')
      setErrorMessage(msg)
      onSubmitError?.(msg)
    } finally {
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }

  useConfirmedSubmission(submitTrigger, !isMissingConfig,
    isSubmitting || submitStatus === 'success' || isMissingConfig, handleSubmit)

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-purple-50 to-violet-50">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-purple-600" />
          {t('chatComponents.batchInferenceConfig.title')}
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          {submitStatus === 'success'
            ? t('chatComponents.batchInferenceConfig.inferenceStarted')
            : t('chatComponents.batchInferenceConfig.description')}
        </p>
      </div>

      {/* Config Display */}
      <div className="p-5 space-y-4">
        {isMissingConfig ? (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{t('chatComponents.batchInferenceConfig.missingConfig')}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                {t('chatComponents.batchInferenceConfig.model')}
              </label>
              <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
                <div className="font-medium text-gray-900 text-sm">{config.model_name || config.model_id}</div>
                {config.task_type && (
                  <div className="text-xs text-gray-500 mt-0.5">{t(`training.taskSetup.${config.task_type}`, { defaultValue: config.task_type })}</div>
                )}
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                {t('chatComponents.batchInferenceConfig.dataset')}
              </label>
              <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg">
                <div className="font-medium text-gray-900 text-sm">
                  {isUploadedWsiMode
                    ? t('chatComponents.batchInferenceConfig.uploadedImages')
                    : config.dataset_name || config.dataset_id}
                </div>
                {isUploadedWsiMode && (
                  <div className="text-xs text-gray-500 mt-0.5">
                    {t('chatComponents.batchInferenceConfig.imageCount', { count: config.wsi_ids?.length ?? 0 })}
                  </div>
                )}
                {config.data_type && (
                  <div className="text-xs text-gray-500 mt-0.5">{dataTypeLabel(t, config.data_type)}</div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Error Message */}
      {submitStatus === 'error' && errorMessage && (
        <div className="mx-5 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">{t('chatComponents.batchInferenceConfig.failedToSubmit')}</p>
            <p className="text-xs text-red-600 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Success Navigation */}
      {submitStatus === 'success' && config.submitted_task_id && (
        <div className="mx-5 mb-4 space-y-3">
          <div className="p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <p className="text-sm font-medium text-green-700">{t('chatComponents.batchInferenceConfig.submitted')}</p>
          </div>
          <button
            onClick={() => navigate(`/task/${config.submitted_task_id}`)}
            className="w-full py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-medium text-sm flex items-center justify-center gap-2 transition-colors shadow-sm hover:shadow-md"
          >
            <PlayCircle className="w-4 h-4" />
            {t('chatComponents.batchInferenceConfig.viewTaskDetail')}
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Submit Button */}
      <div className="px-5 py-4 bg-gray-50 border-t border-gray-100">
        <button
          onClick={handleSubmit}
          disabled={isSubmitting || submitStatus === 'success' || isMissingConfig}
          className="w-full py-2.5 text-white rounded-lg font-medium text-sm
                     bg-purple-600 hover:bg-purple-700 active:bg-purple-800
                     disabled:bg-gray-300 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 transition-colors"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('chatComponents.batchInferenceConfig.submitting')}
            </>
          ) : submitStatus === 'success' ? (
            <>
              <CheckCircle className="w-4 h-4" />
              {t('chatComponents.batchInferenceConfig.submitted')}
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              {t('chatComponents.batchInferenceConfig.submit')}
            </>
          )}
        </button>
      </div>
    </div>
  )
}
