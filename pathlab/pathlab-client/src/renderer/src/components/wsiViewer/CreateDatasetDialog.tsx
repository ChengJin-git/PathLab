import { useState, useMemo, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { PackagePlus, Loader2, ChevronDown } from 'lucide-react'
import { Tooltip } from '../ui/tooltip'
import { AnnotationsMap, DatasetAnnotationSummaryResponse } from '../../api/annotation'
import type { TaskType } from '../../constants/training'
import { organSources, organSourceKeyMap } from '../../constants/wsi'

interface CreateDatasetDialogProps {
  show: boolean
  onClose: () => void
  allAnnotations: AnnotationsMap
  summary?: DatasetAnnotationSummaryResponse | null
  labelColors: Record<string, string>
  hasWsiSources?: boolean
  defaultSource?: string | null
  onSubmitCreateDataset: (params: { datasetName: string; taskType: TaskType | 'classification' | 'segmentation'; sourceOrgan: string }) => Promise<void>
}

export function CreateDatasetDialog({
  show, onClose, allAnnotations, summary, labelColors,
  hasWsiSources = false,
  defaultSource,
  onSubmitCreateDataset,
}: CreateDatasetDialogProps) {
  const { t } = useTranslation()
  const [datasetName, setDatasetName] = useState('')
  const [nameError, setNameError] = useState(false)
  const [taskType, setTaskType] = useState<'classification' | 'segmentation'>('classification')
  const [sourceSelection, setSourceSelection] = useState('')
  const [sourceCustom, setSourceCustom] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const knownSources = useMemo(() => organSources.filter(s => s !== 'Other'), [])

  const resolvedSource = useMemo(() => {
    if (sourceSelection === 'Other') return sourceCustom.trim()
    return sourceSelection.trim()
  }, [sourceSelection, sourceCustom])

  const localSummary = useMemo(() => {
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

  const effectiveSummary = useMemo(() => {
    if (!summary) return localSummary
    return {
      totalRegions: summary.total_regions,
      totalSlides: summary.total_slides,
      labelCounts: Object.fromEntries(
        Object.entries(summary.labels).map(([label, data]) => [label, data.total_regions])
      ),
    }
  }, [localSummary, summary])

  useEffect(() => {
    if (show) {
      setDatasetName('')
      setNameError(false)
      setTaskType('classification')
      setSubmitting(false)
      const normalized = defaultSource?.trim() || ''
      if (!normalized) {
        setSourceSelection('')
        setSourceCustom('')
      } else if (knownSources.includes(normalized)) {
        setSourceSelection(normalized)
        setSourceCustom('')
      } else {
        setSourceSelection('Other')
        setSourceCustom(normalized)
      }
    }
  }, [show, defaultSource, knownSources])

  const handleSubmit = async () => {
    if (!datasetName.trim() || effectiveSummary.totalRegions === 0 || submitting) return
    setSubmitting(true)
    try {
      await onSubmitCreateDataset({ datasetName: datasetName.trim(), taskType, sourceOrgan: resolvedSource })
      onClose()
    } catch {
      setSubmitting(false)
    }
  }

  const getSourceLabel = (val: string) => {
    if (!val) return ''
    const key = organSourceKeyMap[val]
    return key ? String(t(`organSources.${key}`)) : val
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

          <div className="mb-4">
            <label htmlFor="create-dataset-name" className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.datasetName')}</label>
            <input
              id="create-dataset-name"
              type="text"
              value={datasetName}
              onChange={e => { setDatasetName(e.target.value); if (e.target.value.trim()) setNameError(false) }}
              onBlur={() => setNameError(!datasetName.trim())}
              placeholder={t('annotation.datasetNamePlaceholder')}
              className={`w-full px-3 py-2 text-sm border rounded-lg outline-none focus:ring-1 ${
                nameError
                  ? 'border-red-400 focus:ring-red-500 focus:border-red-500'
                  : 'border-gray-200 focus:ring-indigo-500 focus:border-indigo-500'
              }`}
              disabled={submitting}
            />
            {nameError && (
              <p className="mt-1 text-xs text-red-600">{t('annotation.datasetNameRequired')}</p>
            )}
          </div>

          <fieldset className="mb-4">
            <legend className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.taskType')}</legend>
            <div className="flex gap-2">
              {(['classification', 'segmentation'] as const).map(tt => {
                const isDisabled = submitting || (tt === 'segmentation' && hasWsiSources)
                return (
                  <Tooltip key={tt} content={tt === 'segmentation' && hasWsiSources ? t('annotation.segmentationWsiNotSupported') : undefined}>
                    <button
                      type="button"
                      onClick={() => !isDisabled && setTaskType(tt)}
                      disabled={isDisabled}
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
                  </Tooltip>
                )
              })}
            </div>
            {hasWsiSources && (
              <p className="text-xs text-amber-600 mt-1">{t('annotation.segmentationWsiNotSupported')}</p>
            )}
          </fieldset>

          <div className="mb-4">
            <div className="flex items-center gap-2 mb-1">
              <label htmlFor="create-dataset-source" className="text-sm font-medium text-gray-700">{t('annotation.datasetSource')}</label>
              {defaultSource?.trim() && (
                <span className="text-xs font-normal text-indigo-500">{t('annotation.sourceInherited')}</span>
              )}
            </div>
            <div className="relative">
              <select
                id="create-dataset-source"
                value={sourceSelection}
                onChange={e => {
                  setSourceSelection(e.target.value)
                  if (e.target.value !== 'Other') setSourceCustom('')
                }}
                disabled={submitting}
                className="w-full appearance-none px-3 py-2 pr-8 text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none bg-white text-gray-700 disabled:bg-gray-50 disabled:text-gray-400"
              >
                <option value="">{t('annotation.sourceSelectPlaceholder')}</option>
                {organSources.map(src => (
                  <option key={src} value={src}>
                    {getSourceLabel(src)}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
            {sourceSelection === 'Other' && (
              <input
                type="text"
                value={sourceCustom}
                onChange={e => setSourceCustom(e.target.value)}
                placeholder={t('annotation.sourceCustomPlaceholder')}
                disabled={submitting}
                className="mt-2 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
              />
            )}
          </div>

          {/* Annotation summary */}
          <div className="bg-gray-50 rounded-lg p-3 mb-2">
            <h4 className="text-xs font-semibold text-gray-600 mb-2">{t('annotation.annotationSummary')}</h4>
            <div className="grid grid-cols-2 gap-2 text-xs mb-2">
              <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalRegions')}</span><span className="font-medium text-gray-900">{effectiveSummary.totalRegions}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalSlides')}</span><span className="font-medium text-gray-900">{effectiveSummary.totalSlides}</span></div>
            </div>
            <h4 className="text-xs font-semibold text-gray-600 mb-1">{t('annotation.labelDistribution')}</h4>
            <div className="space-y-1">
              {Object.entries(effectiveSummary.labelCounts).map(([label, count]) => (
                <div key={label} className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full border border-gray-200 flex-shrink-0" style={{ backgroundColor: labelColors[label] || summary?.labels[label]?.color || '#3b82f6' }} />
                  <span className="flex-1 text-gray-700 truncate">{label}</span>
                  <span className="text-gray-500">{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!datasetName.trim() || effectiveSummary.totalRegions === 0 || submitting}
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
