import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Database, RefreshCw, Layers, Calendar, Star, ToggleRight, ToggleLeft, Trash2, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, CheckCircle, XCircle, BarChart3, FlaskConical } from 'lucide-react'
import { Card } from '../ui/card'
import { Select } from '../ui/select'
import { TrainedModel, getTrainedModels, updateTrainedModel, deleteTrainedModel } from '../../api'
import { ShowConfirmDialog } from './ConfirmDialog'
import { isSegmentationTask } from '../../lib/externalValidationUtils'

export interface ModelsTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

interface MetricDisplay {
  label: string
  value: unknown
}

export function ModelsTab({ showConfirmDialog, closeConfirmDialog }: ModelsTabProps) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [modelsTotal, setModelsTotal] = useState(0)

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)

  const loadTrainedModels = useCallback(async () => {
    setLoadingModels(true)
    setModelsError(null)
    try {
      const skip = (page - 1) * pageSize
      const response = await getTrainedModels(skip, pageSize)
      setTrainedModels(response.items)
      setModelsTotal(response.total)
    } catch (err) {
      console.error('Failed to load trained models:', err)
      setModelsError(err instanceof Error ? err.message : t('settings.modelsTab.failedToLoadModels'))
    } finally {
      setLoadingModels(false)
    }
  }, [page, pageSize, t])

  const handleViewAnalysis = (model: TrainedModel) => {
    navigate(`/results?task_id=${model.task_id}`)
  }

  const handleExternalValidation = (model: TrainedModel) => {
    navigate('/results', {
      state: {
        pageMode: 'external-validation',
        selectedModelId: model.model_id
      }
    })
  }

  const handleSetDefaultModel = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_default: true })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : t('settings.modelsTab.failedToSetDefault'))
    }
  }, [loadTrainedModels, t])

  const handleToggleModelActive = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_active: !model.is_active })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : t('settings.modelsTab.failedToUpdateStatus'))
    }
  }, [loadTrainedModels, t])

  const handleDeleteModel = useCallback((model: TrainedModel) => {
    showConfirmDialog({
      title: t('settings.modelsTab.deleteModel'),
      message: t('settings.modelsTab.deleteModelConfirm', { name: model.model_name }),
      confirmText: t('settings.modelsTab.delete'),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          await deleteTrainedModel(model.model_id)
          if (trainedModels.length === 1 && page > 1) {
            setPage(p => p - 1)
          } else {
            await loadTrainedModels()
          }
        } catch (err) {
          setModelsError(err instanceof Error ? err.message : t('settings.modelsTab.failedToDelete'))
        }
      }
    })
  }, [loadTrainedModels, showConfirmDialog, closeConfirmDialog, trainedModels.length, page, t])

  useEffect(() => {
    loadTrainedModels()
  }, [loadTrainedModels])

  const formatValue = (v: unknown) => {
    if (typeof v === 'number') return v.toFixed(3)
    if (typeof v === 'string') return v
    return '—'
  }

  const getDisplayClasses = (model: TrainedModel) => {
    const taskClasses = Array.isArray(model.task_classes)
      ? model.task_classes.filter((cls): cls is string => typeof cls === 'string' && cls.trim().length > 0)
      : []
    const modelClasses = Array.isArray(model.classes)
      ? model.classes.filter((cls): cls is string => typeof cls === 'string' && cls.trim().length > 0)
      : []

    if (model.task_type === 'segmentation' && taskClasses.length > 0) {
      return taskClasses
    }

    return modelClasses
  }

  const getMetricDisplay = (model: TrainedModel, displayClasses: string[]) => {
    const metrics = (model.val_metrics || {}) as Record<string, unknown>
    const isSurvival = metrics.c_index !== undefined
    const isSegmentation = isSegmentationTask(model.task_type ?? undefined)

    let primaryMetric: MetricDisplay = { label: 'Loss', value: metrics.loss }
    let secondaryMetric: MetricDisplay = { label: 'Accuracy', value: metrics.accuracy }

    if (isSurvival) {
      primaryMetric = { label: 'C-Index', value: metrics.c_index }
      secondaryMetric = { label: 'Loss', value: metrics.loss }
    } else if (isSegmentation) {
      const isMulticlassSegmentation =
        displayClasses.length > 1 ||
        metrics.miou !== undefined ||
        (Array.isArray(metrics.iou_per_class) && metrics.iou_per_class.length > 1)

      primaryMetric = {
        label: isMulticlassSegmentation ? 'mIoU' : 'IoU',
        value: isMulticlassSegmentation
          ? (metrics.miou ?? metrics.iou ?? metrics.dice)
          : (metrics.iou ?? metrics.miou ?? metrics.dice)
      }
      secondaryMetric = { label: 'Loss', value: metrics.loss }
    } else if (metrics.auc !== undefined || metrics.macro_auc !== undefined) {
      primaryMetric = { label: 'AUC', value: metrics.auc ?? metrics.macro_auc }
      secondaryMetric = { label: 'Accuracy', value: metrics.accuracy }
    }

    return { metrics, isSurvival, primaryMetric, secondaryMetric }
  }

  const totalPages = Math.ceil(modelsTotal / pageSize)

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-start">
          <Database className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 mt-1" />
          <div className="flex flex-col">
            <span>{t('settings.modelsTab.title')}</span>
            <span className="text-gray-500 font-normal text-sm mt-0.5">{t('settings.modelsTab.subtitle')}</span>
          </div>
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">{t('settings.modelsTab.modelCount', { count: modelsTotal })}</span>
          <button
            onClick={loadTrainedModels}
            disabled={loadingModels}
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            title={t('settings.modelsTab.refreshModels')}
          >
            <RefreshCw className={`w-4 h-4 ${loadingModels ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {modelsError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {modelsError}
        </div>
      )}

      {loadingModels ? (
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto mb-2"></div>
            <p className="text-gray-500 text-sm">{t('settings.modelsTab.loadingModels')}</p>
          </div>
        </div>
      ) : trainedModels.length === 0 ? (
        <div className="text-center py-12">
          <Database className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">{t('settings.modelsTab.noModels')}</p>
          <p className="text-gray-400 text-sm mt-1">
            {t('settings.modelsTab.noModelsHint')}
          </p>
        </div>
      ) : (
        <>
          {/* Mobile Card View */}
          <div className="block sm:hidden space-y-4">
            {trainedModels.map((model) => {
              const taskName = model.task_name || t('settings.modelsTab.unknownTask')
              const displayClasses = getDisplayClasses(model)
              const { metrics, isSurvival, primaryMetric, secondaryMetric } = getMetricDisplay(model, displayClasses)

              return (
                <div key={model.model_id} className="bg-white border rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow">
                   {/* Card Header: Name and Status */}
                   <div className="flex justify-between items-start mb-3">
                      <div className="min-w-0 pr-2">
                        <div
                           className="text-base font-bold text-gray-900 truncate cursor-pointer hover:text-primary-600"
                           title={model.model_name}
                           onClick={() => handleViewAnalysis(model)}
                        >
                          {model.model_name}
                        </div>
                         <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-gray-400 flex items-center gap-1">
                              <Calendar className="w-3 h-3" />
                              {model.created_at && new Date(model.created_at).toLocaleDateString()}
                            </span>
                         </div>
                      </div>
                      <div className={`
                        flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border shadow-sm transition-colors
                        ${model.is_active
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : 'bg-gray-50 text-gray-500 border-gray-200'}
                      `}>
                         <div className={`w-1.5 h-1.5 rounded-full ${model.is_active ? 'bg-emerald-500' : 'bg-gray-400'}`} />
                         {model.is_active ? t('settings.modelsTab.active') : t('settings.modelsTab.inactive')}
                      </div>
                   </div>

                   {/* Task & Architecture Info */}
                   <div className="flex flex-wrap gap-2 mb-3">
                     <div className="inline-flex items-center gap-1 bg-gray-100 px-2 py-0.5 rounded text-xs font-semibold text-gray-600">
                        <Layers className="w-3 h-3 text-gray-500" />
                        <span className="truncate max-w-[120px]">{taskName}</span>
                     </div>
                     <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100 text-xs text-gray-500">{model.feature_extractor}</span>
                      {model.aggregator && (
                        <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100 text-xs text-gray-500">+{model.aggregator}</span>
                      )}
                   </div>

                   {!isSurvival && displayClasses.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {displayClasses.slice(0, 4).map((cls, idx) => (
                          <span key={idx} className="inline-flex items-center bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-medium border border-indigo-100">
                            {cls}
                          </span>
                        ))}
                        {displayClasses.length > 4 && (
                          <span className="text-gray-400 font-medium text-xs flex items-center px-1">+{displayClasses.length - 4}</span>
                        )}
                      </div>
                   )}

                   {/* Metrics for Mobile */}
                   {Object.keys(metrics).length > 0 && (
                      <div className="grid grid-cols-2 gap-2 mb-3 bg-gray-50 p-2 rounded text-center">
                          <div>
                             <div className="text-xs text-gray-500 font-medium uppercase">{primaryMetric.label}</div>
                             <div className="font-mono font-bold text-gray-900">{formatValue(primaryMetric.value)}</div>
                          </div>
                          {secondaryMetric.value !== undefined && (
                             <div>
                                <div className="text-xs text-gray-500 font-medium uppercase">{secondaryMetric.label}</div>
                                <div className="font-mono font-bold text-gray-900">{formatValue(secondaryMetric.value)}</div>
                             </div>
                          )}
                      </div>
                   )}

                   {/* Actions */}
                   <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
                      <button
                            onClick={() => handleViewAnalysis(model)}
                            className="p-2 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-all"
                            title={t('settings.modelsTab.viewTrainingResults')}
                          >
                            <BarChart3 className="w-5 h-5" />
                      </button>
                      <button
                            onClick={() => handleExternalValidation(model)}
                            className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all"
                            title={t('settings.modelsTab.runExternalValidation')}
                          >
                            <FlaskConical className="w-5 h-5" />
                      </button>
                        {!model.is_default && model.is_active && (
                          <button
                            onClick={() => handleSetDefaultModel(model)}
                            className="p-2 text-gray-400 hover:text-amber-500 hover:bg-amber-50 rounded-lg transition-all"
                            title={t('settings.modelsTab.setAsDefault')}
                          >
                            <Star className="w-5 h-5" />
                          </button>
                        )}
                        <button
                          onClick={() => handleToggleModelActive(model)}
                          className={`p-2 rounded-lg transition-all ${model.is_active
                            ? 'text-emerald-600 hover:bg-emerald-50'
                            : 'text-gray-400 hover:text-emerald-600 hover:bg-gray-100'
                          }`}
                          title={model.is_active ? t('settings.modelsTab.deactivate') : t('settings.modelsTab.activate')}
                        >
                          {model.is_active ? <CheckCircle className="w-5 h-5 text-emerald-600" /> : <XCircle className="w-5 h-5" />}
                        </button>
                        <button
                          onClick={() => handleDeleteModel(model)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                          title={t('settings.modelsTab.deleteModelAction')}
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                   </div>
                </div>
              )
            })}
          </div>

          {/* Table View (Desktop) */}
          <div className="hidden sm:block overflow-x-auto -mx-4 sm:mx-0">
            <table className="w-full min-w-[600px]">
              <thead>
                <tr className="border-b border-gray-200 text-left text-base font-semibold text-gray-900 tracking-wide bg-gray-50/50">
                  <th className="px-5 py-4">{t('settings.modelsTab.columnModel')}</th>
                  <th className="px-5 py-4 hidden md:table-cell">{t('settings.modelsTab.columnClasses')}</th>
                  <th className="px-5 py-4 hidden lg:table-cell">{t('settings.modelsTab.columnMetrics')}</th>
                  <th className="px-5 py-4">{t('settings.modelsTab.columnStatus')}</th>
                  <th className="px-5 py-4 text-right">{t('settings.modelsTab.columnActions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {trainedModels.map((model) => {
                  const taskName = model.task_name || t('settings.modelsTab.unknownTask')
                  const displayClasses = getDisplayClasses(model)
                  const { metrics, isSurvival, primaryMetric, secondaryMetric } = getMetricDisplay(model, displayClasses)

                  return (
                    <tr key={model.model_id} className="hover:bg-gray-50 transition-colors group border-b last:border-0 border-gray-100">
                      <td className="px-6 py-4 align-middle">
                        <div className="min-w-0 flex flex-col gap-1.5">
                          <div className="flex items-center gap-2">
                            <div className="flex items-center gap-1.5 bg-gray-100 px-2.5 py-0.5 rounded-full text-xs font-semibold text-gray-600">
                              <Layers className="w-3 h-3 text-gray-500" />
                              <span className="truncate max-w-[120px]" title={taskName}>{taskName}</span>
                            </div>
                            <span className="text-gray-300">|</span>
                            <span className="text-xs text-gray-400 flex items-center gap-1">
                              <Calendar className="w-3 h-3" />
                              {model.created_at && new Date(model.created_at).toLocaleDateString()}
                            </span>
                          </div>
                        <div
                          className="text-lg font-bold text-gray-900 truncate max-w-[200px] sm:max-w-[320px] cursor-pointer hover:text-primary-600 hover:underline"
                          title={t('settings.modelsTab.viewResultsFor', { name: model.model_name })}
                          onClick={() => handleViewAnalysis(model)}
                        >
                            {model.model_name}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">{model.feature_extractor}</span>
                            {model.aggregator && (
                              <>
                                <span className="text-gray-300">+</span>
                                <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">{model.aggregator}</span>
                              </>
                            )}
                          </div>
                        </div>
                      </td>

                      <td className="px-6 py-4 hidden md:table-cell align-middle">
                        <div className="flex flex-wrap gap-1.5 max-w-[240px]">
                          {isSurvival ? (
                            <span className="inline-flex items-center bg-emerald-50 text-emerald-700 px-2.5 py-1 rounded text-xs font-medium border border-emerald-100">
                              {t('settings.modelsTab.timeIntervals', { count: displayClasses.length || 4 })}
                            </span>
                          ) : (
                            <>
                              {displayClasses.slice(0, 4).map((cls, idx) => (
                                <span key={idx} className="inline-flex items-center bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-medium border border-indigo-100">
                                  {cls}
                                </span>
                              ))}
                              {displayClasses.length > 4 && (
                                <span className="text-gray-400 font-medium text-xs flex items-center px-1">+{displayClasses.length - 4}</span>
                              )}
                            </>
                          )}
                        </div>
                      </td>

                      <td className="px-6 py-4 hidden lg:table-cell align-middle">
                        {Object.keys(metrics).length > 0 ? (
                          <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between gap-4 max-w-[160px]">
                              <span className="text-gray-500 text-xs font-bold uppercase tracking-wider">{primaryMetric.label}</span>
                              <span className="font-mono font-bold text-gray-900 text-xl tracking-tight">
                                {formatValue(primaryMetric.value)}
                              </span>
                            </div>
                            {secondaryMetric.value !== undefined && (
                              <div className="flex items-center justify-between gap-4 max-w-[160px] opacity-75">
                                <span className="text-gray-400 text-[10px] font-semibold uppercase tracking-wider">{secondaryMetric.label}</span>
                                <span className="font-mono font-medium text-gray-600 text-sm">
                                  {formatValue(secondaryMetric.value)}
                                </span>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-sm text-gray-300 italic">{t('settings.modelsTab.noMetrics')}</span>
                        )}
                      </td>

                      <td className="px-6 py-4 align-middle">
                        <div className="flex flex-col gap-2 items-start">
                          {model.is_default && (
                            <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-bold uppercase tracking-wide shadow-sm">
                              <Star className="w-3 h-3 fill-current" />
                              {t('settings.modelsTab.default')}
                            </div>
                          )}
                          <div className={`
                            inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full text-xs font-medium border shadow-sm transition-colors
                            ${model.is_active
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-gray-50 text-gray-500 border-gray-200'}
                          `}>
                            <div className={`w-1.5 h-1.5 rounded-full ${model.is_active ? 'bg-emerald-500' : 'bg-gray-400'}`} />
                            {model.is_active ? t('settings.modelsTab.active') : t('settings.modelsTab.inactive')}
                          </div>
                        </div>
                      </td>

                      <td className="px-6 py-4 align-middle text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleViewAnalysis(model)}
                            className="p-2 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-all"
                            title={t('settings.modelsTab.viewTrainingResults')}
                          >
                            <BarChart3 className="w-5 h-5" />
                          </button>
                          <button
                             onClick={() => handleExternalValidation(model)}
                             className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all"
                             title={t('settings.modelsTab.runExternalValidation')}
                           >
                            <FlaskConical className="w-5 h-5" />
                          </button>
                          {!model.is_default && model.is_active && (
                            <button
                              onClick={() => handleSetDefaultModel(model)}
                              className="p-2 text-gray-400 hover:text-amber-500 hover:bg-amber-50 rounded-lg transition-all"
                              title={t('settings.modelsTab.setAsDefault')}
                            >
                              <Star className="w-5 h-5" />
                            </button>
                          )}
                          <button
                            onClick={() => handleToggleModelActive(model)}
                            className={`p-2 rounded-lg transition-all ${model.is_active
                              ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                              : 'text-gray-400 hover:text-emerald-600 hover:bg-gray-100'
                            }`}
                            title={model.is_active ? t('settings.modelsTab.deactivate') : t('settings.modelsTab.activate')}
                          >
                            {model.is_active ? <CheckCircle className="w-5 h-5 text-emerald-600" /> : <XCircle className="w-5 h-5" />}
                          </button>
                          <button
                            onClick={() => handleDeleteModel(model)}
                            className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                            title={t('settings.modelsTab.deleteModelAction')}
                          >
                            <Trash2 className="w-5 h-5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-6 pt-4 border-t border-gray-100">
             <div className="flex flex-col sm:flex-row items-center gap-2 text-sm text-gray-500">
                <span>
                   {t('settings.modelsTab.showing')} <span className="font-medium mx-1">{modelsTotal > 0 ? (page - 1) * pageSize + 1 : 0}</span>
                   {t('settings.modelsTab.to')} <span className="font-medium mx-1">{Math.min(page * pageSize, modelsTotal)}</span>
                   {t('settings.modelsTab.of')} <span className="font-medium mx-1">{modelsTotal}</span> {t('settings.modelsTab.entries')}
                </span>
                <div className="flex items-center mt-2 sm:mt-0">
                   <span className="text-sm text-gray-500 mr-2">{t('settings.modelsTab.show')}:</span>
                   <Select
                     value={String(pageSize)}
                     onChange={(v) => { setPageSize(Number(v)); setPage(1) }}
                     options={[
                       { value: '5', label: '5' },
                       { value: '10', label: '10' },
                       { value: '20', label: '20' },
                     ]}
                     triggerClassName="w-20"
                   />
                </div>
             </div>

            <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed text-gray-600"
                  title={t('settings.modelsTab.firstPage')}
                >
                  <ChevronsLeft className="w-5 h-5" />
                </button>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed text-gray-600"
                  title={t('settings.modelsTab.previousPage')}
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>

                <div className="flex items-center px-2 min-w-[60px] justify-center">
                  <span className="text-sm font-medium text-gray-900">
                    {page}
                  </span>
                  <span className="text-sm text-gray-500 mx-1">/</span>
                  <span className="text-sm text-gray-500">
                    {totalPages || 1}
                  </span>
                </div>

                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages || totalPages === 0}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed text-gray-600"
                  title={t('settings.modelsTab.nextPage')}
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages || totalPages === 0}
                  className="p-1 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed text-gray-600"
                  title={t('settings.modelsTab.lastPage')}
                >
                  <ChevronsRight className="w-5 h-5" />
                </button>
              </div>
          </div>
        </>
      )}
    </Card>
  )
}
