import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart3, Play, History, Download, ChevronDown, ChevronUp, Loader2, CheckCircle2, Trash2, AlertCircle, X, FlaskConical, ArrowLeft, Star } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KMCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KMCurveData } from '../components/charts/AnalysisCharts'
import { getTrainedModels, TrainedModel } from '../api'

type PageMode = 'internal-analysis' | 'external-validation'

interface ValidationProgress {
  validation_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  total_wsi: number
  processed_wsi: number
  model_id: string
  model_task_id: string
  data_task_id: string
  error: string | null
  results_count?: number
}

interface TrainingTask {
  task_id: string
  name: string
  model_type: string
  status: string
  created_at: string | null
  has_analysis: boolean
  feature_extractor: string | null
  has_features: boolean
  has_model: boolean
  has_ai_results: boolean
  ai_results_count: number
  model_id: string | null
}

interface ChartData {
  confusion_matrix?: ConfusionMatrixData
  roc_curve?: RocCurveData
  loss_curve?: LossCurveData
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

interface AnalysisSummary {
  analysis_id: string
  task_id: string
  task_type?: string  // 'classification' or 'survival_prediction'
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
}

interface AnalysisResult {
  task_id: string
  analysis_id: string
  analysis_dir: string
  summary: AnalysisSummary
  chart_paths: Record<string, string>
  metrics: Record<string, number>
  charts?: ChartData
}

// Classification metrics and charts
const CLASSIFICATION_METRICS = [
  { id: 'accuracy', label: 'Accuracy', description: 'Overall prediction accuracy' },
  { id: 'precision', label: 'Precision', description: 'Positive predictive value' },
  { id: 'sensitivity', label: 'Sensitivity', description: 'True positive rate' },
  { id: 'specificity', label: 'Specificity', description: 'True negative rate' },
  { id: 'f1', label: 'F1 Score', description: 'Harmonic mean of precision and recall' },
  { id: 'auc', label: 'AUC', description: 'Area under ROC curve' }
]

const CLASSIFICATION_CHARTS = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs' }
]

// Survival analysis metrics and charts
const SURVIVAL_METRICS = [
  { id: 'c_index', label: 'C-Index', description: 'Concordance index for survival prediction' }
]

const SURVIVAL_CHARTS = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs' }
]

// External Validation charts (no loss_curve since there's no training)
const EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve' }
]

const EXTERNAL_VALIDATION_SURVIVAL_CHARTS = [
  { id: 'km_curve', label: 'KM Curve', description: 'Kaplan-Meier survival curve' }
]

// Helper to check if task is survival type
const isSurvivalTask = (modelType: string | undefined): boolean => {
  return modelType === 'wsi_survival' || modelType === 'survival_prediction'
}

