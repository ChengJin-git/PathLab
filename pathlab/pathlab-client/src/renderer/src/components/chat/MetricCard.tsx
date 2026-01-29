import { useState, useEffect, useMemo, useRef } from 'react'
import { Loader2, TrendingUp, Target, Percent, Activity, AlertCircle, RefreshCw } from 'lucide-react'
import { getTaskQuickAnalysis, getTrainingTasks } from '../../api'

export interface AgentMetricConfig {
  task_id: string
  task_name?: string
  metrics: string[]  // e.g., ['accuracy', 'auc', 'f1', 'precision', 'sensitivity', 'specificity']
  show_class_metrics?: boolean
  submitted?: boolean
}

interface MetricCardProps {
  config: AgentMetricConfig
  onError?: (error: string) => void
}

// Icon mapping for different metric types
const METRIC_ICONS: Record<string, React.ReactNode> = {
  accuracy: <Target className="w-4 h-4" />,
  auc: <TrendingUp className="w-4 h-4" />,
  f1: <Activity className="w-4 h-4" />,
  precision: <Percent className="w-4 h-4" />,
  recall: <Percent className="w-4 h-4" />,
  sensitivity: <Percent className="w-4 h-4" />,
  specificity: <Percent className="w-4 h-4" />,
}

// Color mapping for different metric types
const METRIC_COLORS: Record<string, string> = {
  accuracy: 'text-blue-600 bg-blue-50 border-blue-200',
  auc: 'text-purple-600 bg-purple-50 border-purple-200',
  f1: 'text-green-600 bg-green-50 border-green-200',
  precision: 'text-amber-600 bg-amber-50 border-amber-200',
  recall: 'text-teal-600 bg-teal-50 border-teal-200',
  sensitivity: 'text-teal-600 bg-teal-50 border-teal-200',
  specificity: 'text-orange-600 bg-orange-50 border-orange-200',
}

