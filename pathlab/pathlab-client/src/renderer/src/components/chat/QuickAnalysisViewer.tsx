import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Tooltip } from '../ui/tooltip'
import { Loader2, BarChart3, TrendingUp, AlertCircle, RefreshCw, Activity, Target, Percent, Layers } from 'lucide-react'
import { getTaskQuickAnalysis, getAnalysisStatus } from '../../api'
import { ApiError } from '../../api/client'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KFoldLossCurveChart, KMCurveChart, MetricCurveChart, type ConfusionMatrixData, type RocCurveData, type LossCurveData, type KFoldLossCurveData, type KMCurveData, type MetricCurveData } from '../charts/AnalysisCharts'
import {
  METRIC_COLORS,
  METRIC_ABBREVIATIONS,
  isPercentageMetric,
  formatMetricName,
  formatMetricValue
} from '../../constants/metrics'

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
  // Retained for backward compatibility in persisted messages.
  // Do not render it before backend access is revalidated.
  cached_data?: CachedAnalysisData
  // External validation flag - enables polling for task completion before fetching analysis
  is_external_validation?: boolean
}

interface QuickAnalysisViewerProps {
  config: AgentQuickAnalysisConfig
  onError?: (error: string) => void
  onDataLoaded?: (data: CachedAnalysisData) => void  // Callback to persist loaded data
}

// Icon mappings (keep here as they use JSX)
const METRIC_ICONS: Record<string, React.ReactNode> = {
  accuracy: <Target className="w-4 h-4" />,
  auc: <TrendingUp className="w-4 h-4" />,
  f1: <Activity className="w-4 h-4" />,
  precision: <Percent className="w-4 h-4" />,
  recall: <Percent className="w-4 h-4" />,
  sensitivity: <Percent className="w-4 h-4" />,
  specificity: <Percent className="w-4 h-4" />,
  c_index: <TrendingUp className="w-4 h-4" />,
  integrated_brier_score: <BarChart3 className="w-4 h-4" />,
  // Segmentation-specific metrics
  iou: <Layers className="w-4 h-4" />,
  miou: <Layers className="w-4 h-4" />,
  dice: <Layers className="w-4 h-4" />,
  mean_iou: <Layers className="w-4 h-4" />,
  mean_dice: <Layers className="w-4 h-4" />,
  pixel_accuracy: <Target className="w-4 h-4" />,
}

/** Check if task type is segmentation */
function isSegmentationTask(taskType: string): boolean {
  return taskType === 'segmentation' || taskType === 'patch_segmentation'
}

/** Check if task type is survival */
function isSurvivalTask(taskType: string): boolean {
  return taskType === 'survival'
}

/** Get header gradient classes based on task type */
function getHeaderGradient(taskType: string): string {
  if (isSegmentationTask(taskType)) return 'bg-gradient-to-r from-violet-50 via-purple-50 to-fuchsia-50'
  if (isSurvivalTask(taskType)) return 'bg-gradient-to-r from-emerald-50 via-teal-50 to-cyan-50'
  return 'bg-gradient-to-r from-indigo-50 via-purple-50 to-blue-50'
}

/** Get header icon color based on task type */
function getHeaderIconColor(taskType: string): string {
  if (isSegmentationTask(taskType)) return 'text-violet-600'
  if (isSurvivalTask(taskType)) return 'text-emerald-600'
  return 'text-indigo-600'
}

