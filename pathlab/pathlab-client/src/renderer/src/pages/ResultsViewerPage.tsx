import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import { BarChart3, Play, History, Download, ChevronDown, ChevronUp, Loader2, CheckCircle2, CheckCircle, Trash2, AlertCircle, X, FlaskConical, ArrowLeft, Star, Plus, Check } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KFoldLossCurveChart, KMCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KFoldLossCurveData, type KMCurveData } from '../components/charts/AnalysisCharts'
import { getTrainedModels, TrainedModel, getAuthToken, startExternalValidation as apiStartExternalValidation, fetchDatasetsForValidation, ValidationDataset } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import {
  CLASSIFICATION_METRICS,
  CLASSIFICATION_CHARTS,
  SURVIVAL_METRICS,
  SURVIVAL_CHARTS,
  EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS,
  EXTERNAL_VALIDATION_SURVIVAL_CHARTS,
  DEFAULT_CLASSIFICATION_METRICS,
  DEFAULT_CLASSIFICATION_CHARTS
} from '../constants/metrics'

/**
 * Helper to create fetch options with authentication header
 */
function authFetchOptions(options: RequestInit = {}): RequestInit {
  const token = getAuthToken()
  return {
    ...options,
    headers: {
      ...options.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  }
}

/**
 * Helper to add auth token to URL for <img> tags
 */
function authUrl(url: string): string {
  const token = getAuthToken()
  if (!token) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}token=${encodeURIComponent(token)}`
}

type PageMode = 'internal-analysis' | 'external-validation'

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
  display_count: number  // Count based on aggregation level
  wsi_ids: string[]  // WSI IDs for overlap detection
  model_id: string | null
  is_kfold: boolean  // Whether this task was trained with K-Fold cross-validation
}

interface ChartData {
  confusion_matrix?: ConfusionMatrixData
  roc_curve?: RocCurveData
  loss_curve?: LossCurveData | KFoldLossCurveData
  km_curve?: KMCurveData
}

// K-Fold training metrics structure
interface KFoldMetricValue {
  mean: number
  std: number
}

interface KFoldFoldResult {
  history: Record<string, number[]>
  val_metrics: Record<string, number>
}

interface KFoldTrainingInfo {
  is_kfold: boolean
  num_folds: number
  folds: Record<string, KFoldFoldResult>
  aggregated: Record<string, KFoldMetricValue>
}

// Bootstrap CI types (matching api.ts)
interface BootstrapCI {
  lower: number
  upper: number
  n_samples: number
}

interface BootstrapCIResult {
  metrics_ci: Record<string, BootstrapCI | null>
  class_metrics_ci?: Record<string, Record<string, BootstrapCI | null>>
  n_bootstrap: number
  confidence_level: number
}

interface AnalysisSummary {
  analysis_id: string
  task_id: string
  task_type?: string  // 'classification' or 'survival'
  timestamp: string
  description: string | null
  num_samples: number
  classes?: string[]
  is_binary?: boolean
  requested_metrics?: string[]
  requested_charts?: string[]
  metrics: Record<string, number>
  class_metrics?: Record<string, Record<string, number>>
  chart_paths?: Record<string, string>
  chart_data?: ChartData
  kfold_training?: KFoldTrainingInfo  // K-Fold training info if available
  bootstrap_ci?: BootstrapCIResult  // Bootstrap 95% confidence intervals if computed
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

// Helper to check if task is survival type
const isSurvivalTask = (modelType: string | undefined): boolean => {
  return modelType === 'wsi_survival' || modelType === 'survival'
}

export default function ResultsViewerPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { analysisTasks, subscribeAnalysisSSE } = useBackgroundTask()

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

  const [tasks, setTasks] = useState<TrainingTask[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(initialSelectedTaskId)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([...DEFAULT_CLASSIFICATION_METRICS])
  const [selectedCharts, setSelectedCharts] = useState<string[]>([...DEFAULT_CLASSIFICATION_CHARTS])
  const [description, setDescription] = useState('')
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([])
  const [currentResult, setCurrentResult] = useState<AnalysisResult | null>(null)
  const [expandedAnalysis, setExpandedAnalysis] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [isTaskDropdownOpen, setIsTaskDropdownOpen] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [bootstrapCIMetrics, setBootstrapCIMetrics] = useState<string[]>([])  // Metrics to compute 95% CI for

  // External Validation state
  const [pageMode, setPageMode] = useState<PageMode>('internal-analysis')
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [validationDatasets, setValidationDatasets] = useState<ValidationDataset[]>([])
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false)
  const [isDataDropdownOpen, setIsDataDropdownOpen] = useState(false)
  const [validationProgress, setValidationProgress] = useState<ValidationProgress | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // Completed external validation tasks (for restoring results on page return)
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
  const [completedExtValTasks, setCompletedExtValTasks] = useState<CompletedExtValTask[]>([])

  useEffect(() => {
    loadTasks()
    loadTrainedModels()
    loadValidationDatasets()
    loadCompletedExtValTasks()
  }, [])

  useEffect(() => {
    if (selectedTaskId) {
      loadAnalyses(selectedTaskId)
    }
  }, [selectedTaskId])

  // Auto-expand the most recent analysis when navigating via URL param or state
  useEffect(() => {
    if (initialSelectedTaskId && analyses.length > 0 && !expandedAnalysis) {
      // Sort by timestamp descending and expand the most recent
      const sortedAnalyses = [...analyses].sort((a, b) =>
        new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      )
      setExpandedAnalysis(sortedAnalyses[0].analysis_id)
    }
  }, [analyses, initialSelectedTaskId, expandedAnalysis])

  // Reset metrics/charts selection when task type changes
  useEffect(() => {
    const task = tasks.find(t => t.task_id === selectedTaskId)
    if (task) {
      if (isSurvivalTask(task.task_type)) {
        setSelectedMetrics(['c_index', 'integrated_brier_score'])
        setSelectedCharts(['km_curve', 'loss_curve'])
      } else {
        setSelectedMetrics(['accuracy', 'precision', 'sensitivity', 'f1', 'auc', 'specificity'])
        setSelectedCharts(['confusion_matrix', 'roc_curve', 'loss_curve'])
      }
    }
  }, [selectedTaskId, tasks])

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
      // Load analysis results for this task
      ;(async () => {
        try {
          const response = await fetch(
            `${API_BASE}/results/tasks/${matchingTask.task_id}/analysis`,
            authFetchOptions()
          )
          if (response.ok) {
            const data = await response.json()
            const analysesList: AnalysisSummary[] = data.analyses || []
            if (analysesList.length > 0) {
              // Use the most recent analysis
              setCurrentResult({
                task_id: matchingTask.task_id,
                analysis_id: analysesList[0].analysis_id,
                analysis_dir: '',
                summary: analysesList[0],
                chart_paths: analysesList[0].chart_paths || {},
                metrics: analysesList[0].metrics || {},
              })
            }
          }
        } catch (error) {
          console.error('Failed to load external validation analysis:', error)
        }
      })()
    } else if (!validationProgress || validationProgress.model_id !== selectedModelId || validationProgress.dataset_id !== datasetId) {
      // No matching completed task and selection changed — clear stale results
      setValidationProgress(null)
      setCurrentResult(null)
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
          // Load analysis results for the external validation task
          const extTaskId = task.trainingTaskId
          ;(async () => {
            try {
              const response = await fetch(
                `${API_BASE}/results/tasks/${extTaskId}/analysis`,
                authFetchOptions()
              )
              if (response.ok) {
                const data = await response.json()
                const analysesList: AnalysisSummary[] = data.analyses || []
                if (analysesList.length > 0) {
                  setCurrentResult({
                    task_id: extTaskId,
                    analysis_id: analysesList[0].analysis_id,
                    analysis_dir: '',
                    summary: analysesList[0],
                    chart_paths: analysesList[0].chart_paths || {},
                    metrics: analysesList[0].metrics || {},
                  })
                }
              }
            } catch (error) {
              console.error('Failed to load external validation analysis:', error)
            }
          })()
          // Also refresh the completed extval tasks list for future visits
          loadCompletedExtValTasks()
        } else {
          // Internal analysis — existing logic
          if (currentResult?._pending) {
            setCurrentResult(null)
          }
          if (selectedTaskId) {
            loadAnalyses(selectedTaskId)
          }
        }
      }
    }
  }, [analysisTasks, selectedTaskId, currentResult])

  const loadTasks = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/results/tasks`, authFetchOptions())
      if (response.ok) {
        const data = await response.json()
        const taskList = data.items || []
        setTasks(taskList)
        if (taskList.length > 0 && !selectedTaskId) {
          setSelectedTaskId(taskList[0].task_id)
        }
      }
    } catch (error) {
      console.error('Failed to load tasks:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadTrainedModels = async () => {
    try {
      const data = await getTrainedModels()
      const activeModels = data.items.filter(m => m.is_active)
      setTrainedModels(activeModels)
      // Auto-select default model if exists
      const defaultModel = activeModels.find(m => m.is_default)
      if (defaultModel && !selectedModelId) {
        setSelectedModelId(defaultModel.model_id)
      }
    } catch (error) {
      console.error('Failed to load trained models:', error)
    }
  }

  const loadValidationDatasets = async () => {
    try {
      const data = await fetchDatasetsForValidation()
      setValidationDatasets(data.items || [])
    } catch (error) {
      console.error('Failed to load validation datasets:', error)
    }
  }

  const loadCompletedExtValTasks = async () => {
    try {
      const response = await fetch(`${API_BASE}/results/external-validation/completed`, authFetchOptions())
      if (response.ok) {
        const data = await response.json()
        setCompletedExtValTasks(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load completed external validation tasks:', error)
    }
  }

  const loadAnalyses = async (taskId: string) => {
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${taskId}/analysis`, authFetchOptions())
      if (response.ok) {
        const data = await response.json()
        setAnalyses(data.analyses || [])
      }
    } catch (error) {
      console.error('Failed to load analyses:', error)
    }
  }

  const startExternalValidation = async () => {
    if (!selectedModelId || !datasetId) return

    const selectedModel = trainedModels.find(m => m.model_id === selectedModelId)
    if (!selectedModel) return

    setValidationError(null)
    try {
      // Use the API function which supports all parameters including bootstrap CI
      const result = await apiStartExternalValidation(selectedModelId, datasetId)
      // Task submitted successfully - show pending status
      // Progress will be tracked via SSE in the Background Task Panel
      setValidationProgress({
        validation_id: result.task_id,
        status: 'pending',
        progress: 0,
        total_wsi: result.total_wsi || 0,
        processed_wsi: 0,
        model_id: selectedModelId,
        model_task_id: selectedModel.task_id,
        dataset_id: datasetId,
        error: null,
      })
      // Start polling to track this specific task's progress
      startPolling(result.task_id)
    } catch (error) {
      console.error('Failed to start external validation:', error)
      if (error instanceof Error) {
        setValidationError(error.message)
      } else {
        setValidationError('Failed to connect to the server. Please try again.')
      }
    }
  }

  const startPolling = (taskId: string) => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/results/external-validation/${taskId}`, authFetchOptions())
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
              await loadTasks()
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
  const modelTask = selectedModel ? tasks.find(t => t.task_id === selectedModel.task_id) : null
  const selectedDataset = validationDatasets.find(ds => ds.dataset_id === datasetId)

  const runAnalysis = async () => {
    if (!selectedTaskId || selectedMetrics.length === 0) return

    setRunning(true)
    setAnalysisError(null)
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis`, authFetchOptions({
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
            message: 'Analysis submitted! Track progress in the Background Tasks panel.',
            _pending: true
          })
        } else {
          setCurrentResult(result)
          setExpandedAnalysis(result.analysis_id)
          // Reload analyses list
          await loadAnalyses(selectedTaskId)
        }
      } else {
        const error = await response.json()
        setAnalysisError(error.detail || 'Unknown error occurred')
      }
    } catch (error) {
      console.error('Failed to run analysis:', error)
      setAnalysisError('Failed to connect to the server. Please try again.')
    } finally {
      setRunning(false)
    }
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

  const formatDate = (dateStr: string) => {
    if (!dateStr) return ''
    
    // Fix case where both +00:00 and Z might be present from backend
    const sanitizedDate = dateStr.replace(/\+00:00Z$/, 'Z')
    
    // Ensure the date string is treated as UTC if no timezone is specified
    const normalizedDate = (!sanitizedDate.endsWith('Z') && !sanitizedDate.includes('+')) 
      ? `${sanitizedDate}Z` 
      : sanitizedDate
      
    const date = new Date(normalizedDate)
    return isNaN(date.getTime()) ? dateStr : date.toLocaleString()
  }

  const handleDeleteAnalysis = (analysisId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteConfirmId(analysisId)
  }

  const confirmDeleteAnalysis = async () => {
    if (!deleteConfirmId || !selectedTaskId) return

    setDeleting(true)
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis/${deleteConfirmId}`, authFetchOptions({
        method: 'DELETE'
      }))

      if (response.ok) {
        // Remove from local state
        setAnalyses(prev => prev.filter(a => a.analysis_id !== deleteConfirmId))
        // If it was the current result, clear it
        if (currentResult?.analysis_id === deleteConfirmId) {
          setCurrentResult(null)
        }
        // If it was expanded, collapse it
        if (expandedAnalysis === deleteConfirmId) {
          setExpandedAnalysis(null)
        }
        setDeleteConfirmId(null)
      } else {
        const error = await response.json()
        setAnalysisError(`Failed to delete analysis: ${error.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to delete analysis:', error)
      setAnalysisError('Failed to delete analysis. Please try again.')
    } finally {
      setDeleting(false)
    }
  }

  const cancelDelete = () => {
    setDeleteConfirmId(null)
  }

  const selectedTask = tasks.find(t => t.task_id === selectedTaskId)

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin text-indigo-600 mx-auto mb-4" />
          <p className="text-gray-600">Loading tasks...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6">
      <PageHeader
        title="Results Analysis"
        description="Analyze training task results with customizable metrics and visualizations"
      >
        <Button
          variant="outline"
          onClick={() => navigate(fromAIChat ? '/ai-chat' : '/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          {fromAIChat ? 'Back to Chat' : 'Back to Dashboard'}
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
          Internal Analysis
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
          External Validation
        </button>
      </div>

      {tasks.length === 0 ? (
        <Card className="p-12 text-center">
          <BarChart3 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No Completed Tasks</h3>
          <p className="text-gray-500">Complete a training task to analyze its results.</p>
        </Card>
      ) : pageMode === 'external-validation' ? (
        /* External Validation Mode */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
          {/* Left Panel - Task Selection */}
          <div className="lg:col-span-1 space-y-6">
            {/* Model Selection */}
            <Card className="p-6 overflow-visible">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Select Model</h3>
                <Badge variant="secondary" className="bg-gray-100 text-gray-700">Step 1</Badge>
              </div>
              <p className="text-base md:text-lg text-gray-600 mb-6 leading-relaxed">
                Select a trained model for inference. Manage models in Settings.
              </p>

              <div className="relative">
                <button
                  onClick={() => { setIsModelDropdownOpen(!isModelDropdownOpen); setIsDataDropdownOpen(false); }}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    isModelDropdownOpen ? 'border-gray-400 ring-4 ring-gray-200' : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex flex-col items-start">
                    <span className={selectedModel ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {selectedModel ? selectedModel.model_name : 'Select model...'}
                    </span>
                    {selectedModel && (
                      <span className="text-xs text-gray-500">
                        Trained on: {tasks.find(t => t.task_id === selectedModel.task_id)?.name || 'Unknown'}
                      </span>
                    )}
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isModelDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isModelDropdownOpen && (
                  <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-80 overflow-y-auto">
                    {trainedModels.map(model => {
                      const trainTask = tasks.find(t => t.task_id === model.task_id)
                      const isSurvival = isSurvivalTask(trainTask?.task_type) || model.aggregator === 'survival'
                      const metrics = model.val_metrics as Record<string, number> | undefined
                      const metricValue = isSurvival
                        ? metrics?.c_index
                        : (metrics?.macro_auc || metrics?.auc)
                      const metricLabel = isSurvival ? 'C-Index' : 'AUC'

                      return (
                        <button
                          key={model.model_id}
                          onClick={() => { setSelectedModelId(model.model_id); setIsModelDropdownOpen(false); }}
                          className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                            selectedModelId === model.model_id ? 'bg-gray-100' : ''
                          }`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-gray-900 flex items-center gap-2">
                              {model.model_name}
                              {model.is_default && <Star className="w-3 h-3 text-gray-500 flex-shrink-0" />}
                            </div>
                            <div className="text-xs text-gray-500 truncate">
                              Trained on: {trainTask?.name || 'Unknown'}
                            </div>
                          </div>
                          <div className="flex items-center gap-3 ml-2">
                            {metricValue !== undefined && (
                              <span className="text-xs font-mono bg-gray-100 px-2 py-1 rounded">
                                {metricLabel}: {(metricValue * 100).toFixed(1)}%
                              </span>
                            )}
                            {selectedModelId === model.model_id && <CheckCircle2 className="w-4 h-4 text-gray-600 flex-shrink-0" />}
                          </div>
                        </button>
                      )
                    })}
                    {trainedModels.length === 0 && (
                      <div className="px-4 py-8 text-center text-gray-500">No active models. Train a model first.</div>
                    )}
                  </div>
                )}
              </div>
            </Card>

            {/* Target Dataset Selection */}
            <Card className="p-6 overflow-visible">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Target Dataset</h3>
                <Badge variant="secondary" className="bg-gray-100 text-gray-700">Step 2</Badge>
              </div>
              <p className="text-base md:text-lg text-gray-600 mb-6 leading-relaxed">
                Select a dataset to run inference on. Features will be extracted automatically if needed.
              </p>

              <div className="relative">
                <button
                  onClick={() => { setIsDataDropdownOpen(!isDataDropdownOpen); setIsModelDropdownOpen(false); }}
                  disabled={!selectedModelId}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    !selectedModelId ? 'opacity-50 cursor-not-allowed' :
                    isDataDropdownOpen ? 'border-gray-400 ring-4 ring-gray-200' : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex flex-col items-start">
                    <span className={selectedDataset ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {selectedDataset ? selectedDataset.name : (selectedModelId ? 'Select dataset...' : 'Select model first')}
                    </span>
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isDataDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isDataDropdownOpen && selectedModel && modelTask && (
                  <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-64 overflow-y-auto">
                    {/* Filter datasets by: 1. Same data_type 2. Matching task type 3. Class count match (classification) 4. No WSI overlap */}
                    {validationDatasets.filter(ds => {
                      // Must match data_type (WSI <-> WSI, Patch <-> Patch)
                      const modelDataType = modelTask.data_type || 'wsi'
                      if (ds.data_type !== modelDataType) return false
                      // Must match task type (Classification <-> Classification, Survival <-> Survival)
                      const modelIsSurvival = isSurvivalTask(modelTask.task_type)
                      const datasetIsSurvival = ds.task_type === 'survival'
                      if (modelIsSurvival !== datasetIsSurvival) return false
                      // For classification: must match class count (not class names)
                      if (!modelIsSurvival) {
                        const modelClassCount = selectedModel.classes?.length || 0
                        if (modelClassCount !== ds.distinct_label_count) return false
                      }
                      // Exclude datasets with WSI overlap (prevent data leakage)
                      const modelWsiIds = new Set(modelTask.wsi_ids || [])
                      if (modelWsiIds.size > 0 && ds.wsi_ids?.some(id => modelWsiIds.has(id))) return false
                      return true
                    }).map(dataset => (
                      <button
                        key={dataset.dataset_id}
                        onClick={() => { setDatasetId(dataset.dataset_id); setIsDataDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                          datasetId === dataset.dataset_id ? 'bg-gray-100' : ''
                        }`}
                      >
                        <div>
                          <div className="font-medium text-gray-900">{dataset.name}</div>
                          <div className="text-xs text-gray-500">
                            {dataset.display_count || 0} {dataset.aggregation_level === 'case' ? 'cases' : 'slides'} • {dataset.data_type?.toUpperCase() || 'WSI'}
                          </div>
                        </div>
                        {datasetId === dataset.dataset_id && <CheckCircle2 className="w-4 h-4 text-gray-600" />}
                      </button>
                    ))}
                    {validationDatasets.filter(ds => {
                      const modelDataType = modelTask.data_type || 'wsi'
                      if (ds.data_type !== modelDataType) return false
                      const modelIsSurvival = isSurvivalTask(modelTask.task_type)
                      const datasetIsSurvival = ds.task_type === 'survival'
                      if (modelIsSurvival !== datasetIsSurvival) return false
                      if (!modelIsSurvival) {
                        const modelClassCount = selectedModel.classes?.length || 0
                        if (modelClassCount !== ds.distinct_label_count) return false
                      }
                      const modelWsiIds = new Set(modelTask.wsi_ids || [])
                      if (modelWsiIds.size > 0 && ds.wsi_ids?.some(id => modelWsiIds.has(id))) return false
                      return true
                    }).length === 0 && (
                      <div className="px-4 py-8 text-center text-gray-500">
                        <p className="font-medium">No compatible datasets</p>
                        <p className="text-xs mt-1">
                          Looking for: {modelTask.data_type?.toUpperCase() || 'WSI'} level, {isSurvivalTask(modelTask.task_type) ? 'Survival' : 'Classification'} type, matching class count, no WSI overlap
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Card>

            {/* Run Validation Button */}
            <Button
              onClick={startExternalValidation}
              disabled={!selectedModelId || !datasetId || (validationProgress?.status === 'running')}
              className="w-full bg-orange-600 hover:bg-orange-700 text-white py-3 gap-2 shadow-lg shadow-orange-600/20"
            >
              {validationProgress?.status === 'running' ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Running Validation...
                </>
              ) : (
                <>
                  <FlaskConical className="w-5 h-5" />
                  Run External Validation
                </>
              )}
            </Button>

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

          {/* Right Panel - Progress & Results */}
          <div className="lg:col-span-2 space-y-6">
            {validationProgress ? (
              <>
                {/* Progress Card */}
                <Card className="p-4 sm:p-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Validation Progress</h3>

                  <div className="space-y-4">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600">Status</span>
                      <Badge variant="secondary" className={
                        validationProgress.status === 'completed' ? 'bg-green-100 text-green-700' :
                        validationProgress.status === 'failed' ? 'bg-red-100 text-red-700' :
                        validationProgress.status === 'running' ? 'bg-blue-100 text-blue-700' :
                        'bg-gray-100 text-gray-700'
                      }>
                        {validationProgress.status}
                      </Badge>
                    </div>

                    <div>
                      <div className="flex items-center justify-between text-sm mb-2">
                        <span className="text-gray-600">Progress</span>
                        <span className="font-medium">{validationProgress.processed_wsi} / {validationProgress.total_wsi} WSIs</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-3">
                        <div
                          className={`h-3 rounded-full transition-all duration-300 ${
                            validationProgress.status === 'completed' ? 'bg-green-500' :
                            validationProgress.status === 'failed' ? 'bg-red-500' :
                            'bg-orange-500'
                          }`}
                          style={{ width: `${validationProgress.progress}%` }}
                        />
                      </div>
                    </div>

                    {validationProgress.status === 'completed' && (
                      <div className="p-4 bg-green-50 rounded-lg border border-green-200">
                        <div className="flex items-center gap-2 text-green-700">
                          <CheckCircle2 className="w-5 h-5" />
                          <span className="font-medium">Validation completed!</span>
                        </div>
                        <p className="text-sm text-green-600 mt-2">
                          Generated {validationProgress.results_count || validationProgress.processed_wsi} inference results.
                          Configure metrics and charts below, then run analysis.
                        </p>
                      </div>
                    )}

                    {validationProgress.status === 'failed' && validationProgress.error && (
                      <div className="p-4 bg-red-50 rounded-lg border border-red-200">
                        <div className="flex items-center gap-2 text-red-700">
                          <AlertCircle className="w-5 h-5" />
                          <span className="font-medium">Validation failed</span>
                        </div>
                        <p className="text-sm text-red-600 mt-2">{validationProgress.error}</p>
                      </div>
                    )}
                  </div>
                </Card>

                {/* Analysis Configuration - Show when validation completed */}
                {validationProgress.status === 'completed' && (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {/* Metrics Selection */}
                      <Card className="p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">
                          Metrics
                          {modelTask && isSurvivalTask(modelTask.task_type) && (
                            <span className="ml-2 text-xs font-normal text-emerald-600"></span>
                          )}
                        </h3>
                        <div className="space-y-3">
                          {(isSurvivalTask(modelTask?.task_type) ? SURVIVAL_METRICS : CLASSIFICATION_METRICS).map(metric => (
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
                                    {metric.label}
                                  </span>
                                  {/* 95% CI button only for non-K-Fold models (K-Fold uses mean ± std) */}
                                  {selectedMetrics.includes(metric.id) && !modelTask?.is_kfold && (
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
                                <p className="text-xs text-gray-500">{metric.description}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                        {/* 95% CI computation time note */}
                        {bootstrapCIMetrics.length > 0 && (
                          <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p className="text-xs text-amber-700">
                              <span className="font-semibold">Note:</span> Computing 95% CI with 1000 bootstrap samples would take longer time.
                            </p>
                          </div>
                        )}
                      </Card>

                      {/* Charts Selection */}
                      <Card className="p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">
                          Charts
                          {modelTask && isSurvivalTask(modelTask.task_type) && (
                            <span className="ml-2 text-xs font-normal text-emerald-600"></span>
                          )}
                        </h3>
                        <div className="space-y-3">
                          {(isSurvivalTask(modelTask?.task_type) ? EXTERNAL_VALIDATION_SURVIVAL_CHARTS : EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS).map(chart => (
                            <label key={chart.id} className="flex items-start gap-3 cursor-pointer group">
                              <input
                                type="checkbox"
                                checked={selectedCharts.includes(chart.id)}
                                onChange={() => toggleChart(chart.id)}
                                className="mt-1 w-4 h-4 text-orange-600 border-gray-300 rounded focus:ring-orange-500"
                              />
                              <div>
                                <span className="text-sm font-medium text-gray-900 group-hover:text-orange-600">
                                  {chart.label}
                                </span>
                                <p className="text-xs text-gray-500">{chart.description}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </Card>
                    </div>

                    {/* Description */}
                    <Card className="p-6">
                      <h3 className="text-lg font-semibold text-gray-900 mb-4">Description (Optional)</h3>
                      <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        placeholder="Add notes about this external validation analysis..."
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 resize-none"
                        rows={2}
                      />
                    </Card>

                    {/* Run Analysis Button */}
                    <Button
                      onClick={async () => {
                        // Use the external validation task ID for analysis
                        const taskIdToAnalyze = validationProgress.validation_id
                        setRunning(true)
                        setAnalysisError(null)
                        try {
                          const response = await fetch(`${API_BASE}/results/tasks/${taskIdToAnalyze}/analysis`, authFetchOptions({
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
                              // Store the analysis_id for later
                              setCurrentResult({
                                ...result,
                                message: 'Analysis submitted! Track progress in the Background Tasks panel.',
                                _pending: true
                              })
                            } else {
                              setCurrentResult(result)
                              setExpandedAnalysis(result.analysis_id)
                            }
                          } else {
                            const error = await response.json()
                            setAnalysisError(error.detail || 'Unknown error occurred')
                          }
                        } catch (error) {
                          console.error('Failed to run analysis:', error)
                          setAnalysisError('Failed to connect to the server. Please try again.')
                        } finally {
                          setRunning(false)
                        }
                      }}
                      disabled={running || selectedMetrics.length === 0}
                      className="w-full bg-gray-800 hover:bg-gray-900 text-white py-3 gap-2"
                    >
                      {running ? (
                        <>
                          <Loader2 className="w-5 h-5 animate-spin" />
                          Submitting...
                        </>
                      ) : (
                        <>
                          <BarChart3 className="w-5 h-5" />
                          Run Analysis on Validation Results
                        </>
                      )}
                    </Button>

                    {/* Analysis Submitted Message */}
                    {currentResult?._pending && (
                      <Card className="p-4 bg-blue-50 border-blue-200">
                        <div className="flex items-center gap-3">
                          <CheckCircle className="w-5 h-5 text-blue-500 flex-shrink-0" />
                          <p className="text-sm text-blue-700">
                            Analysis submitted! Track progress in the Background Tasks panel.
                          </p>
                        </div>
                      </Card>
                    )}

                    {/* Analysis Error */}
                    {analysisError && (
                      <Card className="p-4 bg-red-50 border-red-200">
                        <div className="flex items-start gap-3">
                          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                          <div className="flex-1">
                            <p className="text-sm text-red-600">{analysisError}</p>
                          </div>
                          <button onClick={() => setAnalysisError(null)} className="text-red-400 hover:text-red-600">
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      </Card>
                    )}

                    {/* Show current result if available - reuse AnalysisDetails for full feature parity */}
                    {currentResult && currentResult.summary && !currentResult._pending && (
                      <Card className="p-4 sm:p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">External Validation Results</h3>
                        <AnalysisDetails
                          analysis={currentResult.summary}
                          taskId={currentResult.task_id}
                          selectedMetrics={selectedMetrics}
                          selectedCharts={selectedCharts}
                          isExternal
                        />
                      </Card>
                    )}
                  </>
                )}
              </>
            ) : (
              <Card className="p-12 text-center">
                <FlaskConical className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-gray-900 mb-2">External Validation</h3>
                <p className="text-gray-500 max-w-md mx-auto">
                  Test a trained model on data from a different task. Select a model source and feature source, then run validation to generate inference results.
                </p>
              </Card>
            )}
          </div>
        </div>
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
                  <h3 className="text-lg font-semibold text-gray-900">Select Task</h3>
                </div>
                <span className="bg-gray-100 text-gray-600 text-xs px-2.5 py-0.5 rounded-full font-medium">
                  {tasks.length} available
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
                      {selectedTask ? selectedTask.name : 'Select a task...'}
                    </span>
                    {selectedTask && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-[10px] uppercase tracking-wider font-bold px-2">
                          {selectedTask.task_type}
                        </Badge>
                        {selectedTask.feature_extractor && (
                          <Badge variant="secondary" className="bg-purple-50 text-purple-700 hover:bg-purple-100 text-[10px] uppercase tracking-wider font-bold px-2">
                            {selectedTask.feature_extractor}
                          </Badge>
                        )}
                        <span className="text-xs text-gray-400 font-medium">
                          {formatDate(selectedTask.created_at || '')}
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
                                  {task.feature_extractor && (
                                    <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                      selectedTaskId === task.task_id
                                        ? 'bg-white/20 text-white'
                                        : 'bg-purple-50 text-purple-700'
                                    }`}>
                                      {task.feature_extractor}
                                    </span>
                                  )}
                                  {task.created_at && (
                                    <span className={`text-xs transition-colors duration-200 ${
                                      selectedTaskId === task.task_id ? 'text-indigo-100' : 'text-gray-400'
                                    }`}>
                                      {formatDate(task.created_at)}
                                    </span>
                                  )}
                                  {/* AI Results Status Badge */}
                                  <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                    selectedTaskId === task.task_id
                                      ? 'bg-white/20 text-white'
                                      : task.has_ai_results
                                        ? 'bg-green-50 text-green-700'
                                        : 'bg-amber-50 text-amber-700'
                                  }`}>
                                    {task.has_ai_results ? `${task.ai_results_count} results` : 'no results'}
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
                             <p>No tasks available</p>
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
                Metrics
                {selectedTask && isSurvivalTask(selectedTask.task_type) && (
                  <span className="ml-2 text-xs font-normal text-emerald-600"></span>
                )}
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.task_type) ? SURVIVAL_METRICS : CLASSIFICATION_METRICS).map(metric => (
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
                          {metric.label}
                        </span>
                        {/* 95% CI button only for non-K-Fold tasks (K-Fold uses mean ± std) */}
                        {selectedMetrics.includes(metric.id) && !selectedTask?.is_kfold && (
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
                      <p className="text-xs text-gray-500">{metric.description}</p>
                    </div>
                  </div>
                ))}
              </div>
              {/* 95% CI computation time note */}
              {bootstrapCIMetrics.length > 0 && (
                <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-xs text-amber-700">
                    <span className="font-semibold">Note:</span> Computing 95% CI with 1000 bootstrap samples would take longer time.
                  </p>
                </div>
              )}
            </Card>

            {/* Charts Selection */}
            <Card className="p-4 sm:p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Charts
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.task_type) ? SURVIVAL_CHARTS : CLASSIFICATION_CHARTS).map(chart => (
                  <label key={chart.id} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedCharts.includes(chart.id)}
                      onChange={() => toggleChart(chart.id)}
                      className="mt-1 w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900 group-hover:text-indigo-600">
                        {chart.label}
                      </span>
                      <p className="text-xs text-gray-500">{chart.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </Card>

            {/* Description */}
            <Card className="p-4 sm:p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Description (Optional)</h3>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Add notes about this analysis..."
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
                    Submitting...
                  </>
                ) : currentResult?._pending ? (
                  <>
                    <CheckCircle className="w-5 h-5" />
                    Analysis Submitted
                  </>
                ) : (
                  <>
                    <Play className="w-5 h-5" />
                    Run Analysis
                  </>
                )}
              </Button>

              {/* Analysis Submitted Message */}
              {currentResult?._pending && (
                <Card className="p-4 bg-blue-50 border-blue-200">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-5 h-5 text-blue-500 flex-shrink-0" />
                    <p className="text-sm text-blue-700">
                      Analysis submitted! Track progress in the Background Tasks panel.
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
                      <h4 className="text-sm font-medium text-red-800">Analysis Failed</h4>
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
                {showHistory ? 'Analysis History' : 'Latest Result'}
              </h3>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-800"
              >
                <History className="w-4 h-4" />
                {showHistory ? 'Show Latest' : 'View History'}
              </button>
            </div>

            <div className="flex-1 min-h-0">
              {showHistory ? (
                /* History List */
                <div className="space-y-4">
                  {analyses.length === 0 ? (
                    <Card className="p-8 text-center">
                      <History className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                      <p className="text-gray-500">No analysis history for this task</p>
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
                              {formatDate(analysis.timestamp)}
                            </p>
                            <p className="text-sm text-gray-500">
                              {analysis.num_samples} samples{analysis.classes && ` • ${analysis.classes.length} classes`}
                            </p>
                            {analysis.description && (
                              <p className="text-sm text-gray-600 mt-1">{analysis.description}</p>
                            )}
                          </button>
                          <div className="flex items-center gap-2 ml-3">
                            <button
                              onClick={(e) => handleDeleteAnalysis(analysis.analysis_id, e)}
                              className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                              title="Delete this analysis"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
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
                            <AnalysisDetails analysis={analysis} taskId={selectedTaskId!} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
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
                        <h4 className="font-semibold text-gray-900">Analysis Complete</h4>
                        <p className="text-sm text-gray-500">
                          {formatDate(currentResult.summary.timestamp)}
                        </p>
                      </div>
                      <CheckCircle2 className="w-6 h-6 text-green-500" />
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={currentResult.summary} taskId={selectedTaskId!} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
                    </div>
                  </Card>
                ) : analyses.length > 0 ? (
                  <Card className="h-full flex flex-col p-4 sm:p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">Latest Analysis</h4>
                        <p className="text-sm text-gray-500">
                          {formatDate(analyses[0].timestamp)}
                        </p>
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={analyses[0]} taskId={selectedTaskId!} selectedMetrics={selectedMetrics} selectedCharts={selectedCharts} />
                    </div>
                  </Card>
                ) : (
                  <Card className="p-12 text-center h-full flex flex-col items-center justify-center">
                    <BarChart3 className="w-16 h-16 text-gray-300 mb-4" />
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">No Analysis Yet</h3>
                    <p className="text-gray-500">Configure metrics and charts, then run analysis.</p>
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
              <h3 className="text-lg font-semibold text-gray-900">Delete Analysis</h3>
            </div>
            <p className="text-gray-600 mb-6">
              Are you sure you want to delete this analysis? This action cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <Button
                variant="outline"
                onClick={cancelDelete}
                disabled={deleting}
              >
                Cancel
              </Button>
              <Button
                onClick={confirmDeleteAnalysis}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                {deleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    Deleting...
                  </>
                ) : (
                  'Delete'
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface AnalysisDetailsProps {
  analysis: AnalysisSummary
  taskId?: string
  selectedMetrics?: string[]
  selectedCharts?: string[]
  isExternal?: boolean
}

function AnalysisDetails({ analysis, taskId, selectedMetrics, selectedCharts, isExternal = false }: AnalysisDetailsProps) {
  // Use task_id from analysis object if available, fallback to prop
  const effectiveTaskId = analysis.task_id || taskId
  const isSurvival = analysis.task_type === 'wsi_survival' || analysis.task_type === 'survival'
  // Color scheme helpers: orange for external, indigo for internal (survival always emerald)
  const accentBg = isExternal ? 'bg-orange-600' : 'bg-indigo-600'
  const accentText = isExternal ? 'text-orange-600' : 'text-indigo-600'
  const accentTextHover = isExternal ? 'hover:text-orange-800' : 'hover:text-indigo-800'
  const accentHoverBorder = isExternal ? 'hover:border-orange-100' : 'hover:border-indigo-100'
  const accentCIBadge = isExternal ? 'bg-orange-100 text-orange-700' : 'bg-indigo-100 text-indigo-700'
  const accentRowHover = isExternal ? 'hover:bg-orange-50/30' : 'hover:bg-indigo-50/30'
  const accentDlBtn = isExternal ? 'bg-white hover:bg-orange-50 text-orange-700 border-orange-100 hover:border-orange-200' : 'bg-white hover:bg-indigo-50 text-indigo-700 border-indigo-100 hover:border-indigo-200'
  const accentDlIcon = isExternal ? 'bg-orange-50' : 'bg-indigo-50'

  // Define metric key mappings (backend key -> metric id)
  const metricKeyToId: Record<string, string> = {
    'accuracy': 'accuracy',
    'macro_precision': 'precision',
    'precision': 'precision',
    'macro_sensitivity': 'sensitivity',
    'sensitivity': 'sensitivity',
    'macro_specificity': 'specificity',
    'specificity': 'specificity',
    'macro_f1': 'f1',
    'f1': 'f1',
    'macro_auc': 'auc',
    'auc': 'auc',
    'c_index': 'c_index',
    'integrated_brier_score': 'integrated_brier_score',
    'ibs': 'integrated_brier_score'
  }

  // Check if a metric key should be displayed based on selectedMetrics
  const shouldShowMetric = (key: string): boolean => {
    if (!selectedMetrics || selectedMetrics.length === 0) return true
    const metricId = metricKeyToId[key]
    return metricId ? selectedMetrics.includes(metricId) : false
  }

  // Check if a chart should be displayed based on selectedCharts
  const shouldShowChart = (chartId: string): boolean => {
    if (!selectedCharts || selectedCharts.length === 0) return true
    return selectedCharts.includes(chartId)
  }

  // Helper for direct file download
  const handleDownload = async (e: React.MouseEvent, url: string, filename: string) => {
    e.preventDefault()
    try {
      const response = await fetch(url, authFetchOptions())
      if (!response.ok) throw new Error('Download failed')
      const blob = await response.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = blobUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(blobUrl)
    } catch (error) {
      console.error('Download failed:', error)
      window.open(url, '_blank')
    }
  }

  // Format metric value based on metric type
  const formatMetricValue = (key: string, value: number) => {
    // These metrics are shown as decimal (0.xxx format)
    if (key === 'c_index' || key === 'integrated_brier_score' || key === 'ibs') {
      return value.toFixed(4)
    }
    // Other metrics shown as percentage
    return `${(value * 100).toFixed(1)}%`
  }

  // Get display name for metric
  const getMetricDisplayName = (key: string) => {
    if (key === 'c_index') return 'C-Index'
    return key.replace('macro_', '').replace(/_/g, ' ')
  }

  return (
    <div className="h-full flex flex-col space-y-6">
      <div className="flex-1 space-y-6">
        {/* K-Fold Training Results - if available */}
      {analysis.kfold_training && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
          <h5 className="text-sm font-semibold text-purple-800 mb-3 flex items-center gap-2">
            <FlaskConical className="w-4 h-4" />
            K-Fold Cross-Validation Results ({analysis.kfold_training.num_folds} folds)
          </h5>

          {/* Aggregated Statistics */}
          {Object.entries(analysis.kfold_training.aggregated)
            .filter(([key]) => key !== 'loss' && shouldShowMetric(key)).length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-purple-600 font-medium mb-2">Aggregated Statistics (mean ± std)</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(analysis.kfold_training.aggregated)
                .filter(([key]) => key !== 'loss' && shouldShowMetric(key))
                .map(([key, stats]) => (
                <div key={key} className="bg-white p-3 rounded-lg border border-purple-200">
                  <p className="text-xs text-gray-500 uppercase">{getMetricDisplayName(key)}</p>
                  <p className="text-lg font-bold text-purple-600">
                    {key === 'c_index'
                      ? `${stats.mean.toFixed(4)} ± ${stats.std.toFixed(4)}`
                      : `${(stats.mean * 100).toFixed(1)}% ± ${(stats.std * 100).toFixed(1)}%`
                    }
                  </p>
                </div>
              ))}
            </div>
          </div>
          )}

          {/* Per-Fold Results */}
          {Object.keys(analysis.kfold_training.aggregated)
            .filter(key => key !== 'loss' && shouldShowMetric(key)).length > 0 && (
          <details className="group">
            <summary className="text-xs text-purple-600 font-medium cursor-pointer hover:text-purple-800">
              Show per-fold details
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-purple-200">
                    <th className="py-2 text-left text-gray-500">Fold</th>
                    {Object.keys(analysis.kfold_training.aggregated)
                      .filter(key => key !== 'loss' && shouldShowMetric(key))
                      .map(key => (
                      <th key={key} className="py-2 text-center text-gray-500">{getMetricDisplayName(key)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(analysis.kfold_training.folds)
                    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
                    .map(([foldName, foldData]) => (
                    <tr key={foldName} className="border-b border-purple-100">
                      <td className="py-2 font-medium text-purple-700">
                        {foldName.replace('fold_', 'Fold ')}
                      </td>
                      {Object.keys(analysis.kfold_training!.aggregated)
                        .filter(key => key !== 'loss' && shouldShowMetric(key))
                        .map(key => {
                        const val = foldData.val_metrics[key] ?? foldData.val_metrics[`val_${key}`]
                        return (
                          <td key={key} className="py-2 text-center">
                            {val !== undefined
                              ? (key === 'c_index' ? val.toFixed(4) : `${(val * 100).toFixed(1)}%`)
                              : '-'
                            }
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          )}
        </div>
      )}

      {/* Metrics Grid */}
      {Object.entries(analysis.metrics).filter(([key]) => !key.includes('recall') && shouldShowMetric(key)).length > 0 && (
      <div className="pt-4">
        <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
          <div className={`w-1.5 h-6 ${accentBg} rounded-full`} />
          Metrics
        </h5>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {Object.entries(analysis.metrics)
            .filter(([key]) => !key.includes('recall') && shouldShowMetric(key))
            .map(([key, value]) => {
              // Check if CI is available for this metric
              const ci = analysis.bootstrap_ci?.metrics_ci?.[key] || analysis.bootstrap_ci?.metrics_ci?.[`macro_${key}`]
              return (
                <div key={key} className={`p-4 sm:p-6 rounded-2xl border-2 transition-all hover:shadow-md ${isSurvival ? 'bg-emerald-50/50 border-emerald-100 hover:border-emerald-200' : `bg-white border-gray-100 ${accentHoverBorder}`}`}>
                  <p className="text-xs text-gray-400 uppercase font-bold tracking-wider mb-2">{getMetricDisplayName(key)}</p>
                  <p className={`text-2xl sm:text-3xl font-black ${isSurvival ? 'text-emerald-600' : accentText}`}>
                    {formatMetricValue(key, value)}
                  </p>
                  {ci && (
                    <div className="mt-3 flex items-center gap-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider ${isSurvival ? 'bg-emerald-100 text-emerald-700' : accentCIBadge}`}>95% CI</span>
                      <span className="text-sm font-medium text-gray-500">
                        {formatMetricValue(key, ci.lower)} – {formatMetricValue(key, ci.upper)}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
        </div>
      </div>
      )}

      {/* Per-Class Metrics - Only for classification tasks */}
      {!isSurvival && analysis.class_metrics && Object.keys(analysis.class_metrics).length > 0 && (() => {
        // Define per-class columns with their metric IDs
        const perClassColumns = [
          { id: 'precision', label: 'Precision', getValue: (m: any) => m.precision || 0, getCIKey: 'precision' },
          { id: 'sensitivity', label: 'Sensitivity', getValue: (m: any) => m.sensitivity || m.recall || 0, getCIKey: 'sensitivity' },
          { id: 'specificity', label: 'Specificity', getValue: (m: any) => m.specificity || 0, getCIKey: 'specificity' },
          { id: 'f1', label: 'F1 Score', getValue: (m: any) => m.f1 || 0, getCIKey: 'f1' },
          { id: 'auc', label: 'AUC', getValue: (m: any) => m.auc || 0, getCIKey: 'auc' }
        ]
        // Filter columns based on selectedMetrics
        const visibleColumns = perClassColumns.filter(col =>
          !selectedMetrics || selectedMetrics.length === 0 || selectedMetrics.includes(col.id)
        )
        // Only show table if there are visible columns
        if (visibleColumns.length === 0) return null
        return (
        <div className="pt-8">
          <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
            <div className={`w-1.5 h-6 ${accentBg} rounded-full`} />
            Per-Class Performance
          </h5>
          <div className="overflow-x-auto rounded-2xl border border-gray-100 shadow-sm bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/50 border-b border-gray-100">
                  <th className="px-4 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Class</th>
                  {visibleColumns.map(col => (
                    <th key={col.id} className="px-4 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">{col.label}</th>
                  ))}
                  <th className="px-4 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Support</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {Object.entries(analysis.class_metrics).map(([cls, metrics]) => {
                  const classCI = analysis.bootstrap_ci?.class_metrics_ci?.[cls]
                  return (
                    <tr key={cls} className={`${accentRowHover} transition-colors`}>
                      <td className="px-4 py-4 font-bold text-gray-900">{cls}</td>
                      {visibleColumns.map(col => {
                        const value = col.getValue(metrics)
                        const ci = classCI?.[col.getCIKey as keyof typeof classCI] as { lower: number; upper: number } | undefined
                        return (
                          <td key={col.id} className="px-4 py-4 text-center">
                            <span className={`font-medium ${accentText}`}>{(value * 100).toFixed(1)}%</span>
                            {ci && (
                              <span className="block text-xs text-gray-400">({(ci.lower * 100).toFixed(1)}-{(ci.upper * 100).toFixed(1)})</span>
                            )}
                          </td>
                        )
                      })}
                      <td className="px-4 py-4 text-center text-gray-500 font-mono">{metrics.support || 0}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
        )
      })()}

      {/* Charts - Use ECharts if chart_data available, fallback to static images */}
      {/* Only render section if there's actual chart data and selected charts */}
      {((analysis.chart_data && Object.keys(analysis.chart_data).length > 0) ||
        (analysis.chart_paths && Object.keys(analysis.chart_paths).length > 0)) && (
        <div className="pt-8 mb-8">
          <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
            <div className={`w-1.5 h-6 ${accentBg} rounded-full`} />
            Analysis Charts
          </h5>
          <div className={`grid grid-cols-1 ${isSurvival ? 'xl:grid-cols-2 lg:max-w-5xl' : 'xl:grid-cols-2 2xl:grid-cols-3'} gap-8`}>
            {/* Confusion Matrix */}
            {shouldShowChart('confusion_matrix') && (analysis.chart_data?.confusion_matrix ? (
              <ConfusionMatrixChart data={analysis.chart_data.confusion_matrix} title="Confusion Matrix" />
            ) : analysis.chart_paths?.confusion_matrix && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Confusion Matrix</span>
                  <button
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`, 'confusion_matrix.png')}
                    className={`${accentText} ${accentTextHover}`}
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={authUrl(`${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`)} alt="Confusion Matrix" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            ))}

            {/* ROC Curve */}
            {shouldShowChart('roc_curve') && (analysis.chart_data?.roc_curve ? (
              <RocCurveChart data={analysis.chart_data.roc_curve} title="ROC Curve" />
            ) : analysis.chart_paths?.roc_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">ROC Curve</span>
                  <button
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`, 'roc_curve.png')}
                    className={`${accentText} ${accentTextHover}`}
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={authUrl(`${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`)} alt="ROC Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            ))}

            {/* Loss Curve */}
            {shouldShowChart('loss_curve') && (analysis.chart_data?.loss_curve ? (
              // Check if it's K-Fold loss data
              'is_kfold' in analysis.chart_data.loss_curve && analysis.chart_data.loss_curve.is_kfold ? (
                <KFoldLossCurveChart data={analysis.chart_data.loss_curve as KFoldLossCurveData} title="K-Fold Training Loss Curve" />
              ) : (
                <LossCurveChart data={analysis.chart_data.loss_curve as LossCurveData} title="Training Loss Curve" />
              )
            ) : analysis.chart_paths?.loss_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Loss Curve</span>
                  <button
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`, 'loss_curve.png')}
                    className={`${accentText} ${accentTextHover}`}
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={authUrl(`${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`)} alt="Loss Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            ))}

            {/* KM Curve - Survival Analysis */}
            {shouldShowChart('km_curve') && (analysis.chart_data?.km_curve ? (
              <KMCurveChart data={analysis.chart_data.km_curve} title="Kaplan-Meier Survival Curve" />
            ) : analysis.chart_paths?.km_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">KM Curve</span>
                  <button
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/km_curve.png`, 'km_curve.png')}
                    className="text-emerald-600 hover:text-emerald-800"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={authUrl(`${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/km_curve.png`)} alt="KM Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {/* Download All */}
      <div className="flex flex-col sm:flex-row gap-4 pt-4 border-t border-gray-100">
        <button
          onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/summary.json`, `analysis_summary_${analysis.analysis_id}.json`)}
          className={`flex-1 flex items-center justify-center gap-3 px-6 py-4 ${accentDlBtn} rounded-xl text-sm font-bold shadow-sm transition-all active:scale-[0.98]`}
        >
          <div className={`p-2 ${accentDlIcon} rounded-lg group-hover:bg-white transition-colors`}>
            <Download className="w-5 h-5" />
          </div>
          <div className="text-left">
            <div className="text-[10px] uppercase tracking-wider opacity-60">Metadata</div>
            Download Summary (JSON)
          </div>
        </button>
        <button
          onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${effectiveTaskId}/analysis/${analysis.analysis_id}/file/results.json`, `full_results_${analysis.analysis_id}.json`)}
          className="flex-1 flex items-center justify-center gap-3 px-6 py-4 bg-white hover:bg-emerald-50 text-emerald-700 rounded-xl text-sm font-bold border border-emerald-100 shadow-sm transition-all hover:border-emerald-200 active:scale-[0.98]"
        >
          <div className="p-2 bg-emerald-50 rounded-lg group-hover:bg-white transition-colors">
            <Download className="w-5 h-5" />
          </div>
          <div className="text-left">
            <div className="text-[10px] uppercase tracking-wider opacity-60">Raw Data</div>
            Download Full Results (JSON)
          </div>
        </button>
      </div>
    </div>
  )
}
