import { MessageSquare, RefreshCw, Trash2, Download, X, ThumbsUp, ThumbsDown, Clock } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { MessageFeedback } from '../../api'

export interface FeedbackTabProps {
  feedbacks: MessageFeedback[]
  feedbackTotal: number
  feedbackPage: number
  feedbackLimit: number
  loadingFeedbacks: boolean
  resettingFeedbacks: boolean
  exportingFeedbacks: boolean
  feedbackTypeFilter: 'thumbs_up' | 'thumbs_down' | null
  helpfulnessFilter: 'helpful' | 'not_helpful' | null
  exportDateFrom: string
  exportDateTo: string
  onLoadFeedbacks: () => void
  onResetFeedbacks: () => void
  onExportFeedbacks: (format: 'csv' | 'json') => void
  onFeedbackTypeFilterChange: (value: 'thumbs_up' | 'thumbs_down' | null) => void
  onHelpfulnessFilterChange: (value: 'helpful' | 'not_helpful' | null) => void
  onExportDateFromChange: (value: string) => void
  onExportDateToChange: (value: string) => void
  onPageChange: (page: number) => void
}

export function FeedbackTab({
  feedbacks,
  feedbackTotal,
  feedbackPage,
  feedbackLimit,
  loadingFeedbacks,
  resettingFeedbacks,
  exportingFeedbacks,
  feedbackTypeFilter,
  helpfulnessFilter,
  exportDateFrom,
  exportDateTo,
  onLoadFeedbacks,
  onResetFeedbacks,
  onExportFeedbacks,
  onFeedbackTypeFilterChange,
  onHelpfulnessFilterChange,
  onExportDateFromChange,
  onExportDateToChange,
  onPageChange
}: FeedbackTabProps) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 flex items-center">
          <MessageSquare className="w-6 h-6 mr-3 text-gray-700" />
          User Feedback Analytics
        </h2>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onLoadFeedbacks} disabled={loadingFeedbacks} className="gap-2">
            <RefreshCw className={`w-4 h-4 ${loadingFeedbacks ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            variant="outline"
            onClick={onResetFeedbacks}
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
                onChange={(val) => onFeedbackTypeFilterChange(val ? val as 'thumbs_up' | 'thumbs_down' : null)}
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
                onChange={(val) => onHelpfulnessFilterChange(val ? val as 'helpful' | 'not_helpful' : null)}
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
          <div className="flex flex-col sm:flex-row gap-3 items-end w-full xl:w-auto">
            <div>
              <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Date Range</Label>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={exportDateFrom}
                  onChange={(e) => onExportDateFromChange(e.target.value)}
                  className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                />
                <span className="text-gray-400">-</span>
                <input
                  type="date"
                  value={exportDateTo}
                  onChange={(e) => onExportDateToChange(e.target.value)}
                  className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                />
                {(exportDateFrom || exportDateTo) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => { onExportDateFromChange(''); onExportDateToChange('') }}
                    className="h-9 w-9 p-0 text-gray-400 hover:text-gray-600"
                    title="Clear dates"
                  >
                    <X className="w-4 h-4" />
                  </Button>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => onExportFeedbacks('csv')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 gap-2 bg-white">
                <Download className="w-4 h-4" />CSV
              </Button>
              <Button variant="outline" onClick={() => onExportFeedbacks('json')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 gap-2 bg-white">
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
              onClick={() => onPageChange(Math.max(0, feedbackPage - 1))}
              disabled={feedbackPage === 0 || loadingFeedbacks}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(feedbackPage + 1)}
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
