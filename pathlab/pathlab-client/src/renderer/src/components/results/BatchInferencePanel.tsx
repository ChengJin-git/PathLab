import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Loader2, Download, ChevronDown, ChevronUp, Activity } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import {
  fetchDatasetsForInference,
  listBatchInferenceTasks,
  getBatchInferenceResults,
  exportBatchInferenceCsv,
  startBatchInference,
  type BatchInferenceTask,
  type BatchInferenceResult,
  type InferenceDataset,
} from '../../api/batchInference'
import { getTrainedModels, type TrainedModel } from '../../api'
import { useAsyncAction } from '../../lib/useAsyncAction'
import { formatDateTime } from '../../lib/utils'

const PAGE_SIZE = 20

function isCompatible(model: TrainedModel, dataset: InferenceDataset): boolean {
  const modelTaskType = (model.task_type ?? '').toLowerCase()
  const datasetTaskType = (dataset.task_type ?? '').toLowerCase()
  return modelTaskType === datasetTaskType
}

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'running' || status === 'pending') return 'secondary'
  return 'outline'
}

interface BatchInferencePanelProps {
  trainedModels: TrainedModel[]
}

export function BatchInferencePanel({ trainedModels }: BatchInferencePanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedModelTaskId, setSelectedModelTaskId] = useState<string | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [isModelOpen, setIsModelOpen] = useState(false)
  const [isDatasetOpen, setIsDatasetOpen] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [resultsPage, setResultsPage] = useState(1)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const selectedModel = trainedModels.find(
    (m) => m.model_id === selectedModelId
  ) ?? null

  const { data: inferenceDatasets = [] } = useQuery({
    queryKey: ['inference-datasets'],
    queryFn: async () => {
      const data = await fetchDatasetsForInference(true)
      return data.items
    },
    staleTime: 3 * 60 * 1000,
  })

  const { data: biTasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['batch-inference-tasks'],
    queryFn: () => listBatchInferenceTasks(0, 50),
    staleTime: 30 * 1000,
    refetchInterval: 15 * 1000,
  })
  const biTasks: BatchInferenceTask[] = biTasksData?.items ?? []

  const selectedTask = biTasks.find((t) => t.task_id === selectedTaskId) ?? null

  const { data: resultsData } = useQuery({
    queryKey: ['batch-inference-results', selectedTaskId, resultsPage],
    queryFn: () =>
      getBatchInferenceResults(
        selectedTaskId!,
        (resultsPage - 1) * PAGE_SIZE,
        PAGE_SIZE
      ),
    enabled: !!selectedTaskId && selectedTask?.status === 'completed',
    staleTime: 60 * 1000,
  })
  const results: BatchInferenceResult[] = resultsData?.items ?? []
  const resultsTotal = resultsData?.total ?? 0
  const taskType = resultsData?.task_type ?? selectedTask?.task_type ?? ''

  const [submitting, runSubmit] = useAsyncAction()
  const [exporting, runExport] = useAsyncAction()

  const doSubmit = () => runSubmit(async () => {
    if (!selectedModelId || !selectedModelTaskId || !selectedDatasetId) return
    setSubmitError(null)
    try {
      await startBatchInference({
        model_task_id: selectedModelTaskId,
        model_id: selectedModelId,
        dataset_id: selectedDatasetId,
      })
      await queryClient.invalidateQueries({ queryKey: ['batch-inference-tasks'] })
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : t('resultsPage.batchInference.failedToSubmit'))
    }
  })

  const doExport = () => runExport(async () => {
    if (!selectedTaskId) return
    await exportBatchInferenceCsv(selectedTaskId)
  })

  const compatibleDatasets = selectedModel
    ? inferenceDatasets.filter((d) => isCompatible(selectedModel, d))
    : inferenceDatasets

  const selectedDataset = inferenceDatasets.find(
    (d) => d.dataset_id === selectedDatasetId
  ) ?? null

  const canSubmit =
    !!selectedModelId && !!selectedModelTaskId && !!selectedDatasetId &&
    selectedModel != null && selectedDataset != null &&
    isCompatible(selectedModel, selectedDataset) &&
    !submitting

  const totalResultPages = Math.max(1, Math.ceil(resultsTotal / PAGE_SIZE))

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 sm:gap-6 items-start">
      {/* Config Panel */}
      <div className="lg:col-span-1 flex flex-col gap-4">
        <Card className="p-4 sm:p-6 overflow-visible">
          <h3 className="text-base font-semibold text-gray-900 mb-1">
            {t('resultsPage.selectModel')}
          </h3>
          <p className="text-xs text-gray-500 mb-4">
            {t('resultsPage.batchInference.panelDescription')}
          </p>

          {/* Model selector */}
          <div className="relative mb-4">
            <button
              type="button"
              onClick={() => { setIsModelOpen((p) => !p); setIsDatasetOpen(false) }}
              className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-xl shadow-sm transition-all text-sm ${
                isModelOpen
                  ? 'border-purple-500 ring-4 ring-purple-500/10'
                  : 'border-gray-200 hover:border-purple-300'
              }`}
            >
              <span className={selectedModel ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                {selectedModel ? selectedModel.task_name ?? selectedModel.model_id : t('resultsPage.batchInference.selectModelPlaceholder')}
              </span>
              {isModelOpen ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
            </button>
            {isModelOpen && (
              <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg max-h-60 overflow-y-auto">
                {trainedModels.length === 0 ? (
                  <div className="px-3 py-4 text-sm text-gray-500 text-center">
                    {t('resultsPage.noActiveModels')}
                  </div>
                ) : (
                  trainedModels.map((m) => (
                    <button
                      type="button"
                      key={m.model_id}
                      onClick={() => {
                        setSelectedModelId(m.model_id)
                        setSelectedModelTaskId(m.task_id ?? null)
                        setSelectedDatasetId(null)
                        setIsModelOpen(false)
                      }}
                      className={`w-full text-left px-3 py-2.5 text-sm hover:bg-purple-50 transition-colors ${
                        selectedModelId === m.model_id ? 'bg-purple-50 font-medium text-purple-700' : 'text-gray-700'
                      }`}
                    >
                      <div className="font-medium truncate">{m.task_name ?? m.model_id}</div>
                       <div className="text-xs text-gray-400 mt-0.5">
                         {t(`resultsPage.batchInference.taskType.${m.task_type}`, { defaultValue: m.task_type })}
                       </div>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          {/* Dataset selector */}
          <p className="block text-xs font-medium text-gray-700 mb-1.5">
            {t('resultsPage.batchInference.selectDataset')}
          </p>
          <div className="relative mb-4">
            <button
              type="button"
              onClick={() => { setIsDatasetOpen((p) => !p); setIsModelOpen(false) }}
              className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-xl shadow-sm transition-all text-sm ${
                isDatasetOpen
                  ? 'border-purple-500 ring-4 ring-purple-500/10'
                  : 'border-gray-200 hover:border-purple-300'
              }`}
            >
              <span className={selectedDataset ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                {selectedDataset ? selectedDataset.name : t('resultsPage.batchInference.selectDatasetPlaceholder')}
              </span>
              {isDatasetOpen ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
            </button>
            {isDatasetOpen && (
              <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg max-h-60 overflow-y-auto">
                {compatibleDatasets.length === 0 ? (
                  <div className="px-3 py-4 text-sm text-gray-500 text-center">
                    {t('resultsPage.batchInference.noUnlabeledDatasets')}
                    <p className="text-xs mt-1 text-gray-400">
                      {t('resultsPage.batchInference.noUnlabeledDatasetsHint')}
                    </p>
                  </div>
                ) : (
                  compatibleDatasets.map((d) => {
                    const compat = selectedModel ? isCompatible(selectedModel, d) : true
                     return (
                       <button
                         type="button"
                         key={d.dataset_id}
                         onClick={() => {
                          if (!compat) return
                          setSelectedDatasetId(d.dataset_id)
                          setIsDatasetOpen(false)
                        }}
                        disabled={!compat}
                        className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${
                          !compat
                            ? 'opacity-40 cursor-not-allowed'
                            : selectedDatasetId === d.dataset_id
                            ? 'bg-purple-50 font-medium text-purple-700'
                            : 'hover:bg-purple-50 text-gray-700'
                        }`}
                      >
                        <div className="font-medium truncate">{d.name}</div>
                        <div className="text-xs text-gray-400 mt-0.5">
                          {d.task_type} · {t(`resultsPage.batchInference.dataType.${d.data_type}`, { defaultValue: d.data_type })} · {d.slide_count} {t('resultsPage.batchInference.items')}
                        </div>
                        {!compat && (
                          <div className="text-xs text-red-400 mt-0.5">
                            {t('resultsPage.batchInference.incompatibleDataset')}
                          </div>
                        )}
                      </button>
                    )
                  })
                )}
              </div>
            )}
          </div>

          {submitError && (
            <p className="text-xs text-red-500 mb-3">{submitError}</p>
          )}

          <Button
            onClick={doSubmit}
            disabled={!canSubmit}
            className="w-full gap-2 bg-purple-600 hover:bg-purple-700 text-white"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('resultsPage.batchInference.submitting')}
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                {t('resultsPage.batchInference.submit')}
              </>
            )}
          </Button>
        </Card>

        {/* Task list */}
        <Card className="p-4 sm:p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            {t('resultsPage.batchInference.selectTask')}
          </h3>
          {tasksLoading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          ) : biTasks.length === 0 ? (
            <div className="text-center py-6">
              <Activity className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">{t('resultsPage.batchInference.noCompletedTasks')}</p>
              <p className="text-xs text-gray-400 mt-1">{t('resultsPage.batchInference.noCompletedHint')}</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {biTasks.map((task) => (
                <button
                  type="button"
                  key={task.task_id}
                  onClick={() => { setSelectedTaskId(task.task_id); setResultsPage(1) }}
                  className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all text-sm ${
                    selectedTaskId === task.task_id
                      ? 'border-purple-400 bg-purple-50'
                      : 'border-gray-100 bg-gray-50 hover:border-purple-200 hover:bg-purple-50/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-medium text-gray-900 truncate text-xs">
                      {task.task_name}
                    </span>
                    <Badge variant={statusBadgeVariant(task.status)} className="text-xs shrink-0">
                      {t(`resultsPage.batchInference.status.${task.status}`) ?? task.status}
                    </Badge>
                  </div>
                  <div className="text-xs text-gray-400">
                    {t(`resultsPage.batchInference.taskType.${task.task_type}`, { defaultValue: task.task_type })} · {task.results_count} {t('resultsPage.resultsCount', { count: task.results_count })}
                  </div>
                  {task.status === 'running' && (
                    <div className="mt-1.5 h-1 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-500 rounded-full transition-all"
                        style={{ width: `${Math.min(100, task.progress)}%` }}
                      />
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Results Panel */}
      <div className="lg:col-span-3">
        {!selectedTaskId ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <Activity className="w-16 h-16 text-gray-300 mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              {t('resultsPage.batchInference.results')}
            </h3>
            <p className="text-gray-500 text-sm">
              {t('resultsPage.batchInference.selectTaskPlaceholder')}
            </p>
          </Card>
        ) : selectedTask?.status === 'running' || selectedTask?.status === 'pending' ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <Loader2 className="w-12 h-12 text-purple-500 animate-spin mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              {t('resultsPage.batchInference.inProgress')}
            </h3>
            {selectedTask?.status === 'running' && (
              <div className="w-48 h-2 bg-gray-200 rounded-full overflow-hidden mt-2">
                <div
                  className="h-full bg-purple-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, selectedTask.progress)}%` }}
                />
              </div>
            )}
          </Card>
        ) : selectedTask?.status === 'failed' ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <h3 className="text-lg font-semibold text-red-600 mb-2">
              {t('resultsPage.analysisFailed')}
            </h3>
            {selectedTask.error && (
              <p className="text-sm text-gray-500 max-w-sm">{selectedTask.error}</p>
            )}
          </Card>
        ) : (
          <Card className="p-4 sm:p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold text-gray-900">
                  {selectedTask?.task_name ?? t('resultsPage.batchInference.results')}
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  {t(`resultsPage.batchInference.taskType.${selectedTask?.task_type}`, { defaultValue: selectedTask?.task_type })} · {t(`resultsPage.batchInference.dataType.${selectedTask?.data_type}`, { defaultValue: selectedTask?.data_type })} ·{' '}
                  {resultsTotal} {t('resultsPage.resultsCount', { count: resultsTotal })}
                  {selectedTask?.finished_at && (
                    <> · {formatDateTime(selectedTask.finished_at, '')}</>
                  )}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={doExport}
                disabled={exporting}
                className="gap-2 shrink-0"
              >
                {exporting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
                {exporting
                  ? t('resultsPage.batchInference.exporting')
                  : t('resultsPage.batchInference.exportCsv')}
              </Button>
            </div>

            {results.length === 0 ? (
              <div className="text-center py-8 text-gray-500 text-sm">
                {t('resultsPage.batchInference.noResults')}
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">
                          {t('resultsPage.batchInference.slideId')}
                        </th>
                        {(taskType.includes('classification')) && (
                          <>
                            <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">
                              {t('resultsPage.batchInference.predictionClass')}
                            </th>
                            <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">
                              {t('resultsPage.batchInference.confidence')}
                            </th>
                          </>
                        )}
                        {(taskType.includes('survival')) && (
                          <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">
                            {t('resultsPage.batchInference.riskScore')}
                          </th>
                        )}
                        {(taskType.includes('segmentation')) && (
                          <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">
                            {t('resultsPage.batchInference.instanceCount')}
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {results.map((r) => {
                        const topClass = r.pred ?? '—'
                        const confidence =
                          r.probs && r.pred && r.probs[r.pred] != null
                            ? `${(r.probs[r.pred]! * 100).toFixed(1)}%`
                            : '—'
                        const riskScore =
                          r.metadata?.risk_score != null
                            ? Number(r.metadata.risk_score).toFixed(3)
                            : '—'
                        const instanceCount =
                          r.metadata?.instance_count != null
                            ? String(r.metadata.instance_count)
                            : '—'
                        return (
                          <tr key={r.wsi_id} className="hover:bg-gray-50/50 transition-colors">
                            <td className="py-2 px-3 text-gray-700 text-xs max-w-[180px] truncate">
                              <span title={r.wsi_id}>{r.original_filename ?? r.wsi_id}</span>
                            </td>
                            {taskType.includes('classification') && (
                              <>
                                <td className="py-2 px-3">
                                  <Badge variant="secondary" className="text-xs">{topClass}</Badge>
                                </td>
                                <td className="py-2 px-3 text-gray-600 text-xs">{confidence}</td>
                              </>
                            )}
                            {taskType.includes('survival') && (
                              <td className="py-2 px-3 text-gray-600 text-xs">{riskScore}</td>
                            )}
                            {taskType.includes('segmentation') && (
                              <td className="py-2 px-3 text-gray-600 text-xs">{instanceCount}</td>
                            )}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalResultPages > 1 && (
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100 text-sm">
                    <span className="text-xs text-gray-500">
                      {t('resultsPage.batchInference.pagination.showing', {
                        start: (resultsPage - 1) * PAGE_SIZE + 1,
                        end: Math.min(resultsPage * PAGE_SIZE, resultsTotal),
                        total: resultsTotal,
                      })}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setResultsPage((p) => Math.max(1, p - 1))}
                        disabled={resultsPage <= 1}
                      >
                        {t('resultsPage.batchInference.pagination.previous')}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setResultsPage((p) => Math.min(totalResultPages, p + 1))}
                        disabled={resultsPage >= totalResultPages}
                      >
                        {t('resultsPage.batchInference.pagination.next')}
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}
