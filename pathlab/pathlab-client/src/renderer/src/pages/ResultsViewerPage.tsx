import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart3, Play, History, Download, ChevronDown, ChevronUp, Loader2, CheckCircle2, Trash2, AlertCircle, X, FlaskConical, ArrowLeft } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KMCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KMCurveData } from '../components/charts/AnalysisCharts'

type PageMode = 'analysis' | 'external-validation'

interface ValidationProgress {
  validation_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  total_wsi: number
  processed_wsi: number
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
  { id: 'recall', label: 'Recall/Sensitivity', description: 'True positive rate' },
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
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(['accuracy', 'precision', 'recall', 'f1', 'auc','specificity'])
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
  const [pageMode, setPageMode] = useState<PageMode>('analysis')
  const [modelTaskId, setModelTaskId] = useState<string | null>(null)
  const [dataTaskId, setDataTaskId] = useState<string | null>(null)
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false)
  const [isDataDropdownOpen, setIsDataDropdownOpen] = useState(false)
  const [validationProgress, setValidationProgress] = useState<ValidationProgress | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    loadTasks()
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
        setSelectedMetrics(['accuracy', 'precision', 'recall', 'f1', 'auc', 'specificity'])
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
    if (!modelTaskId || !dataTaskId) return
    if (modelTaskId === dataTaskId) {
      setValidationError('Model task and data task must be different')
      return
    }

    setValidationError(null)
    try {
      const response = await fetch(`${API_BASE}/results/external-validation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_task_id: modelTaskId,
          data_task_id: dataTaskId,
        })
      })

      if (response.ok) {
        const result = await response.json()
        // Start polling for progress
        setValidationProgress({
          validation_id: result.validation_id,
          status: 'pending',
          progress: 0,
          total_wsi: result.total_wsi,
          processed_wsi: 0,
          model_task_id: modelTaskId,
          data_task_id: dataTaskId,
          error: null,
        })
        startPolling(result.validation_id)
      } else {
        const error = await response.json()
        setValidationError(error.detail || 'Failed to start validation')
      }
    } catch (error) {
      console.error('Failed to start external validation:', error)
      setValidationError('Failed to connect to the server. Please try again.')
    }
  }

  const startPolling = (validationId: string) => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
    }

    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/results/external-validation/${validationId}`)
        if (response.ok) {
          const progress = await response.json()
          setValidationProgress(progress)

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
    pollingRef.current = setInterval(poll, 1000)
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [])

  const modelTask = tasks.find(t => t.task_id === modelTaskId)
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
    <div className="max-w-6xl mx-auto">
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
          onClick={() => setPageMode('analysis')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all ${
            pageMode === 'analysis'
              ? 'bg-indigo-600 text-white shadow-md'
              : 'bg-white text-gray-600 hover:bg-gray-50 border border-gray-200'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          Analysis
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
            {/* Model Task Selection */}
            <Card className="p-6 overflow-visible">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Model Source</h3>
                <Badge variant="secondary" className="bg-indigo-50 text-indigo-700">Step 1</Badge>
              </div>
              <p className="text-sm text-gray-500 mb-4">Select the task whose trained model will be used for inference.</p>

              <div className="relative">
                <button
                  onClick={() => { setIsModelDropdownOpen(!isModelDropdownOpen); setIsDataDropdownOpen(false); }}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    isModelDropdownOpen ? 'border-indigo-500 ring-4 ring-indigo-500/10' : 'border-gray-200 hover:border-indigo-300'
                  }`}
                >
                  <span className={modelTask ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                    {modelTask ? modelTask.name : 'Select model task...'}
                  </span>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isModelDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isModelDropdownOpen && (
                  <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-64 overflow-y-auto">
                    {tasks.filter(t => t.has_model).map(task => (
                      <button
                        key={task.task_id}
                        onClick={() => { setModelTaskId(task.task_id); setIsModelDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                          modelTaskId === task.task_id ? 'bg-indigo-50' : ''
                        }`}
                      >
                        <div>
                          <div className="font-medium text-gray-900">{task.name}</div>
                          <div className="text-xs text-gray-500">{task.feature_extractor} • {task.ai_results_count} results</div>
                        </div>
                        {modelTaskId === task.task_id && <CheckCircle2 className="w-4 h-4 text-indigo-600" />}
                      </button>
                    ))}
                    {tasks.filter(t => t.has_model).length === 0 && (
                      <div className="px-4 py-8 text-center text-gray-500">No tasks with models available</div>
                    )}
                  </div>
                )}
              </div>
            </Card>

            {/* Data Task Selection */}
            <Card className="p-6 overflow-visible">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Feature Source</h3>
                <Badge variant="secondary" className="bg-orange-50 text-orange-700">Step 2</Badge>
              </div>
              <p className="text-sm text-gray-500 mb-4">
                Select the task whose <strong>pre-extracted features</strong> will be used for validation.
                Features must use the same extractor as the model.
              </p>

              {modelTask && (
                <div className="mb-4 p-3 bg-indigo-50 rounded-lg text-sm">
                  <span className="text-indigo-700">Model uses: </span>
                  <Badge variant="secondary" className="bg-indigo-100 text-indigo-800 font-mono">
                    {modelTask.feature_extractor || 'unknown'}
                  </Badge>
                </div>
              )}

              <div className="relative">
                <button
                  onClick={() => { setIsDataDropdownOpen(!isDataDropdownOpen); setIsModelDropdownOpen(false); }}
                  disabled={!modelTaskId}
                  className={`w-full flex items-center justify-between px-4 py-3 bg-white border rounded-xl shadow-sm transition-all duration-200 ${
                    !modelTaskId ? 'opacity-50 cursor-not-allowed' :
                    isDataDropdownOpen ? 'border-orange-500 ring-4 ring-orange-500/10' : 'border-gray-200 hover:border-orange-300'
                  }`}
                >
                  <div className="flex flex-col items-start">
                    <span className={dataTask ? 'text-gray-900 font-medium' : 'text-gray-400'}>
                      {dataTask ? dataTask.name : (modelTaskId ? 'Select feature source...' : 'Select model first')}
                    </span>
                    {dataTask && (
                      <span className="text-xs text-gray-500">{dataTask.feature_extractor}</span>
                    )}
                  </div>
                  <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${isDataDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isDataDropdownOpen && modelTask && (
                  <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-xl max-h-64 overflow-y-auto">
                    {/* Matching extractor tasks first */}
                    {tasks.filter(t => t.has_features && t.task_id !== modelTaskId && t.feature_extractor === modelTask.feature_extractor).length > 0 && (
                      <div className="px-4 py-2 text-xs font-semibold text-green-700 bg-green-50 border-b">
                        ✓ Compatible (same feature extractor)
                      </div>
                    )}
                    {tasks.filter(t => t.has_features && t.task_id !== modelTaskId && t.feature_extractor === modelTask.feature_extractor).map(task => (
                      <button
                        key={task.task_id}
                        onClick={() => { setDataTaskId(task.task_id); setIsDataDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                          dataTaskId === task.task_id ? 'bg-orange-50' : ''
                        }`}
                      >
                        <div>
                          <div className="font-medium text-gray-900">{task.name}</div>
                          <div className="text-xs text-green-600 font-mono">{task.feature_extractor}</div>
                        </div>
                        {dataTaskId === task.task_id && <CheckCircle2 className="w-4 h-4 text-orange-600" />}
                      </button>
                    ))}

                    {/* Non-matching extractor tasks */}
                    {tasks.filter(t => t.has_features && t.task_id !== modelTaskId && t.feature_extractor !== modelTask.feature_extractor).length > 0 && (
                      <div className="px-4 py-2 text-xs font-semibold text-amber-700 bg-amber-50 border-b border-t">
                        ⚠ Different feature extractor (may not work)
                      </div>
                    )}
                    {tasks.filter(t => t.has_features && t.task_id !== modelTaskId && t.feature_extractor !== modelTask.feature_extractor).map(task => (
                      <button
                        key={task.task_id}
                        onClick={() => { setDataTaskId(task.task_id); setIsDataDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between opacity-60 ${
                          dataTaskId === task.task_id ? 'bg-orange-50' : ''
                        }`}
                      >
                        <div>
                          <div className="font-medium text-gray-900">{task.name}</div>
                          <div className="text-xs text-amber-600 font-mono">{task.feature_extractor}</div>
                        </div>
                        {dataTaskId === task.task_id && <CheckCircle2 className="w-4 h-4 text-orange-600" />}
                      </button>
                    ))}

                    {tasks.filter(t => t.has_features && t.task_id !== modelTaskId).length === 0 && (
                      <div className="px-4 py-8 text-center text-gray-500">No other tasks with features available</div>
                    )}
                  </div>
                )}
              </div>

              {/* Warning for mismatched extractors */}
              {dataTask && modelTask && dataTask.feature_extractor !== modelTask.feature_extractor && (
                <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-amber-700">
                      <strong>Feature extractor mismatch:</strong> Model uses <code className="bg-amber-100 px-1 rounded">{modelTask.feature_extractor}</code> but
                      data uses <code className="bg-amber-100 px-1 rounded">{dataTask.feature_extractor}</code>.
                      This may cause errors or incorrect results.
                    </div>
                  </div>
                </div>
              )}
            </Card>

            {/* Run Validation Button */}
            <Button
              onClick={startExternalValidation}
              disabled={!modelTaskId || !dataTaskId || modelTaskId === dataTaskId || (validationProgress?.status === 'running')}
              className="w-full bg-orange-600 hover:bg-orange-700 text-white py-3 gap-2"
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
                          {(isSurvivalTask(modelTask?.model_type) ? SURVIVAL_CHARTS : CLASSIFICATION_CHARTS).map(chart => (
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
                      onClick={() => {
                        // Use model task for analysis (results are saved under model task)
                        setSelectedTaskId(modelTaskId)
                        runAnalysis()
                      }}
                      disabled={running || selectedMetrics.length === 0}
                      className="w-full bg-orange-600 hover:bg-orange-700 text-white py-3 gap-2"
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
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">Analysis Results</h3>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
                          {Object.entries(currentResult.metrics).map(([key, value]) => (
                            <div key={key} className="bg-orange-50 p-3 rounded-lg border border-orange-100">
                              <p className="text-xs text-gray-500 uppercase">{key.replace('macro_', '')}</p>
                              <p className="text-lg font-bold text-orange-600">
                                {typeof value === 'number' ? (value * 100).toFixed(1) + '%' : String(value)}
                              </p>
                            </div>
                          ))}
                        </div>

                        {/* Charts */}
                        <div className="space-y-6">
                          {currentResult.charts?.confusion_matrix && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-700 mb-2">Confusion Matrix</h4>
                              <ConfusionMatrixChart data={currentResult.charts.confusion_matrix} title="Confusion Matrix" />
                            </div>
                          )}
                          {currentResult.charts?.roc_curve && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-700 mb-2">ROC Curve</h4>
                              <RocCurveChart data={currentResult.charts.roc_curve} title="ROC Curve" />
                            </div>
                          )}
                          {currentResult.charts?.loss_curve && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-700 mb-2">Loss Curve</h4>
                              <LossCurveChart data={currentResult.charts.loss_curve} title="Loss Curve" />
                            </div>
                          )}
                        </div>
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
        /* Analysis Mode */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Panel - Configuration */}
          <div className="lg:col-span-1 space-y-6">
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
                className="w-full bg-orange-600 hover:bg-orange-700 text-white py-3 gap-2"
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
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 gap-2"
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

          {/* Right Panel - Results */}
          <div className="lg:col-span-2 space-y-6">
            {/* History Toggle */}
            <div className="flex items-center justify-between">
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
                <Card className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h4 className="font-semibold text-gray-900">Analysis Complete</h4>
                      <p className="text-sm text-gray-500">
                        {formatDate(currentResult.summary.timestamp)}
                      </p>
                    </div>
                    <CheckCircle2 className="w-6 h-6 text-green-500" />
                  </div>
                  <AnalysisDetails analysis={currentResult.summary} taskId={selectedTaskId!} />
                </Card>
              ) : analyses.length > 0 ? (
                <Card className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h4 className="font-semibold text-gray-900">Latest Analysis</h4>
                      <p className="text-sm text-gray-500">
                        {formatDate(analyses[0].timestamp)}
                      </p>
                    </div>
                  </div>
                  <AnalysisDetails analysis={analyses[0]} taskId={selectedTaskId!} />
                </Card>
              ) : (
                <Card className="p-12 text-center">
                  <BarChart3 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-gray-900 mb-2">No Analysis Yet</h3>
                  <p className="text-gray-500">Configure metrics and charts, then run analysis.</p>
                </Card>
              )
            )}
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
    <div className="space-y-6">
      {/* Metrics Grid */}
      <div>
        <h5 className="text-sm font-semibold text-gray-700 mb-3">
          Metrics
          {isSurvival && <span className="ml-2 text-xs font-normal text-emerald-600">(Survival)</span>}
        </h5>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {Object.entries(analysis.metrics).map(([key, value]) => (
            <div key={key} className={`p-3 rounded-lg border ${isSurvival ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-gray-200'}`}>
              <p className="text-xs text-gray-500 uppercase">{getMetricDisplayName(key)}</p>
              <p className={`text-lg font-bold ${isSurvival ? 'text-emerald-600' : 'text-indigo-600'}`}>
                {formatMetricValue(key, value)}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-Class Metrics - Only for classification tasks */}
      {!isSurvival && analysis.class_metrics && Object.keys(analysis.class_metrics).length > 0 && (
        <div>
          <h5 className="text-sm font-semibold text-gray-700 mb-3">Per-Class Metrics</h5>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="py-2 text-left text-gray-500">Class</th>
                  <th className="py-2 text-center text-gray-500">Precision</th>
                  <th className="py-2 text-center text-gray-500">Recall</th>
                  <th className="py-2 text-center text-gray-500">F1</th>
                  <th className="py-2 text-center text-gray-500">Support</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(analysis.class_metrics).map(([cls, metrics]) => (
                  <tr key={cls} className="border-b border-gray-100">
                    <td className="py-2 font-medium">{cls}</td>
                    <td className="py-2 text-center">{((metrics.precision || 0) * 100).toFixed(1)}%</td>
                    <td className="py-2 text-center">{((metrics.recall || 0) * 100).toFixed(1)}%</td>
                    <td className="py-2 text-center">{((metrics.f1 || 0) * 100).toFixed(1)}%</td>
                    <td className="py-2 text-center">{metrics.support || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Charts - Use ECharts if chart_data available, fallback to static images */}
      {(analysis.chart_data || analysis.chart_paths) && (
        <div>
          <h5 className="text-sm font-semibold text-gray-700 mb-3">Charts</h5>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Confusion Matrix */}
            {analysis.chart_data?.confusion_matrix ? (
              <ConfusionMatrixChart data={analysis.chart_data.confusion_matrix} title="Confusion Matrix" />
            ) : analysis.chart_paths?.confusion_matrix && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Confusion Matrix</span>
                  <a href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`} download className="text-indigo-600 hover:text-indigo-800"><Download className="w-4 h-4" /></a>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/confusion_matrix.png`} alt="Confusion Matrix" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* ROC Curve */}
            {analysis.chart_data?.roc_curve ? (
              <RocCurveChart data={analysis.chart_data.roc_curve} title="ROC Curve" />
            ) : analysis.chart_paths?.roc_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">ROC Curve</span>
                  <a href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`} download className="text-indigo-600 hover:text-indigo-800"><Download className="w-4 h-4" /></a>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/roc_curve.png`} alt="ROC Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* Loss Curve */}
            {analysis.chart_data?.loss_curve ? (
              <LossCurveChart data={analysis.chart_data.loss_curve} title="Training Loss Curve" />
            ) : analysis.chart_paths?.loss_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">Loss Curve</span>
                  <a href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`} download className="text-indigo-600 hover:text-indigo-800"><Download className="w-4 h-4" /></a>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/loss_curve.png`} alt="Loss Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}

            {/* KM Curve - Survival Analysis */}
            {analysis.chart_data?.km_curve ? (
              <KMCurveChart data={analysis.chart_data.km_curve} title="Kaplan-Meier Survival Curve" />
            ) : analysis.chart_paths?.km_curve && (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">KM Curve</span>
                  <a href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/km_curve.png`} download className="text-emerald-600 hover:text-emerald-800"><Download className="w-4 h-4" /></a>
                </div>
                <img src={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/km_curve.png`} alt="KM Curve" className="w-full" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Download All */}
      <div className="flex gap-3">
        <a
          href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/summary.json`}
          download
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium text-gray-700"
        >
          <Download className="w-4 h-4" />
          Download Summary
        </a>
        <a
          href={`${API_BASE}/results/tasks/${taskId}/analysis/${analysis.analysis_id}/file/results.json`}
          download
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium text-gray-700"
        >
          <Download className="w-4 h-4" />
          Download Full Results
        </a>
      </div>
    </div>
  )
}
