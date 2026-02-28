import { useState, useMemo, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { PackagePlus, Loader2 } from 'lucide-react'
import { AnnotationsMap, extractRegions } from '../../api/annotation'
import { useToast } from '../../contexts/ToastContext'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'

interface CreateDatasetDialogProps {
  show: boolean
  onClose: () => void
  allAnnotations: AnnotationsMap
  labelColors: Record<string, string>
  sourceDatasetId?: string
  draftId?: string
  /** True if any annotated source slide is a WSI (not a patch image) */
  hasWsiSources?: boolean
}

export function CreateDatasetDialog({
  show, onClose, allAnnotations, labelColors, sourceDatasetId, draftId,
  hasWsiSources = false,
}: CreateDatasetDialogProps) {
  const { t } = useTranslation()
  const toast = useToast()
  const { addExtractionTask } = useBackgroundTask()
  const [datasetName, setDatasetName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'segmentation'>('classification')
  const [submitting, setSubmitting] = useState(false)

  // Compute summary
  const summary = useMemo(() => {
    const labelCounts: Record<string, number> = {}
    let totalRegions = 0
    const slideIds = new Set<string>()
    for (const [wsiId, regions] of Object.entries(allAnnotations)) {
      if (regions.length === 0) continue
      slideIds.add(wsiId)
      for (const r of regions) {
        totalRegions++
        labelCounts[r.label] = (labelCounts[r.label] || 0) + 1
      }
    }
    return { totalRegions, totalSlides: slideIds.size, labelCounts }
  }, [allAnnotations])

  // Reset state when dialog opens
  useEffect(() => {
    if (show) {
      setDatasetName('')
      setTaskType('classification')
      setSubmitting(false)
    }
  }, [show])

  // Segmentation on existing dataset: reuse instead of creating new
  const isSegReuse = taskType === 'segmentation' && !!sourceDatasetId

  const handleSubmit = async () => {
    if ((!isSegReuse && !datasetName.trim()) || summary.totalRegions === 0 || submitting) return
    setSubmitting(true)

    try {
      const result = await extractRegions({
        draft_id: draftId,
        annotations: allAnnotations,
        dataset_name: isSegReuse ? '' : datasetName.trim(),
        task_type: taskType,
        ...(isSegReuse ? { source_dataset_id: sourceDatasetId } : {}),
      })
      // Register extraction task in background task center for progress tracking
      addExtractionTask(result.task_id, isSegReuse ? t('annotation.reuseDataset') : datasetName.trim())
      toast.success(t('annotation.extractSubmitted'))
      onClose()
    } catch (err: any) {
      toast.error(err.message || t('annotation.extractFailed'))
      setSubmitting(false)
    }
  }

  if (!show) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-indigo-100 rounded-lg">
              <PackagePlus className="w-5 h-5 text-indigo-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">{t('annotation.createDatasetTitle')}</h3>
          </div>

          {/* Dataset name input — hidden when reusing existing dataset */}
          {isSegReuse ? (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-700">{t('annotation.reuseDatasetHint')}</p>
            </div>
          ) : (
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.datasetName')}</label>
              <input
                type="text"
                value={datasetName}
                onChange={e => setDatasetName(e.target.value)}
                placeholder={t('annotation.datasetNamePlaceholder')}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                disabled={submitting}
                autoFocus
              />
            </div>
          )}

          {/* Task type selector */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.taskType')}</label>
            <div className="flex gap-2">
              {(['classification', 'segmentation'] as const).map(tt => {
                const isDisabled = submitting || (tt === 'segmentation' && hasWsiSources)
                return (
                  <button
                    key={tt}
                    onClick={() => !isDisabled && setTaskType(tt)}
                    disabled={isDisabled}
                    title={tt === 'segmentation' && hasWsiSources ? t('annotation.segmentationWsiNotSupported') : undefined}
                    className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border transition-all ${
                      taskType === tt
                        ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                        : isDisabled
                          ? 'bg-gray-100 border-gray-200 text-gray-400 cursor-not-allowed'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {t(`annotation.${tt}`)}
                  </button>
                )
              })}
            </div>
            {hasWsiSources && (
              <p className="text-xs text-amber-600 mt-1">{t('annotation.segmentationWsiNotSupported')}</p>
            )}
          </div>

          {/* Annotation summary */}
          <div className="bg-gray-50 rounded-lg p-3 mb-2">
            <h4 className="text-xs font-semibold text-gray-600 mb-2">{t('annotation.annotationSummary')}</h4>
            <div className="grid grid-cols-2 gap-2 text-xs mb-2">
              <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalRegions')}</span><span className="font-medium text-gray-900">{summary.totalRegions}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalSlides')}</span><span className="font-medium text-gray-900">{summary.totalSlides}</span></div>
            </div>
            <h4 className="text-xs font-semibold text-gray-600 mb-1">{t('annotation.labelDistribution')}</h4>
            <div className="space-y-1">
              {Object.entries(summary.labelCounts).map(([label, count]) => (
                <div key={label} className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full border border-gray-200 flex-shrink-0" style={{ backgroundColor: labelColors[label] || '#3b82f6' }} />
                  <span className="flex-1 text-gray-700 truncate">{label}</span>
                  <span className="text-gray-500">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
          <button
            onClick={onClose}
            disabled={submitting}
            className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={(!isSegReuse && !datasetName.trim()) || summary.totalRegions === 0 || submitting}
            className="flex-1 px-4 py-2 text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {submitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <PackagePlus className="w-4 h-4" />
            )}
            {submitting ? t('annotation.creating') : t('annotation.createConfirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

