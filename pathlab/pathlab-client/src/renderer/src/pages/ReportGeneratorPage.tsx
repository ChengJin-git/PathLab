import { useState, useEffect, useMemo } from 'react'
import { useDraftState } from '../lib/useDraftState'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Download, Settings, FileSpreadsheet, FileDown, FileText, ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Select } from '../components/ui/select'
import { downloadBlobFile, fetchAllResults } from '../api'

interface ReportConfig {
  title: string
  includeStats: boolean
  includeResults: boolean
  includeCharts: boolean
  includeMetadata: boolean
  filterLabel: string
  format: 'csv' | 'json' | 'markdown'
}

interface WSIResult {
  wsi_id: string
  original_filename: string
  case_id: string
  label: string
  pred: string | null
  probs: Record<string, number> | null
  confidence?: number
  is_correct?: boolean
}

interface Stats {
  total: number
  analyzed: number
  accuracy: number
  label_distribution: Record<string, number>
  pred_distribution: Record<string, number>
  confusion_matrix: Record<string, Record<string, number>>
}

export default function ReportGeneratorPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [config, setConfig] = useDraftState<ReportConfig>('draft:report:config', {
    title: `PathLab Analysis Report - ${new Date().toLocaleDateString()}`,
    includeStats: true,
    includeResults: true,
    includeCharts: false,
    includeMetadata: true,
    filterLabel: 'all',
    format: 'csv'
  })
  const [generating, setGenerating] = useState(false)
  const [resultsPage, setResultsPage] = useState(1)
  const [resultsPageSize, setResultsPageSize] = useState(10)

  const { data: fetchedResults, isLoading: loading } = useQuery({
    queryKey: ['all-results'],
    queryFn: async () => {
      const response = await fetchAllResults()
      const items = response.items || []
      return items.map((item): WSIResult => {
        const confidence = item.probs && item.pred ? item.probs[item.pred] : undefined
        return {
          wsi_id: item.wsi_id,
          original_filename: item.original_filename || item.wsi_id,
          case_id: item.case_id || '',
          label: item.label || '',
          pred: item.pred || null,
          probs: item.probs,
          confidence,
          is_correct: item.pred && item.label ? item.pred === item.label : undefined
        }
      })
    },
    staleTime: 60 * 1000,
  })

  const results: WSIResult[] = fetchedResults ?? []
  const filteredResults = useMemo(
    () => config.filterLabel === 'all' ? results : results.filter(r => r.label === config.filterLabel),
    [config.filterLabel, results]
  )

  const calculateStats = (data: WSIResult[]): Stats => {
    const analyzed = data.filter(r => r.pred !== null)
    const correct = analyzed.filter(r => r.is_correct === true)
    
    const labelDist: Record<string, number> = {}
    const predDist: Record<string, number> = {}
    const confusionMatrix: Record<string, Record<string, number>> = {}
    
    data.forEach(r => {
      labelDist[r.label] = (labelDist[r.label] || 0) + 1
      if (r.pred) {
        predDist[r.pred] = (predDist[r.pred] || 0) + 1
        
        // Build confusion matrix
        if (!confusionMatrix[r.label]) {
          confusionMatrix[r.label] = {}
        }
        confusionMatrix[r.label][r.pred] = (confusionMatrix[r.label][r.pred] || 0) + 1
      }
    })

    return {
      total: data.length,
      analyzed: analyzed.length,
      accuracy: analyzed.length > 0 ? (correct.length / analyzed.length) * 100 : 0,
      label_distribution: labelDist,
      pred_distribution: predDist,
      confusion_matrix: confusionMatrix
    }
  }

  const stats: Stats | null = results.length > 0 ? calculateStats(results) : null
  const previewStats: Stats | null = filteredResults.length > 0 ? calculateStats(filteredResults) : null
  const totalResultPages = Math.max(1, Math.ceil(filteredResults.length / resultsPageSize) || 1)
  const pageStart = filteredResults.length === 0 ? 0 : (resultsPage - 1) * resultsPageSize + 1
  const pageEnd = Math.min(resultsPage * resultsPageSize, filteredResults.length)
  const paginatedResults = filteredResults.slice(
    (resultsPage - 1) * resultsPageSize,
    resultsPage * resultsPageSize
  )

  useEffect(() => {
    setResultsPage(1)
  }, [config.filterLabel, resultsPageSize])

  useEffect(() => {
    setResultsPage(page => Math.min(page, totalResultPages))
  }, [totalResultPages])

  const generateCSV = () => {
    const filteredData = config.filterLabel === 'all' 
      ? results 
      : results.filter(r => r.label === config.filterLabel)

    let csv = ''

    // Title
    if (config.includeMetadata) {
      csv += `# ${config.title}\n`
      csv += `# ${t('reportPage.csvGenerated')}: ${new Date().toISOString()}\n`
      csv += `# ${t('reportPage.totalSlides')}: ${filteredData.length}\n\n`
    }

    // Stats
    if (config.includeStats && stats) {
      csv += `# ${t('reportPage.summaryStatistics')}\n`
      csv += `${t('reportPage.totalSlides')},${stats.total}\n`
      csv += `${t('reportPage.analyzed')},${stats.analyzed}\n`
      csv += `${t('reportPage.accuracy')},${stats.accuracy.toFixed(2)}%\n\n`
      
      csv += `# ${t('reportPage.labelDistribution')}\n`
      csv += `${t('reportPage.label')},${t('reportPage.count')}\n`
      Object.entries(stats.label_distribution).forEach(([label, count]) => {
        csv += `${label},${count}\n`
      })
      csv += '\n'
    }

    // Results
    if (config.includeResults) {
      csv += `# ${t('reportPage.analysisResults')}\n`
      csv += `${t('reportPage.colFilename')},${t('reportPage.colCaseId')},${t('reportPage.colTrueLabel')},${t('reportPage.colPrediction')},${t('reportPage.colConfidence')},${t('reportPage.colCorrect')}\n`
      filteredData.forEach(r => {
        csv += `${r.original_filename},${r.case_id},${r.label},${r.pred || t('reportPage.na')},${
          r.confidence ? r.confidence.toFixed(4) : t('reportPage.na')
        },${r.is_correct === null ? t('reportPage.pending') : (r.is_correct ? t('reportPage.yes') : t('reportPage.no'))}\n`
      })
    }

    return csv
  }

  const generateJSON = () => {
    const filteredData = config.filterLabel === 'all' 
      ? results 
      : results.filter(r => r.label === config.filterLabel)

    const report: any = {
      metadata: {
        title: config.title,
        generated_at: new Date().toISOString(),
        total_slides: filteredData.length
      }
    }

    if (config.includeStats && stats) {
      report.statistics = {
        total: stats.total,
        analyzed: stats.analyzed,
        accuracy: stats.accuracy,
        label_distribution: stats.label_distribution,
        prediction_distribution: stats.pred_distribution,
        confusion_matrix: stats.confusion_matrix
      }
    }

    if (config.includeResults) {
      report.results = filteredData.map(r => ({
        filename: r.original_filename,
        wsi_id: r.wsi_id,
        case_id: r.case_id,
        true_label: r.label,
        prediction: r.pred,
        confidence: r.confidence,
        probabilities: r.probs,
        is_correct: r.is_correct
      }))
    }

    return JSON.stringify(report, null, 2)
  }

  const generateMarkdown = () => {
    const filteredData = config.filterLabel === 'all' 
      ? results 
      : results.filter(r => r.label === config.filterLabel)

    let md = `# ${config.title}\n\n`

    if (config.includeMetadata) {
      md += `**${t('reportPage.csvGenerated')}:** ${new Date().toLocaleString()}\n\n`
      md += `**${t('reportPage.totalSlides')}:** ${filteredData.length}\n\n`
    }

    if (config.includeStats && stats) {
      md += `## ${t('reportPage.summaryStatistics')}\n\n`
      md += `| ${t('reportPage.metric')} | ${t('reportPage.value')} |\n`
      md += `|--------|-------|\n`
      md += `| ${t('reportPage.totalSlides')} | ${stats.total} |\n`
      md += `| ${t('reportPage.analyzed')} | ${stats.analyzed} |\n`
      md += `| ${t('reportPage.accuracy')} | ${stats.accuracy.toFixed(2)}% |\n\n`

      md += `### ${t('reportPage.labelDistribution')}\n\n`
      md += `| ${t('reportPage.label')} | ${t('reportPage.count')} |\n`
      md += `|-------|-------|\n`
      Object.entries(stats.label_distribution).forEach(([label, count]) => {
        md += `| ${label} | ${count} |\n`
      })
      md += `\n`

      md += `### ${t('reportPage.confusionMatrix')}\n\n`
      const labels = Object.keys(stats.label_distribution)
      md += `| ${t('reportPage.truePred')} | ${labels.join(' | ')} |\n`
      md += `|${labels.map(() => '---').join('|')}|\n`
      labels.forEach(trueLabel => {
        const row = labels.map(predLabel => 
          stats.confusion_matrix[trueLabel]?.[predLabel] || 0
        )
        md += `| ${trueLabel} | ${row.join(' | ')} |\n`
      })
      md += `\n`
    }

    if (config.includeResults) {
      md += `## ${t('reportPage.analysisResults')}\n\n`
      md += `| ${t('reportPage.colFilename')} | ${t('reportPage.colCaseId')} | ${t('reportPage.colTrueLabel')} | ${t('reportPage.colPrediction')} | ${t('reportPage.colConfidence')} | ${t('reportPage.colCorrect')} |\n`
      md += `|--------|---------|------------|------------|------------|----------|\n`
      filteredData.forEach(r => {
        md += `| ${r.original_filename} | ${r.case_id} | ${r.label} | ${r.pred || t('reportPage.na')} | ${
          r.confidence ? (r.confidence * 100).toFixed(1) + '%' : t('reportPage.na')
        } | ${r.is_correct === null ? t('reportPage.pending') : (r.is_correct ? t('reportPage.yes') : t('reportPage.no'))} |\n`
      })
    }

    return md
  }

  const handleGenerate = () => {
    setGenerating(true)
    
    setTimeout(() => {
      let content = ''
      let filename = ''
      let mimeType = ''

      if (config.format === 'csv') {
        content = generateCSV()
        filename = `report_${new Date().toISOString().split('T')[0]}.csv`
        mimeType = 'text/csv'
      } else if (config.format === 'json') {
        content = generateJSON()
        filename = `report_${new Date().toISOString().split('T')[0]}.json`
        mimeType = 'application/json'
      } else {
        content = generateMarkdown()
        filename = `report_${new Date().toISOString().split('T')[0]}.md`
        mimeType = 'text/markdown'
      }

      const blob = new Blob([content], { type: mimeType })
      downloadBlobFile(blob, filename)

      setGenerating(false)
    }, 500)
  }

  const uniqueLabels = Array.from(new Set(results.map(r => r.label)))

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{t('reportPage.loadingData')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <PageHeader
        title={t('reportPage.title')}
        description={t('reportPage.description')}
      >
        <Button
          variant="outline"
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('reportPage.backToDashboard')}
        </Button>
      </PageHeader>

      <div className="grid gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <div className="space-y-6">
          {/* Configuration Panel */}
          <Card className="p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <Settings className="w-5 h-5 mr-2" />
              {t('reportPage.reportConfiguration')}
            </h2>

            <div className="space-y-4">
              {/* Title */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('reportPage.reportTitle')}
                </label>
                <input
                  type="text"
                  value={config.title}
                  onChange={(e) => setConfig({ ...config, title: e.target.value })}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                />
              </div>

              {/* Format */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('reportPage.exportFormat')}
                </label>
                <div className="grid grid-cols-3 gap-3">
                  <button
                    onClick={() => setConfig({ ...config, format: 'csv' })}
                    className={`px-4 py-3 rounded-lg border-2 transition-all ${
                      config.format === 'csv'
                        ? 'border-green-500 bg-green-50 text-green-700'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <FileSpreadsheet className="w-6 h-6 mx-auto mb-1" />
                    <span className="text-sm font-medium">CSV</span>
                  </button>
                  <button
                    onClick={() => setConfig({ ...config, format: 'json' })}
                    className={`px-4 py-3 rounded-lg border-2 transition-all ${
                      config.format === 'json'
                        ? 'border-green-500 bg-green-50 text-green-700'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <FileDown className="w-6 h-6 mx-auto mb-1" />
                    <span className="text-sm font-medium">JSON</span>
                  </button>
                  <button
                    onClick={() => setConfig({ ...config, format: 'markdown' })}
                    className={`px-4 py-3 rounded-lg border-2 transition-all ${
                      config.format === 'markdown'
                        ? 'border-green-500 bg-green-50 text-green-700'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <FileText className="w-6 h-6 mx-auto mb-1" />
                    <span className="text-sm font-medium">Markdown</span>
                  </button>
                </div>
              </div>

              {/* Filter */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('reportPage.filterByLabel')}
                </label>
                <Select
                  value={config.filterLabel}
                  onChange={(v) => setConfig({ ...config, filterLabel: v })}
                  options={[
                    { value: 'all', label: t('reportPage.allLabels') },
                    ...uniqueLabels.map(label => ({ value: label, label })),
                  ]}
                />
              </div>

              {/* Include Options */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('reportPage.includeInReport')}
                </label>
                <div className="space-y-2">
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={config.includeMetadata}
                      onChange={(e) => setConfig({ ...config, includeMetadata: e.target.checked })}
                      className="w-4 h-4 text-green-600 border-gray-300 rounded focus:ring-green-500"
                    />
                    <span className="ml-2 text-sm text-gray-700">{t('reportPage.includeMetadata')}</span>
                  </label>
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={config.includeStats}
                      onChange={(e) => setConfig({ ...config, includeStats: e.target.checked })}
                      className="w-4 h-4 text-green-600 border-gray-300 rounded focus:ring-green-500"
                    />
                    <span className="ml-2 text-sm text-gray-700">{t('reportPage.includeSummaryStats')}</span>
                  </label>
                  <label className="flex items-center">
                    <input
                      type="checkbox"
                      checked={config.includeResults}
                      onChange={(e) => setConfig({ ...config, includeResults: e.target.checked })}
                      className="w-4 h-4 text-green-600 border-gray-300 rounded focus:ring-green-500"
                    />
                    <span className="ml-2 text-sm text-gray-700">{t('reportPage.includeDetailedResults')}</span>
                  </label>
                </div>
              </div>
            </div>
          </Card>

          {/* Generate Button */}
          <Button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full px-8 py-6 text-lg gap-3 bg-green-600 hover:bg-green-700"
          >
            {generating ? (
              <>
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                {t('reportPage.generating')}
              </>
            ) : (
              <>
                <Download className="w-5 h-5" />
                {t('reportPage.generateAndDownload')}
              </>
            )}
          </Button>
        </div>

        <Card className="min-w-0 overflow-hidden">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-xl font-semibold text-gray-900">{t('reportPage.workspace')}</h2>
            <p className="mt-1 text-sm text-gray-500">{t('reportPage.resultsPreview')}</p>
          </div>

          <div className="max-h-[calc(100vh-220px)] min-h-[520px] overflow-y-auto px-6 py-5">
            {previewStats ? (
              <div className="space-y-6">
                <section>
                  <h3 className="text-base font-semibold text-gray-900 mb-3">{t('reportPage.preview')}</h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <div className="text-center p-4 bg-gray-50 rounded-lg">
                      <p className="text-sm text-gray-600 mb-1">{t('reportPage.totalSlides')}</p>
                      <p className="text-2xl font-bold text-gray-900">{previewStats.total}</p>
                    </div>
                    <div className="text-center p-4 bg-gray-50 rounded-lg">
                      <p className="text-sm text-gray-600 mb-1">{t('reportPage.analyzed')}</p>
                      <p className="text-2xl font-bold text-green-600">{previewStats.analyzed}</p>
                    </div>
                    <div className="text-center p-4 bg-gray-50 rounded-lg">
                      <p className="text-sm text-gray-600 mb-1">{t('reportPage.accuracy')}</p>
                      <p className="text-2xl font-bold text-blue-600">{previewStats.accuracy.toFixed(1)}%</p>
                    </div>
                  </div>
                </section>

                <section>
                  <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <h3 className="text-base font-semibold text-gray-900">{t('reportPage.analysisResults')}</h3>
                    <span className="text-sm text-gray-500">
                      {t('reportPage.showingResults', {
                        start: pageStart,
                        end: pageEnd,
                        total: filteredResults.length,
                      })}
                    </span>
                  </div>

                  <div className="overflow-x-auto rounded-lg border border-gray-200">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colFilename')}</th>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colCaseId')}</th>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colTrueLabel')}</th>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colPrediction')}</th>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colConfidence')}</th>
                          <th className="px-4 py-3 text-left font-semibold text-gray-600">{t('reportPage.colCorrect')}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 bg-white">
                        {paginatedResults.map((result) => (
                          <tr key={result.wsi_id}>
                            <td className="max-w-[220px] truncate px-4 py-3 text-gray-900" title={result.original_filename}>
                              {result.original_filename}
                            </td>
                            <td className="px-4 py-3 text-gray-600">{result.case_id || t('reportPage.na')}</td>
                            <td className="px-4 py-3 text-gray-600">{result.label || t('reportPage.na')}</td>
                            <td className="px-4 py-3 text-gray-600">{result.pred || t('reportPage.na')}</td>
                            <td className="px-4 py-3 text-gray-600">
                              {result.confidence !== undefined
                                ? `${(result.confidence * 100).toFixed(1)}%`
                                : t('reportPage.na')}
                            </td>
                            <td className="px-4 py-3 text-gray-600">
                              {result.is_correct === undefined
                                ? t('reportPage.pending')
                                : result.is_correct
                                  ? t('reportPage.yes')
                                  : t('reportPage.no')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 flex flex-col gap-3 border-t border-gray-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <span>{t('reportPage.itemsPerPage')}</span>
                      <Select
                        value={String(resultsPageSize)}
                        onChange={(value) => setResultsPageSize(Number(value))}
                        options={['10', '25', '50'].map(value => ({ value, label: value }))}
                        className="w-20"
                      />
                    </div>

                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <span className="text-sm text-gray-500">
                        {t('reportPage.pageInfo', {
                          current: Math.min(resultsPage, totalResultPages),
                          total: totalResultPages,
                        })}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setResultsPage(page => Math.max(1, page - 1))}
                          disabled={resultsPage <= 1}
                          className="gap-1"
                        >
                          <ChevronLeft className="h-3.5 w-3.5" />
                          {t('reportPage.previousPage')}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setResultsPage(page => Math.min(totalResultPages, page + 1))}
                          disabled={resultsPage >= totalResultPages}
                          className="gap-1"
                        >
                          {t('reportPage.nextPage')}
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            ) : (
              <div className="flex min-h-[440px] items-center justify-center rounded-lg border border-dashed border-gray-200 text-center">
                <p className="text-sm text-gray-500">{t('reportPage.noResults')}</p>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
