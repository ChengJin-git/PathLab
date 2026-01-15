import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Filter, Download, Eye, BarChart3, PieChart, AlertCircle, CheckCircle2, XCircle } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'

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

interface Stats {
  total: number
  analyzed: number
  accuracy: number
  label_distribution: Record<string, number>
  pred_distribution: Record<string, number>
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
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('table')
  const [stats, setStats] = useState<Stats | null>(null)

  useEffect(() => {
    loadResults()
  }, [])

  useEffect(() => {
    applyFilters()
  }, [results, searchQuery, filterLabel, filterPred, filterCorrect, sortBy])

  const loadResults = async () => {
    setLoading(true)
    try {
      // Fetch all WSI
      const wsiResponse = await fetch('/wsi')
      const wsiList = await wsiResponse.json()

      // Fetch results for each WSI
      const resultsPromises = wsiList.map(async (wsi: any) => {
        try {
          const resultResponse = await fetch(`/results/${wsi.wsi_id}`)
          const result = await resultResponse.json()
          
          const confidence = result.probs && result.pred 
            ? result.probs[result.pred] 
            : null

          return {
            wsi_id: wsi.wsi_id,
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
      calculateStats(allResults)
    } catch (error) {
      console.error('Failed to load results:', error)
    } finally {
      setLoading(false)
    }
  }

  const calculateStats = (data: WSIResult[]) => {
    const analyzed = data.filter(r => r.pred !== null)
    const correct = analyzed.filter(r => r.is_correct === true)
    
    const labelDist: Record<string, number> = {}
    const predDist: Record<string, number> = {}
    
    data.forEach(r => {
      labelDist[r.label] = (labelDist[r.label] || 0) + 1
      if (r.pred) {
        predDist[r.pred] = (predDist[r.pred] || 0) + 1
      }
    })

    setStats({
      total: data.length,
      analyzed: analyzed.length,
      accuracy: analyzed.length > 0 ? (correct.length / analyzed.length) * 100 : 0,
      label_distribution: labelDist,
      pred_distribution: predDist
    })
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

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Total Slides</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
              </div>
              <BarChart3 className="w-8 h-8 text-gray-400" />
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Analyzed</p>
                <p className="text-2xl font-bold text-indigo-600">{stats.analyzed}</p>
              </div>
              <CheckCircle2 className="w-8 h-8 text-indigo-400" />
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Accuracy</p>
                <p className="text-2xl font-bold text-green-600">{stats.accuracy.toFixed(1)}%</p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-400" />
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Pending</p>
                <p className="text-2xl font-bold text-gray-600">{stats.total - stats.analyzed}</p>
              </div>
              <AlertCircle className="w-8 h-8 text-gray-400" />
            </div>
          </Card>
        </div>
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
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">WSI ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Case ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">True Label</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Prediction</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Confidence</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredResults.map((result) => (
                <tr key={result.wsi_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    {getCorrectnessIcon(result.is_correct)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="text-sm font-medium text-gray-900" title={`UUID: ${result.wsi_id}`}>
                      {result.original_filename || result.wsi_id}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="text-sm text-gray-600">{result.case_id}</span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded">
                      {result.label}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {result.pred ? (
                      <span className={`px-2 py-1 text-xs font-medium rounded ${
                        result.is_correct 
                          ? 'bg-green-100 text-green-800' 
                          : 'bg-red-100 text-red-800'
                      }`}>
                        {result.pred}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">Not analyzed</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {result.confidence !== null ? (
                      <span className={`text-sm font-semibold ${getConfidenceColor(result.confidence)}`}>
                        {(result.confidence * 100).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <button
                      onClick={() => navigate(`/wsi/${result.wsi_id}`)}
                      className="text-indigo-600 hover:text-indigo-900 flex items-center gap-1"
                    >
                      <Eye className="w-4 h-4" />
                      <span className="text-sm">View</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {filteredResults.length === 0 && (
          <div className="text-center py-12">
            <AlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-600">No results found</p>
          </div>
        )}
      </Card>
    </div>
  )
}

