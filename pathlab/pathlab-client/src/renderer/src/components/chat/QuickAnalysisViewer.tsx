import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Loader2, BarChart3, TrendingUp, AlertCircle, RefreshCw, Activity, Target, Percent } from 'lucide-react'
import { getTaskQuickAnalysis, getTrainingTasks, getAnalysisStatus } from '../../api'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KMCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KMCurveData } from '../charts/AnalysisCharts'

export interface AgentQuickAnalysisConfig {
  task_id: string
  task_name?: string
  metrics?: string[]  // e.g., ['accuracy', 'auc', 'f1']
  charts?: string[]   // e.g., ['roc_curve', 'confusion_matrix']
  show_class_metrics?: boolean
  submitted?: boolean
}

interface QuickAnalysisViewerProps {
  config: AgentQuickAnalysisConfig
  onError?: (error: string) => void
}

// Icon and color mappings
const METRIC_ICONS: Record<string, React.ReactNode> = { accuracy: <Target className="w-4 h-4" />, auc: <TrendingUp className="w-4 h-4" />, f1: <Activity className="w-4 h-4" />, precision: <Percent className="w-4 h-4" />, recall: <Percent className="w-4 h-4" />, sensitivity: <Percent className="w-4 h-4" />, specificity: <Percent className="w-4 h-4" /> }
const METRIC_COLORS: Record<string, string> = { accuracy: 'text-blue-600 bg-blue-50 border-blue-200', auc: 'text-purple-600 bg-purple-50 border-purple-200', f1: 'text-green-600 bg-green-50 border-green-200', precision: 'text-amber-600 bg-amber-50 border-amber-200', recall: 'text-teal-600 bg-teal-50 border-teal-200', sensitivity: 'text-teal-600 bg-teal-50 border-teal-200', specificity: 'text-orange-600 bg-orange-50 border-orange-200' }

