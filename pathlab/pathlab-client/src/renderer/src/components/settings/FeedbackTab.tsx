import { useState, useEffect, useCallback } from 'react'
import { MessageSquare, RefreshCw, Trash2, Download, X, ThumbsUp, ThumbsDown, Clock } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import {
  MessageFeedback, FeedbackStats,
  getAdminFeedbacks, getFeedbackStats, exportFeedbacks as exportFeedbacksApi,
  resetAllFeedbacks, startAsyncExport, getExportTaskStatus, downloadExportFile,
  ExportTaskStatus
} from '../../api'
import { ShowConfirmDialog } from './ConfirmDialog'

export interface FeedbackTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export function FeedbackTab({ showConfirmDialog, closeConfirmDialog }: FeedbackTabProps) {
  // State
  const [feedbacks, setFeedbacks] = useState<MessageFeedback[]>([])
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
  const [feedbackTotal, setFeedbackTotal] = useState(0)
  const [feedbackPage, setFeedbackPage] = useState(0)
  const [feedbackLimit] = useState(20)
  const [loadingFeedbacks, setLoadingFeedbacks] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [feedbackTypeFilter, setFeedbackTypeFilter] = useState<'thumbs_up' | 'thumbs_down' | null>(null)
  const [helpfulnessFilter, setHelpfulnessFilter] = useState<'helpful' | 'not_helpful' | null>(null)
  const [exportingFeedbacks, setExportingFeedbacks] = useState(false)
  const [resettingFeedbacks, setResettingFeedbacks] = useState(false)
  const [exportDateFrom, setExportDateFrom] = useState<string>(() => {
    const d = new Date(); d.setMonth(d.getMonth() - 3); return d.toISOString().split('T')[0]
  })
  const [exportDateTo, setExportDateTo] = useState<string>(() => new Date().toISOString().split('T')[0])
  const [exportTaskId, setExportTaskId] = useState<string | null>(null)
  const [exportTaskStatus, setExportTaskStatus] = useState<ExportTaskStatus | null>(null)
  const [exportPollingInterval, setExportPollingInterval] = useState<NodeJS.Timeout | null>(null)

  // Load feedbacks
  const loadFeedbacks = useCallback(async () => {
    setLoadingFeedbacks(true)
    setFeedbackError(null)
    try {
      const [feedbackResponse, statsResponse] = await Promise.all([
        getAdminFeedbacks(feedbackPage * feedbackLimit, feedbackLimit, feedbackTypeFilter, helpfulnessFilter),
        getFeedbackStats()
      ])
      setFeedbacks(feedbackResponse.feedbacks)
      setFeedbackTotal(feedbackResponse.total)
      setFeedbackStats(statsResponse)
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to load feedbacks')
    } finally {
      setLoadingFeedbacks(false)
    }
  }, [feedbackPage, feedbackLimit, feedbackTypeFilter, helpfulnessFilter])

