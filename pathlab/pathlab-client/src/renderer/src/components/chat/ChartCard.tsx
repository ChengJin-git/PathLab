import { useState, useEffect, useRef } from 'react'
import { Loader2, BarChart3, AlertCircle, RefreshCw } from 'lucide-react'
import { getTaskQuickAnalysis, getTrainingTasks } from '../../api'
import {
  ConfusionMatrixChart,
  RocCurveChart,
  LossCurveChart,
  KFoldLossCurveChart,
  KMCurveChart,
  type ConfusionMatrixData,
  type RocCurveData,
  type LossCurveData,
  type KFoldLossCurveData,
  type KMCurveData
} from '../charts/AnalysisCharts'

export interface AgentChartConfig {
  task_id: string
  task_name?: string
  charts: string[]  // e.g., ['roc_curve', 'confusion_matrix', 'loss_curve', 'km_curve']
  submitted?: boolean
}

interface ChartCardProps {
  config: AgentChartConfig
  onError?: (error: string) => void
}

/**
 * Parse [CHART_CONFIG] block from message content
 */
export function parseChartConfig(content: string): AgentChartConfig | null {
  const match = content.match(/\[CHART_CONFIG\]([\s\S]*?)\[\/CHART_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [CHART_CONFIG] block from content for display
 */
export function removeChartConfigBlock(content: string): string {
  return content.replace(/\[CHART_CONFIG\][\s\S]*?\[\/CHART_CONFIG\]/g, '').trim()
}

export function ChartCard({ config, onError }: ChartCardProps) {
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [taskExists, setTaskExists] = useState(true)
  const [chartData, setChartData] = useState<{
    confusion_matrix?: ConfusionMatrixData
    roc_curve?: RocCurveData
    loss_curve?: LossCurveData | KFoldLossCurveData
    km_curve?: KMCurveData
  }>({})

  // Use ref for onError to avoid triggering useEffect on callback changes
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true)
      setError('')

      try {
        // Validate task exists
        const tasks = await getTrainingTasks()
        const found = tasks.some(t => t.task_id === config.task_id && t.status === 'completed')

        if (!found) {
          setTaskExists(false)
          setError('Task not found or not completed')
          return
        }
        setTaskExists(true)

        // Fetch quick analysis with specified charts
        const result = await getTaskQuickAnalysis(config.task_id, {
          charts: config.charts,
          runIfMissing: true
        })

        if (!result.has_analysis) {
          setError(result.message || 'No analysis results available')
          return
        }

        setChartData(result.chart_data || {})
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to fetch chart data'
        setError(msg)
        onErrorRef.current?.(msg)
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.task_id, config.charts.join(',')])

  const handleRefresh = () => {
    setIsLoading(true)
    setError('')
    window.location.reload()
  }

  if (isLoading) {
    return (
      <div className="mt-4 w-full bg-white border border-gray-200 rounded-2xl shadow-sm p-6">
        <div className="flex items-center justify-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
          <span className="text-gray-600">Loading charts...</span>
        </div>
      </div>
    )
  }

  if (!taskExists || error) {
    return (
      <div className="mt-4 w-full bg-white border border-red-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 bg-red-50 border-b border-red-100">
          <h3 className="font-semibold text-red-800 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            Charts Unavailable
          </h3>
        </div>
        <div className="p-5">
          <p className="text-red-700 text-sm">{error}</p>
          <p className="text-gray-500 text-xs mt-2">Task: {config.task_name || config.task_id}</p>
        </div>
      </div>
    )
  }

  const hasCharts = Object.keys(chartData).some(k => config.charts.includes(k))

  if (!hasCharts) {
    return (
      <div className="mt-4 w-full bg-white border border-amber-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 bg-amber-50 border-b border-amber-100">
          <h3 className="font-semibold text-amber-800 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            No Charts Available
          </h3>
        </div>
        <div className="p-5">
          <p className="text-amber-700 text-sm">
            Requested charts not found in analysis results.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 w-full bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-purple-50 to-indigo-50 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-purple-600" />
            Analysis Charts
          </h3>
          <p className="text-xs text-gray-500 mt-1">{config.task_name || config.task_id}</p>
        </div>
        <button onClick={handleRefresh} className="p-1.5 text-gray-400 hover:text-purple-600 hover:bg-white rounded-lg transition-colors" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Charts */}
      <div className="p-5 space-y-4">
        {config.charts.includes('roc_curve') && chartData.roc_curve && (
          <RocCurveChart data={chartData.roc_curve} title="ROC Curve" />
        )}
        {config.charts.includes('confusion_matrix') && chartData.confusion_matrix && (
          <ConfusionMatrixChart data={chartData.confusion_matrix} title="Confusion Matrix" />
        )}
        {config.charts.includes('loss_curve') && chartData.loss_curve && (
          'is_kfold' in chartData.loss_curve && chartData.loss_curve.is_kfold
            ? <KFoldLossCurveChart data={chartData.loss_curve as KFoldLossCurveData} title="Training Loss (K-Fold)" />
            : <LossCurveChart data={chartData.loss_curve as LossCurveData} title="Training Loss" />
        )}
        {config.charts.includes('km_curve') && chartData.km_curve && (
          <KMCurveChart data={chartData.km_curve} title="Kaplan-Meier Survival Curve" />
        )}
      </div>
    </div>
  )
}