function formatMetricName(name: string): string { return name.replace('macro_', '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) }

/** Parse [QUICK_ANALYSIS_CONFIG] block from message */
export function parseQuickAnalysisConfig(content: string): AgentQuickAnalysisConfig | null {
  const match = content.match(/\[QUICK_ANALYSIS_CONFIG\]([\s\S]*?)\[\/QUICK_ANALYSIS_CONFIG\]/)
  if (!match) return null
  try { return JSON.parse(match[1].trim()) } catch { return null }
}

/** Remove [QUICK_ANALYSIS_CONFIG] block from content */
export function removeQuickAnalysisConfigBlock(content: string): string {
  return content.replace(/\[QUICK_ANALYSIS_CONFIG\][\s\S]*?\[\/QUICK_ANALYSIS_CONFIG\]/g, '').trim()
}

// Polling interval for checking analysis status (in ms)
const POLL_INTERVAL = 2000

export function QuickAnalysisViewer({ config, onError }: QuickAnalysisViewerProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [taskExists, setTaskExists] = useState(true)
  const [metrics, setMetrics] = useState<Record<string, number>>({})
  const [classMetrics, setClassMetrics] = useState<Record<string, Record<string, number>>>({})
  const [chartData, setChartData] = useState<{ confusion_matrix?: ConfusionMatrixData; roc_curve?: RocCurveData; loss_curve?: LossCurveData; km_curve?: KMCurveData }>({})
  const [numSamples, setNumSamples] = useState<number | undefined>()
  const [taskType, setTaskType] = useState<string>('classification')

  // Async analysis state
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<string>('')
  const [progress, setProgress] = useState(0)
  const [statusMessage, setStatusMessage] = useState('')
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  // Fetch completed analysis results
  const fetchResults = useCallback(async () => {
    try {
      const result = await getTaskQuickAnalysis(config.task_id, {
        metrics: config.metrics,
        charts: config.charts,
        runIfMissing: false  // Don't trigger new analysis, just fetch
      })
      if (result.has_analysis) {
        setMetrics(result.metrics || {})
        setClassMetrics(result.class_metrics || {})
        setChartData(result.chart_data || {})
        setNumSamples(result.num_samples)
        setTaskType(result.task_type || 'classification')
        setAnalysisStatus('completed')
        setIsLoading(false)
        return true
      }
    } catch (err) {
      console.error('Failed to fetch analysis results:', err)
    }
    return false
  }, [config.task_id, config.metrics, config.charts])

  // Poll analysis status
  const pollStatus = useCallback(async (aid: string) => {
    try {
      const status = await getAnalysisStatus(aid)
      setProgress(status.progress)
      setStatusMessage(status.message || '')
      setAnalysisStatus(status.status)

      if (status.status === 'completed') {
        // Stop polling and fetch results
        if (pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
        await fetchResults()
      } else if (status.status === 'failed') {
        // Stop polling and show error
        if (pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
        setError(status.error_message || 'Analysis failed')
        setIsLoading(false)
      }
    } catch (err) {
      console.error('Failed to poll analysis status:', err)
    }
  }, [fetchResults])

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true); setError(''); setAnalysisStatus('')
      try {
        const tasks = await getTrainingTasks()
        const found = tasks.some(t => t.task_id === config.task_id && t.status === 'completed')
        if (!found) { setTaskExists(false); setError('Task not found or not completed'); setIsLoading(false); return }
        setTaskExists(true)

        const result = await getTaskQuickAnalysis(config.task_id, { metrics: config.metrics, charts: config.charts, runIfMissing: true })

        // Check if analysis is async (pending/running)
        if (!result.has_analysis && result.status && ['pending', 'running'].includes(result.status)) {
          // Start polling
          const aid = result.analysis_id
          if (aid) {
            setAnalysisId(aid)
            setAnalysisStatus(result.status)
            setProgress(result.progress || 0)
            setStatusMessage(result.message || 'Analysis in progress...')

            // Start polling interval
            pollingRef.current = setInterval(() => pollStatus(aid), POLL_INTERVAL)
          }
          return
        }

        if (!result.has_analysis) { setError(result.message || 'No analysis results available'); setIsLoading(false); return }

        setMetrics(result.metrics || {})
        setClassMetrics(result.class_metrics || {})
        setChartData(result.chart_data || {})
        setNumSamples(result.num_samples)
        setTaskType(result.task_type || 'classification')
        setAnalysisStatus('completed')
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch analysis'
        setError(msg); onError?.(msg)
      } finally {
        // Only set loading to false if not polling
        if (!pollingRef.current) setIsLoading(false)
      }
    }
    fetchData()

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [config.task_id, config.metrics?.join(','), config.charts?.join(','), onError, pollStatus])

  const displayMetrics = useMemo(() => {
    if (!config.metrics) return Object.entries(metrics).map(([k, v]) => ({ key: k, value: v }))
    return config.metrics.map(m => ({ key: m, value: metrics[m] ?? metrics[`macro_${m}`] })).filter(x => x.value !== undefined)
  }, [metrics, config.metrics])

  const handleRefresh = () => { setIsLoading(true); setError(''); window.location.reload() }

  // Show loading state with progress for async analysis
  if (isLoading || (analysisStatus && ['pending', 'running'].includes(analysisStatus))) {
    const isPolling = ['pending', 'running'].includes(analysisStatus)
    return (
      <div className="mt-4 w-full min-w-[500px] bg-white border border-gray-200 rounded-2xl shadow-sm p-6">
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
            <span className="text-gray-600">
              {isPolling ? statusMessage || 'Running analysis...' : 'Loading analysis...'}
            </span>
          </div>
          {isPolling && (
            <div className="w-full max-w-xs">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>{analysisStatus === 'pending' ? 'Queued' : 'Processing'}</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  if (!taskExists || error) return (
    <div className="mt-4 w-full min-w-[500px] bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 bg-red-50 border-b border-red-100"><h3 className="font-semibold text-red-800 flex items-center gap-2"><AlertCircle className="w-4 h-4" />Analysis Unavailable</h3></div>
      <div className="p-5"><p className="text-red-700 text-sm">{error}</p><p className="text-gray-500 text-xs mt-2">Task: {config.task_name || config.task_id}</p></div>
    </div>
  )

  const hasMetrics = displayMetrics.length > 0
  const hasCharts = Object.keys(chartData).length > 0

  return (
    <div className="mt-4 w-full min-w-[500px] bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-indigo-50 via-purple-50 to-blue-50 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 flex items-center gap-2"><BarChart3 className="w-4 h-4 text-indigo-600" />Analysis Results</h3>
          <p className="text-xs text-gray-500 mt-1">{config.task_name || config.task_id}{numSamples && ` • ${numSamples} test samples`}{taskType && ` • ${taskType}`}</p>
        </div>
        <button onClick={handleRefresh} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-white rounded-lg transition-colors" title="Refresh"><RefreshCw className="w-4 h-4" /></button>
      </div>

      <div className="p-5 space-y-6">
        {/* Metrics */}
        {hasMetrics && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2"><TrendingUp className="w-4 h-4 text-indigo-500" />Metrics</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {displayMetrics.map(({ key, value }) => (
                <div key={key} className={`p-4 rounded-xl border ${METRIC_COLORS[key] || 'text-gray-600 bg-gray-50 border-gray-200'} transition-transform hover:scale-105`}>
                  <div className="flex items-center gap-2 mb-2">{METRIC_ICONS[key] || <Activity className="w-4 h-4" />}<span className="text-xs font-medium uppercase tracking-wide">{formatMetricName(key)}</span></div>
                  <div className="text-2xl font-bold">{(value * 100).toFixed(1)}%</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Charts */}
        {hasCharts && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2"><BarChart3 className="w-4 h-4 text-purple-500" />Charts</h4>
            <div className="space-y-4">
              {chartData.roc_curve && <RocCurveChart data={chartData.roc_curve} title="ROC Curve" />}
              {chartData.confusion_matrix && <ConfusionMatrixChart data={chartData.confusion_matrix} title="Confusion Matrix" />}
              {chartData.loss_curve && <LossCurveChart data={chartData.loss_curve} title="Training Loss" />}
              {chartData.km_curve && <KMCurveChart data={chartData.km_curve} title="Kaplan-Meier Survival Curve" />}
            </div>
          </div>
        )}

        {/* Class metrics */}
        {config.show_class_metrics && Object.keys(classMetrics).length > 0 && (
          <div className="pt-4 border-t border-gray-100">
            <h4 className="text-sm font-semibold text-gray-700 mb-3">Per-Class Metrics</h4>
            <div className="space-y-3">
              {Object.entries(classMetrics).map(([cls, m]) => (
                <div key={cls} className="bg-gray-50 rounded-lg p-3">
                  <div className="font-medium text-gray-900 mb-2">{cls}</div>
                  <div className="flex flex-wrap gap-2">{Object.entries(m).map(([k, v]) => <span key={k} className="text-xs bg-white px-2 py-1 rounded border border-gray-200">{formatMetricName(k)}: {(v * 100).toFixed(1)}%</span>)}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

