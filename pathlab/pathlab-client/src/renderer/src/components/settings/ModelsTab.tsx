import { useState, useEffect, useCallback } from 'react'
import { Database, RefreshCw, Layers, Calendar, Star, ToggleRight, ToggleLeft, Trash2 } from 'lucide-react'
import { Card } from '../ui/card'
import { TrainedModel, getTrainedModels, updateTrainedModel, deleteTrainedModel, getAuthToken } from '../../api'
import { API_BASE } from '../../config'
import { ShowConfirmDialog } from './ConfirmDialog'

interface TaskItem {
  task_id: string
  task_name?: string
  name?: string
}

export interface ModelsTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export function ModelsTab({ showConfirmDialog, closeConfirmDialog }: ModelsTabProps) {
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [modelsTotal, setModelsTotal] = useState(0)
  const [tasks, setTasks] = useState<TaskItem[]>([])

  const loadTasks = useCallback(async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE}/results/tasks`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      })
      if (response.ok) {
        const data = await response.json()
        setTasks(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load tasks:', error)
    }
  }, [])

  const loadTrainedModels = useCallback(async () => {
    setLoadingModels(true)
    setModelsError(null)
    try {
      const response = await getTrainedModels(0, 100)
      setTrainedModels(response.items)
      setModelsTotal(response.total)
    } catch (err) {
      console.error('Failed to load trained models:', err)
      setModelsError(err instanceof Error ? err.message : 'Failed to load models')
    } finally {
      setLoadingModels(false)
    }
  }, [])

  const handleSetDefaultModel = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_default: true })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to set default')
    }
  }, [loadTrainedModels])

  const handleToggleModelActive = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_active: !model.is_active })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to update status')
    }
  }, [loadTrainedModels])

  const handleDeleteModel = useCallback((model: TrainedModel) => {
    showConfirmDialog({
      title: 'Delete Model',
      message: `Are you sure you want to delete "${model.model_name}"? This cannot be undone.`,
      confirmText: 'Delete',
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        try {
          await deleteTrainedModel(model.model_id)
          await loadTrainedModels()
        } catch (err) {
          setModelsError(err instanceof Error ? err.message : 'Failed to delete')
        }
      }
    })
  }, [loadTrainedModels, showConfirmDialog, closeConfirmDialog])

  useEffect(() => {
    loadTrainedModels()
    loadTasks()
  }, [loadTrainedModels, loadTasks])

  const formatValue = (v: unknown) => (typeof v === 'number' ? v.toFixed(3) : (v || '—'))

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-start">
          <Database className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 mt-1" />
          <div className="flex flex-col">
            <span>Model Management</span>
            <span className="text-gray-500 font-normal text-sm mt-0.5">(for External Validation)</span>
          </div>
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">{modelsTotal} model{modelsTotal !== 1 ? 's' : ''}</span>
          <button
            onClick={loadTrainedModels}
            disabled={loadingModels}
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh models"
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
            <p className="text-gray-500 text-sm">Loading models...</p>
          </div>
        </div>
      ) : trainedModels.length === 0 ? (
        <div className="text-center py-12">
          <Database className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">No trained models yet</p>
          <p className="text-gray-400 text-sm mt-1">
            Complete a training task to see models here
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full min-w-[600px]">
            <thead>
              <tr className="border-b border-gray-200 text-left text-base font-semibold text-gray-900 tracking-wide bg-gray-50/50">
                <th className="px-5 py-4">Model</th>
                <th className="px-5 py-4 hidden md:table-cell">Classes</th>
                <th className="px-5 py-4 hidden lg:table-cell">Metrics</th>
                <th className="px-5 py-4">Status</th>
                <th className="px-5 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {trainedModels.map((model) => {
                const task = tasks.find(t => t.task_id === model.task_id)
                const taskName = task?.name || task?.task_name || 'Unknown Task'

                const metrics = model.val_metrics || {}
                const isSurvival = (metrics as Record<string, unknown>).c_index !== undefined

                let primaryMetric = { label: 'Loss', value: (metrics as Record<string, unknown>).loss }
                let secondaryMetric = { label: 'Accuracy', value: (metrics as Record<string, unknown>).accuracy }

                if (isSurvival) {
                  primaryMetric = { label: 'C-Index', value: (metrics as Record<string, unknown>).c_index }
                  secondaryMetric = { label: 'Loss', value: (metrics as Record<string, unknown>).loss }
                } else if ((metrics as Record<string, unknown>).auc !== undefined || (metrics as Record<string, unknown>).macro_auc !== undefined) {
                  primaryMetric = { label: 'AUC', value: (metrics as Record<string, unknown>).auc || (metrics as Record<string, unknown>).macro_auc }
                  secondaryMetric = { label: 'Accuracy', value: (metrics as Record<string, unknown>).accuracy }
                }

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
                        <div className="text-lg font-bold text-gray-900 truncate max-w-[200px] sm:max-w-[320px]" title={model.model_name}>
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
                            {model.classes?.length || 4} Time Intervals
                          </span>
                        ) : (
                          <>
                            {model.classes?.slice(0, 4).map((cls, idx) => (
                              <span key={idx} className="inline-flex items-center bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-medium border border-indigo-100">
                                {cls}
                              </span>
                            ))}
                            {model.classes && model.classes.length > 4 && (
                              <span className="text-gray-400 font-medium text-xs flex items-center px-1">+{model.classes.length - 4}</span>
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
                        <span className="text-sm text-gray-300 italic">No metrics</span>
                      )}
                    </td>

                    <td className="px-6 py-4 align-middle">
                      <div className="flex flex-col gap-2 items-start">
                        {model.is_default && (
                          <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-bold uppercase tracking-wide shadow-sm">
                            <Star className="w-3 h-3 fill-current" />
                            Default
                          </div>
                        )}
                        <div className={`
                          inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full text-xs font-medium border shadow-sm transition-colors
                          ${model.is_active
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : 'bg-gray-50 text-gray-500 border-gray-200'}
                        `}>
                          <div className={`w-1.5 h-1.5 rounded-full ${model.is_active ? 'bg-emerald-500' : 'bg-gray-400'}`} />
                          {model.is_active ? 'Active' : 'Inactive'}
                        </div>
                      </div>
                    </td>

                    <td className="px-6 py-4 align-middle text-right">
                      <div className="flex items-center justify-end gap-2">
                        {!model.is_default && model.is_active && (
                          <button
                            onClick={() => handleSetDefaultModel(model)}
                            className="p-2 text-gray-400 hover:text-amber-500 hover:bg-amber-50 rounded-lg transition-all"
                            title="Set as default"
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
                          title={model.is_active ? 'Deactivate' : 'Activate'}
                        >
                          {model.is_active ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
                        </button>
                        <button
                          onClick={() => handleDeleteModel(model)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                          title="Delete model"
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
      )}
    </Card>
  )
}
