import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Loader2, BarChart3, TrendingUp, AlertCircle, RefreshCw, Activity, Target, Percent } from 'lucide-react'
import { getTaskQuickAnalysis, getTrainingTasks, getAnalysisStatus } from '../../api'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KFoldLossCurveChart, KMCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KFoldLossCurveData, type KMCurveData } from '../charts/AnalysisCharts'

// Metric value type
export type MetricValue = number | { value: number; ci_lower: number; ci_upper: number }

// Cached analysis data for persistence - minimal data only (no charts to avoid large payloads)
export interface CachedAnalysisData {
  metrics: Record<string, MetricValue>
  class_metrics: Record<string, Record<string, number>>
  num_samples?: number
  task_type: string
  // Only cache aggregated K-Fold metrics, not per-fold history (too large)
  kfold_aggregated?: Record<string, { mean: number; std: number }>
  is_kfold?: boolean
  num_folds?: number
}

export interface AgentQuickAnalysisConfig {
  task_id: string
  task_name?: string
  metrics?: string[]  // e.g., ['accuracy', 'auc', 'f1']
  charts?: string[]   // e.g., ['roc_curve', 'confusion_matrix']
  show_class_metrics?: boolean
  submitted?: boolean
  // Bootstrap CI options
  compute_bootstrap_ci?: boolean  // Whether to compute 95% CI for all metrics
  bootstrap_ci_metrics?: string[] // Specific metrics to compute 95% CI for
  // Cached data for persistence (populated after first load)
  cached_data?: CachedAnalysisData
}

interface QuickAnalysisViewerProps {
  config: AgentQuickAnalysisConfig
  onError?: (error: string) => void
  onDataLoaded?: (data: CachedAnalysisData) => void  // Callback to persist loaded data
}

// Icon and color mappings
const METRIC_ICONS: Record<string, React.ReactNode> = { accuracy: <Target className="w-4 h-4" />, auc: <TrendingUp className="w-4 h-4" />, f1: <Activity className="w-4 h-4" />, precision: <Percent className="w-4 h-4" />, recall: <Percent className="w-4 h-4" />, sensitivity: <Percent className="w-4 h-4" />, specificity: <Percent className="w-4 h-4" /> }
const METRIC_COLORS: Record<string, string> = { accuracy: 'text-blue-600 bg-blue-50 border-blue-200', auc: 'text-purple-600 bg-purple-50 border-purple-200', f1: 'text-green-600 bg-green-50 border-green-200', precision: 'text-amber-600 bg-amber-50 border-amber-200', recall: 'text-teal-600 bg-teal-50 border-teal-200', sensitivity: 'text-teal-600 bg-teal-50 border-teal-200', specificity: 'text-orange-600 bg-orange-50 border-orange-200' }

// Metrics that should NOT be displayed as percentages (they are raw values)
const RAW_VALUE_METRICS = new Set([
  'loss', 'train_loss', 'val_loss', 'test_loss',
  'integrated_brier_score', 'brier_score',
  'mse', 'rmse', 'mae',  // regression metrics
  'log_loss', 'cross_entropy',
])

// Check if a metric should be displayed as percentage
function isPercentageMetric(metricName: string): boolean {
  const normalizedName = metricName.toLowerCase().replace('macro_', '')
  return !RAW_VALUE_METRICS.has(normalizedName)
}

// Format metric value based on whether it's a percentage or raw value
function formatMetricValue(value: number, metricName: string): string {
  if (isPercentageMetric(metricName)) {
    return `${(value * 100).toFixed(2)}%`
  }
  // For raw values, show with appropriate precision
  return value.toFixed(4)
}

// Metric name mapper
const METRIC_ABBREVIATIONS: Record<string, string> = {
  accuracy: 'ACC',
  precision: 'PREC',
  recall: 'REC',
  sensitivity: 'SENS',
  specificity: 'SPEC',
  f1: 'F1',
  auc: 'AUC',
  tp: 'TP',
  fp: 'FP',
  fn: 'FN',
  tn: 'TN',
  balanced_accuracy: 'B.ACC',
  mcc: 'MCC',
  support: 'SUPP',
  brier_score: 'BRIER',
  c_index: 'C-INDEX',

}

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

// K-Fold training data type
interface KFoldTrainingData {
  is_kfold: boolean
  num_folds: number
  folds: Record<string, { history?: Record<string, number[]>; val_metrics?: Record<string, number> }>
  aggregated: Record<string, { mean: number; std: number }>
}