export default function ResultsViewerPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<TrainingTask[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(['accuracy', 'precision', 'sensitivity', 'f1', 'auc','specificity'])
  const [selectedCharts, setSelectedCharts] = useState<string[]>(['confusion_matrix', 'roc_curve', 'loss_curve'])
  const [description, setDescription] = useState('')
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([])
  const [currentResult, setCurrentResult] = useState<AnalysisResult | null>(null)
  const [expandedAnalysis, setExpandedAnalysis] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [isTaskDropdownOpen, setIsTaskDropdownOpen] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)

  // External Validation state
  const [pageMode, setPageMode] = useState<PageMode>('internal-analysis')
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [dataTaskId, setDataTaskId] = useState<string | null>(null)
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false)
  const [isDataDropdownOpen, setIsDataDropdownOpen] = useState(false)
  const [validationProgress, setValidationProgress] = useState<ValidationProgress | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    loadTasks()
    loadTrainedModels()
  }, [])

  useEffect(() => {
    if (selectedTaskId) {
      loadAnalyses(selectedTaskId)
    }
  }, [selectedTaskId])

  // Reset metrics/charts selection when task type changes
  useEffect(() => {
    const task = tasks.find(t => t.task_id === selectedTaskId)
    if (task) {
      if (isSurvivalTask(task.model_type)) {
        setSelectedMetrics(['c_index'])
        setSelectedCharts(['km_curve', 'loss_curve'])
      } else {
        setSelectedMetrics(['accuracy', 'precision', 'sensitivity', 'f1', 'auc', 'specificity'])
        setSelectedCharts(['confusion_matrix', 'roc_curve', 'loss_curve'])
      }
    }
  }, [selectedTaskId, tasks])

  const loadTasks = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/results/tasks`)
      if (response.ok) {
        const data = await response.json()
        setTasks(data.tasks || [])
        if (data.tasks?.length > 0 && !selectedTaskId) {
          setSelectedTaskId(data.tasks[0].task_id)
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

  const loadAnalyses = async (taskId: string) => {
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${taskId}/analysis`)
      if (response.ok) {
        const data = await response.json()
        setAnalyses(data.analyses || [])
      }
    } catch (error) {
      console.error('Failed to load analyses:', error)
    }
  }

  const regenerateResults = async () => {
    if (!selectedTaskId) return

    setRegenerating(true)
    setAnalysisError(null)
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })

      if (response.ok) {
        // Reload tasks to update has_ai_results status
        await loadTasks()
        setAnalysisError(null)
      } else {
        const error = await response.json()
        setAnalysisError(error.detail || 'Failed to regenerate results')
      }
    } catch (error) {
      console.error('Failed to regenerate results:', error)
      setAnalysisError('Failed to connect to the server. Please try again.')
    } finally {
      setRegenerating(false)
    }
  }

  const startExternalValidation = async () => {
    if (!selectedModelId || !dataTaskId) return

    const selectedModel = trainedModels.find(m => m.model_id === selectedModelId)
    if (!selectedModel) return

    // Check if model's task and data task are the same
    if (selectedModel.task_id === dataTaskId) {
      setValidationError('Cannot validate on the same dataset used for training')
      return
    }

    setValidationError(null)
    try {
      const response = await fetch(`${API_BASE}/results/external-validation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_id: selectedModelId,
          data_task_id: dataTaskId,
        })
      })

      if (response.ok) {
        const result = await response.json()
        // Task submitted successfully - show pending status
        // Progress will be tracked via SSE in the Background Task Panel
        setValidationProgress({
          validation_id: result.task_id,  // API now returns task_id instead of validation_id
          status: 'pending',
          progress: 0,
          total_wsi: result.total_wsi,
          processed_wsi: 0,
          model_id: selectedModelId,
          model_task_id: selectedModel.task_id,
          data_task_id: dataTaskId,
          error: null,
        })
        // Start polling to track this specific task's progress
        startPolling(result.task_id)
      } else {
        const error = await response.json()
        setValidationError(error.detail || 'Failed to start validation')
      }
    } catch (error) {
      console.error('Failed to start external validation:', error)
      setValidationError('Failed to connect to the server. Please try again.')
    }
  }

  const startPolling = (taskId: string) => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/results/external-validation/${taskId}`)
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
            data_task_id: progress.data_task_id,
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
  const dataTask = tasks.find(t => t.task_id === dataTaskId)

  const runAnalysis = async () => {
    if (!selectedTaskId || selectedMetrics.length === 0) return

    setRunning(true)
    setAnalysisError(null)
    try {
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metrics: selectedMetrics,
          charts: selectedCharts,
          description: description || null
        })
      })

      if (response.ok) {
        const result = await response.json()
        setCurrentResult(result)
        setExpandedAnalysis(result.analysis_id)
        // Reload analyses list
        await loadAnalyses(selectedTaskId)
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
      const response = await fetch(`${API_BASE}/results/tasks/${selectedTaskId}/analysis/${deleteConfirmId}`, {
        method: 'DELETE'
      })

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
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Button>
      </PageHeader>

      {/* Mode Tabs */}
      <div className="flex gap-2 mb-6">
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
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
                      const isSurvival = trainTask?.model_type === 'survival' || model.aggregator === 'survival'
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
                    <span className={dataTask ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {dataTask ? dataTask.name : (selectedModelId ? 'Select dataset...' : 'Select model first')}
                    </span>
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isDataDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isDataDropdownOpen && selectedModel && (
                  <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-64 overflow-y-auto">
                    {tasks.filter(t => t.task_id !== selectedModel.task_id).map(task => (
                      <button
                        key={task.task_id}
                        onClick={() => { setDataTaskId(task.task_id); setIsDataDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                          dataTaskId === task.task_id ? 'bg-gray-100' : ''
                        }`}
                      >
                        <div>
                          <div className="font-medium text-gray-900">{task.name}</div>
                          <div className="text-xs text-gray-500">{task.ai_results_count} slides</div>
                        </div>
                        {dataTaskId === task.task_id && <CheckCircle2 className="w-4 h-4 text-gray-600" />}
                      </button>
                    ))}
                    {tasks.filter(t => t.task_id !== selectedModel.task_id).length === 0 && (
                      <div className="px-4 py-8 text-center text-gray-500">No other datasets available</div>
                    )}
                  </div>
                )}
              </div>
            </Card>

            {/* Run Validation Button */}
            <Button
              onClick={startExternalValidation}
              disabled={!selectedModelId || !dataTaskId || (selectedModel?.task_id === dataTaskId) || (validationProgress?.status === 'running')}
              className="w-full bg-gray-800 hover:bg-gray-900 text-white py-3 gap-2"
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
                <Card className="p-6">
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
                          {modelTask && isSurvivalTask(modelTask.model_type) && (
                            <span className="ml-2 text-xs font-normal text-emerald-600">(Survival)</span>
                          )}
                        </h3>
                        <div className="space-y-3">
                          {(isSurvivalTask(modelTask?.model_type) ? SURVIVAL_METRICS : CLASSIFICATION_METRICS).map(metric => (
                            <label key={metric.id} className="flex items-start gap-3 cursor-pointer group">
                              <input
                                type="checkbox"
                                checked={selectedMetrics.includes(metric.id)}
                                onChange={() => toggleMetric(metric.id)}
                                className="mt-1 w-4 h-4 text-orange-600 border-gray-300 rounded focus:ring-orange-500"
                              />
                              <div>
                                <span className="text-sm font-medium text-gray-900 group-hover:text-orange-600">
                                  {metric.label}
                                </span>
                                <p className="text-xs text-gray-500">{metric.description}</p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </Card>

                      {/* Charts Selection */}
                      <Card className="p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">
                          Charts
                          {modelTask && isSurvivalTask(modelTask.model_type) && (
                            <span className="ml-2 text-xs font-normal text-emerald-600">(Survival)</span>
                          )}
                        </h3>
                        <div className="space-y-3">
                          {(isSurvivalTask(modelTask?.model_type) ? EXTERNAL_VALIDATION_SURVIVAL_CHARTS : EXTERNAL_VALIDATION_CLASSIFICATION_CHARTS).map(chart => (
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
                          const response = await fetch(`${API_BASE}/results/tasks/${taskIdToAnalyze}/analysis`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              metrics: selectedMetrics,
                              charts: selectedCharts,
                              description: description || null
                            })
                          })
                          if (response.ok) {
                            const result = await response.json()
                            setCurrentResult(result)
                            setExpandedAnalysis(result.analysis_id)
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
                          Running Analysis...
                        </>
                      ) : (
                        <>
                          <BarChart3 className="w-5 h-5" />
                          Run Analysis on Validation Results
                        </>
                      )}
                    </Button>

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

                    {/* Show current result if available */}
                    {currentResult && (
                      <Card className="p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">External Validation Results</h3>

                        {/* Metrics Grid */}
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
                          {Object.entries(currentResult.summary?.metrics || currentResult.metrics || {})
                            .filter(([key]) => !key.includes('recall'))
                            .map(([key, value]) => (
                            <div key={key} className="bg-gray-50 p-3 rounded-lg border border-gray-200">
                              <p className="text-xs text-gray-500 uppercase">{key.replace('macro_', '')}</p>
                              <p className="text-lg font-bold text-gray-800">
                                {typeof value === 'number' ? (value * 100).toFixed(1) + '%' : String(value)}
                              </p>
                            </div>
                          ))}
                        </div>

                        {/* Charts - Use ECharts if chart_data available, fallback to static images */}
                        {(currentResult.summary?.chart_data || currentResult.chart_paths) && (
                          <div className="space-y-6">
                            <h4 className="text-base font-semibold text-gray-800">Charts</h4>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                              {/* Confusion Matrix */}
                              {currentResult.summary?.chart_data?.confusion_matrix ? (
                                <ConfusionMatrixChart data={currentResult.summary.chart_data.confusion_matrix} title="Confusion Matrix" />
                              ) : currentResult.chart_paths?.confusion_matrix && (
                                <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                  <div className="p-2 bg-gray-50 border-b border-gray-200">
                                    <span className="text-sm font-medium text-gray-700">Confusion Matrix</span>
                                  </div>
                                  <img
                                    src={`${API_BASE}/results/tasks/${currentResult.task_id}/analysis/${currentResult.analysis_id}/file/confusion_matrix.png`}
                                    alt="Confusion Matrix"
                                    className="w-full"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                  />
                                </div>
                              )}

                              {/* ROC Curve */}
                              {currentResult.summary?.chart_data?.roc_curve ? (
                                <RocCurveChart data={currentResult.summary.chart_data.roc_curve} title="ROC Curve" />
                              ) : currentResult.chart_paths?.roc_curve && (
                                <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                  <div className="p-2 bg-gray-50 border-b border-gray-200">
                                    <span className="text-sm font-medium text-gray-700">ROC Curve</span>
                                  </div>
                                  <img
                                    src={`${API_BASE}/results/tasks/${currentResult.task_id}/analysis/${currentResult.analysis_id}/file/roc_curve.png`}
                                    alt="ROC Curve"
                                    className="w-full"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                  />
                                </div>
                              )}

                              {/* KM Curve - for survival validation */}
                              {currentResult.summary?.chart_data?.km_curve ? (
                                <KMCurveChart data={currentResult.summary.chart_data.km_curve} title="Kaplan-Meier Survival Curve" />
                              ) : currentResult.chart_paths?.km_curve && (
                                <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                  <div className="p-2 bg-gray-50 border-b border-gray-200">
                                    <span className="text-sm font-medium text-gray-700">KM Curve</span>
                                  </div>
                                  <img
                                    src={`${API_BASE}/results/tasks/${currentResult.task_id}/analysis/${currentResult.analysis_id}/file/km_curve.png`}
                                    alt="KM Curve"
                                    className="w-full"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        )}
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
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-stretch">
          {/* Left Panel - Configuration */}
          <div className="lg:col-span-1 flex flex-col">
            <div className="space-y-6 flex-1">
              {/* Task Selection */}
              <Card className="p-6 overflow-visible">
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
                          {selectedTask.model_type}
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
                                    {task.model_type}
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
            <Card className="p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Metrics
                {selectedTask && isSurvivalTask(selectedTask.model_type) && (
                  <span className="ml-2 text-xs font-normal text-emerald-600">(Survival)</span>
                )}
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.model_type) ? SURVIVAL_METRICS : CLASSIFICATION_METRICS).map(metric => (
                  <label key={metric.id} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedMetrics.includes(metric.id)}
                      onChange={() => toggleMetric(metric.id)}
                      className="mt-1 w-4 h-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900 group-hover:text-indigo-600">
                        {metric.label}
                      </span>
                      <p className="text-xs text-gray-500">{metric.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </Card>

            {/* Charts Selection */}
            <Card className="p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">
                Charts
                {selectedTask && isSurvivalTask(selectedTask.model_type) && (
                  <span className="ml-2 text-xs font-normal text-emerald-600">(Survival)</span>
                )}
              </h3>
              <div className="space-y-3">
                {(isSurvivalTask(selectedTask?.model_type) ? SURVIVAL_CHARTS : CLASSIFICATION_CHARTS).map(chart => (
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
            <Card className="p-6">
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
              {/* Status Alert - Show when no AI results */}
              {selectedTask && !selectedTask.has_ai_results && (
                <Card className="p-4 bg-amber-50 border-amber-200">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-amber-800">No AI Results Available</h4>
                      <p className="text-sm text-amber-600 mt-1">
                        This task has features and model but no AI results. Click "Regenerate AI Results" to run inference and generate results.
                      </p>
                    </div>
                  </div>
                </Card>
              )}

              {/* Run Button - Show Regenerate if no AI results, otherwise Run Analysis */}
              {selectedTask && !selectedTask.has_ai_results ? (
                <Button
                  onClick={regenerateResults}
                  disabled={regenerating || !selectedTaskId}
                  className="w-full bg-orange-600 hover:bg-orange-700 text-white py-4 gap-2 text-base font-bold shadow-lg shadow-orange-500/20 rounded-xl"
                >
                  {regenerating ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Regenerating Results...
                    </>
                  ) : (
                    <>
                      <Play className="w-5 h-5" />
                      Regenerate AI Results
                    </>
                  )}
                </Button>
              ) : (
                <Button
                  onClick={runAnalysis}
                  disabled={running || !selectedTaskId || selectedMetrics.length === 0}
                  className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-4 gap-2 text-base font-bold shadow-lg shadow-indigo-500/20 rounded-xl"
                >
                  {running ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Running Analysis...
                    </>
                  ) : (
                    <>
                      <Play className="w-5 h-5" />
                      Run Analysis
                    </>
                  )}
                </Button>
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
                            <AnalysisDetails analysis={analysis} taskId={selectedTaskId!} />
                          </div>
                        )}
                      </Card>
                    ))
                  )}
                </div>
              ) : (
                /* Latest Result */
                currentResult ? (
                  <Card className="h-full flex flex-col p-6 overflow-hidden">
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
                      <AnalysisDetails analysis={currentResult.summary} taskId={selectedTaskId!} />
                    </div>
                  </Card>
                ) : analyses.length > 0 ? (
                  <Card className="h-full flex flex-col p-6 overflow-hidden">
                    <div className="flex-none flex items-center justify-between mb-6">
                      <div>
                        <h4 className="font-semibold text-gray-900">Latest Analysis</h4>
                        <p className="text-sm text-gray-500">
                          {formatDate(analyses[0].timestamp)}
                        </p>
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                      <AnalysisDetails analysis={analyses[0]} taskId={selectedTaskId!} />
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

function AnalysisDetails({ analysis, taskId }: { analysis: AnalysisSummary; taskId: string }) {
  const isSurvival = analysis.task_type === 'survival_prediction' || analysis.task_type === 'wsi_survival'

  // Helper for direct file download
  const handleDownload = async (e: React.MouseEvent, url: string, filename: string) => {
    e.preventDefault()
    try {
      const response = await fetch(url)
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
    // C-Index is shown as decimal (0.xxx format)
    if (key === 'c_index') {
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
          <div className="mb-4">
            <p className="text-xs text-purple-600 font-medium mb-2">Aggregated Statistics (mean ± std)</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(analysis.kfold_training.aggregated).map(([key, stats]) => (
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

          {/* Per-Fold Results */}
          <details className="group">
            <summary className="text-xs text-purple-600 font-medium cursor-pointer hover:text-purple-800">
              Show per-fold details
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-purple-200">
                    <th className="py-2 text-left text-gray-500">Fold</th>
                    {Object.keys(analysis.kfold_training.aggregated).map(key => (
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
                      {Object.keys(analysis.kfold_training!.aggregated).map(key => {
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
        </div>
      )}

      {/* Metrics Grid */}
      <div className="pt-4">
        <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
          <div className="w-1.5 h-6 bg-indigo-600 rounded-full" />
          Metrics
          {isSurvival && <span className="ml-2 text-sm font-normal text-emerald-600">(Survival Analysis)</span>}
        </h5>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
          {Object.entries(analysis.metrics)
            .filter(([key]) => !key.includes('recall'))
            .map(([key, value]) => (
            <div key={key} className={`p-6 rounded-2xl border-2 transition-all hover:shadow-md ${isSurvival ? 'bg-emerald-50/50 border-emerald-100 hover:border-emerald-200' : 'bg-white border-gray-100 hover:border-indigo-100'}`}>
              <p className="text-xs text-gray-400 uppercase font-bold tracking-wider mb-2">{getMetricDisplayName(key)}</p>
              <p className={`text-3xl font-black ${isSurvival ? 'text-emerald-600' : 'text-indigo-600'}`}>
                {formatMetricValue(key, value)}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-Class Metrics - Only for classification tasks */}
      {!isSurvival && analysis.class_metrics && Object.keys(analysis.class_metrics).length > 0 && (
        <div className="pt-8">
          <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
            <div className="w-1.5 h-6 bg-indigo-600 rounded-full" />
            Per-Class Performance
          </h5>
          <div className="overflow-hidden rounded-2xl border border-gray-100 shadow-sm bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50/50 border-b border-gray-100">
                  <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Class</th>
                  <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Precision</th>
                  <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Sensitivity</th>
                  <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">F1 Score</th>
                  <th className="px-6 py-4 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Support</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {Object.entries(analysis.class_metrics).map(([cls, metrics]) => (
                  <tr key={cls} className="hover:bg-indigo-50/30 transition-colors">
                    <td className="px-6 py-4 font-bold text-gray-900">{cls}</td>
                    <td className="px-6 py-4 text-center font-medium text-indigo-600">{((metrics.precision || 0) * 100).toFixed(1)}%</td>
                    <td className="px-6 py-4 text-center font-medium text-indigo-600">{((metrics.sensitivity || metrics.recall || 0) * 100).toFixed(1)}%</td>
                    <td className="px-6 py-4 text-center font-medium text-indigo-600">{((metrics.f1 || 0) * 100).toFixed(1)}%</td>
                    <td className="px-6 py-4 text-center text-gray-500 font-mono">{metrics.support || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Charts - Use ECharts if chart_data available, fallback to static images */}
      {(analysis.chart_data || analysis.chart_paths) && (
        <div className="pt-8 mb-8">
          <h5 className="text-xl font-bold text-gray-900 mb-6 flex items-center gap-2">
            <div className="w-1.5 h-6 bg-indigo-600 rounded-full" />
            Analysis Charts
          </h5>
          <div className={`grid grid-cols-1 ${isSurvival ? 'md:grid-cols-2 lg:max-w-4xl' : 'md:grid-cols-2 xl:grid-cols-3'} gap-6`}>
            {/* Confusion Matrix */}
            {analysis.chart_data?.confusion_matrix ? (
              <ConfusionMatrixChart data={analysis.chart_data.confusion_matrix} title="Confusion Matrix" />
            ) : analysis.chart_paths?.confusion_matrix && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Confusion Matrix</span>
                  <button 
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`, 'confusion_matrix.png')} 
                    className="text-indigo-600 hover:text-indigo-800"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`} alt="Confusion Matrix" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* ROC Curve */}
            {analysis.chart_data?.roc_curve ? (
              <RocCurveChart data={analysis.chart_data.roc_curve} title="ROC Curve" />
            ) : analysis.chart_paths?.roc_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">ROC Curve</span>
                  <button 
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`, 'roc_curve.png')} 
                    className="text-indigo-600 hover:text-indigo-800"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`} alt="ROC Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* Loss Curve */}
            {analysis.chart_data?.loss_curve ? (
              <LossCurveChart data={analysis.chart_data.loss_curve} title="Training Loss Curve" />
            ) : analysis.chart_paths?.loss_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Loss Curve</span>
                  <button 
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`, 'loss_curve.png')} 
                    className="text-indigo-600 hover:text-indigo-800"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`} alt="Loss Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* KM Curve - Survival Analysis */}
            {analysis.chart_data?.km_curve ? (
              <KMCurveChart data={analysis.chart_data.km_curve} title="Kaplan-Meier Survival Curve" />
            ) : analysis.chart_paths?.km_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">KM Curve</span>
                  <button 
                    onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/km_curve.png`, 'km_curve.png')} 
                    className="text-emerald-600 hover:text-emerald-800"
                  >
                    <Download className="w-4 h-4" />
                  </button>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/km_curve.png`} alt="KM Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}
          </div>
        </div>
      )}
      </div>

      {/* Download All */}
      <div className="flex flex-col sm:flex-row gap-4 pt-4 border-t border-gray-100">
        <button
          onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/summary.json`, `analysis_summary_${analysis.analysis_id}.json`)}
          className="flex-1 flex items-center justify-center gap-3 px-6 py-4 bg-white hover:bg-indigo-50 text-indigo-700 rounded-xl text-sm font-bold border border-indigo-100 shadow-sm transition-all hover:border-indigo-200 active:scale-[0.98]"
        >
          <div className="p-2 bg-indigo-50 rounded-lg group-hover:bg-white transition-colors">
            <Download className="w-5 h-5" />
          </div>
          <div className="text-left">
            <div className="text-[10px] uppercase tracking-wider opacity-60">Metadata</div>
            Download Summary (JSON)
          </div>
        </button>
        <button
          onClick={(e) => handleDownload(e, `${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/results.json`, `full_results_${analysis.analysis_id}.json`)}
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