/** Get header hover color based on task type */
function getHeaderHoverColor(taskType: string): string {
  if (isSegmentationTask(taskType)) return 'hover:text-violet-600'
  if (isSurvivalTask(taskType)) return 'hover:text-emerald-600'
  return 'hover:text-indigo-600'
}

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
  const { t } = useTranslation()
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [taskExists, setTaskExists] = useState(true)
  const [metrics, setMetrics] = useState<Record<string, MetricValue>>({})
  const [classMetrics, setClassMetrics] = useState<Record<string, Record<string, number>>>({})
  const [chartData, setChartData] = useState<{ confusion_matrix?: ConfusionMatrixData; roc_curve?: RocCurveData; loss_curve?: LossCurveData | KFoldLossCurveData; km_curve?: KMCurveData; iou_curve?: MetricCurveData; dice_curve?: MetricCurveData }>({})
  const [numSamples, setNumSamples] = useState<number | undefined>(undefined)
  const [taskType, setTaskType] = useState<string>('classification')
  const [kfoldTraining, setKfoldTraining] = useState<KFoldTrainingData | null>(null)

  // Mobile tabs state
  const [activeTab, setActiveTab] = useState<string>('roc_curve')

  // Update active tab based on available data
  useEffect(() => {
    // Prioritize segmentation charts when available
    if (chartData.iou_curve) setActiveTab('iou_curve')
    else if (chartData.dice_curve) setActiveTab('dice_curve')
    else if (chartData.roc_curve) setActiveTab('roc_curve')
    else if (chartData.confusion_matrix) setActiveTab('confusion_matrix')
    else if (chartData.loss_curve) setActiveTab('loss_curve')
    else if (chartData.km_curve) setActiveTab('km_curve')
  }, [chartData])

  // Async analysis state
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [analysisStatus, setAnalysisStatus] = useState<string>('')
  const [progress, setProgress] = useState(0)
  const [statusMessage, setStatusMessage] = useState('')
  const iouCurveTitle = chartData.iou_curve?.metric_name ? `${chartData.iou_curve.metric_name} Curve` : t('chatComponents.quickAnalysis.iouCurve')
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  // Smooth progress animation - gradually interpolate toward target progress
  const [animatedProgress, setAnimatedProgress] = useState(0)
  const animationRef = useRef<number | null>(null)
  const targetProgressRef = useRef(0)

  useEffect(() => {
    targetProgressRef.current = progress

    // Cancel any existing animation
    if (animationRef.current) cancelAnimationFrame(animationRef.current)

    const animate = () => {
      setAnimatedProgress(prev => {
        const target = targetProgressRef.current
        if (prev >= target) return target
        // Smooth easing: move 8% of remaining distance per frame, minimum 0.5 per frame
        const step = Math.max((target - prev) * 0.08, 0.5)
        const next = Math.min(prev + step, target)
        return Math.round(next * 10) / 10  // Round to 1 decimal
      })
      animationRef.current = requestAnimationFrame(animate)
    }

    animationRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
    }
  }, [progress])

  // Use ref for callbacks to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const onDataLoadedRef = useRef(onDataLoaded)
  onDataLoadedRef.current = onDataLoaded

  const clearLoadedAnalysis = useCallback(() => {
    setMetrics({})
    setClassMetrics({})
    setChartData({})
    setNumSamples(undefined)
    setTaskType('classification')
    setKfoldTraining(null)
  }, [])

  const getAnalysisErrorMessage = useCallback((err: unknown, fallbackKey: string) => {
    if (err instanceof ApiError) {
      if (err.isAuthError()) {
        return t('chatComponents.quickAnalysis.accessRevoked')
      }
      if (err.isNotFound()) {
        return t('chatComponents.quickAnalysis.taskNotFound')
      }
    }
    return err instanceof Error ? err.message : t(fallbackKey)
  }, [t])

  // Cleanup polling and animation on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
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
        setTaskExists(true)
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

      clearLoadedAnalysis()
      setError(result.message || t('chatComponents.quickAnalysis.noResults'))
      setIsLoading(false)
    } catch (err) {
      const msg = getAnalysisErrorMessage(err, 'chatComponents.quickAnalysis.fetchFailed')
      clearLoadedAnalysis()
      setTaskExists(!(err instanceof ApiError && err.isNotFound()))
      setAnalysisStatus('')
      setError(msg)
      setIsLoading(false)
      onErrorRef.current?.(msg)
    }
    return false
  }, [config.task_id, config.metrics, config.charts, bootstrapCIMetrics, clearLoadedAnalysis, getAnalysisErrorMessage, notifyDataLoaded, t])

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
        setError(status.error_message || t('chatComponents.quickAnalysis.analysisFailed'))
        setIsLoading(false)
      }
    } catch (err) {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      const msg = getAnalysisErrorMessage(err, 'chatComponents.quickAnalysis.fetchFailed')
      clearLoadedAnalysis()
      setTaskExists(!(err instanceof ApiError && err.isNotFound()))
      setAnalysisStatus('')
      setError(msg)
      setIsLoading(false)
      onErrorRef.current?.(msg)
    }
  }, [clearLoadedAnalysis, fetchResults, getAnalysisErrorMessage, t])

  useEffect(() => {
    // Capture current pollStatus to avoid stale closure
    const currentPollStatus = pollStatus

    const fetchData = async () => {
      setIsLoading(true)
      setError('')
      setAnalysisStatus('')
      setStatusMessage('')
      setTaskExists(true)

      try {
        const result = await getTaskQuickAnalysis(config.task_id, { metrics: config.metrics, charts: config.charts, runIfMissing: true, bootstrapCIMetrics })

        if (!result.has_analysis && result.status && ['pending', 'queued', 'running'].includes(result.status)) {
          // Start polling
          const aid = result.analysis_id
          if (aid) {
            setAnalysisId(aid)
            setAnalysisStatus(result.status)
            setProgress(result.progress || 0)
            setStatusMessage(result.message || t('chatComponents.quickAnalysis.analysisInProgress'))

            // Start polling interval
            pollingRef.current = setInterval(() => currentPollStatus(aid), POLL_INTERVAL)
          }
          return
        }

        if (!result.has_analysis) {
          clearLoadedAnalysis()
          setError(result.message || t('chatComponents.quickAnalysis.noResults'))
          return
        }

        setTaskExists(true)
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

        notifyDataLoaded(loadedMetrics, loadedClassMetrics, loadedNumSamples, loadedTaskType, loadedKfoldTraining)
      } catch (err) {
        const msg = getAnalysisErrorMessage(err, 'chatComponents.quickAnalysis.fetchFailed')
        clearLoadedAnalysis()
        setTaskExists(!(err instanceof ApiError && err.isNotFound()))
        setError(msg)
        onErrorRef.current?.(msg)
      } finally {
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
  }, [config.task_id, config.metrics?.join(','), config.charts?.join(','), bootstrapCIMetrics?.join(','), clearLoadedAnalysis, getAnalysisErrorMessage, pollStatus, t])

  const displayMetrics = useMemo(() => {
    if (!config.metrics) return Object.entries(metrics).map(([k, v]) => ({ key: k, value: v }))
    return config.metrics.map(m => ({ key: m, value: metrics[m] ?? metrics[`macro_${m}`] })).filter(x => x.value !== undefined)
  }, [metrics, config.metrics])

  const handleRefresh = () => { setIsLoading(true); setError(''); window.location.reload() }

  // Show loading state with progress for async analysis
  if (isLoading || (analysisStatus && ['pending', 'queued', 'running', 'waiting'].includes(analysisStatus))) {
    const isPolling = ['pending', 'queued', 'running', 'waiting'].includes(analysisStatus)
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
            <span className="text-gray-600 text-sm sm:text-base">
              {isPolling ? statusMessage || t('chatComponents.quickAnalysis.runningAnalysis') : t('chatComponents.quickAnalysis.loadingAnalysis')}
            </span>
          </div>
          {isPolling && (
            <div className="w-full max-w-xs">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>{analysisStatus === 'waiting' ? t('chatComponents.quickAnalysis.waitingForInference') : ['pending', 'queued'].includes(analysisStatus) ? t('chatComponents.quickAnalysis.queued') : t('chatComponents.quickAnalysis.processing')}</span>
                <span>{analysisStatus === 'waiting' ? '' : `${Math.round(animatedProgress)}%`}</span>
              </div>
              {analysisStatus !== 'waiting' && (
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full"
                    style={{ width: `${animatedProgress}%` }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (!taskExists || error) return (
    <div className="mt-4 w-full max-w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-red-50 border-b border-red-100"><h3 className="font-semibold text-red-800 flex items-center gap-2 text-sm sm:text-base"><AlertCircle className="w-4 h-4 flex-shrink-0" />{t('chatComponents.quickAnalysis.analysisUnavailable')}</h3></div>
      <div className="p-4 sm:p-5"><p className="text-red-700 text-sm">{error}</p><p className="text-gray-500 text-xs mt-2 truncate">{t('chatComponents.quickAnalysis.task')}: {config.task_name || config.task_id}</p></div>
    </div>
  )

  const hasMetrics = displayMetrics.length > 0
  const hasCharts = Object.keys(chartData).length > 0

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className={`px-4 sm:px-5 py-3 sm:py-4 ${getHeaderGradient(taskType)} border-b border-gray-100 flex items-center justify-between`}>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 text-sm sm:text-base">
            {isSegmentationTask(taskType)
              ? <Layers className={`w-4 h-4 ${getHeaderIconColor(taskType)} flex-shrink-0`} />
              : <BarChart3 className={`w-4 h-4 ${getHeaderIconColor(taskType)} flex-shrink-0`} />}
            <span className="truncate">{t('chatComponents.quickAnalysis.analysisResults')}</span>
          </h3>
          <p className="text-xs text-gray-500 mt-1 truncate">{config.task_name || config.task_id}{numSamples && ` • ${t('chatComponents.quickAnalysis.testSamples', { count: numSamples })}`}{taskType && ` • ${taskType}`}</p>
        </div>
        <Tooltip content={t('chatComponents.quickAnalysis.refresh')}>
          <button
            onClick={handleRefresh}
            className={`p-1.5 text-gray-400 ${getHeaderHoverColor(taskType)} hover:bg-white rounded-lg transition-colors flex-shrink-0`}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </Tooltip>
      </div>

      <div className="p-4 sm:p-5 space-y-4 sm:space-y-6">
        {/* Metrics */}
        {hasMetrics && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2 sm:mb-3 flex items-center gap-2">
              {isSegmentationTask(taskType)
                ? <Layers className="w-4 h-4 text-violet-500" />
                : <TrendingUp className={`w-4 h-4 ${isSurvivalTask(taskType) ? 'text-emerald-500' : 'text-indigo-500'}`} />}
              {t('chatComponents.quickAnalysis.metrics')}
            </h4>
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
              <span className="truncate">{t('chatComponents.quickAnalysis.kfoldTitle', { folds: kfoldTraining.num_folds })}</span>
            </h4>

            {/* Aggregated metrics */}
            {Object.keys(kfoldTraining.aggregated).length > 0 && (
              <div className="mb-3 sm:mb-4">
                <div className="text-xs text-gray-500 mb-2">{t('chatComponents.quickAnalysis.aggregatedMeanStd')}</div>
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
            <div className="text-xs text-gray-500 mb-2">{t('chatComponents.quickAnalysis.perFoldResults')}</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 sm:gap-3">
              {Object.entries(kfoldTraining.folds)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([foldName, foldData]) => {
                  // Convert fold_0 to FOLD 1, fold_1 to FOLD 2, etc.
                  const foldNumber = parseInt(foldName.replace('fold_', ''), 10) + 1
                  const displayName = t('chatComponents.quickAnalysis.foldLabel', { number: foldNumber })
                  return (
                    <div key={foldName} className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm hover:border-purple-300 transition-colors">
                      <div className="text-xs font-bold text-gray-700 mb-2 uppercase tracking-wider border-b border-gray-100 pb-2">
                        {displayName}
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
                  )
                })}
            </div>
          </div>
        )}

        {/* Charts */}
        {hasCharts && (
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-purple-500" />
              {t('chatComponents.quickAnalysis.charts')}
            </h4>

            {/* Desktop View: Stacked */}
            <div className="hidden sm:block space-y-4">
              {chartData.iou_curve && <MetricCurveChart data={chartData.iou_curve} title={iouCurveTitle} compact={true} />}
              {chartData.dice_curve && <MetricCurveChart data={chartData.dice_curve} title={t('chatComponents.quickAnalysis.diceCurve')} compact={true} />}
              {chartData.roc_curve && <RocCurveChart data={chartData.roc_curve} title={t('chatComponents.quickAnalysis.rocCurve')} compact={true} />}
              {chartData.confusion_matrix && <ConfusionMatrixChart data={chartData.confusion_matrix} title={t('chatComponents.quickAnalysis.confusionMatrix')} compact={true} />}
              {chartData.loss_curve && (
                'is_kfold' in chartData.loss_curve && chartData.loss_curve.is_kfold
                  ? <KFoldLossCurveChart data={chartData.loss_curve as KFoldLossCurveData} title={t('chatComponents.quickAnalysis.trainingLossKFold')} compact={true} />
                  : <LossCurveChart data={chartData.loss_curve as LossCurveData} title={t('chatComponents.quickAnalysis.trainingLoss')} compact={true} />
              )}
              {chartData.km_curve && <KMCurveChart data={chartData.km_curve} title={t('chatComponents.quickAnalysis.kmSurvivalCurve')} compact={true} />
              }
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
                    {t('chatComponents.quickAnalysis.rocCurve')}
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
                    {t('chatComponents.quickAnalysis.confusionMatrix')}
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
                    {t('chatComponents.quickAnalysis.trainingLoss')}
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
                    {t('chatComponents.quickAnalysis.survivalCurve')}
                  </button>
                )}
                {chartData.iou_curve && (
                  <button
                    onClick={() => setActiveTab('iou_curve')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'iou_curve'
                      ? 'bg-violet-100 text-violet-700 ring-1 ring-violet-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    {iouCurveTitle}
                  </button>
                )}
                {chartData.dice_curve && (
                  <button
                    onClick={() => setActiveTab('dice_curve')}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${activeTab === 'dice_curve'
                      ? 'bg-violet-100 text-violet-700 ring-1 ring-violet-200'
                      : 'bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100'
                      }`}
                  >
                    {t('chatComponents.quickAnalysis.diceCurve')}
                  </button>
                )}
              </div>

              <div className="min-h-[350px]">
                {activeTab === 'iou_curve' && chartData.iou_curve && (
                  <MetricCurveChart data={chartData.iou_curve} title={iouCurveTitle} compact={true} />
                )}
                {activeTab === 'dice_curve' && chartData.dice_curve && (
                  <MetricCurveChart data={chartData.dice_curve} title={t('chatComponents.quickAnalysis.diceCurve')} compact={true} />
                )}
                {activeTab === 'roc_curve' && chartData.roc_curve && (
                  <RocCurveChart data={chartData.roc_curve} title={t('chatComponents.quickAnalysis.rocCurve')} compact={true} />
                )}
                {activeTab === 'confusion_matrix' && chartData.confusion_matrix && (
                  <ConfusionMatrixChart data={chartData.confusion_matrix} title={t('chatComponents.quickAnalysis.confusionMatrix')} compact={true} />
                )}
                {activeTab === 'loss_curve' && chartData.loss_curve && (
                  'is_kfold' in chartData.loss_curve && chartData.loss_curve.is_kfold
                    ? <KFoldLossCurveChart data={chartData.loss_curve as KFoldLossCurveData} title={t('chatComponents.quickAnalysis.trainingLossKFold')} compact={true} />
                    : <LossCurveChart data={chartData.loss_curve as LossCurveData} title={t('chatComponents.quickAnalysis.trainingLoss')} compact={true} />
                )}
                {activeTab === 'km_curve' && chartData.km_curve && (
                  <KMCurveChart data={chartData.km_curve} title={t('chatComponents.quickAnalysis.kmSurvivalCurve')} compact={true} />
                )}
              </div>
            </div>
          </div>
        )}

        {/* Class metrics */}
        {config.show_class_metrics && Object.keys(classMetrics).length > 0 && (
          <div className="pt-3 sm:pt-4 border-t border-gray-100">
            <h4 className="text-xs sm:text-sm font-semibold text-gray-700 mb-2 sm:mb-3">{t('chatComponents.quickAnalysis.perClassMetrics')}</h4>
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

