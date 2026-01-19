import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Download, Eye, BarChart3, AlertCircle, CheckCircle2, XCircle, ChevronDown, ChevronUp, LineChart, Activity } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'

interface WSIResult {
  wsi_id: string
  original_filename?: string
  case_id: string
  label: string
  pred: string | null
  probs: Record<string, number> | null
  created_at: string
  confidence?: number
  is_correct?: boolean
}

interface ClassMetrics {
  tp: number
  fp: number
  fn: number
  tn: number
  precision: number
  recall: number
  sensitivity: number
  specificity: number
  f1: number
  support: number
}

interface RocPoint {
  fpr: number
  tpr: number
  threshold: number
}

interface AnalysisStats {
  total: number
  analyzed: number
  is_binary: boolean
  classes: string[]
  metrics: {
    accuracy: number
    macro_precision: number
    macro_recall: number
    macro_sensitivity: number
    macro_specificity: number
    macro_f1: number
    macro_auc?: number
    weighted_precision: number
    weighted_recall: number
    weighted_f1: number
  }
  class_metrics: Record<string, ClassMetrics>
  confusion_matrix: {
    matrix: Record<string, Record<string, number>>
    classes: string[]
  }
  roc_data: Record<string, { points: RocPoint[], auc: number }>
  label_distribution: Record<string, number>
  prediction_distribution: Record<string, number>
}

