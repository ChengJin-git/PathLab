import { useState, useEffect, useRef } from 'react'
import { useAsyncAction } from '../lib/useAsyncAction'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import { BarChart3, Play, History, ChevronDown, ChevronUp, Loader2, CheckCircle2, CheckCircle, Trash2, AlertCircle, X, FlaskConical, ArrowLeft, Star, Plus, Check, Activity } from 'lucide-react'
import { Tooltip } from '../components/ui/tooltip'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'

import { getTrainedModels, TrainedModel, buildAuthRequestInit, startExternalValidation as apiStartExternalValidation, fetchDatasetsForValidation, ValidationDataset } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { AnalysisDetails, type AnalysisSummary, type BootstrapCI, type ChartData } from '../components/results/AnalysisDetails'
import { BatchInferencePanel } from '../components/results/BatchInferencePanel'
import {
  CLASSIFICATION_METRICS,
  CLASSIFICATION_CHARTS,
  SURVIVAL_METRICS,
  SURVIVAL_CHARTS,
  getSegmentationMetrics,
  SEGMENTATION_CHARTS,
  EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS,
  EXTERNAL_VALIDATION_SURVIVAL_CHARTS,
  EXTERNAL_VALIDATION_SEGMENTATION_CHARTS,
  DEFAULT_CLASSIFICATION_METRICS,
  DEFAULT_CLASSIFICATION_CHARTS,
  DEFAULT_SURVIVAL_METRICS,
  getDefaultSegmentationMetrics,
  DEFAULT_SEGMENTATION_CHARTS,
  DEFAULT_EXTERNAL_CLASSIFICATION_CHARTS,
  DEFAULT_EXTERNAL_SURVIVAL_CHARTS,
  DEFAULT_EXTERNAL_SEGMENTATION_CHARTS
} from '../constants/metrics'
import { filterCompatibleDatasets, isSurvivalTask as utilIsSurvivalTask, isSegmentationTask as utilIsSegmentationTask } from '../lib/externalValidationUtils'
import { formatDateTime } from '../lib/utils'

type PageMode = 'internal-analysis' | 'external-validation' | 'batch-inference'

const getSegmentationClassCount = (task?: Pick<TrainingTask, 'classes'> | null): number => {
  const classCount = task?.classes?.filter(Boolean).length ?? 0
  return Math.max(1, classCount)
}

interface ValidationProgress {
  validation_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  total_wsi: number
  processed_wsi: number
  model_id: string
  model_task_id: string
  dataset_id: string
  error: string | null
  results_count?: number
}

interface TrainingTask {
  task_id: string
  name: string
  task_type: string
  data_type: string  // "wsi" or "patch"
  aggregation_level: string  // "file" or "case"
  status: string
  created_at: string | null
  has_analysis: boolean
  feature_extractor: string | null
  has_features: boolean
  has_model: boolean
  has_ai_results: boolean
  ai_results_count: number
  total_wsi_count: number  // Total WSI count (file-level)
  total_case_count: number  // Total case count (case-level)
  test_wsi_count?: number
  test_case_count?: number
  test_display_count?: number
  display_count: number  // Count based on aggregation level
  wsi_ids: string[]  // WSI IDs for overlap detection
  classes?: string[] | null
  source_dataset_id?: string | null
  model_config?: Record<string, unknown> | null
  split_config?: {
    strategy?: 'random' | 'k_fold' | 'manual'
    n_splits?: number
    ratios?: { train: number; val: number; test: number }
    stratified?: boolean
  } | null
  model_id: string | null
  is_kfold: boolean  // Whether this task was trained with K-Fold cross-validation
}

interface AnalysisResult {
  task_id: string
  analysis_id: string
  analysis_dir: string
  summary: AnalysisSummary
  chart_paths: Record<string, string>
  metrics: Record<string, number>
  charts?: ChartData
  _pending?: boolean  // Internal flag to indicate analysis is pending/running
}

// Use imported helpers from shared utils
const isSurvivalTask = utilIsSurvivalTask
const isSegmentationTask = utilIsSegmentationTask

const getTaskModelDisplayLabel = (task?: TrainingTask | null): string | null => {
  if (!task) return null
  if (isSegmentationTask(task.task_type)) {
    const backbone = typeof task.model_config?.backbone === 'string' ? task.model_config.backbone : null
    return backbone || task.feature_extractor || null
  }
  return task.feature_extractor || null
}

const getTaskResultsDisplayCount = (task?: TrainingTask | null): number => {
  if (!task) return 0
  const testCount = task.test_display_count ?? 0
  return testCount > 0 ? testCount : task.ai_results_count
}

const isTaskKFold = (task?: TrainingTask | null): boolean => {
  if (!task) return false
  return task.is_kfold || task.split_config?.strategy === 'k_fold'
}

const getTaskSplitLabel = (
  task: TrainingTask | null | undefined,
  t: ReturnType<typeof useTranslation>['t']
): string | null => {
  const strategy = task?.split_config?.strategy
  if (!strategy) return null
  if (strategy === 'random') return t('taskDetail.configuration.splitRandom')
  if (strategy === 'k_fold') return `${task?.split_config?.n_splits ?? 'K'}${t('taskDetail.configuration.splitKFold')}`
  return t('taskDetail.configuration.splitManual')
}