// Format metric name for display
function formatMetricName(name: string): string {
  return name
    .replace('macro_', '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, l => l.toUpperCase())
}

/**
 * Parse [METRIC_CONFIG] block from message content
 */
export function parseMetricConfig(content: string): AgentMetricConfig | null {
  const match = content.match(/\[METRIC_CONFIG\]([\s\S]*?)\[\/METRIC_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [METRIC_CONFIG] block from content for display
 */
export function removeMetricConfigBlock(content: string): string {
  return content.replace(/\[METRIC_CONFIG\][\s\S]*?\[\/METRIC_CONFIG\]/g, '').trim()
}

export function MetricCard({ config, onError }: MetricCardProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [metrics, setMetrics] = useState<Record<string, number>>({})
  const [classMetrics, setClassMetrics] = useState<Record<string, Record<string, number>>>({})
  const [taskExists, setTaskExists] = useState(true)
  const [numSamples, setNumSamples] = useState<number | undefined>()
  const [classes, setClasses] = useState<string[]>([])

  // Use ref for onError to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  // Fetch analysis on mount
  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true)
      setError('')

      try {
        // First validate task exists
        const tasks = await getTrainingTasks()
        const found = tasks.some(t => t.task_id === config.task_id && t.status === 'completed')
        
        if (!found) {
          setTaskExists(false)
          setError('Task not found or not completed')
          return
        }
        setTaskExists(true)

        // Fetch quick analysis with specified metrics
        const result = await getTaskQuickAnalysis(config.task_id, {
          metrics: config.metrics,
          runIfMissing: true
        })

        if (!result.has_analysis) {
          setError(result.message || 'No analysis results available')
          return
        }

        setMetrics(result.metrics || {})
        setClassMetrics(result.class_metrics || {})
        setNumSamples(result.num_samples)
        setClasses(result.classes || [])
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch metrics'
        setError(msg)
        onErrorRef.current?.(msg)
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.task_id, config.metrics.join(',')])

  const handleRefresh = () => {
    setIsLoading(true)
    setError('')
    // Trigger re-fetch by changing key would be ideal, but for simplicity:
    window.location.reload()
  }

  // Filter and order metrics based on config
  const displayMetrics = useMemo(() => {
    const result: Array<{ key: string; value: number }> = []
    for (const requestedMetric of config.metrics) {
      // Try exact match first, then try with macro_ prefix
      const value = metrics[requestedMetric] ?? metrics[`macro_${requestedMetric}`]
      if (value !== undefined) {
        result.push({ key: requestedMetric, value })
      }
    }
    return result
  }, [metrics, config.metrics])

  if (isLoading) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
        <div className="flex items-center justify-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
          <span className="text-gray-600 text-sm sm:text-base">Loading metrics...</span>
        </div>
      </div>
    )
  }

  if (!taskExists || error) {
    return (
      <div className="mt-4 w-full max-w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-4 sm:px-5 py-3 sm:py-4 bg-red-50 border-b border-red-100">
          <h3 className="font-semibold text-red-800 flex items-center gap-2 text-sm sm:text-base">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            Metrics Unavailable
          </h3>
        </div>
        <div className="p-4 sm:p-5">
          <p className="text-red-700 text-sm">{error}</p>
          <p className="text-gray-500 text-xs mt-2 truncate">Task: {config.task_name || config.task_id}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 w-full max-w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 sm:py-4 bg-gradient-to-r from-indigo-50 to-blue-50 border-b border-gray-100 flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2 text-sm sm:text-base">
            <TrendingUp className="w-4 h-4 text-indigo-600 flex-shrink-0" />
            <span className="truncate">Performance Metrics</span>
          </h3>
          <p className="text-xs text-gray-500 mt-1 truncate">
            {config.task_name || config.task_id}
            {numSamples && ` • ${numSamples} samples`}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-white rounded-lg transition-colors flex-shrink-0"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="p-4 sm:p-5">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
          {displayMetrics.map(({ key, value }) => {
            const colorClass = METRIC_COLORS[key] || 'text-gray-600 bg-gray-50 border-gray-200'
            const icon = METRIC_ICONS[key] || <Activity className="w-4 h-4" />
            
            return (
              <div
                key={key}
                className={`p-3 sm:p-4 rounded-xl border ${colorClass} transition-transform hover:scale-105`}
              >
                <div className="flex items-center gap-1.5 sm:gap-2 mb-1.5 sm:mb-2">
                  {icon}
                  <span className="text-xs font-medium uppercase tracking-wide truncate">
                    {formatMetricName(key)}
                  </span>
                </div>
                <div className="text-xl sm:text-2xl font-bold">
                  {(value * 100).toFixed(1)}%
                </div>
              </div>
            )
          })}
        </div>

        {/* Class-level metrics (optional) */}
        {config.show_class_metrics && Object.keys(classMetrics).length > 0 && (
          <div className="mt-5 pt-5 border-t border-gray-100">
            <h4 className="text-sm font-semibold text-gray-700 mb-3">Per-Class Metrics</h4>
            <div className="space-y-3">
              {Object.entries(classMetrics).map(([className, metrics]) => (
                <div key={className} className="bg-gray-50 rounded-lg p-3">
                  <div className="font-medium text-gray-900 mb-2">{className}</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(metrics)
                      .filter(([k]) => config.metrics.some(m => k.includes(m)))
                      .map(([metricKey, metricValue]) => {
                        // tp, fp, fn, tn, support are counts (integers), not percentages
                        const isCount = ['tp', 'fp', 'fn', 'tn', 'support'].includes(metricKey)
                        const displayValue = isCount ? metricValue.toString() : `${(metricValue * 100).toFixed(1)}%`
                        return (
                          <span
                            key={metricKey}
                            className="text-xs bg-white px-2 py-1 rounded border border-gray-200"
                          >
                            {formatMetricName(metricKey)}: {displayValue}
                          </span>
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