  // Load on mount and when filters change
  useEffect(() => { loadFeedbacks() }, [loadFeedbacks])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { if (exportPollingInterval) clearInterval(exportPollingInterval) }
  }, [exportPollingInterval])

  // Async export
  const handleAsyncExport = async (format: 'json' | 'csv') => {
    if (exportPollingInterval) { clearInterval(exportPollingInterval); setExportPollingInterval(null) }
    setExportTaskId(null); setExportTaskStatus(null); setExportingFeedbacks(true); setFeedbackError(null)
    try {
      const result = await startAsyncExport(format, exportDateFrom || null, exportDateTo || null, feedbackTypeFilter, helpfulnessFilter)
      setExportTaskId(result.task_id)
      const pollStatus = async () => {
        try {
          const status = await getExportTaskStatus(result.task_id)
          setExportTaskStatus(status)
          if (status.status === 'completed') {
            if (exportPollingInterval) { clearInterval(exportPollingInterval); setExportPollingInterval(null) }
            setExportingFeedbacks(false)
            const blob = await downloadExportFile(result.task_id)
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a'); a.href = url
            a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.${format}`
            document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
          } else if (status.status === 'failed') {
            if (exportPollingInterval) { clearInterval(exportPollingInterval); setExportPollingInterval(null) }
            setExportingFeedbacks(false); setFeedbackError(status.error_message || 'Export failed')
          }
        } catch { /* continue polling */ }
      }
      const interval = setInterval(pollStatus, 2000); setExportPollingInterval(interval)
      await pollStatus()
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to start export'); setExportingFeedbacks(false)
    }
  }

  // Export feedbacks (sync for small datasets, async for large)
  const handleExportFeedbacks = async (format: 'csv' | 'json') => {
    if (feedbackStats && feedbackStats.total_feedbacks > 1000) { await handleAsyncExport(format); return }
    setExportingFeedbacks(true)
    try {
      const result = await exportFeedbacksApi(format)
      if (format === 'csv' && result instanceof Blob) {
        const url = URL.createObjectURL(result); const a = document.createElement('a'); a.href = url
        a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.csv`
        document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
      } else if (format === 'json' && !(result instanceof Blob)) {
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url
        a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.json`
        document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
      }
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to export feedbacks')
    } finally { setExportingFeedbacks(false) }
  }

  // Reset all feedbacks
  const handleResetFeedbacks = () => {
    showConfirmDialog({
      title: 'Reset All Feedbacks',
      message: 'Are you sure you want to delete ALL feedback data? This action cannot be undone.',
      confirmText: 'Delete All', confirmVariant: 'danger', showCancel: true,
      onConfirm: async () => {
        closeConfirmDialog()
        setResettingFeedbacks(true)
        try {
          const result = await resetAllFeedbacks()
          setTimeout(() => {
            showConfirmDialog({
              title: 'Success', message: `Successfully deleted ${result.deleted_count} feedbacks.`,
              confirmText: 'OK', confirmVariant: 'info', showCancel: false,
              onConfirm: () => closeConfirmDialog()
            })
          }, 100)
          await loadFeedbacks()
        } catch (err) {
          setFeedbackError(err instanceof Error ? err.message : 'Failed to reset feedbacks')
        } finally { setResettingFeedbacks(false) }
      }
    })
  }
  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
          <MessageSquare className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
          User Feedback Analytics
        </h2>
        <div className="flex gap-2 self-end sm:self-auto">
          <Button variant="outline" onClick={loadFeedbacks} disabled={loadingFeedbacks} className="gap-2">
            <RefreshCw className={`w-4 h-4 ${loadingFeedbacks ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            variant="outline"
            onClick={handleResetFeedbacks}
            disabled={loadingFeedbacks || resettingFeedbacks}
            className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
          >
            <Trash2 className={`w-4 h-4 ${resettingFeedbacks ? 'animate-pulse' : ''}`} />
            Reset All
          </Button>
        </div>
      </div>

      {/* Export Section & Filters */}
      <div className="mb-6 p-4 bg-gray-50/50 border border-gray-200/60 rounded-xl space-y-4">
        <div className="flex flex-col xl:flex-row gap-4 items-end xl:items-center justify-between">
          {/* Filters */}
          <div className="flex flex-wrap gap-3 items-center w-full xl:w-auto">
            <div className="w-full sm:w-48">
              <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Feedback Type</Label>
              <Select
                value={feedbackTypeFilter || ''}
                onChange={(val) => { setFeedbackTypeFilter(val ? val as 'thumbs_up' | 'thumbs_down' : null); setFeedbackPage(0) }}
                options={[
                  { value: '', label: 'All Types' },
                  { value: 'thumbs_up', label: 'Thumbs Up' },
                  { value: 'thumbs_down', label: 'Thumbs Down' }
                ]}
              />
            </div>
            <div className="w-full sm:w-48">
              <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Helpfulness</Label>
              <Select
                value={helpfulnessFilter || ''}
                onChange={(val) => { setHelpfulnessFilter(val ? val as 'helpful' | 'not_helpful' : null); setFeedbackPage(0) }}
                options={[
                  { value: '', label: 'All Ratings' },
                  { value: 'helpful', label: 'Helpful' },
                  { value: 'not_helpful', label: 'Not Helpful' }
                ]}
              />
            </div>
          </div>

          <div className="hidden xl:block w-px h-10 bg-gray-200 mx-2"></div>

          {/* Date Range + Export */}
          <div className="flex flex-col sm:flex-row flex-wrap gap-3 items-end w-full xl:w-auto">
            <div>
              <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Date Range</Label>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="date"
                  value={exportDateFrom}
                  onChange={(e) => setExportDateFrom(e.target.value)}
                  className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                />
                <span className="text-gray-400">-</span>
                <input
                  type="date"
                  value={exportDateTo}
                  onChange={(e) => setExportDateTo(e.target.value)}
                  className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                />
                {(exportDateFrom || exportDateTo) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => { setExportDateFrom(''); setExportDateTo('') }}
                    className="h-9 w-9 p-0 text-gray-400 hover:text-gray-600"
                    title="Clear dates"
                  >
                    <X className="w-4 h-4" />
                  </Button>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => handleExportFeedbacks('csv')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 gap-2 bg-white">
                <Download className="w-4 h-4" />CSV
              </Button>
              <Button variant="outline" onClick={() => handleExportFeedbacks('json')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 gap-2 bg-white">
                <Download className="w-4 h-4" />JSON
              </Button>
            </div>
          </div>
        </div>
      </div>

      {loadingFeedbacks ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-6 h-6 animate-spin text-gray-400 mr-2" />
          <span className="text-gray-500">Loading feedbacks...</span>
        </div>
      ) : feedbacks.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <MessageSquare className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <p>No feedbacks found</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Message Content</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Username</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Feedback</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Helpfulness</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Task</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time to Action</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {feedbacks.map((feedback) => (
                <tr key={feedback.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-900 font-mono text-xs">{feedback.id}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs max-w-[200px] truncate" title={feedback.message_content || ''}>
                    {feedback.message_content
                      ? feedback.message_content.length > 50
                        ? feedback.message_content.slice(0, 50) + '...'
                        : feedback.message_content
                      : '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-900 text-sm">
                    {feedback.username || feedback.user_id.slice(0, 8) + '...'}
                  </td>
                  <td className="px-4 py-3">
                    {feedback.feedback_type === 'thumbs_up' && (
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                        <ThumbsUp className="w-3 h-3" /> Up
                      </span>
                    )}
                    {feedback.feedback_type === 'thumbs_down' && (
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700">
                        <ThumbsDown className="w-3 h-3" /> Down
                      </span>
                    )}
                    {!feedback.feedback_type && <span className="text-gray-400">-</span>}
                  </td>
                  <td className="px-4 py-3">
                    {feedback.task_helpfulness === 'helpful' && (
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">Helpful</span>
                    )}
                    {feedback.task_helpfulness === 'not_helpful' && (
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-700">Not Helpful</span>
                    )}
                    {!feedback.task_helpfulness && <span className="text-gray-400">-</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs max-w-[150px]">
                    {feedback.task_title ? (
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-purple-50 text-purple-700 truncate capitalize" title={`${feedback.task_type?.replace(/_/g, ' ')}: ${feedback.task_title}`}>
                        {feedback.task_type && <span className="font-medium">{feedback.task_type.replace(/_/g, ' ')}:</span>}
                        <span className="truncate max-w-[80px]">{feedback.task_title}</span>
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {feedback.time_to_action_seconds != null ? (
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-cyan-50 text-cyan-700">
                        <Clock className="w-3 h-3" />
                        {feedback.time_to_action_seconds.toFixed(1)}s
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {new Date(feedback.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {feedbackTotal > feedbackLimit && (
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-200">
          <div className="text-sm text-gray-600">
            Showing {feedbackPage * feedbackLimit + 1} - {Math.min((feedbackPage + 1) * feedbackLimit, feedbackTotal)} of {feedbackTotal}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFeedbackPage(Math.max(0, feedbackPage - 1))}
              disabled={feedbackPage === 0 || loadingFeedbacks}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFeedbackPage(feedbackPage + 1)}
              disabled={(feedbackPage + 1) * feedbackLimit >= feedbackTotal || loadingFeedbacks}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