export default function ResultsViewerPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { analysisTasks, subscribeAnalysisSSE } = useBackgroundTask()
  const { isAdmin } = useAuth()
  const { t } = useTranslation()
  const qc = useQueryClient()

  // Subscribe to analysis SSE when this page is mounted
  useEffect(() => {
    const unsubscribe = subscribeAnalysisSSE()
    return () => unsubscribe()
  }, [subscribeAnalysisSSE])

  // Check for task_id in URL params first, then fall back to navigation state
  const taskIdFromUrl = searchParams.get('task_id') || searchParams.get('task')
  const taskIdFromState = (location.state as { selectedTaskId?: string } | null)?.selectedTaskId
  const initialSelectedTaskId = taskIdFromUrl || taskIdFromState || null
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true

  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(initialSelectedTaskId)
  const [running, runRunning] = useAsyncAction<void>()
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([...DEFAULT_CLASSIFICATION_METRICS])
  const [selectedCharts, setSelectedCharts] = useState<string[]>([...DEFAULT_CLASSIFICATION_CHARTS])
  const [description, setDescription] = useState('')
  const [currentResult, setCurrentResult] = useState<AnalysisResult | null>(null)
  const [expandedAnalysis, setExpandedAnalysis] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [deleting, runDeleting] = useAsyncAction<void>({ onError: (err) => setAnalysisError(err instanceof Error ? err.message : t('resultsPage.failedToDeleteRetry')) })
  const [isTaskDropdownOpen, setIsTaskDropdownOpen] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [bootstrapCIMetrics, setBootstrapCIMetrics] = useState<string[]>([])

  const [pageMode, setPageMode] = useState<PageMode>(() => {
    const stored = localStorage.getItem('results-page-mode') as PageMode | null
    const valid: PageMode[] = ['internal-analysis', 'external-validation', 'batch-inference']
    return stored && valid.includes(stored) ? stored : 'internal-analysis'
  })
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false)
  const [modelSearchQuery, setModelSearchQuery] = useState('')
  const [isDataDropdownOpen, setIsDataDropdownOpen] = useState(false)
  const [validationProgress, setValidationProgress] = useState<ValidationProgress | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const selectedTaskIdRef = useRef<string | null>(selectedTaskId)
  const [extValidationPendingTaskId, setExtValidationPendingTaskId] = useState<string | null>(null)
  // Track previous selectedModelId to detect user-initiated model changes (vs initial load)
  const prevModelIdForDatasetRef = useRef<string | null>(null)

  interface CompletedExtValTask {
    task_id: string
    model_id: string | null
    model_task_id: string | null
    dataset_id: string | null
    total_wsi: number
    results_count: number
    has_analysis: boolean
    created_at: string | null
  }

  const [extValQueryTaskId, setExtValQueryTaskId] = useState<string | null>(null)
  const [showExtHistory, setShowExtHistory] = useState(false)
  const [expandedExtAnalysis, setExpandedExtAnalysis] = useState<string | null>(null)

  const { data: tasks = [] as TrainingTask[], isLoading: loading } = useQuery({
    queryKey: ['results-tasks'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/results/tasks`, buildAuthRequestInit())
      if (!response.ok) throw new Error('Failed to load tasks')
      const data = await response.json()
      return (data.items || []) as TrainingTask[]
    },
    staleTime: 2 * 60 * 1000,
  })

  const { data: trainedModels = [] as TrainedModel[] } = useQuery({
    queryKey: ['trained-models'],
    queryFn: async () => {
      const data = await getTrainedModels()
      return data.items.filter(m => m.is_active) as TrainedModel[]
    },
    staleTime: 2 * 60 * 1000,
    enabled: pageMode === 'external-validation' || pageMode === 'batch-inference',
  })

  const { data: validationDatasets = [] as ValidationDataset[] } = useQuery({
    queryKey: ['validation-datasets'],
    queryFn: async () => {
      const data = await fetchDatasetsForValidation()
      return (data.items || []) as ValidationDataset[]
    },
    staleTime: 5 * 60 * 1000,
    enabled: pageMode === 'external-validation',
  })

  const { data: completedExtValTasks = [] as CompletedExtValTask[] } = useQuery({
    queryKey: ['completed-ext-val-tasks'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/results/external-validation/completed`, buildAuthRequestInit())
      if (!response.ok) throw new Error('Failed to load completed ext val tasks')
      const data = await response.json()
      return (data.items || []) as CompletedExtValTask[]
    },
    staleTime: 30 * 1000,
    enabled: pageMode === 'external-validation',
  })

  const { data: analyses = [] as AnalysisSummary[] } = useQuery({
    queryKey: ['analyses', selectedTaskId],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis`, buildAuthRequestInit())
      if (!response.ok) throw new Error('Failed to load analyses')
      const data = await response.json()
      return (data.analyses || []) as AnalysisSummary[]
    },
    enabled: !!selectedTaskId,
    staleTime: 30 * 1000,
  })

  const { data: extAnalyses = [] as AnalysisSummary[] } = useQuery({
    queryKey: ['ext-analyses', extValQueryTaskId],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/results/tasks/${extValQueryTaskId}/analysis`, buildAuthRequestInit())
      if (!response.ok) throw new Error('Failed to load ext analyses')
      const data = await response.json()
      return (data.analyses || []) as AnalysisSummary[]
    },
    enabled: !!extValQueryTaskId,
    staleTime: 30 * 1000,
  })

  useEffect(() => {
    localStorage.setItem('results-page-mode', pageMode)
  }, [pageMode])

  useEffect(() => {
    // Check for task_id in URL params first
    if (taskIdFromUrl && taskIdFromUrl !== selectedTaskId) {
      setSelectedTaskId(taskIdFromUrl)
      // Switch back to internal analysis if we were elsewhere
      if (pageMode !== 'internal-analysis') {
        setPageMode('internal-analysis')
      }
    }

    // Check navigation state for mode switching or pre-selection
    const state = location.state as { pageMode?: PageMode, selectedModelId?: string, selectedTaskId?: string } | null
    if (state?.pageMode && state.pageMode !== pageMode) {
      setPageMode(state.pageMode)
    }
    if (state?.selectedModelId) {
      // We need to wait for trainedModels to load, but we can set the intent
      setSelectedModelId(state.selectedModelId)
    }
    // Handle task_id from state
    if (state?.selectedTaskId && !taskIdFromUrl && state.selectedTaskId !== selectedTaskId) {
      if (state?.pageMode === 'external-validation') {
        // For external validation, load analyses directly instead of setting internal selectedTaskId
        setExtValQueryTaskId(state.selectedTaskId)
        void qc.invalidateQueries({ queryKey: ['completed-ext-val-tasks'] })
      } else {
        setSelectedTaskId(state.selectedTaskId)
      }
    }
  }, [location.state, taskIdFromUrl]) // removed dependency loop risks

  // Track whether we've already done the initial auto-expand (one-shot, don't re-expand after user collapses)
  const autoExpandedRef = useRef(false)

  // Auto-expand the most recent analysis when navigating via URL param or state — fires once per mount
  useEffect(() => {
    if (autoExpandedRef.current) return  // already done, user is in control now
    if (initialSelectedTaskId && analyses.length > 0) {
      // Sort by timestamp descending and expand the most recent
      const sortedAnalyses = [...analyses].sort((a, b) =>
        new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      )
      setExpandedAnalysis(sortedAnalyses[0].analysis_id)
      autoExpandedRef.current = true
    }
  }, [analyses, initialSelectedTaskId])

  // Reset metrics/charts selection when task type changes
  useEffect(() => {
    const task = tasks.find(t => t.task_id === selectedTaskId)
    if (task) {
      if (isSurvivalTask(task.task_type)) {
        setSelectedMetrics(['c_index', 'integrated_brier_score'])
        setSelectedCharts(['km_curve', 'loss_curve'])
      } else if (isSegmentationTask(task.task_type)) {
        setSelectedMetrics(getDefaultSegmentationMetrics(getSegmentationClassCount(task)))
        setSelectedCharts([...DEFAULT_SEGMENTATION_CHARTS])
      } else {
        setSelectedMetrics(['accuracy', 'precision', 'sensitivity', 'f1', 'auc', 'specificity'])
        setSelectedCharts(['confusion_matrix', 'roc_curve', 'loss_curve'])
      }
    }
  }, [selectedTaskId, tasks])

  useEffect(() => {
    setCurrentResult(null)
    setAnalysisError(null)
  }, [selectedTaskId])

  // Reset metrics/charts selection when external model changes
  useEffect(() => {
    if (pageMode !== 'external-validation' || !selectedModelId) return
    const model = trainedModels.find(m => m.model_id === selectedModelId)
    const task = model ? tasks.find(t => t.task_id === model.task_id) : null
    if (task) {
      if (isSurvivalTask(task.task_type)) {
        setSelectedMetrics([...DEFAULT_SURVIVAL_METRICS])
        setSelectedCharts([...DEFAULT_EXTERNAL_SURVIVAL_CHARTS])
      } else if (isSegmentationTask(task.task_type)) {
        setSelectedMetrics(getDefaultSegmentationMetrics(getSegmentationClassCount(task)))
        setSelectedCharts([...DEFAULT_EXTERNAL_SEGMENTATION_CHARTS])
      } else {
        setSelectedMetrics([...DEFAULT_CLASSIFICATION_METRICS])
        setSelectedCharts([...DEFAULT_EXTERNAL_CLASSIFICATION_CHARTS])
      }
      setBootstrapCIMetrics([])
    }
  }, [pageMode, selectedModelId, trainedModels, tasks])

  useEffect(() => {
    if (pageMode !== 'external-validation') return
    const prevModelId = prevModelIdForDatasetRef.current
    prevModelIdForDatasetRef.current = selectedModelId
    if (prevModelId !== null && prevModelId !== selectedModelId) {
      setDatasetId(null)
      setValidationProgress(null)
      setExtValQueryTaskId(null)
      setExtValidationPendingTaskId(null)
    }
  }, [pageMode, selectedModelId])

  // Auto-select most recent completed external validation task's model+dataset
  // when entering external validation mode with nothing selected
  useEffect(() => {
    if (pageMode !== 'external-validation') return
    if (selectedModelId || datasetId) return // Already have a selection
    if (completedExtValTasks.length === 0) return

    const latestTask = completedExtValTasks[0] // Sorted by created_at desc from backend
    if (latestTask.model_id) setSelectedModelId(latestTask.model_id)
    if (latestTask.dataset_id) setDatasetId(latestTask.dataset_id)
  }, [pageMode, completedExtValTasks])

  // Auto-restore external validation results when model+dataset selection matches a completed task
  useEffect(() => {
    if (pageMode !== 'external-validation' || !selectedModelId || !datasetId) return
    // Don't override an actively running validation
    if (validationProgress && validationProgress.status !== 'completed' && validationProgress.status !== 'failed') return

    const matchingTask = completedExtValTasks.find(
      t => t.model_id === selectedModelId && t.dataset_id === datasetId && t.has_analysis
    )
    if (matchingTask) {
      // Restore validationProgress to completed state so rendering logic works
      const model = trainedModels.find(m => m.model_id === selectedModelId)
      setValidationProgress({
        validation_id: matchingTask.task_id,
        status: 'completed',
        progress: 100,
        total_wsi: matchingTask.total_wsi,
        processed_wsi: matchingTask.total_wsi,
        model_id: selectedModelId,
        model_task_id: model?.task_id || matchingTask.model_task_id || '',
        dataset_id: datasetId,
        error: null,
        results_count: matchingTask.results_count,
      })
      // Load analysis history for this task
      setExtValQueryTaskId(matchingTask.task_id)
    } else if (!validationProgress || validationProgress.model_id !== selectedModelId || validationProgress.dataset_id !== datasetId) {
      setValidationProgress(null)
      setCurrentResult(null)
      setExtValQueryTaskId(null)
    }
  }, [pageMode, selectedModelId, datasetId, completedExtValTasks])

  // Track completed analysis tasks to refresh UI when analysis finishes
  const completedAnalysisIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    // Check for newly completed analysis tasks
    const completedTasks = analysisTasks.filter(t => t.status === 'success' || t.status === 'error')

    for (const task of completedTasks) {
      // Extract analysis_id from task.id (format: "analysis_{analysis_id}")
      const analysisId = task.id.replace('analysis_', '')

      // If this is a newly completed task we haven't processed yet
      if (!completedAnalysisIdsRef.current.has(analysisId)) {
        completedAnalysisIdsRef.current.add(analysisId)

        // Check if this is an external validation analysis
        if (task.analysisType === 'external' && task.trainingTaskId) {
          setExtValQueryTaskId(task.trainingTaskId)
          setExtValidationPendingTaskId(null)
          void qc.invalidateQueries({ queryKey: ['completed-ext-val-tasks'] })
        } else {
          if (currentResult?._pending) {
            setCurrentResult(null)
          }
          if (selectedTaskId) {
            void qc.invalidateQueries({ queryKey: ['analyses', selectedTaskId] })
          }
        }
      }
    }
  }, [analysisTasks, selectedTaskId, currentResult])

  // Keep ref in sync with state
  useEffect(() => {
    selectedTaskIdRef.current = selectedTaskId
  }, [selectedTaskId])

  useEffect(() => {
    if (tasks.length > 0) {
      if (!selectedTaskIdRef.current) {
        setSelectedTaskId(tasks[0].task_id)
      } else {
        const taskExists = tasks.some(t => t.task_id === selectedTaskIdRef.current)
        if (!taskExists) {
          setSelectedTaskId(tasks[0].task_id)
        }
      }
    }
  }, [tasks])

  useEffect(() => {
    if (trainedModels.length > 0) {
      const defaultModel = trainedModels.find(m => m.is_default)
      if (defaultModel && !selectedModelId) {
        setSelectedModelId(defaultModel.model_id)
      }
    }
  }, [trainedModels])

  const startExternalValidation = () => {
    if (!selectedModelId || !datasetId || selectedMetrics.length === 0) return

    const selectedModel = trainedModels.find(m => m.model_id === selectedModelId)
    if (!selectedModel) {
      setValidationError(t('resultsPage.modelNoLongerAvailable'))
      return
    }

    setValidationError(null)
    void runRunning(async () => {
      const result = await apiStartExternalValidation(
        selectedModelId,
        datasetId,
        selectedMetrics,
        selectedCharts,
        bootstrapCIMetrics.length > 0
      )

      const responseStatus = (result as unknown as Record<string, unknown>).status as string

      if (responseStatus === 'completed') {
        setValidationProgress({
          validation_id: result.task_id,
          status: 'completed',
          progress: 100,
          total_wsi: result.total_wsi || 0,
          processed_wsi: result.total_wsi || 0,
          model_id: selectedModelId,
          model_task_id: selectedModel?.task_id || '',
          dataset_id: datasetId,
          error: null,
        })
        setExtValQueryTaskId(result.task_id)
      } else if (responseStatus === 'analysis_started') {
        setValidationProgress({
          validation_id: result.task_id,
          status: 'completed',
          progress: 100,
          total_wsi: result.total_wsi || 0,
          processed_wsi: result.total_wsi || 0,
          model_id: selectedModelId,
          model_task_id: selectedModel?.task_id || '',
          dataset_id: datasetId,
          error: null,
        })
      } else {
        setExtValidationPendingTaskId(result.task_id)
      }
    }).catch((error: unknown) => {
      console.error('Failed to start external validation:', error)
      if (error instanceof Error) {
        setValidationError(error.message)
      } else {
        setValidationError(t('resultsPage.failedToConnect'))
      }
    })
  }

  const startPolling = (taskId: string) => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/results/external-validation/${taskId}`, buildAuthRequestInit())
        if (response.ok) {
          const progress = await response.json()
          setValidationProgress({
            validation_id: progress.task_id,
            status: progress.status,
            progress: progress.progress,
            total_wsi: progress.total_wsi,
            processed_wsi: progress.processed_wsi,
            model_id: progress.model_id,
            model_task_id: progress.model_task_id,
            dataset_id: progress.dataset_id,
            error: progress.error,
            results_count: progress.results_count,
          })

          if (progress.status === 'completed' || progress.status === 'failed') {
            if (pollingRef.current) {
              clearInterval(pollingRef.current)
              pollingRef.current = null
            }
            // Reload tasks to update ai_results counts
            if (progress.status === 'completed') {
              await qc.invalidateQueries({ queryKey: ['results-tasks'] })
            }
          }
        }
      } catch (error) {
        console.error('Failed to poll validation progress:', error)
      }
    }

    poll() // Immediate first poll
    pollingRef.current = setInterval(poll, 2000)  // Poll every 2 seconds (matches SSE interval)
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [])

  const selectedModel = trainedModels.find(m => m.model_id === selectedModelId)
  const rawModelTask = selectedModel ? tasks.find(t => t.task_id === selectedModel.task_id) : null

  const { data: modelTaskWsiIds = [] } = useQuery({
    queryKey: ['task-wsi-ids', selectedModel?.task_id],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedModel!.task_id}/wsi-ids`, buildAuthRequestInit())
      if (!response.ok) return []
      const data = await response.json()
      return (data.wsi_ids || []) as string[]
    },
    enabled: pageMode === 'external-validation' && !!selectedModel,
    staleTime: 10 * 60 * 1000,
  })

  const modelTask = rawModelTask ? { ...rawModelTask, wsi_ids: modelTaskWsiIds } : null
  const selectedDataset = validationDatasets.find(ds => ds.dataset_id === datasetId)

  const runAnalysis = () => {
    if (!selectedTaskId || selectedMetrics.length === 0) return

    setAnalysisError(null)
    void runRunning(async () => {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis`, buildAuthRequestInit({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metrics: selectedMetrics,
          charts: selectedCharts,
          description: description || null,
          bootstrap_ci_metrics: bootstrapCIMetrics.length > 0 ? bootstrapCIMetrics : undefined
        })
      }))

      if (response.ok) {
        const result = await response.json()
        // Analysis is now async - result contains status, not full analysis
        if (result.status === 'pending' || result.status === 'running') {
          // Show submitted message - user can track in Background Tasks panel
          setAnalysisError(null)
          setCurrentResult({
            ...result,
            message: t('resultsPage.analysisSubmittedTrack'),
            _pending: true
          })
        } else {
          setCurrentResult(result)
          setExpandedAnalysis(result.analysis_id)
          // Reload analyses list
          void qc.invalidateQueries({ queryKey: ['analyses', selectedTaskId] })
        }
      } else {
        const error = await response.json()
        setAnalysisError(error.detail || t('resultsPage.unknownError'))
      }
    }).catch((error: unknown) => {
      console.error('Failed to run analysis:', error)
      setAnalysisError(t('resultsPage.failedToConnect'))
    })
  }

  const toggleMetric = (metricId: string) => {
    setSelectedMetrics(prev =>
      prev.includes(metricId)
        ? prev.filter(m => m !== metricId)
        : [...prev, metricId]
    )
    // Also remove from bootstrap CI metrics if metric is deselected
    if (selectedMetrics.includes(metricId)) {
      setBootstrapCIMetrics(prev => prev.filter(m => m !== metricId))
    }
  }

  const toggleBootstrapCI = (metricId: string) => {
    setBootstrapCIMetrics(prev =>
      prev.includes(metricId)
        ? prev.filter(m => m !== metricId)
        : [...prev, metricId]
    )
  }

  const toggleChart = (chartId: string) => {
    setSelectedCharts(prev =>
      prev.includes(chartId)
        ? prev.filter(c => c !== chartId)
        : [...prev, chartId]
    )
  }

  const handleDeleteAnalysis = (analysisId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteConfirmId(analysisId)
  }

  const confirmDeleteAnalysis = () => {
    if (!deleteConfirmId) return

    // Determine the task ID based on current page mode
    const taskId = pageMode === 'external-validation'
      ? validationProgress?.validation_id
      : selectedTaskId
    if (!taskId) return

    void runDeleting(async () => {
      const response = await fetch(`${API_BASE}/results/tasks/${taskId}/analysis/${deleteConfirmId}`, buildAuthRequestInit({
        method: 'DELETE'
      }))

      if (response.ok) {
        if (pageMode === 'external-validation') {
          void qc.invalidateQueries({ queryKey: ['ext-analyses', extValQueryTaskId] })
          if (expandedExtAnalysis === deleteConfirmId) {
            setExpandedExtAnalysis(null)
          }
        } else {
          void qc.invalidateQueries({ queryKey: ['analyses', selectedTaskId] })
          if (expandedAnalysis === deleteConfirmId) {
            setExpandedAnalysis(null)
          }
        }
        // If it was the current result, clear it
        if (currentResult?.analysis_id === deleteConfirmId) {
          setCurrentResult(null)
        }
        setDeleteConfirmId(null)
      } else {
        const error = await response.json()
        setAnalysisError(t('resultsPage.failedToDeleteDetail', { detail: error.detail || t('resultsPage.unknownError') }))
      }
    })
  }

  const cancelDelete = () => {
    setDeleteConfirmId(null)
  }

  const selectedTask = tasks.find(t => t.task_id === selectedTaskId)

  if (loading) {
    return (
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6">
        <PageHeader
          title={t('resultsPage.title')}
          description={t('resultsPage.description')}
        >
          <Button variant="outline" onClick={() => navigate('/dashboard')} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            {t('resultsPage.backToDashboard')}
          </Button>
        </PageHeader>
        <div className="flex flex-wrap gap-2 mb-6">
          <div className="h-10 w-40 bg-gray-100 rounded-lg animate-pulse" />
          <div className="h-10 w-40 bg-gray-100 rounded-lg animate-pulse" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 sm:gap-6">
          <div className="lg:col-span-1 space-y-4">
            <div className="h-40 bg-gray-100 rounded-xl animate-pulse" />
            <div className="h-56 bg-gray-100 rounded-xl animate-pulse" />
            <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />
          </div>
          <div className="lg:col-span-3 space-y-4">
            <div className="h-8 w-48 bg-gray-100 rounded animate-pulse" />
            <div className="h-96 bg-gray-100 rounded-xl animate-pulse" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6">
      <PageHeader
        title={t('resultsPage.title')}
        description={t('resultsPage.description')}
      >
        <Button
          variant="outline"
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('resultsPage.backToDashboard')}
        </Button>
      </PageHeader>

      {/* Mode Tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setPageMode('internal-analysis')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all ${
            pageMode === 'internal-analysis'
              ? 'bg-indigo-600 text-white shadow-md'
              : 'bg-white text-gray-600 hover:bg-gray-50 border border-gray-200'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          {t('resultsPage.internalAnalysis')}
        </button>
        <button
          onClick={() => setPageMode('external-validation')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all ${
            pageMode === 'external-validation'
              ? 'bg-orange-600 text-white shadow-md'
              : 'bg-white text-gray-600 hover:bg-gray-50 border border-gray-200'
          }`}
        >
          <FlaskConical className="w-4 h-4" />
          {t('resultsPage.externalValidation')}
        </button>
        <button
          type="button"
          onClick={() => setPageMode('batch-inference')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all ${
            pageMode === 'batch-inference'
              ? 'bg-purple-600 text-white shadow-md'
              : 'bg-white text-gray-600 hover:bg-gray-50 border border-gray-200'
          }`}
        >
          <Activity className="w-4 h-4" />
          {t('resultsPage.batchInference.tabTitle')}
        </button>
      </div>

      {tasks.length === 0 ? (
        <Card className="p-12 text-center">
          <BarChart3 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('resultsPage.noCompletedTasks')}</h3>
          <p className="text-gray-500">{t('resultsPage.completeTaskHint')}</p>
        </Card>
      ) : pageMode === 'external-validation' ? (
        /* External Validation Mode — 4-col layout matching Internal Analysis */
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 sm:gap-6 items-stretch">
          {/* Left Panel - Configuration */}
          <div className="lg:col-span-1 flex flex-col">
            <div className="space-y-6 flex-1">
            {/* Model Selection */}
            <Card className="p-4 sm:p-6 overflow-visible">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.selectModel')}</h3>
              <div className="relative">
                <button
                  onClick={() => { setIsModelDropdownOpen(prev => { if (prev) setModelSearchQuery(''); return !prev }); setIsDataDropdownOpen(false); }}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    isModelDropdownOpen ? 'border-orange-500 ring-4 ring-orange-500/10' : 'border-gray-200 hover:border-orange-300'
                  }`}
                >
                  <div className="flex flex-col items-start">
                    <span className={selectedModel ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {selectedModel ? selectedModel.model_name : t('resultsPage.selectModelPlaceholder')}
                    </span>
                    {selectedModel && (
                      <span className="text-xs text-gray-500">
                        {t('resultsPage.trainedOn', { name: tasks.find(tt => tt.task_id === selectedModel.task_id)?.name || t('resultsPage.unknown') })}
                      </span>
                    )}
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isModelDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isModelDropdownOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => { setIsModelDropdownOpen(false); setModelSearchQuery('') }} />
                    <div className="absolute z-20 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden">
                      <div className="px-3 py-2 border-b border-gray-100">
                        <input
                          type="text"
                          value={modelSearchQuery}
                          onChange={e => setModelSearchQuery(e.target.value)}
                          placeholder={t('resultsPage.searchModels', { defaultValue: 'Search models...' })}
                          className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500/30 focus:border-orange-400"
                          onClick={e => e.stopPropagation()}
                        />
                      </div>
                      <div className="max-h-72 overflow-y-auto">
                        {(() => {
                          const q = modelSearchQuery.trim().toLowerCase()
                          const filtered = q
                            ? trainedModels.filter(m => m.model_name.toLowerCase().includes(q))
                            : trainedModels
                          if (filtered.length === 0) {
                            return (
                              <div className="px-4 py-8 text-center text-gray-500">
                                {trainedModels.length === 0 ? t('resultsPage.noActiveModels') : t('resultsPage.noMatchingModels', { defaultValue: 'No models match your search' })}
                              </div>
                            )
                          }
                          return filtered.map(model => {
                            const trainTask = tasks.find(t => t.task_id === model.task_id)
                            const isSurvival = isSurvivalTask(trainTask?.task_type) || model.aggregator === 'survival'
                            const isSegmentation = isSegmentationTask(trainTask?.task_type)
                            const metrics = model.val_metrics as Record<string, number> | undefined
                            const metricValue = isSurvival
                              ? metrics?.c_index
                              : isSegmentation
                                ? (metrics?.miou ?? metrics?.iou ?? metrics?.dice)
                                : (metrics?.macro_auc || metrics?.auc)
                            const metricLabel = isSurvival
                              ? t('resultsPage.cIndex')
                              : isSegmentation
                                ? (metrics?.miou != null ? 'mIoU' : 'IoU')
                                : t('resultsPage.auc')

                            return (
                              <button
                                key={model.model_id}
                                onClick={() => { setSelectedModelId(model.model_id); setIsModelDropdownOpen(false); setModelSearchQuery('') }}
                                className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                                  selectedModelId === model.model_id ? 'bg-orange-50' : ''
                                }`}
                              >
                                <div className="flex-1 min-w-0">
                                  <div className="font-medium text-gray-900 flex items-center gap-2">
                                    {model.model_name}
                                    {model.is_default && <Star className="w-3 h-3 text-gray-500 flex-shrink-0" />}
                                  </div>
                                  <div className="text-xs text-gray-500 truncate">
                                    {t('resultsPage.trainedOn', { name: trainTask?.name || t('resultsPage.unknown') })}
                                  </div>
                                </div>
                                <div className="flex items-center gap-3 ml-2">
                                  {metricValue !== undefined && (
                                    <span className="text-xs font-mono bg-gray-100 px-2 py-1 rounded">
                                      {metricLabel}: {(metricValue * 100).toFixed(1)}%
                                    </span>
                                  )}
                                  {selectedModelId === model.model_id && <CheckCircle2 className="w-4 h-4 text-orange-600 flex-shrink-0" />}
                                </div>
                              </button>
                            )
                          })
                        })()}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </Card>

            {/* Target Dataset Selection */}
            <Card className="p-4 sm:p-6 overflow-visible">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.targetDataset')}</h3>
              <div className="relative">
                <button
                  onClick={() => { setIsDataDropdownOpen(!isDataDropdownOpen); setIsModelDropdownOpen(false); }}
                  disabled={!selectedModelId}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    !selectedModelId ? 'opacity-50 cursor-not-allowed' :
                    isDataDropdownOpen ? 'border-orange-500 ring-4 ring-orange-500/10' : 'border-gray-200 hover:border-orange-300'
                  }`}
                >
                  <div className="flex flex-col items-start">
                    <span className={selectedDataset ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {selectedDataset ? selectedDataset.name : (selectedModelId ? t('resultsPage.selectDatasetPlaceholder') : t('resultsPage.selectModelFirst'))}
                    </span>
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isDataDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isDataDropdownOpen && selectedModel && modelTask && (() => {
                  // Use shared filtering logic from externalValidationUtils
                  const compatibleDatasets = filterCompatibleDatasets(
                    selectedModel,
                    modelTask,
                    validationDatasets
                  )
                  return (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setIsDataDropdownOpen(false)} />
                    <div className="absolute z-20 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-64 overflow-y-auto">
                      {compatibleDatasets.map(dataset => (
                        <button
                          key={dataset.dataset_id}
                          onClick={() => { setDatasetId(dataset.dataset_id); setIsDataDropdownOpen(false); }}
                          className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                            datasetId === dataset.dataset_id ? 'bg-orange-50' : ''
                          }`}
                        >
                          <div>
                            <div className="font-medium text-gray-900">{dataset.name}</div>
                            <div className="text-xs text-gray-500">
                              {dataset.display_count || 0} {dataset.aggregation_level === 'case' ? t('resultsPage.cases') : t('resultsPage.slides')} • {dataset.data_type?.toUpperCase() || 'WSI'}
                            </div>
                          </div>
                          {datasetId === dataset.dataset_id && <CheckCircle2 className="w-4 h-4 text-orange-600" />}
                        </button>
                      ))}
                      {compatibleDatasets.length === 0 && (
                        <div className="px-4 py-8 text-center text-gray-500">
                          <p className="font-medium">{t('resultsPage.noCompatibleDatasets')}</p>
                          <p className="text-xs mt-1">
                            {t('resultsPage.checkDatasetLabels')}
                          </p>
                          <button
                            onClick={(e) => { e.stopPropagation(); navigate('/wsi-list') }}
                            className="text-xs text-orange-600 hover:text-orange-700 underline mt-2 inline-block"
                          >
                            {t('resultsPage.goToDataRepository')}
                          </button>
                        </div>
                      )}
                    </div>
                  </>
                  )
                })()}
              </div>
            </Card>

            {/* Metrics Selection — shown when model is selected */}
            {selectedModel && (
              <Card className="p-4 sm:p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.metrics')}</h3>
                <div className="space-y-3">
                  {(isSurvivalTask(modelTask?.task_type) ? SURVIVAL_METRICS : isSegmentationTask(modelTask?.task_type) ? getSegmentationMetrics(getSegmentationClassCount(modelTask)) : CLASSIFICATION_METRICS).map(metric => (
                    <div key={metric.id} className="flex items-start gap-3 group">
                      <input
                        type="checkbox"
                        checked={selectedMetrics.includes(metric.id)}
                        onChange={() => toggleMetric(metric.id)}
                        className="mt-1 w-4 h-4 text-orange-600 border-gray-300 rounded focus:ring-orange-500 cursor-pointer"
                      />
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <span
                            className="text-sm font-medium text-gray-900 group-hover:text-orange-600 cursor-pointer"
                            onClick={() => toggleMetric(metric.id)}
                          >
                            {t(metric.labelKey, { defaultValue: metric.label })}
                          </span>
                          {/* 95% CI button — always available for external validation (no K-Fold concept) */}
                          {selectedMetrics.includes(metric.id) && (
                            <button
                              type="button"
                              onClick={() => toggleBootstrapCI(metric.id)}
                              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold tracking-tight transition-all duration-200 focus:outline-none border ${
                                bootstrapCIMetrics.includes(metric.id)
                                  ? 'bg-orange-500 text-white shadow-sm border-orange-500 ring-2 ring-orange-500/20'
                                  : 'bg-gray-50 text-gray-400 border-gray-200 hover:border-orange-200 hover:bg-orange-50 hover:text-orange-600'
                              }`}
                            >
                              {bootstrapCIMetrics.includes(metric.id) ? (
                                <Check className="w-2.5 h-2.5 stroke-[3]" />
                              ) : (
                                <Plus className="w-2.5 h-2.5 stroke-[3]" />
                              )}
                              95% CI
                            </button>
                          )}
                        </div>
                        <p className="text-xs text-gray-500">{t(metric.descriptionKey, { defaultValue: metric.description })}</p>
                      </div>
                    </div>
                  ))}
                </div>
                {bootstrapCIMetrics.length > 0 && (
                  <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                    <p className="text-xs text-amber-700">
                      <span className="font-semibold">{t('resultsPage.note')}</span> {t('resultsPage.bootstrapCINote')}
                    </p>
                  </div>
                )}
              </Card>
            )}

            {/* Charts Selection — shown when model is selected */}
            {selectedModel && (
              <Card className="p-4 sm:p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.charts')}</h3>
                <div className="space-y-3">
                  {(isSurvivalTask(modelTask?.task_type) ? EXTERNAL_VALIDATION_SURVIVAL_CHARTS : isSegmentationTask(modelTask?.task_type) ? EXTERNAL_VALIDATION_SEGMENTATION_CHARTS : EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS).map(chart => (
                    <label key={chart.id} className="flex items-start gap-3 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={selectedCharts.includes(chart.id)}
                        onChange={() => toggleChart(chart.id)}
                        className="mt-1 w-4 h-4 text-orange-600 border-gray-300 rounded focus:ring-orange-500"
                      />
                      <div>
                        <span className="text-sm font-medium text-gray-900 group-hover:text-orange-600">
                          {t(chart.labelKey, { defaultValue: chart.label })}
                        </span>
                        <p className="text-xs text-gray-500">{t(chart.descriptionKey, { defaultValue: chart.description })}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </Card>
            )}

            {/* Description */}
            {selectedModel && (
              <Card className="p-4 sm:p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.descriptionOptional')}</h3>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('resultsPage.addNotesExternal')}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 resize-none"
                  rows={3}
                />
              </Card>
            )}

            </div>

            <div className="mt-auto pt-6 space-y-4">
              {/* Submit Button */}
              <Button
                onClick={startExternalValidation}
                disabled={running || !selectedModelId || !datasetId || selectedMetrics.length === 0 || (validationProgress?.status === 'running') || !!extValidationPendingTaskId}
                className="w-full bg-orange-600 hover:bg-orange-700 text-white py-4 gap-2 text-base font-bold shadow-lg shadow-orange-500/20 rounded-xl"
              >
                {running ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    {t('resultsPage.submitting')}
                  </>
                ) : extValidationPendingTaskId ? (
                  <>
                    <CheckCircle className="w-5 h-5" />
                    {t('resultsPage.extValidationSubmitted')}
                  </>
                ) : validationProgress?.status === 'running' ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    {t('resultsPage.validationInProgressBtn')}
                  </>
                ) : (
                  <>
                    <FlaskConical className="w-5 h-5" />
                    {t('resultsPage.runExternalValidation')}
                  </>
                )}
              </Button>

              {extValidationPendingTaskId && (
                <Card className="p-4 bg-blue-50 border-blue-200">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-5 h-5 text-blue-500 flex-shrink-0" />
                    <p className="text-sm text-blue-700">
                      {t('resultsPage.extValidationSubmittedInfo')}{' '}
                      <button
                        onClick={() => navigate(`/task/${extValidationPendingTaskId}`)}
                        className="underline font-medium hover:text-blue-900"
                      >
                        {t('resultsPage.viewTaskDetail')}
                      </button>
                    </p>
                  </div>
                </Card>
              )}

              {validationError && (
                <Card className="p-4 bg-red-50 border-red-200">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                    <div className="flex-1">
                      <p className="text-sm text-red-600">{validationError}</p>
                    </div>
                    <button onClick={() => setValidationError(null)} className="text-red-400 hover:text-red-600">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </Card>
              )}
            </div>
          </div>

          {/* Right Panel — Results (mirrors internal analysis layout) */}
          <div className="lg:col-span-3 flex flex-col gap-6">
            {/* History Toggle */}
            <div className="flex-none flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                {showExtHistory ? t('resultsPage.analysisHistory') : t('resultsPage.latestResult')}
              </h3>
              <button
                onClick={() => setShowExtHistory(!showExtHistory)}
                className="flex items-center gap-2 text-sm text-orange-600 hover:text-orange-800"
              >
                <History className="w-4 h-4" />
                {showExtHistory ? t('resultsPage.showLatest') : t('resultsPage.viewHistory')}
              </button>
            </div>

            <div className="flex-1 min-h-0">
              {/* Progress — shown while validation is running/pending */}
              {validationProgress && (validationProgress.status === 'running' || validationProgress.status === 'pending') ? (
                <Card className="p-6">
                  <h4 className="font-semibold text-gray-900 mb-4">{t('resultsPage.validationInProgress')}</h4>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600">{t('resultsPage.status')}</span>
                      <Badge variant="secondary" className={
                        validationProgress.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-700'
                      }>
                        {validationProgress.status}
                      </Badge>
                    </div>
                    <div>
                      <div className="flex items-center justify-between text-sm mb-2">
                        <span className="text-gray-600">{t('resultsPage.progress')}</span>
                        <span className="font-medium">{validationProgress.processed_wsi} / {validationProgress.total_wsi} {t('resultsPage.wsis')}</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-3">
                        <div className="h-3 rounded-full transition-all duration-300 bg-orange-500" style={{ width: `${validationProgress.progress}%` }} />
                      </div>
                    </div>
                  </div>
                </Card>

              ) : validationProgress?.status === 'failed' ? (
                <Card className="p-6">
                  <div className="p-4 bg-red-50 rounded-lg border border-red-200">
                    <div className="flex items-center gap-2 text-red-700">
                      <AlertCircle className="w-5 h-5" />
                      <span className="font-medium">{t('resultsPage.validationFailed')}</span>
                    </div>
                    {validationProgress.error && (
                      <p className="text-sm text-red-600 mt-2">{validationProgress.error}</p>
                    )}
                  </div>
                </Card>

              ) : showExtHistory ? (
                /* History List */
                <div className="space-y-4">
                  {extAnalyses.length === 0 ? (
                    <Card className="p-8 text-center">
                      <History className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                      <p className="text-gray-500">{t('resultsPage.noAnalysisHistory')}</p>
                    </Card>
                  ) : (
                    extAnalyses.map(analysis => (
                      <Card key={analysis.analysis_id} className="overflow-hidden">
                        <div className="p-4 flex items-center justify-between hover:bg-gray-50">
                          <button
                            onClick={() => setExpandedExtAnalysis(
                              expandedExtAnalysis === analysis.analysis_id ? null : analysis.analysis_id
                            )}
                            className="flex-1 text-left"
                          >
                            <p className="font-medium text-gray-900">
                              {formatDateTime(analysis.timestamp, '')}
                            </p>
                            <p className="text-sm text-gray-500">
                              {t('resultsPage.samples', { count: analysis.num_samples })}{analysis.classes && ` • ${t('resultsPage.classesCount', { count: analysis.classes.length })}`}
                              {isAdmin && analysis.submitted_by && (
                                <span className="ml-2 text-orange-600">• {analysis.submitted_by}</span>
                              )}
                            </p>
                            {analysis.description && (
                              <p className="text-sm text-gray-600 mt-1">{analysis.description}</p>
                            )}
                          </button>
                          <div className="flex items-center gap-2 ml-3">
                            <Tooltip content={t('resultsPage.deleteThisAnalysis')}>
                            <button
                              onClick={(e) => handleDeleteAnalysis(analysis.analysis_id, e)}
                              className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                            </Tooltip>
                            <button
                              onClick={() => setExpandedExtAnalysis(
                                expandedExtAnalysis === analysis.analysis_id ? null : analysis.analysis_id
                              )}
                              className="p-2 text-gray-400 hover:bg-gray-100 rounded-lg transition-colors"
                            >
                              {expandedExtAnalysis === analysis.analysis_id ? (
                                <ChevronUp className="w-5 h-5" />
                              ) : (
                                <ChevronDown className="w-5 h-5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {expandedExtAnalysis === analysis.analysis_id && (
                          <div className="border-t border-gray-100 p-4 bg-gray-50">
                            <AnalysisDetails analysis={analysis} taskId={validationProgress?.validation_id} modelId={selectedModelId ?? validationProgress?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} isExternal />
                          </div>
                        )}
                      </Card>
                    ))
                  )}
                </div>
              ) : (
                /* Latest Result */
                currentResult && currentResult.summary && !currentResult._pending ? (
                  <Card className="h-full flex flex-col p-4 sm:p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">{t('resultsPage.analysisComplete')}</h4>
                        <p className="text-sm text-gray-500">
                          {formatDateTime(currentResult.summary.timestamp, '')}
                        </p>
                      </div>
                      <CheckCircle2 className="w-6 h-6 text-green-500" />
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={currentResult.summary} taskId={validationProgress?.validation_id} modelId={selectedModelId ?? validationProgress?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} isExternal />
                    </div>
                  </Card>
                ) : extAnalyses.length > 0 ? (
                  <Card className="h-full flex flex-col p-4 sm:p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">{t('resultsPage.latestAnalysis')}</h4>
                        <p className="text-sm text-gray-500">
                          {formatDateTime(extAnalyses[0].timestamp, '')}
                        </p>
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={extAnalyses[0]} taskId={validationProgress?.validation_id} modelId={selectedModelId ?? validationProgress?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} isExternal />
                    </div>
                  </Card>
                ) : (
                  <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
                    <FlaskConical className="w-16 h-16 text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('resultsPage.externalValidation')}</h3>
                    <p className="text-gray-500">{t('resultsPage.externalValidationEmptyHint')}</p>
                  </Card>
                )
              )}
            </div>
          </div>
        </div>
      ) : pageMode === 'batch-inference' ? (
        /* Batch Inference Mode */
        <BatchInferencePanel trainedModels={trainedModels} />
      ) : (
        /* Internal Analysis Mode */
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 sm:gap-6 items-stretch">
          {/* Left Panel - Configuration */}
          <div className="lg:col-span-1 flex flex-col">
            <div className="space-y-6 flex-1">
              {/* Task Selection */}
              <Card className="p-4 sm:p-6 overflow-visible">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-gray-900">{t('resultsPage.selectTask')}</h3>
                </div>
                <span className="bg-gray-100 text-gray-600 text-xs px-2.5 py-0.5 rounded-full font-medium">
                  {t('resultsPage.available', { count: tasks.length })}
                </span>
              </div>
              
              <div className="relative">
                <button
                  onClick={() => setIsTaskDropdownOpen(!isTaskDropdownOpen)}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 active:scale-[0.99] group ${
                    isTaskDropdownOpen ? 'border-indigo-500 ring-4 ring-indigo-500/10' : 'border-gray-200 hover:border-indigo-300 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-start gap-1.5">
                    <span className="text-gray-900 font-semibold text-[15px] tracking-tight">
                      {selectedTask ? selectedTask.name : t('resultsPage.selectTaskPlaceholder')}
                    </span>
                    {selectedTask && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-[10px] uppercase tracking-wider font-bold px-2">
                          {selectedTask.task_type}
                        </Badge>
                        {getTaskModelDisplayLabel(selectedTask) && (
                          <Badge variant="secondary" className="bg-purple-50 text-purple-700 hover:bg-purple-100 text-[10px] tracking-wider font-bold px-2">
                            {getTaskModelDisplayLabel(selectedTask)}
                          </Badge>
                        )}
                        {getTaskSplitLabel(selectedTask, t) && (
                          <Badge variant="secondary" className="bg-sky-50 text-sky-700 hover:bg-sky-100 text-[10px] tracking-wider font-bold px-2">
                            {getTaskSplitLabel(selectedTask, t)}
                          </Badge>
                        )}
                        <span className="text-xs text-gray-400 font-medium">
                          {formatDateTime(selectedTask.created_at || '', '')}
                        </span>
                      </div>
                    )}
                  </div>
                  <ChevronDown
                    className={`w-5 h-5 text-gray-400 transition-transform duration-300 ease-in-out group-hover:text-indigo-500 ${
                      isTaskDropdownOpen ? 'rotate-180 text-indigo-500' : ''
                    }`}
                  />
                </button>

                {isTaskDropdownOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-10"
                      onClick={() => setIsTaskDropdownOpen(false)}
                    />
                    <div className="absolute z-20 w-full mt-2 bg-white/80 backdrop-blur-xl border border-white/20 rounded-xl shadow-2xl shadow-indigo-500/10 overflow-hidden animate-in fade-in zoom-in-95 duration-200 origin-top ring-1 ring-black/5">
                      <div className="max-h-[320px] overflow-y-auto py-2 scrollbar-thin scrollbar-thumb-gray-200">
                        {tasks.map(task => (
                          <button
                            key={task.task_id}
                            onClick={() => {
                              setSelectedTaskId(task.task_id)
                              setIsTaskDropdownOpen(false)
                            }}
                            onMouseEnter={() => {
                              if (task.task_id !== selectedTaskId) {
                                void qc.prefetchQuery({
                                  queryKey: ['analyses', task.task_id],
                                  queryFn: async () => {
                                    const response = await fetch(`${API_BASE}/results/tasks/${task.task_id}/analysis`, buildAuthRequestInit())
                                    if (!response.ok) throw new Error('Failed to load analyses')
                                    const data = await response.json()
                                    return (data.analyses || []) as AnalysisSummary[]
                                  },
                                  staleTime: 30 * 1000,
                                })
                              }
                            }}
                            className="w-full text-left px-2 py-1 mx-2 rounded-lg transition-all duration-200 group/item flex items-center mb-1 last:mb-0 relative overflow-hidden max-w-[calc(100%-16px)]"
                          >
                            <div className={`absolute inset-0 transition-opacity duration-200 ${
                              selectedTaskId === task.task_id 
                                ? 'bg-indigo-600 opacity-100' 
                                : 'bg-gray-50 opacity-0 group-hover/item:opacity-100'
                            }`} />
                            
                            <div className="relative z-10 w-full px-3 py-2.5 flex items-center justify-between">
                              <div className="flex flex-col gap-1">
                                <span className={`text-[15px] font-semibold tracking-tight transition-colors duration-200 ${
                                  selectedTaskId === task.task_id ? 'text-white' : 'text-gray-700'
                                }`}>
                                  {task.name}
                                </span>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                    selectedTaskId === task.task_id
                                      ? 'bg-white/20 text-white'
                                      : 'bg-indigo-50 text-indigo-700'
                                  }`}>
                                    {task.task_type}
                                  </span>
                                  {getTaskModelDisplayLabel(task) && (
                                    <span className={`text-[10px] tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                      selectedTaskId === task.task_id
                                        ? 'bg-white/20 text-white'
                                        : 'bg-purple-50 text-purple-700'
                                    }`}>
                                      {getTaskModelDisplayLabel(task)}
                                    </span>
                                  )}
                                  {getTaskSplitLabel(task, t) && (
                                    <span className={`text-[10px] tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                      selectedTaskId === task.task_id
                                        ? 'bg-white/20 text-white'
                                        : 'bg-sky-50 text-sky-700'
                                    }`}>
                                      {getTaskSplitLabel(task, t)}
                                    </span>
                                  )}
                                  {task.created_at && (
                                    <span className={`text-xs transition-colors duration-200 ${
                                      selectedTaskId === task.task_id ? 'text-indigo-100' : 'text-gray-400'
                                    }`}>
                                      {formatDateTime(task.created_at, '')}
                                    </span>
                                  )}
                                  {/* AI Results Status Badge */}
                                  <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                    selectedTaskId === task.task_id
                                      ? 'bg-white/20 text-white'
                                      : task.ai_results_count > 0
                                        ? 'bg-green-50 text-green-700'
                                        : task.has_analysis
                                          ? 'bg-blue-50 text-blue-700'
                                          : 'bg-amber-50 text-amber-700'
                                  }`}>
                                    {task.ai_results_count > 0
                                      ? t('resultsPage.resultsCount', { count: getTaskResultsDisplayCount(task) })
                                      : task.has_analysis
                                        ? t('resultsPage.analysisAvailable')
                                        : t('resultsPage.noResults')}
                                  </span>
                                </div>
                              </div>
                              
                              {selectedTaskId === task.task_id && (
                                <div className="bg-white/20 p-1 rounded-full">
                                  <CheckCircle2 className="w-4 h-4 text-white" />
                                </div>
                              )}
                            </div>
                          </button>
                        ))}
                        {tasks.length === 0 && (
                          <div className="px-4 py-8 text-sm text-gray-500 text-center flex flex-col items-center gap-2">
                             <div className="w-10 h-10 rounded-full bg-gray-50 flex items-center justify-center">
                               <History className="w-5 h-5 text-gray-400" />
                             </div>
                             <p>{t('resultsPage.noTasksAvailable')}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </Card>

            {/* Metrics Selection */}
            <Card className="p-4 sm:p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                {t('resultsPage.metrics')}
                {selectedTask && isSurvivalTask(selectedTask.task_type) && (
                  <span className="ml-2 text-xs font-normal text-emerald-600"></span>
                )}
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.task_type) ? SURVIVAL_METRICS : isSegmentationTask(selectedTask?.task_type) ? getSegmentationMetrics(getSegmentationClassCount(selectedTask)) : CLASSIFICATION_METRICS).map(metric => (
                  <div key={metric.id} className="flex items-start gap-3 group">
                    <input
                      type="checkbox"
                      checked={selectedMetrics.includes(metric.id)}
                      onChange={() => toggleMetric(metric.id)}
                      className="mt-1 w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500 cursor-pointer"
                    />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span
                          className="text-sm font-medium text-gray-900 group-hover:text-indigo-600 cursor-pointer"
                          onClick={() => toggleMetric(metric.id)}
                        >
                          {t(metric.labelKey, { defaultValue: metric.label })}
                        </span>
                        {/* 95% CI button only for non-K-Fold tasks (K-Fold uses mean ± std) */}
                        {selectedMetrics.includes(metric.id) && !isTaskKFold(selectedTask) && (
                          <button
                            type="button"
                            onClick={() => toggleBootstrapCI(metric.id)}
                            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold tracking-tight transition-all duration-200 focus:outline-none border ${
                              bootstrapCIMetrics.includes(metric.id)
                                ? 'bg-indigo-600 text-white shadow-sm border-indigo-600 ring-2 ring-indigo-600/20'
                                : 'bg-gray-50 text-gray-400 border-gray-200 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600'
                            }`}
                          >
                            {bootstrapCIMetrics.includes(metric.id) ? (
                              <Check className="w-2.5 h-2.5 stroke-[3]" />
                            ) : (
                              <Plus className="w-2.5 h-2.5 stroke-[3]" />
                            )}
                            95% CI
                          </button>
                        )}
                      </div>
                      <p className="text-xs text-gray-500">{t(metric.descriptionKey, { defaultValue: metric.description })}</p>
                    </div>
                  </div>
                ))}
              </div>
              {/* 95% CI computation time note */}
              {bootstrapCIMetrics.length > 0 && (
                <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-xs text-amber-700">
                    <span className="font-semibold">{t('resultsPage.note')}</span> {t('resultsPage.bootstrapCINote')}
                  </p>
                </div>
              )}
            </Card>

            {/* Charts Selection */}
            <Card className="p-4 sm:p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                {t('resultsPage.charts')}
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.task_type) ? SURVIVAL_CHARTS : isSegmentationTask(selectedTask?.task_type) ? SEGMENTATION_CHARTS : CLASSIFICATION_CHARTS).map(chart => (
                  <label key={chart.id} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedCharts.includes(chart.id)}
                      onChange={() => toggleChart(chart.id)}
                      className="mt-1 w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900 group-hover:text-indigo-600">
                        {t(chart.labelKey, { defaultValue: chart.label })}
                      </span>
                      <p className="text-xs text-gray-500">{t(chart.descriptionKey, { defaultValue: chart.description })}</p>
                    </div>
                  </label>
                ))}
              </div>
            </Card>

            {/* Description */}
            <Card className="p-4 sm:p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('resultsPage.descriptionOptional')}</h3>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t('resultsPage.addNotesInternal')}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 resize-none"
                rows={3}
              />
            </Card>

            </div>

            <div className="mt-auto pt-6 space-y-4">
              {/* Run Analysis Button - works even without AI results (backend handles inference automatically) */}
              <Button
                onClick={runAnalysis}
                disabled={running || !selectedTaskId || selectedMetrics.length === 0 || currentResult?._pending}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-4 gap-2 text-base font-bold shadow-lg shadow-indigo-500/20 rounded-xl"
              >
                {running ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    {t('resultsPage.submitting')}
                  </>
                ) : currentResult?._pending ? (
                  <>
                    <CheckCircle className="w-5 h-5" />
                    {t('resultsPage.analysisSubmitted')}
                  </>
                ) : (
                  <>
                    <Play className="w-5 h-5" />
                    {t('resultsPage.runAnalysis')}
                  </>
                )}
              </Button>

              {/* Analysis Submitted Message */}
              {currentResult?._pending && (
                <Card className="p-4 bg-blue-50 border-blue-200">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-5 h-5 text-blue-500 flex-shrink-0" />
                    <p className="text-sm text-blue-700">
                      {t('resultsPage.analysisSubmittedTrack')}
                    </p>
                  </div>
                </Card>
              )}

              {/* Error Alert */}
              {analysisError && (
                <Card className="p-4 bg-red-50 border-red-200">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-red-800">{t('resultsPage.analysisFailed')}</h4>
                      <p className="text-sm text-red-600 mt-1">{analysisError}</p>
                    </div>
                    <button
                      onClick={() => setAnalysisError(null)}
                      className="text-red-400 hover:text-red-600 transition-colors"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </Card>
              )}
            </div>
          </div>

          {/* Right Panel - Results */}
          <div className="lg:col-span-3 flex flex-col gap-6">
            {/* History Toggle */}
            <div className="flex-none flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                {showHistory ? t('resultsPage.analysisHistory') : t('resultsPage.latestResult')}
              </h3>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-800"
              >
                <History className="w-4 h-4" />
                {showHistory ? t('resultsPage.showLatest') : t('resultsPage.viewHistory')}
              </button>
            </div>

            <div className="flex-1 min-h-0">
              {showHistory ? (
                /* History List */
                <div className="space-y-4">
                  {analyses.length === 0 ? (
                    <Card className="p-8 text-center">
                      <History className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                      <p className="text-gray-500">{t('resultsPage.noAnalysisHistoryTask')}</p>
                    </Card>
                  ) : (
                    analyses.map(analysis => (
                      <Card key={analysis.analysis_id} className="overflow-hidden">
                        <div className="p-4 flex items-center justify-between hover:bg-gray-50">
                          <button
                            onClick={() => setExpandedAnalysis(
                              expandedAnalysis === analysis.analysis_id ? null : analysis.analysis_id
                            )}
                            className="flex-1 text-left"
                          >
                            <p className="font-medium text-gray-900">
                              {formatDateTime(analysis.timestamp, '')}
                            </p>
                            <p className="text-sm text-gray-500">
                              {t('resultsPage.samples', { count: analysis.num_samples })}{analysis.classes && ` • ${t('resultsPage.classesCount', { count: analysis.classes.length })}`}
                              {isAdmin && analysis.submitted_by && (
                                <span className="ml-2 text-indigo-600">• {analysis.submitted_by}</span>
                              )}
                            </p>
                            {analysis.description && (
                              <p className="text-sm text-gray-600 mt-1">{analysis.description}</p>
                            )}
                          </button>
                          <div className="flex items-center gap-2 ml-3">
                            <Tooltip content={t('resultsPage.deleteThisAnalysis')}>
                            <button
                              onClick={(e) => handleDeleteAnalysis(analysis.analysis_id, e)}
                              className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                            </Tooltip>
                            <button
                              onClick={() => setExpandedAnalysis(
                                expandedAnalysis === analysis.analysis_id ? null : analysis.analysis_id
                              )}
                              className="p-2 text-gray-400 hover:bg-gray-100 rounded-lg transition-colors"
                            >
                              {expandedAnalysis === analysis.analysis_id ? (
                                <ChevronUp className="w-5 h-5" />
                              ) : (
                                <ChevronDown className="w-5 h-5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {expandedAnalysis === analysis.analysis_id && (
                          <div className="border-t border-gray-100 p-4 bg-gray-50">
                            <AnalysisDetails analysis={analysis} taskId={selectedTaskId!} modelId={selectedTask?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
                          </div>
                        )}
                      </Card>
                    ))
                  )}
                </div>
              ) : (
                /* Latest Result */
                currentResult && currentResult.summary && !currentResult._pending ? (
                  <Card className="h-full flex flex-col p-4 sm:p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">{t('resultsPage.analysisComplete')}</h4>
                        <p className="text-sm text-gray-500">
                          {formatDateTime(currentResult.summary.timestamp, '')}
                        </p>
                      </div>
                      <CheckCircle2 className="w-6 h-6 text-green-500" />
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={currentResult.summary} taskId={selectedTaskId!} modelId={selectedTask?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
                    </div>
                  </Card>
                ) : analyses.length > 0 ? (
                  <Card className="h-full flex flex-col p-4 sm:p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">{t('resultsPage.latestAnalysis')}</h4>
                        <p className="text-sm text-gray-500">
                          {formatDateTime(analyses[0].timestamp, '')}
                        </p>
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={analyses[0]} taskId={selectedTaskId!} modelId={selectedTask?.model_id ?? undefined} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
                    </div>
                  </Card>
                ) : (
                  <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
                    <BarChart3 className="w-16 h-16 text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">{t('resultsPage.noAnalysisYet')}</h3>
                    <p className="text-gray-500">{t('resultsPage.configureAndRun')}</p>
                  </Card>
                )
              )}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-md mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-red-100 rounded-full">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('resultsPage.deleteAnalysis')}</h3>
            </div>
            <p className="text-gray-600 mb-6">
              {t('resultsPage.deleteConfirmMessage')}
            </p>
            <div className="flex justify-end gap-3">
              <Button
                variant="outline"
                onClick={cancelDelete}
                disabled={deleting}
              >
                {t('resultsPage.cancel')}
              </Button>
              <Button
                onClick={confirmDeleteAnalysis}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                {deleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    {t('resultsPage.deleting')}
                  </>
                ) : (
                  t('resultsPage.delete')
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