export function QuickAnalysisViewer({ config, onError, onDataLoaded }: QuickAnalysisViewerProps) {
  // Check if we have cached data (metrics only - charts are not cached)
  const cachedData = config.cached_data
  const hasCachedData = !!cachedData && Object.keys(cachedData.metrics || {}).length > 0

  const [isLoading, setIsLoading] = useState(!hasCachedData)
  const [error, setError] = useState<string>('')
  const [taskExists, setTaskExists] = useState(true)
  const [metrics, setMetrics] = useState<Record<string, MetricValue>>(cachedData?.metrics || {})
  const [classMetrics, setClassMetrics] = useState<Record<string, Record<string, number>>>(cachedData?.class_metrics || {})
  // Charts are not cached (too large), will be fetched on demand
  const [chartData, setChartData] = useState<{ confusion_matrix?: ConfusionMatrixData; roc_curve?: RocCurveData; loss_curve?: LossCurveData | KFoldLossCurveData; km_curve?: KMCurveData }>({})
  const [numSamples, setNumSamples] = useState<number | undefined>(cachedData?.num_samples)
  const [taskType, setTaskType] = useState<string>(cachedData?.task_type || 'classification')
  // Reconstruct partial K-Fold data from partial K-Fold data from cache (aggregated only, no per-fold history)
  const [kfoldTraining, setKfoldTraining] = useState<KFoldTrainingData | null>(
    cachedData?.is_kfold && cachedData?.kfold_aggregated
      ? { is_kfold: true, num_folds: cachedData.num_folds || 0, folds: {}, aggregated: cachedData.kfold_aggregated }
      : null
  )

  // Mobile tabs state
  const [activeTab, setActiveTab] = useState<string>('roc_curve')

  // Update active tab based on available data
  useEffect(() => {
    if (chartData.roc_curve) setActiveTab('roc_curve')
    else if (chartData.confusion_matrix) setActiveTab('confusion_matrix')
    else if (chartData.loss_curve) setActiveTab('loss_curve')
    else if (chartData.km_curve) setActiveTab('km_curve')
  }, [chartData])

  // Async analysis state
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<string>(hasCachedData ? 'completed' : '')
  const [progress, setProgress] = useState(0)
  const [statusMessage, setStatusMessage] = useState('')
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // Use ref for callbacks to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const onDataLoadedRef = useRef(onDataLoaded)
  onDataLoadedRef.current = onDataLoaded

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  // Helper to notify parent of loaded data for persistence - minimal data only
  const notifyDataLoaded = useCallback((
    loadedMetrics: Record<string, MetricValue>,
    loadedClassMetrics: Record<string, Record<string, number>>,
    loadedNumSamples: number | undefined,
    loadedTaskType: string,
    loadedKfoldTraining: KFoldTrainingData | null
  ) => {
    if (onDataLoadedRef.current) {
      // Only cache minimal data - no charts or per-fold history (too large)
      onDataLoadedRef.current({
        metrics: loadedMetrics,
        class_metrics: loadedClassMetrics,
        num_samples: loadedNumSamples,
        task_type: loadedTaskType,
        // Only cache aggregated K-Fold metrics
        kfold_aggregated: loadedKfoldTraining?.aggregated,
        is_kfold: loadedKfoldTraining?.is_kfold,
        num_folds: loadedKfoldTraining?.num_folds
      })
    }
  }, [])

  // Determine bootstrap CI metrics from config
  const bootstrapCIMetrics = config.bootstrap_ci_metrics || (config.compute_bootstrap_ci ? config.metrics : undefined)

  // Fetch completed analysis results
  const fetchResults = useCallback(async () => {
    try {
      const result = await getTaskQuickAnalysis(config.task_id, {
        metrics: config.metrics,
        charts: config.charts,
        runIfMissing: false,  // Don't trigger new analysis, just fetch
        bootstrapCIMetrics
      })
      if (result.has_analysis) {
        const loadedMetrics = result.metrics || {}
        const loadedClassMetrics = result.class_metrics || {}
        const loadedChartData = result.chart_data || {}
        const loadedNumSamples = result.num_samples
        const loadedTaskType = result.task_type || 'classification'
        const loadedKfoldTraining = result.kfold_training || null

        setMetrics(loadedMetrics)
        setClassMetrics(loadedClassMetrics)
        setChartData(loadedChartData)
        setNumSamples(loadedNumSamples)
        setTaskType(loadedTaskType)
        setKfoldTraining(loadedKfoldTraining)
        setAnalysisStatus('completed')
        setIsLoading(false)

        // Notify parent to persist the data (minimal data only)
        notifyDataLoaded(loadedMetrics, loadedClassMetrics, loadedNumSamples, loadedTaskType, loadedKfoldTraining)
        return true
      }
    } catch (err) {
      console.error('Failed to fetch analysis results:', err)
    }
    return false
  }, [config.task_id, config.metrics, config.charts, bootstrapCIMetrics, notifyDataLoaded])

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
    // Capture current pollStatus to avoid stale closure
    const currentPollStatus = pollStatus

    const fetchData = async () => {
      // If we have cached data, don't show loading state but still fetch charts in background
      if (!hasCachedData) {
        setIsLoading(true); setError(''); setAnalysisStatus('')
      }

      try {
        const tasks = await getTrainingTasks()
        const found = tasks.some(t => t.task_id === config.task_id && t.status === 'completed')
        if (!found) {
          if (!hasCachedData) {
            setTaskExists(false); setError('Task not found or not completed'); setIsLoading(false)
          }
          return
        }
        setTaskExists(true)

        const result = await getTaskQuickAnalysis(config.task_id, { metrics: config.metrics, charts: config.charts, runIfMissing: true, bootstrapCIMetrics })

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
            pollingRef.current = setInterval(() => currentPollStatus(aid), POLL_INTERVAL)
          }
          return
        }

        if (!result.has_analysis) {
          if (!hasCachedData) {
            setError(result.message || 'No analysis results available'); setIsLoading(false)
          }
          return
        }

        const loadedMetrics = result.metrics || {}
        const loadedClassMetrics = result.class_metrics || {}
        const loadedChartData = result.chart_data || {}
        const loadedNumSamples = result.num_samples
        const loadedTaskType = result.task_type || 'classification'
        const loadedKfoldTraining = result.kfold_training || null

        setMetrics(loadedMetrics)
        setClassMetrics(loadedClassMetrics)
        setChartData(loadedChartData)
        setNumSamples(loadedNumSamples)
        setTaskType(loadedTaskType)
        setKfoldTraining(loadedKfoldTraining)
        setAnalysisStatus('completed')

        // Only notify parent to persist if we didn't have cached data (avoid duplicate updates)
        if (!hasCachedData) {
          notifyDataLoaded(loadedMetrics, loadedClassMetrics, loadedNumSamples, loadedTaskType, loadedKfoldTraining)
        }
      } catch (err) {
        // Only show error if we don't have cached data to display
        if (!hasCachedData) {
          const msg = err instanceof Error ? err.message : 'Failed to fetch analysis'
          setError(msg); onErrorRef.current?.(msg)
        } else {
          console.warn('Failed to fetch charts for cached analysis:', err)
        }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.task_id, config.metrics?.join(','), config.charts?.join(','), bootstrapCIMetrics?.join(',')])

  const displayMetrics = useMemo(() => {
    if (!config.metrics) return Object.entries(metrics).map(([k, v]) => ({ key: k, value: v }))
    return config.metrics.map(m => ({ key: m, value: metrics[m] ?? metrics[`macro_${m}`] })).filter(x => x.value !== undefined)
  }, [metrics, config.metrics])

  const handleRefresh = () => { setIsLoading(true); setError(''); window.location.reload() }

  // Show loading state with progress for async analysis
  if (isLoading || (analysisStatus && ['pending', 'running'].includes(analysisStatus))) {
    const isPolling = ['pending', 'running'].includes(analysisStatus)
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
            <span className="text-gray-600 text-sm sm:text-base">
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
    <div className="mt-4 w-full max-w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-red-50 border-b border-red-100"><h3 className="font-semibold text-red-800 flex items-center gap-2 text-sm sm:text-base"><AlertCircle className="w-4 h-4 flex-shrink-0" />Analysis Unavailable</h3></div>
      <div className="p-4 sm:p-5"><p className="text-red-700 text-sm">{error}</p><p className="text-gray-500 text-xs mt-2 truncate">Task: {config.task_name || config.task_id}</p></div>
    </div>
  )

  const hasMetrics = displayMetrics.length > 0
  const hasCharts = Object.keys(chartData).length > 0

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-gradient-to-r from-indigo-50 via-purple-50 to-blue-50 border-b border-gray-100 flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 text-sm sm:text-base"><BarChart3 className="w-4 h-4 text-indigo-600 flex-shrink-0" /><span className="truncate">Analysis Results</span></h3>
          <p className="text-xs text-gray-500 mt-1 truncate">{config.task_name || config.task_id}{numSamples && ` • ${numSamples} test samples`}{taskType && ` • ${taskType}`}</p>
        </div>
        <button onClick={handleRefresh} className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-white rounded-lg transition-colors flex-shrink-0" title="Refresh"><RefreshCw className="w-4 h-4" /></button>
      </div>

      <div className="p-4 sm:p-5 space-y-4 sm:space-y-6">
        {/* Metrics */}
        {hasMetrics && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2 sm:mb-3 flex items-center gap-2"><TrendingUp className="w-4 h-4 text-indigo-500" />Metrics</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
              {displayMetrics.map(({ key, value }) => {
                const val = typeof value === 'object' ? value.value : value
                const ci = typeof value === 'object' ? value : null

                return (
                  <div key={key} className={`p-3 sm:p-4 rounded-xl border ${METRIC_COLORS[key] || 'text-gray-600 bg-gray-50 border-gray-200'} transition-transform hover:scale-105`}>
                    <div className="flex items-center gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
                      {METRIC_ICONS[key] || <Activity className="w-4 h-4" />}
                      <span className="text-xs font-medium uppercase tracking-wide truncate">
                        <span className="hidden sm:inline">{formatMetricName(key)}</span>
                        <span className="sm:hidden">{METRIC_ABBREVIATIONS[key.toLowerCase()] || formatMetricName(key)}</span>
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <div className="text-lg sm:text-2xl font-bold leading-tight">{formatMetricValue(val, key)}</div>
                      {ci && (
                        <div className="text-xs sm:text-sm opacity-80 mt-0.5 font-medium">
                          {isPercentageMetric(key)
                            ? `(${formatMetricValue(ci.ci_lower, key).replace('%', '')}-${formatMetricValue(ci.ci_upper, key)})`
                            : `(${formatMetricValue(ci.ci_lower, key)}-${formatMetricValue(ci.ci_upper, key)})`}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* K-Fold Training Metrics */}
        {kfoldTraining && kfoldTraining.is_kfold && (
          <div className="pt-3 sm:pt-4 border-t border-gray-100">
            <h4 className="text-sm font-semibold text-gray-700 mb-2 sm:mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-purple-500 flex-shrink-0" />
              <span className="truncate">K-Fold Cross-Validation ({kfoldTraining.num_folds} folds)</span>
            </h4>

            {/* Aggregated metrics */}
            {Object.keys(kfoldTraining.aggregated).length > 0 && (
              <div className="mb-3 sm:mb-4">
                <div className="text-xs text-gray-500 mb-2">Aggregated (Mean ± Std)</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(kfoldTraining.aggregated).map(([metricName, stats]) => (
                    <div key={metricName} className="bg-purple-50 border border-purple-200 rounded-lg px-2 sm:px-3 py-1.5 sm:py-2">
                      <span className="text-xs font-medium text-purple-700 uppercase">{formatMetricName(metricName)}</span>
                      <div className="text-base sm:text-lg font-bold text-purple-900">
                        {formatMetricValue(stats.mean, metricName)} <span className="text-xs sm:text-sm font-normal">± {isPercentageMetric(metricName) ? (stats.std * 100).toFixed(2) + '%' : stats.std.toFixed(4)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Per-fold metrics */}
            <div className="text-xs text-gray-500 mb-2">Per-Fold Results</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 sm:gap-3">
              {Object.entries(kfoldTraining.folds)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([foldName, foldData]) => (
                  <div key={foldName} className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm hover:border-purple-300 transition-colors">
                    <div className="text-xs font-bold text-gray-700 mb-2 uppercase tracking-wider border-b border-gray-100 pb-2">
                      {foldName.replace('_', ' ')}
                    </div>
                    {foldData.val_metrics && (
                      <div className="space-y-2">
                        {Object.entries(foldData.val_metrics).map(([k, v]) => (
                          <div key={k} className="flex justify-between items-center text-xs">
                            <span className="text-gray-500 font-medium truncate pr-2" title={formatMetricName(k)}>
                              {formatMetricName(k)}
                            </span>
                            <span className="font-mono font-semibold text-gray-900 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
                              {typeof v === 'number' ? formatMetricValue(v, k) : v}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Charts */}
        {hasCharts && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-purple-500" />
              Charts
            </h4>

            {/* Desktop View: Stacked */}
            <div className="hidden sm:block space-y-4">
              {chartData.roc_curve && <RocCurveChart data={chartData.roc_curve} title="ROC Curve" />}
              {chartData.confusion_matrix && <ConfusionMatrixChart data={chartData.confusion_matrix} title="Confusion Matrix" />}
              {chartData.loss_curve && (
                'is_kfold' in chartData.loss_curve && chartData.loss_curve.is_kfold
                  ? <KFoldLossCurveChart data={chartData.loss_curve as KFoldLossCurveData} title="Training Loss (K-Fold)" />
                  : <LossCurveChart data={chartData.loss_curve as LossCurveData} title="Training Loss" />
              )}
              {chartData.km_curve && <KMCurveChart data={chartData.km_curve} title="Kaplan-Meier Survival Curve" />}
            </div>

            {/* Mobile View: Tabs */}
            <div className="block sm:hidden">
              <div className="flex gap-2 mb-4 overflow-x-auto pb-2 scrollbar-hide">
                {chartData.roc_curve && (
                  <button
                    onClick={() => setActiveTab('roc_curve')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'roc_curve'
                      ? 'bg-purple-100 text-purple-700 ring-1 ring-purple-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    ROC Curve
                  </button>
                )}
                {chartData.confusion_matrix && (
                  <button
                    onClick={() => setActiveTab('confusion_matrix')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'confusion_matrix'
                      ? 'bg-purple-100 text-purple-700 ring-1 ring-purple-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    Confusion Matrix
                  </button>
                )}
                {chartData.loss_curve && (
                  <button
                    onClick={() => setActiveTab('loss_curve')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'loss_curve'
                      ? 'bg-purple-100 text-purple-700 ring-1 ring-purple-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    Training Loss
                  </button>
                )}
                {chartData.km_curve && (
                  <button
                    onClick={() => setActiveTab('km_curve')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'km_curve'
                      ? 'bg-purple-100 text-purple-700 ring-1 ring-purple-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    Survival Curve
                  </button>
                )}
              </div>

              <div className="min-h-[350px]">
                {activeTab === 'roc_curve' && chartData.roc_curve && (
                  <RocCurveChart data={chartData.roc_curve} title="ROC Curve" compact={true} />
                )}
                {activeTab === 'confusion_matrix' && chartData.confusion_matrix && (
                  <ConfusionMatrixChart data={chartData.confusion_matrix} title="Confusion Matrix" compact={true} />
                )}
                {activeTab === 'loss_curve' && chartData.loss_curve && (
                  'is_kfold' in chartData.loss_curve && chartData.loss_curve.is_kfold
                    ? <KFoldLossCurveChart data={chartData.loss_curve as KFoldLossCurveData} title="Training Loss (K-Fold)" compact={true} />
                    : <LossCurveChart data={chartData.loss_curve as LossCurveData} title="Training Loss" compact={true} />
                )}
                {activeTab === 'km_curve' && chartData.km_curve && (
                  <KMCurveChart data={chartData.km_curve} title="Kaplan-Meier Survival Curve" compact={true} />
                )}
              </div>
            </div>
          </div>
        )}

        {/* Class metrics */}
        {config.show_class_metrics && Object.keys(classMetrics).length > 0 && (
          <div className="pt-3 sm:pt-4 border-t border-gray-100">
            <h4 className="text-xs sm:text-sm font-semibold text-gray-700 mb-2 sm:mb-3">Per-Class Metrics</h4>
            <div className="space-y-2 sm:space-y-3">
              {Object.entries(classMetrics).map(([cls, m]) => (
                <div key={cls} className="bg-gray-50 rounded-lg p-2 sm:p-3">
                  <div className="font-medium text-gray-900 text-sm sm:text-base mb-1.5 sm:mb-2">{cls}</div>
                  <div className="grid grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 md:grid-cols-6 gap-1 sm:gap-1.5">
                    {Object.entries(m).map(([k, v]) => {
                      // tp, fp, fn, tn, support are counts (integers), not percentages
                      const isCount = ['tp', 'fp', 'fn', 'tn', 'support'].includes(k)
                      const displayValue = isCount ? v.toString() : formatMetricValue(v, k)
                      return (
                        <div
                          key={k}
                          className="bg-white px-1.5 sm:px-2 py-1 sm:py-1.5 rounded border border-gray-200 text-center"
                          title={`${formatMetricName(k)}: ${displayValue}`}
                        >
                          <div className="text-[10px] sm:text-xs text-gray-500 font-medium truncate">
                            <span className="hidden sm:inline">{formatMetricName(k)}</span>
                            <span className="sm:hidden">{METRIC_ABBREVIATIONS[k.toLowerCase()] || formatMetricName(k)}</span>
                          </div>
                          <div className="text-xs sm:text-sm font-semibold text-gray-900">
                            {displayValue}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

