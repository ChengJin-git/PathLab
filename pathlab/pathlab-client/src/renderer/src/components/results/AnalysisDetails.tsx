import { Download, FlaskConical } from 'lucide-react'
import { ConfusionMatrixChart, RocCurveChart, LossCurveChart, KFoldLossCurveChart, KMCurveChart, type LossCurveData, type KFoldLossCurveData } from '../charts/AnalysisCharts'
import { getAuthToken } from '../../api'
import { API_BASE } from '../../config'

// --- Types shared with ResultsViewerPage ---

export interface ChartData {
  confusion_matrix?: import('../charts/AnalysisCharts').ConfusionMatrixData
  roc_curve?: import('../charts/AnalysisCharts').RocCurveData
  loss_curve?: LossCurveData | KFoldLossCurveData
  km_curve?: import('../charts/AnalysisCharts').KMCurveData
}

export interface KFoldMetricValue {
  mean: number
  std: number
}

export interface KFoldFoldResult {
  history: Record<string, number[]>
  val_metrics: Record<string, number>
}

export interface KFoldTrainingInfo {
  is_kfold: boolean
  num_folds: number
  folds: Record<string, KFoldFoldResult>
  aggregated: Record<string, KFoldMetricValue>
}

export interface BootstrapCI {
  lower: number
  upper: number
  n_samples: number
}

export interface BootstrapCIResult {
  metrics_ci: Record<string, BootstrapCI | null>
  class_metrics_ci?: Record<string, Record<string, BootstrapCI | null>>
  n_bootstrap: number
  confidence_level: number
}

export interface AnalysisSummary {
  analysis_id: string
  task_id: string
  task_type?: string
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
  kfold_training?: KFoldTrainingInfo
  bootstrap_ci?: BootstrapCIResult
  submitted_by?: string
}

// --- Auth helpers ---

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

function authUrl(url: string): string {
  const token = getAuthToken()
  if (!token) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}token=${encodeURIComponent(token)}`
}

// --- Component ---

export interface AnalysisDetailsProps {
  analysis: AnalysisSummary
  taskId?: string
  selectedMetrics?: string[]
  selectedCharts?: string[]
  isExternal?: boolean
}

export function AnalysisDetails({ analysis, taskId, selectedMetrics, selectedCharts, isExternal = false }: AnalysisDetailsProps) {
  const effectiveTaskId = analysis.task_id || taskId
  const isSurvival = analysis.task_type === 'wsi_survival' || analysis.task_type === 'survival' || analysis.task_type === 'external_validation_survival'

  const accentBg = isExternal ? 'bg-orange-600' : 'bg-indigo-600'
  const accentText = isExternal ? 'text-orange-600' : 'text-indigo-600'
  const accentTextHover = isExternal ? 'hover:text-orange-800' : 'hover:text-indigo-800'
  const accentHoverBorder = isExternal ? 'hover:border-orange-100' : 'hover:border-indigo-100'
  const accentCIBadge = isExternal ? 'bg-orange-100 text-orange-700' : 'bg-indigo-100 text-indigo-700'
  const accentRowHover = isExternal ? 'hover:bg-orange-50/30' : 'hover:bg-indigo-50/30'
  const accentDlBtn = isExternal ? 'bg-white hover:bg-orange-50 text-orange-700 border-orange-100 hover:border-orange-200' : 'bg-white hover:bg-indigo-50 text-indigo-700 border-indigo-100 hover:border-indigo-200'
  const accentDlIcon = isExternal ? 'bg-orange-50' : 'bg-indigo-50'

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

  const shouldShowMetric = (key: string): boolean => {
    if (!selectedMetrics || selectedMetrics.length === 0) return true
    const metricId = metricKeyToId[key]
    return metricId ? selectedMetrics.includes(metricId) : false
  }

  const shouldShowChart = (chartId: string): boolean => {
    if (!selectedCharts || selectedCharts.length === 0) return true
    return selectedCharts.includes(chartId)
  }

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

  const formatMetricValue = (key: string, value: number) => {
    if (key === 'c_index' || key === 'integrated_brier_score' || key === 'ibs') {
      return value.toFixed(4)
    }
    return `${(value * 100).toFixed(1)}%`
  }

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

      {/* Per-Class Metrics */}
      {!isSurvival && analysis.class_metrics && Object.keys(analysis.class_metrics).length > 0 && (() => {
        const perClassColumns = [
          { id: 'precision', label: 'Precision', getValue: (m: any) => m.precision || 0, getCIKey: 'precision' },
          { id: 'sensitivity', label: 'Sensitivity', getValue: (m: any) => m.sensitivity || m.recall || 0, getCIKey: 'sensitivity' },
          { id: 'specificity', label: 'Specificity', getValue: (m: any) => m.specificity || 0, getCIKey: 'specificity' },
          { id: 'f1', label: 'F1 Score', getValue: (m: any) => m.f1 || 0, getCIKey: 'f1' },
          { id: 'auc', label: 'AUC', getValue: (m: any) => m.auc || 0, getCIKey: 'auc' }
        ]
        const visibleColumns = perClassColumns.filter(col =>
          !selectedMetrics || selectedMetrics.length === 0 || selectedMetrics.includes(col.id)
        )
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

      {/* Charts */}
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