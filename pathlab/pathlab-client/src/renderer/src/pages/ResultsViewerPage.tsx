import { useState, useEffect } from 'react'
import { BarChart3, Play, History, Download, ChevronDown, ChevronUp, Loader2, CheckCircle2, Trash2 } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData } from '../components/charts/AnalysisCharts'

interface TrainingTask {
  task_id: string
  name: string
  model_type: string
  status: string
  created_at: string | null
  has_analysis: boolean
}

interface ChartData {
  confusion_matrix?: ConfusionMatrixData
  roc_curve?: RocCurveData
  loss_curve?: LossCurveData
}

interface AnalysisSummary {
  analysis_id: string
  task_id: string
  timestamp: string
  description: string | null
  num_samples: number
  classes: string[]
  is_binary: boolean
  requested_metrics: string[]
  requested_charts: string[]
  metrics: Record<string, number>
  class_metrics: Record<string, Record<string, number>>
  chart_paths?: Record<string, string>
  chart_data?: ChartData
}

interface AnalysisResult {
  task_id: string
  analysis_id: string
  analysis_dir: string
  summary: AnalysisSummary
  chart_paths: Record<string, string>
}

const AVAILABLE_METRICS = [
  { id: 'accuracy', label: 'Accuracy', description: 'Overall prediction accuracy' },
  { id: 'precision', label: 'Precision', description: 'Positive predictive value' },
  { id: 'recall', label: 'Recall/Sensitivity', description: 'True positive rate' },
  { id: 'specificity', label: 'Specificity', description: 'True negative rate' },
  { id: 'f1', label: 'F1 Score', description: 'Harmonic mean of precision and recall' },
  { id: 'auc', label: 'AUC', description: 'Area under ROC curve' }
]

const AVAILABLE_CHARTS = [
  { id: 'confusion_matrix', label: 'Confusion Matrix', description: 'Prediction vs ground truth matrix' },
  { id: 'roc_curve', label: 'ROC Curve', description: 'Receiver operating characteristic curve' },
  { id: 'loss_curve', label: 'Loss Curve', description: 'Training loss over epochs' }
]

export default function ResultsViewerPage() {
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

  useEffect(() => {
    loadTasks()
  }, [])

  useEffect(() => {
    if (selectedTaskId) {
      loadAnalyses(selectedTaskId)
    }
  }, [selectedTaskId])

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

  const runAnalysis = async () => {
    if (!selectedTaskId || selectedMetrics.length === 0) return

    setRunning(true)
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
        alert(`Analysis failed: ${error.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to run analysis:', error)
      alert('Failed to run analysis')
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
    return new Date(dateStr).toLocaleString()
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
        alert(`Failed to delete analysis: ${error.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to delete analysis:', error)
      alert('Failed to delete analysis')
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
      />

      {tasks.length === 0 ? (
        <Card className="p-12 text-center">
          <BarChart3 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No Completed Tasks</h3>
          <p className="text-gray-500">Complete a training task to analyze its results.</p>
        </Card>
      ) : (
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
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-[10px] uppercase tracking-wider font-bold px-2">
                          {selectedTask.model_type}
                        </Badge>
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
                                <div className="flex items-center gap-2">
                                  <span className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full transition-colors duration-200 ${
                                    selectedTaskId === task.task_id 
                                      ? 'bg-white/20 text-white' 
                                      : 'bg-indigo-50 text-indigo-700'
                                  }`}>
                                    {task.model_type}
                                  </span>
                                  {task.created_at && (
                                    <span className={`text-xs transition-colors duration-200 ${
                                      selectedTaskId === task.task_id ? 'text-indigo-100' : 'text-gray-400'
                                    }`}>
                                      {new Date(task.created_at).toLocaleDateString()}
                                    </span>
                                  )}
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
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Metrics</h3>
              <div className="space-y-3">
                {AVAILABLE_METRICS.map(metric => (
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
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Charts</h3>
              <div className="space-y-3">
                {AVAILABLE_CHARTS.map(chart => (
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

            {/* Run Button */}
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
                            {analysis.num_samples} samples • {analysis.classes.length} classes
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
  return (
    <div className="space-y-6">
      {/* Metrics Grid */}
      <div>
        <h5 className="text-sm font-semibold text-gray-700 mb-3">Metrics</h5>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {Object.entries(analysis.metrics).map(([key, value]) => (
            <div key={key} className="bg-white p-3 rounded-lg border border-gray-200">
              <p className="text-xs text-gray-500 uppercase">{key.replace('macro_', '')}</p>
              <p className="text-lg font-bold text-indigo-600">
                {(value * 100).toFixed(1)}%
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Per-Class Metrics */}
      {analysis.class_metrics && Object.keys(analysis.class_metrics).length > 0 && (
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