export default function ResultsViewerPage() {
  const navigate = useNavigate()
  const [results, setResults] = useState<WSIResult[]>([])
  const [filteredResults, setFilteredResults] = useState<WSIResult[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterLabel, setFilterLabel] = useState<string>('all')
  const [filterPred, setFilterPred] = useState<string>('all')
  const [filterCorrect, setFilterCorrect] = useState<string>('all')
  const [sortBy, setSortBy] = useState<'confidence' | 'case_id' | 'created_at'>('confidence')
  const [analysisStats, setAnalysisStats] = useState<AnalysisStats | null>(null)
  const [showAdvancedStats, setShowAdvancedStats] = useState(false)
  const [selectedRocClass, setSelectedRocClass] = useState<string | null>(null)
  const rocCanvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    loadResults()
    loadAnalysisStats()
  }, [])

  useEffect(() => {
    applyFilters()
  }, [results, searchQuery, filterLabel, filterPred, filterCorrect, sortBy])

  // Draw ROC curve when data or selection changes
  useEffect(() => {
    if (analysisStats?.roc_data && rocCanvasRef.current) {
      drawRocCurve()
    }
  }, [analysisStats, selectedRocClass])

  const loadResults = async () => {
    setLoading(true)
    try {
      // Fetch all WSI
      const wsiResponse = await fetch(`${API_BASE}/wsi`)
      const wsiData = await wsiResponse.json()
      const wsiList = wsiData.items || wsiData

      // Fetch results for each WSI
      const resultsPromises = wsiList.map(async (wsi: any) => {
        try {
          const resultResponse = await fetch(`${API_BASE}/results/${wsi.wsi_id}`)
          const result = await resultResponse.json()

          const confidence = result.probs && result.pred
            ? result.probs[result.pred]
            : null

          return {
            wsi_id: wsi.wsi_id,
            original_filename: wsi.original_filename,
            case_id: wsi.case_id,
            label: wsi.label,
            pred: result.pred,
            probs: result.probs,
            created_at: result.created_at || wsi.created_at,
            confidence,
            is_correct: result.pred ? result.pred === wsi.label : null
          }
        } catch (error) {
          return {
            wsi_id: wsi.wsi_id,
            original_filename: wsi.original_filename,
            case_id: wsi.case_id,
            label: wsi.label,
            pred: null,
            probs: null,
            created_at: wsi.created_at,
            confidence: null,
            is_correct: null
          }
        }
      })

      const allResults = await Promise.all(resultsPromises)
      setResults(allResults)
    } catch (error) {
      console.error('Failed to load results:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadAnalysisStats = async () => {
    try {
      const response = await fetch(`${API_BASE}/results/analysis/stats`)
      if (response.ok) {
        const stats = await response.json()
        setAnalysisStats(stats)
        // Set default selected class for ROC
        if (stats.classes?.length > 0 && !selectedRocClass) {
          setSelectedRocClass(stats.classes[0])
        }
      }
    } catch (error) {
      console.error('Failed to load analysis stats:', error)
    }
  }

  const drawRocCurve = () => {
    const canvas = rocCanvasRef.current
    if (!canvas || !analysisStats?.roc_data) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const width = canvas.width
    const height = canvas.height
    const padding = 40

    // Clear canvas
    ctx.fillStyle = '#f8fafc'
    ctx.fillRect(0, 0, width, height)

    // Draw grid
    ctx.strokeStyle = '#e2e8f0'
    ctx.lineWidth = 1
    for (let i = 0; i <= 10; i++) {
      const x = padding + (i / 10) * (width - 2 * padding)
      const y = padding + (i / 10) * (height - 2 * padding)
      ctx.beginPath()
      ctx.moveTo(x, padding)
      ctx.lineTo(x, height - padding)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(padding, y)
      ctx.lineTo(width - padding, y)
      ctx.stroke()
    }

    // Draw diagonal line (random classifier)
    ctx.strokeStyle = '#94a3b8'
    ctx.lineWidth = 1
    ctx.setLineDash([5, 5])
    ctx.beginPath()
    ctx.moveTo(padding, height - padding)
    ctx.lineTo(width - padding, padding)
    ctx.stroke()
    ctx.setLineDash([])

    // Draw ROC curves
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']
    let colorIdx = 0

    for (const [className, data] of Object.entries(analysisStats.roc_data)) {
      if (selectedRocClass && className !== selectedRocClass) continue

      const points = data.points
      if (!points || points.length < 2) continue

      ctx.strokeStyle = colors[colorIdx % colors.length]
      ctx.lineWidth = 2
      ctx.beginPath()

      for (let i = 0; i < points.length; i++) {
        const x = padding + points[i].fpr * (width - 2 * padding)
        const y = height - padding - points[i].tpr * (height - 2 * padding)
        if (i === 0) {
          ctx.moveTo(x, y)
        } else {
          ctx.lineTo(x, y)
        }
      }
      ctx.stroke()
      colorIdx++
    }

    // Draw axes labels
    ctx.fillStyle = '#334155'
    ctx.font = '12px Inter, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('False Positive Rate (1 - Specificity)', width / 2, height - 8)

    ctx.save()
    ctx.translate(12, height / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.fillText('True Positive Rate (Sensitivity)', 0, 0)
    ctx.restore()

    // Draw axis ticks
    ctx.fillStyle = '#64748b'
    ctx.font = '10px Inter, sans-serif'
    for (let i = 0; i <= 10; i += 2) {
      const val = (i / 10).toFixed(1)
      const x = padding + (i / 10) * (width - 2 * padding)
      ctx.textAlign = 'center'
      ctx.fillText(val, x, height - padding + 15)
      ctx.textAlign = 'right'
      ctx.fillText(val, padding - 5, height - padding - (i / 10) * (height - 2 * padding) + 4)
    }
  }

  const applyFilters = () => {
    let filtered = [...results]

    // Search filter
    if (searchQuery) {
      filtered = filtered.filter(r => 
        r.wsi_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        r.case_id.toLowerCase().includes(searchQuery.toLowerCase())
      )
    }

    // Label filter
    if (filterLabel !== 'all') {
      filtered = filtered.filter(r => r.label === filterLabel)
    }

    // Prediction filter
    if (filterPred !== 'all') {
      if (filterPred === 'none') {
        filtered = filtered.filter(r => r.pred === null)
      } else {
        filtered = filtered.filter(r => r.pred === filterPred)
      }
    }

    // Correctness filter
    if (filterCorrect !== 'all') {
      if (filterCorrect === 'correct') {
        filtered = filtered.filter(r => r.is_correct === true)
      } else if (filterCorrect === 'incorrect') {
        filtered = filtered.filter(r => r.is_correct === false)
      } else if (filterCorrect === 'pending') {
        filtered = filtered.filter(r => r.pred === null)
      }
    }

    // Sort
    filtered.sort((a, b) => {
      if (sortBy === 'confidence') {
        return (b.confidence || 0) - (a.confidence || 0)
      } else if (sortBy === 'case_id') {
        return a.case_id.localeCompare(b.case_id)
      } else {
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      }
    })

    setFilteredResults(filtered)
  }

  const getConfidenceColor = (confidence: number | null) => {
    if (!confidence) return 'text-gray-400'
    if (confidence >= 0.9) return 'text-green-600'
    if (confidence >= 0.7) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getCorrectnessIcon = (isCorrect: boolean | null) => {
    if (isCorrect === null) return <AlertCircle className="w-5 h-5 text-gray-400" />
    if (isCorrect) return <CheckCircle2 className="w-5 h-5 text-green-600" />
    return <XCircle className="w-5 h-5 text-red-600" />
  }

  const exportToCSV = () => {
    const headers = ['WSI ID', 'Case ID', 'True Label', 'Prediction', 'Confidence', 'Correct']
    const rows = filteredResults.map(r => [
      r.wsi_id,
      r.case_id,
      r.label,
      r.pred || 'N/A',
      r.confidence ? r.confidence.toFixed(4) : 'N/A',
      r.is_correct === null ? 'Pending' : (r.is_correct ? 'Yes' : 'No')
    ])

    const csv = [headers, ...rows].map(row => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `results_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  const uniqueLabels = Array.from(new Set(results.map(r => r.label)))
  const uniquePreds = Array.from(new Set(results.map(r => r.pred).filter(p => p !== null))) as string[]

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading results...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <PageHeader
        title="Results Viewer"
        description="Browse and analyze AI prediction results"
      />

      {/* Basic Stats Cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Total</p>
              <p className="text-2xl font-bold text-gray-900">{results.length}</p>
            </div>
            <BarChart3 className="w-6 h-6 text-gray-400" />
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Analyzed</p>
              <p className="text-2xl font-bold text-indigo-600">{results.filter(r => r.pred).length}</p>
            </div>
            <CheckCircle2 className="w-6 h-6 text-indigo-400" />
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Pending</p>
              <p className="text-2xl font-bold text-gray-500">{results.filter(r => !r.pred).length}</p>
            </div>
            <AlertCircle className="w-6 h-6 text-gray-400" />
          </div>
        </Card>
      </div>

      {/* Analysis Stats - Only show when available and analyzed > 0 */}
      {analysisStats && analysisStats.analyzed > 0 && (
        <>
          {/* Toggle for Advanced Analysis */}
          <div className="mb-4">
            <button
              onClick={() => setShowAdvancedStats(!showAdvancedStats)}
              className="flex items-center gap-2 text-sm font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              {showAdvancedStats ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              {showAdvancedStats ? 'Hide' : 'Show'} Analysis Results
            </button>
          </div>
          {/* Analysis Stats Panel */}
          {showAdvancedStats && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              {/* Confusion Matrix */}
              <Card className="p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-indigo-500" />
                  Confusion Matrix
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th className="p-2 text-left text-gray-500 font-medium">True \ Pred</th>
                        {analysisStats.confusion_matrix.classes.map(cls => (
                          <th key={cls} className="p-2 text-center text-gray-700 font-semibold">{cls}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {analysisStats.confusion_matrix.classes.map(trueClass => (
                        <tr key={trueClass}>
                          <td className="p-2 text-gray-700 font-semibold">{trueClass}</td>
                          {analysisStats.confusion_matrix.classes.map(predClass => {
                            const count = analysisStats.confusion_matrix.matrix[trueClass]?.[predClass] || 0
                            const isCorrect = trueClass === predClass
                            const maxCount = Math.max(
                              ...Object.values(analysisStats.confusion_matrix.matrix).flatMap(row => Object.values(row))
                            )
                            const intensity = count / maxCount
                            return (
                              <td
                                key={predClass}
                                className={`p-2 text-center font-medium ${
                                  isCorrect
                                    ? 'bg-green-100 text-green-800'
                                    : count > 0
                                    ? 'bg-red-100 text-red-800'
                                    : 'bg-gray-50 text-gray-400'
                                }`}
                                style={{
                                  opacity: count > 0 ? 0.5 + intensity * 0.5 : 1
                                }}
                              >
                                {count}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* ROC Curve */}
              <Card className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                    <LineChart className="w-5 h-5 text-indigo-500" />
                    ROC Curve
                    {analysisStats.metrics.macro_auc && (
                      <span className="text-sm font-normal text-gray-500">
                        (Macro AUC: {(analysisStats.metrics.macro_auc * 100).toFixed(1)}%)
                      </span>
                    )}
                  </h3>
                  {analysisStats.classes.length > 1 && (
                    <select
                      value={selectedRocClass || ''}
                      onChange={(e) => setSelectedRocClass(e.target.value)}
                      className="text-sm px-3 py-1 border border-gray-300 rounded-lg"
                    >
                      {analysisStats.classes.map(cls => (
                        <option key={cls} value={cls}>
                          {cls} (AUC: {((analysisStats.roc_data[cls]?.auc || 0) * 100).toFixed(1)}%)
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <canvas
                  ref={rocCanvasRef}
                  width={400}
                  height={300}
                  className="w-full h-auto"
                />
              </Card>

              {/* Per-Class Metrics */}
              <Card className="p-6 lg:col-span-2">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-indigo-500" />
                  Per-Class Metrics
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200">
                        <th className="p-3 text-left text-gray-500 font-medium">Class</th>
                        <th className="p-3 text-center text-gray-500 font-medium">Support</th>
                        <th className="p-3 text-center text-gray-500 font-medium">Precision</th>
                        <th className="p-3 text-center text-gray-500 font-medium">Recall/Sens.</th>
                        <th className="p-3 text-center text-gray-500 font-medium">Specificity</th>
                        <th className="p-3 text-center text-gray-500 font-medium">F1 Score</th>
                        <th className="p-3 text-center text-gray-500 font-medium">AUC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysisStats.classes.map(cls => {
                        const metrics = analysisStats.class_metrics[cls]
                        const auc = analysisStats.roc_data[cls]?.auc
                        return (
                          <tr key={cls} className="border-b border-gray-100 hover:bg-gray-50">
                            <td className="p-3 font-semibold text-gray-900">{cls}</td>
                            <td className="p-3 text-center text-gray-600">{metrics.support}</td>
                            <td className="p-3 text-center">
                              <span className="font-medium text-blue-600">{(metrics.precision * 100).toFixed(1)}%</span>
                            </td>
                            <td className="p-3 text-center">
                              <span className="font-medium text-purple-600">{(metrics.recall * 100).toFixed(1)}%</span>
                            </td>
                            <td className="p-3 text-center">
                              <span className="font-medium text-teal-600">{(metrics.specificity * 100).toFixed(1)}%</span>
                            </td>
                            <td className="p-3 text-center">
                              <span className="font-medium text-orange-600">{(metrics.f1 * 100).toFixed(1)}%</span>
                            </td>
                            <td className="p-3 text-center">
                              {auc !== undefined ? (
                                <span className="font-medium text-green-600">{(auc * 100).toFixed(1)}%</span>
                              ) : (
                                <span className="text-gray-400">-</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                      {/* Macro Average Row */}
                      <tr className="bg-gray-50 font-semibold">
                        <td className="p-3 text-gray-900">Macro Avg</td>
                        <td className="p-3 text-center text-gray-600">{analysisStats.analyzed}</td>
                        <td className="p-3 text-center text-blue-600">{(analysisStats.metrics.macro_precision * 100).toFixed(1)}%</td>
                        <td className="p-3 text-center text-purple-600">{(analysisStats.metrics.macro_recall * 100).toFixed(1)}%</td>
                        <td className="p-3 text-center text-teal-600">{(analysisStats.metrics.macro_specificity * 100).toFixed(1)}%</td>
                        <td className="p-3 text-center text-orange-600">{(analysisStats.metrics.macro_f1 * 100).toFixed(1)}%</td>
                        <td className="p-3 text-center text-green-600">
                          {analysisStats.metrics.macro_auc !== undefined
                            ? `${(analysisStats.metrics.macro_auc * 100).toFixed(1)}%`
                            : '-'}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          )}
        </>
      )}

      {/* Filters and Search */}
      <Card className="p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search WSI or Case ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>

          {/* Label Filter */}
          <select
            value={filterLabel}
            onChange={(e) => setFilterLabel(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          >
            <option value="all">All Labels</option>
            {uniqueLabels.map(label => (
              <option key={label} value={label}>{label}</option>
            ))}
          </select>

          {/* Prediction Filter */}
          <select
            value={filterPred}
            onChange={(e) => setFilterPred(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          >
            <option value="all">All Predictions</option>
            <option value="none">Not Analyzed</option>
            {uniquePreds.map(pred => (
              <option key={pred} value={pred}>{pred}</option>
            ))}
          </select>

          {/* Correctness Filter */}
          <select
            value={filterCorrect}
            onChange={(e) => setFilterCorrect(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          >
            <option value="all">All Status</option>
            <option value="correct">Correct</option>
            <option value="incorrect">Incorrect</option>
            <option value="pending">Pending</option>
          </select>

          {/* Sort */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          >
            <option value="confidence">Sort by Confidence</option>
            <option value="case_id">Sort by Case ID</option>
            <option value="created_at">Sort by Date</option>
          </select>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-200">
          <p className="text-sm text-gray-600">
            Showing {filteredResults.length} of {results.length} results
          </p>
          <Button
            onClick={exportToCSV}
            className="bg-green-600 hover:bg-green-700 text-white gap-2"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </Button>
        </div>
      </Card>

      {/* Results Table */}
      <Card className="overflow-hidden bg-white/50 backdrop-blur-sm border-gray-200/60 shadow-sm rounded-2xl">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50/50 border-b border-gray-100 backdrop-blur-md">
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">WSI ID</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Case ID</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">True Label</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Prediction</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Confidence</th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-transparent">
              {filteredResults.map((result) => (
                <tr key={result.wsi_id} className="group hover:bg-white/60 transition-colors border-l-2 border-transparent hover:border-gray-200">
                  <td className="px-6 py-5 whitespace-nowrap">
                    {getCorrectnessIcon(result.is_correct)}
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    <span className="text-sm font-semibold text-gray-900 block" title={`UUID: ${result.wsi_id}`}>
                      {result.original_filename || result.wsi_id}
                    </span>
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    <span className="text-sm text-gray-500 font-medium">{result.case_id}</span>
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    <span className="px-3 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded-full border border-gray-200">
                      {result.label}
                    </span>
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    {result.pred ? (
                      <span className={`px-3 py-1 text-xs font-medium rounded-full border shadow-sm ${
                        result.is_correct 
                          ? 'bg-green-50 text-green-700 border-green-200' 
                          : 'bg-red-50 text-red-700 border-red-200'
                      }`}>
                        {result.pred}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400 italic">Not analyzed</span>
                    )}
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    {result.confidence !== null ? (
                      <span className={`text-sm font-bold ${getConfidenceColor(result.confidence)}`}>
                        {(result.confidence * 100).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-6 py-5 whitespace-nowrap">
                    <button
                      onClick={() => navigate(`/wsi/${result.wsi_id}`)}
                      className="text-gray-400 hover:text-blue-600 flex items-center gap-2 transition-colors"
                    >
                      <Eye className="w-4 h-4" />
                      <span className="text-sm font-medium">View</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {filteredResults.length === 0 && (
          <div className="text-center py-16">
            <div className="bg-gray-50 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
              <AlertCircle className="w-8 h-8 text-gray-400" />
            </div>
            <p className="text-gray-900 font-medium">No results found</p>
             <p className="text-gray-500 text-sm mt-1">Try adjusting your filters</p>
          </div>
        )}
      </Card>
    </div>
  )
}

