import { useTranslation } from 'react-i18next'
import { Activity, CheckCircle, Layers } from 'lucide-react'

export interface BatchInferenceSummaryConfig {
  task_id: string
  task_name?: string
  model_name?: string
  dataset_name?: string
  total_slides?: number
  completed_slides?: number
  task_type?: string
  status?: string
}

export function parseBatchInferenceSummary(content: string): BatchInferenceSummaryConfig | null {
  const match = content.match(/\[BATCH_INFERENCE_SUMMARY\]([\s\S]*?)\[\/BATCH_INFERENCE_SUMMARY\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim()) as BatchInferenceSummaryConfig
  } catch {
    return null
  }
}

export function removeBatchInferenceSummaryBlock(content: string): string {
  return content.replace(/\[BATCH_INFERENCE_SUMMARY\][\s\S]*?\[\/BATCH_INFERENCE_SUMMARY\]/g, '').trim()
}

interface BatchInferenceSummaryCardProps {
  config: BatchInferenceSummaryConfig
}

export function BatchInferenceSummaryCard({ config }: BatchInferenceSummaryCardProps) {
  const { t } = useTranslation()

  const isComplete = config.status === 'completed'
  const progress = config.total_slides && config.total_slides > 0
    ? Math.round(((config.completed_slides ?? 0) / config.total_slides) * 100)
    : 0

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-purple-50 to-violet-50">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          {isComplete ? (
            <CheckCircle className="w-4 h-4 text-purple-600" />
          ) : (
            <Activity className="w-4 h-4 text-purple-600" />
          )}
          {t('resultsPage.batchInference.summary.title')}
        </h3>
      </div>

      <div className="p-5 space-y-4">
        {config.task_name && (
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              {t('resultsPage.batchInference.selectTask')}
            </p>
            <p className="text-sm font-medium text-gray-900">{config.task_name}</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          {config.model_name && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                {t('resultsPage.batchInference.summary.model')}
              </p>
              <p className="text-sm text-gray-900">{config.model_name}</p>
            </div>
          )}
          {config.dataset_name && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                {t('resultsPage.batchInference.summary.dataset')}
              </p>
              <p className="text-sm text-gray-900">{config.dataset_name}</p>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              {t('resultsPage.batchInference.summary.totalSlides')}
            </p>
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1">
              <Layers className="w-3.5 h-3.5 text-purple-500" />
              {config.total_slides ?? '—'}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              {t('resultsPage.batchInference.summary.completedSlides')}
            </p>
            <p className="text-sm font-semibold text-gray-900">
              {config.completed_slides ?? '—'}
            </p>
          </div>
        </div>

        {config.total_slides && config.total_slides > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-gray-500">{progress}%</span>
            </div>
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
        <a
          href="/results"
          className="text-sm font-medium text-purple-600 hover:text-purple-700 transition-colors"
        >
          {t('resultsPage.batchInference.summary.viewResults')}
        </a>
      </div>
    </div>
  )
}
