import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Activity, BarChart3, CheckCircle, ChevronDown, ChevronUp, Loader2, Play } from 'lucide-react'

import { type TrainedModel } from '../../api'
import {
  fetchWSIForIndependentInference,
  getIndependentInferenceResults,
  listIndependentInferenceTasks,
  startIndependentInference,
  type BatchInferenceResult,
  type IndependentInferenceTask,
  type IndependentInferenceWSI,
} from '../../api/batchInference'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'
import { useToast } from '../../contexts/ToastContext'
import { useAsyncAction } from '../../lib/useAsyncAction'
import { formatDateTime } from '../../lib/utils'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { EmptyStatePanel } from '../ui/workspace-primitives'

const PAGE_SIZE = 20

function statusBadgeVariant(status: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'running' || status === 'pending') return 'secondary'
  return 'outline'
}

function isCompatible(model: TrainedModel, item: IndependentInferenceWSI): boolean {
  return (model.task_type ?? '').toLowerCase() === (item.task_type ?? '').toLowerCase()
}

interface IndependentInferencePanelProps {
  trainedModels: TrainedModel[]
}

export function IndependentInferencePanel({ trainedModels }: IndependentInferencePanelProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { openPanel } = useBackgroundTask()
  const { success, error: showError } = useToast()
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedWsiIds, setSelectedWsiIds] = useState<string[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [isModelOpen, setIsModelOpen] = useState(false)
  const [resultsPage, setResultsPage] = useState(1)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [pendingTaskId, setPendingTaskId] = useState<string | null>(null)
  const [submitting, runSubmit] = useAsyncAction()

  const selectedModel = trainedModels.find((model) => model.model_id === selectedModelId) ?? null

  const { data: wsiData, isLoading: wsiLoading } = useQuery({
    queryKey: ['independent-inference-wsi', selectedModel?.task_type ?? null],
    queryFn: () => fetchWSIForIndependentInference(selectedModel?.task_type),
    staleTime: 60 * 1000,
  })

  const { data: taskData, isLoading: tasksLoading } = useQuery({
    queryKey: ['independent-inference-tasks'],
    queryFn: () => listIndependentInferenceTasks(0, 50),
    staleTime: 30 * 1000,
    refetchInterval: 15 * 1000,
  })

  const tasks: IndependentInferenceTask[] = taskData?.items ?? []
  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId) ?? null

  useEffect(() => {
    if (pendingTaskId && tasks.some((task) => task.task_id === pendingTaskId)) {
      setPendingTaskId(null)
    }
  }, [pendingTaskId, tasks])

  const { data: resultsData } = useQuery({
    queryKey: ['independent-inference-results', selectedTaskId, resultsPage],
    queryFn: () => getIndependentInferenceResults(selectedTaskId!, (resultsPage - 1) * PAGE_SIZE, PAGE_SIZE),
    enabled: !!selectedTaskId && selectedTask?.status === 'completed',
    staleTime: 60 * 1000,
  })

  const candidates = useMemo(() => {
    const items = wsiData?.items ?? []
    return selectedModel ? items.filter((item) => isCompatible(selectedModel, item)) : items
  }, [selectedModel, wsiData?.items])
  const results: BatchInferenceResult[] = resultsData?.items ?? []
  const resultsTotal = resultsData?.total ?? 0
  const totalResultPages = Math.max(1, Math.ceil(resultsTotal / PAGE_SIZE))
  const taskType = resultsData?.task_type ?? selectedTask?.model_task_type ?? selectedTask?.task_type ?? ''
  const canSubmit = !!selectedModelId && selectedWsiIds.length > 0 && !submitting && !pendingTaskId

  const toggleWsi = (wsiId: string) => {
    setSelectedWsiIds((current) =>
      current.includes(wsiId) ? current.filter((id) => id !== wsiId) : [...current, wsiId]
    )
  }

  const doSubmit = () => runSubmit(async () => {
    if (!selectedModelId || selectedWsiIds.length === 0) return
    setSubmitError(null)
    try {
      const result = await startIndependentInference({ model_id: selectedModelId, wsi_ids: selectedWsiIds })
      setPendingTaskId(result.task_id)
      setSelectedTaskId(result.task_id)
      setResultsPage(1)
      await queryClient.invalidateQueries({ queryKey: ['independent-inference-tasks'] })
      openPanel()
      success(`Batch inference submitted for ${result.total_wsi} image(s).`)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to submit batch inference'
      setSubmitError(message)
      showError(message)
    }
  })

  if (trainedModels.length === 0) {
    return (
      <EmptyStatePanel
        icon={<BarChart3 className="h-8 w-8" />}
        title="No active models available"
        description="Train or activate a model before running batch inference on uploaded unlabeled images."
        action={<Button onClick={() => navigate('/task-setup')}>Create training task</Button>}
      />
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 sm:gap-6 items-start">
      <div className="lg:col-span-1 flex flex-col gap-4">
        <Card className="p-4 sm:p-6 overflow-visible">
          <h3 className="text-base font-semibold text-gray-900 mb-1">Batch inference</h3>
          <p className="text-xs text-gray-500 mb-4">
            Select an active model and uploaded unlabeled images, then run inference manually.
          </p>

          <div className="relative mb-4">
            <button
              type="button"
              onClick={() => setIsModelOpen((open) => !open)}
              className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-xl shadow-sm transition-all text-sm ${
                isModelOpen ? 'border-purple-500 ring-4 ring-purple-500/10' : 'border-gray-200 hover:border-purple-300'
              }`}
            >
              <span className={selectedModel ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                {selectedModel ? selectedModel.task_name ?? selectedModel.model_id : 'Select model'}
              </span>
              {isModelOpen ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
            </button>
            {isModelOpen && (
              <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg max-h-60 overflow-y-auto">
                {trainedModels.map((model) => (
                  <button
                    type="button"
                    key={model.model_id}
                    onClick={() => {
                      setSelectedModelId(model.model_id)
                      setSelectedWsiIds([])
                      setIsModelOpen(false)
                    }}
                    className={`w-full text-left px-3 py-2.5 text-sm hover:bg-purple-50 transition-colors ${
                      selectedModelId === model.model_id ? 'bg-purple-50 font-medium text-purple-700' : 'text-gray-700'
                    }`}
                  >
                    <div className="font-medium truncate">{model.task_name ?? model.model_id}</div>
                    <div className="text-xs text-gray-400 mt-0.5">{model.task_type}</div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="mb-4 rounded-xl border border-gray-100 bg-gray-50/70 p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium text-gray-700">Uploaded unlabeled images</p>
              <Badge variant="outline" className="text-xs">{selectedWsiIds.length} selected</Badge>
            </div>
            {wsiLoading ? (
              <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-gray-400" /></div>
            ) : candidates.length === 0 ? (
              <p className="py-4 text-center text-xs text-gray-500">
                {selectedModel ? 'No compatible unlabeled uploads found.' : 'Select a model to filter compatible uploads.'}
              </p>
            ) : (
              <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
                {candidates.map((item) => (
                  <button
                    type="button"
                    key={item.wsi_id}
                    onClick={() => toggleWsi(item.wsi_id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                      selectedWsiIds.includes(item.wsi_id)
                        ? 'border-purple-300 bg-purple-50 text-purple-800'
                        : 'border-gray-100 bg-white text-gray-700 hover:border-purple-200'
                    }`}
                  >
                    <div className="font-medium truncate">{item.original_filename ?? item.wsi_id}</div>
                    <div className="mt-0.5 text-gray-400 truncate">
                      {item.dataset_name ?? item.dataset_id ?? 'No dataset'} · {item.task_type ?? 'unknown'}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {submitError && <p className="text-xs text-red-500 mb-3">{submitError}</p>}
          <Button onClick={doSubmit} disabled={!canSubmit} className="w-full gap-2 bg-purple-600 hover:bg-purple-700 text-white">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : pendingTaskId ? <CheckCircle className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {submitting ? 'Submitting' : pendingTaskId ? 'Submitted' : 'Run inference'}
          </Button>
        </Card>

        <Card className="p-4 sm:p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Batch inference tasks</h3>
          {tasksLoading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 text-gray-400 animate-spin" /></div>
          ) : tasks.length === 0 ? (
            <div className="text-center py-6">
              <Activity className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No batch inference tasks yet.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {tasks.map((task) => (
                <button
                  type="button"
                  key={task.task_id}
                  onClick={() => { setSelectedTaskId(task.task_id); setResultsPage(1) }}
                  className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all text-sm ${
                    selectedTaskId === task.task_id ? 'border-purple-400 bg-purple-50' : 'border-gray-100 bg-gray-50 hover:border-purple-200 hover:bg-purple-50/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-medium text-gray-900 truncate text-xs">{task.task_name}</span>
                    <Badge variant={statusBadgeVariant(task.status)} className="text-xs shrink-0">{task.status}</Badge>
                  </div>
                  <div className="text-xs text-gray-400">{task.total_wsi} images · {task.results_count} results</div>
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="lg:col-span-3">
        {!selectedTaskId ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <Activity className="w-16 h-16 text-gray-300 mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Detailed inference results</h3>
            <p className="text-gray-500 text-sm">Select a batch inference task to inspect predictions.</p>
          </Card>
        ) : selectedTask?.status === 'running' || selectedTask?.status === 'pending' ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <Loader2 className="w-12 h-12 text-purple-500 animate-spin mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Inference in progress</h3>
          </Card>
        ) : selectedTask?.status === 'failed' ? (
          <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
            <h3 className="text-lg font-semibold text-red-600 mb-2">Inference failed</h3>
            {selectedTask.error && <p className="text-sm text-gray-500 max-w-sm">{selectedTask.error}</p>}
          </Card>
        ) : (
          <Card className="p-4 sm:p-6">
            <div className="mb-4">
              <h3 className="text-base font-semibold text-gray-900">{selectedTask?.task_name ?? 'Batch inference results'}</h3>
              <p className="text-xs text-gray-500 mt-0.5">
                {taskType || selectedTask?.task_type} · {resultsTotal} results
                {selectedTask?.finished_at ? <> · {formatDateTime(selectedTask.finished_at, '')}</> : null}
              </p>
            </div>

            {results.length === 0 ? (
              <div className="text-center py-8 text-gray-500 text-sm">No results recorded yet.</div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">Image</th>
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">Prediction</th>
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500">Details</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {results.map((result) => {
                        const confidence = result.probs && result.pred && result.probs[result.pred] != null
                          ? `${(result.probs[result.pred]! * 100).toFixed(1)}%`
                          : null
                        const riskScore = result.metadata?.risk_score != null ? `Risk ${Number(result.metadata.risk_score).toFixed(3)}` : null
                        const mask = result.metadata?.pred_mask_path || result.metadata?.pred_mask_file ? 'Mask generated' : null
                        const createdAt = result.created_at ? formatDateTime(result.created_at, '') : 'Unknown time'
                        const metadataCount = result.metadata ? Object.keys(result.metadata).length : 0
                        return (
                          <tr key={`${result.wsi_id}-${result.created_at ?? ''}`} className="hover:bg-gray-50/50 transition-colors">
                            <td className="py-2 px-3 text-xs max-w-[260px]">
                              <div className="font-medium text-gray-800 truncate">{result.original_filename ?? result.wsi_id}</div>
                              <div className="text-gray-400 truncate">ID {result.wsi_id}</div>
                              {result.case_id && <div className="text-gray-400 truncate">Case {result.case_id}</div>}
                            </td>
                            <td className="py-2 px-3"><Badge variant="secondary" className="text-xs">{result.pred ?? riskScore ?? mask ?? 'Completed'}</Badge></td>
                            <td className="py-2 px-3 text-xs text-gray-500 min-w-[220px]">
                              <div>{confidence ?? riskScore ?? mask ?? 'No prediction metadata'}</div>
                              <div className="text-gray-400">Created {createdAt}</div>
                              <div className="text-gray-400">Metadata fields: {metadataCount}</div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {totalResultPages > 1 && (
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100 text-sm">
                    <span className="text-xs text-gray-500">Page {resultsPage} of {totalResultPages}</span>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => setResultsPage((page) => Math.max(1, page - 1))} disabled={resultsPage <= 1}>Previous</Button>
                      <Button variant="outline" size="sm" onClick={() => setResultsPage((page) => Math.min(totalResultPages, page + 1))} disabled={resultsPage >= totalResultPages}>Next</Button>
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
