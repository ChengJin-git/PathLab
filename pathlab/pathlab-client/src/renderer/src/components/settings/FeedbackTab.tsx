import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { MessageSquare, RefreshCw, Trash2, Download, X, ThumbsUp, ThumbsDown, Clock, Search, Calendar, BarChart3, ChevronLeft, ChevronRight, Users } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import {
  MessageFeedback, FeedbackStats,
  getAdminFeedbacks, getFeedbackStats, exportFeedbacks as exportFeedbacksApi,
  resetAllFeedbacks, startAsyncExport, getExportTaskStatus, downloadExportFile,
  ExportTaskStatus, fetchUserUsageStats, UserUsageItem, downloadBlobFile
} from '../../api'
import { ShowConfirmDialog } from './ConfirmDialog'

export interface FeedbackTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export function FeedbackTab({ showConfirmDialog, closeConfirmDialog }: FeedbackTabProps) {
  const { t } = useTranslation()
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

  // Usage stats state
  const [usageData, setUsageData] = useState<UserUsageItem[]>([])
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [usagePage, setUsagePage] = useState(0)
  const [usagePageSize, setUsagePageSize] = useState(10)

  // Compute totals across all users
  const usageTotals = useMemo(() => {
    return usageData.reduce(
      (acc, u) => ({
        wsi_count: acc.wsi_count + u.wsi_count,
        analysis_count: acc.analysis_count + u.analysis_count,
        training_count: acc.training_count + u.training_count,
        message_count: acc.message_count + u.message_count,
        annotation_count: acc.annotation_count + u.annotation_count,
        feedback_count: acc.feedback_count + u.feedback_count,
        thumbs_up: acc.thumbs_up + u.thumbs_up,
        thumbs_down: acc.thumbs_down + u.thumbs_down,
      }),
      { wsi_count: 0, analysis_count: 0, training_count: 0, message_count: 0, annotation_count: 0, feedback_count: 0, thumbs_up: 0, thumbs_down: 0 }
    )
  }, [usageData])

  // Paginated usage data
  const usageTotalPages = Math.ceil(usageData.length / usagePageSize)
  const paginatedUsageData = useMemo(() => {
    const start = usagePage * usagePageSize
    return usageData.slice(start, start + usagePageSize)
  }, [usageData, usagePage, usagePageSize])

  // Reset page when page size changes or data loads
  useEffect(() => {
    if (usagePage >= usageTotalPages && usageTotalPages > 0) {
      setUsagePage(usageTotalPages - 1)
    }
  }, [usageTotalPages, usagePage])

  // Load usage stats on mount
  useEffect(() => {
    let cancelled = false
    const loadUsage = async () => {
      setUsageLoading(true)
      setUsageError(null)
      try {
        const res = await fetchUserUsageStats()
        if (!cancelled) setUsageData(res.users)
      } catch (err) {
        if (!cancelled) setUsageError(err instanceof Error ? err.message : t('settings.feedbackTab.usageError'))
      } finally {
        if (!cancelled) setUsageLoading(false)
      }
    }
    loadUsage()
    return () => { cancelled = true }
  }, [])

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
      setFeedbackError(err instanceof Error ? err.message : t('settings.feedbackTab.failedToLoad'))
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
            downloadBlobFile(blob, `feedbacks_${new Date().toISOString().split('T')[0]}.${format}`)
          } else if (status.status === 'failed') {
            if (exportPollingInterval) { clearInterval(exportPollingInterval); setExportPollingInterval(null) }
            setExportingFeedbacks(false); setFeedbackError(status.error_message || t('settings.feedbackTab.exportFailed'))
          }
        } catch { /* continue polling */ }
      }
      const interval = setInterval(pollStatus, 2000); setExportPollingInterval(interval)
      await pollStatus()
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : t('settings.feedbackTab.failedToStartExport')); setExportingFeedbacks(false)
    }
  }

  // Export feedbacks (sync for small datasets, async for large)
  const handleExportFeedbacks = async (format: 'csv' | 'json') => {
    if (feedbackStats && feedbackStats.total_feedbacks > 1000) { await handleAsyncExport(format); return }
    setExportingFeedbacks(true)
    try {
      const result = await exportFeedbacksApi(format)
      if (format === 'csv' && result instanceof Blob) {
        downloadBlobFile(result, `feedbacks_${new Date().toISOString().split('T')[0]}.csv`)
      } else if (format === 'json' && !(result instanceof Blob)) {
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
        downloadBlobFile(blob, `feedbacks_${new Date().toISOString().split('T')[0]}.json`)
      }
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : t('settings.feedbackTab.failedToExport'))
    } finally { setExportingFeedbacks(false) }
  }

  // Reset all feedbacks
  const handleResetFeedbacks = () => {
    showConfirmDialog({
      title: t('settings.feedbackTab.resetAllTitle'),
      message: t('settings.feedbackTab.resetAllMessage'),
      confirmText: t('settings.feedbackTab.deleteAll'), confirmVariant: 'danger', showCancel: true,
      onConfirm: async () => {
        closeConfirmDialog()
        setResettingFeedbacks(true)
        try {
          const result = await resetAllFeedbacks()
          setTimeout(() => {
            showConfirmDialog({
              title: t('common.success'), message: t('settings.feedbackTab.deletedSuccess', { count: result.deleted_count }),
              confirmText: t('settings.feedbackTab.ok'), confirmVariant: 'info', showCancel: false,
              onConfirm: () => closeConfirmDialog()
            })
          }, 100)
          await loadFeedbacks()
        } catch (err) {
          setFeedbackError(err instanceof Error ? err.message : t('settings.feedbackTab.failedToReset'))
        } finally { setResettingFeedbacks(false) }
      }
    })
  }

  return (
    <Card className="p-4 sm:p-6">
      {/* ===== Usage Overview Section ===== */}
      <div className="mb-8">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center mb-4">
          <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 flex-shrink-0" />
          {t('settings.feedbackTab.usageOverview')}
        </h2>

        {usageLoading ? (
          <div className="flex flex-col items-center justify-center py-8 text-gray-500">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600 mb-2"></div>
            <p className="text-sm">{t('settings.feedbackTab.usageLoading')}</p>
          </div>
        ) : usageError ? (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{usageError}</div>
        ) : usageData.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-sm">{t('settings.feedbackTab.usageNoData')}</div>
        ) : (
          <>
            {/* Summary Totals Cards - Responsive grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-2 sm:gap-3 mb-5">
              <div className="bg-gradient-to-br from-blue-50 to-blue-100/50 rounded-xl p-2 sm:p-3 text-center">
                <div className="flex items-center justify-center mb-0.5 sm:mb-1">
                  <Users className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-blue-500 mr-0.5 sm:mr-1" />
                  <span className="text-[8px] sm:text-[10px] text-blue-600 uppercase font-semibold tracking-wider">{t('settings.feedbackTab.usageTotalUsers')}</span>
                </div>
                <div className="text-lg sm:text-xl md:text-2xl font-bold text-blue-700">{usageData.length}</div>
              </div>
              {([
                { key: 'usageWsi', value: usageTotals.wsi_count, color: 'indigo' },
                { key: 'usageAiTasks', value: usageTotals.analysis_count, color: 'violet' },
                { key: 'usageTraining', value: usageTotals.training_count, color: 'purple' },
                { key: 'usageMessages', value: usageTotals.message_count, color: 'cyan' },
                { key: 'usageAnnotations', value: usageTotals.annotation_count, color: 'teal' },
                { key: 'usageFeedback', value: usageTotals.feedback_count, color: 'amber' },
              ] as const).map(({ key, value, color }, index, arr) => (
                <div key={key} className={`bg-gradient-to-br from-${color}-50 to-${color}-100/50 rounded-xl p-2 sm:p-3 text-center${index === arr.length - 1 ? ' col-span-2 sm:col-span-1' : ''}`}>
                  <div className={`text-[8px] sm:text-[10px] text-${color}-600 uppercase font-semibold tracking-wider mb-0.5 sm:mb-1`}>{t(`settings.feedbackTab.${key}`)}</div>
                  <div className={`text-lg sm:text-xl md:text-2xl font-bold text-${color}-700`}>{value}</div>
                </div>
              ))}
            </div>


            {/* Mobile: Card layout */}
            <div className="block md:hidden space-y-3">
              {paginatedUsageData.map((u) => (
                <div key={u.user_id} className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <span className="font-medium text-gray-900 text-sm">{u.nickname || u.email}</span>
                      <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase bg-gray-100 text-gray-600">{u.role}</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.wsi_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageWsi')}</div>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.analysis_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageAiTasks')}</div>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.training_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageTraining')}</div>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.message_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageMessages')}</div>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.annotation_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageAnnotations')}</div>
                    </div>
                    <div className="bg-gray-50 rounded-lg p-2">
                      <div className="text-lg font-semibold text-gray-900">{u.feedback_count}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{t('settings.feedbackTab.usageFeedback')}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Desktop: Table layout */}
            <div className="hidden md:block overflow-hidden rounded-lg border border-gray-200 shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50/80">
                    <tr className="border-b border-gray-200">
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageUser')}</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageRole')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageWsi')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageAiTasks')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageTraining')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageMessages')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageAnnotations')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageFeedback')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageThumbsUp')}</th>
                      <th className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('settings.feedbackTab.usageThumbsDown')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {paginatedUsageData.map((u) => (
                      <tr key={u.user_id} className="hover:bg-gray-50/80 transition-colors">
                        <td className="px-4 py-3 text-gray-900 font-medium text-sm truncate max-w-[200px]" title={u.email}>
                          {u.nickname || u.email}
                        </td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-gray-100 text-gray-600">{u.role}</span>
                        </td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.wsi_count}</td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.analysis_count}</td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.training_count}</td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.message_count}</td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.annotation_count}</td>
                        <td className="px-3 py-3 text-center text-gray-700 font-mono text-xs">{u.feedback_count}</td>
                        <td className="px-3 py-3 text-center text-green-600 font-mono text-xs">{u.thumbs_up}</td>
                        <td className="px-3 py-3 text-center text-red-600 font-mono text-xs">{u.thumbs_down}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Pagination Controls */}
             {usageTotalPages > 1 && (
               <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mt-4 pt-4 border-t border-gray-100">
                 <div className="flex items-center gap-2 text-sm text-gray-500">
                   <span>{t('settings.feedbackTab.usageRowsPerPage')}</span>
                   <Select
                     value={String(usagePageSize)}
                     onChange={(v) => { setUsagePageSize(Number(v)); setUsagePage(0) }}
                     options={[
                       { value: '5', label: '5' },
                       { value: '10', label: '10' },
                       { value: '20', label: '20' },
                     ]}
                     triggerClassName="w-20"
                   />
                 </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">
                    {t('settings.feedbackTab.usagePageInfo', {
                      current: usagePage + 1,
                      total: usageTotalPages,
                    })}
                  </span>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setUsagePage((p) => Math.max(0, p - 1))}
                      disabled={usagePage === 0}
                      className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setUsagePage((p) => Math.min(usageTotalPages - 1, p + 1))}
                      disabled={usagePage >= usageTotalPages - 1}
                      className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ===== Divider ===== */}
      <hr className="border-gray-200 mb-6" />

      {/* ===== Feedback Section ===== */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-6">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
          <MessageSquare className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 flex-shrink-0" />
          <div className="flex flex-col">
            <span>{t('settings.feedbackTab.title')}</span>
            <span className="text-gray-500 font-normal text-sm mt-0.5 sm:hidden">
                {t('settings.feedbackTab.subtitle')}
            </span>
          </div>
        </h2>
        <div className="flex gap-2 w-full sm:w-auto">
          <Button variant="outline" onClick={loadFeedbacks} disabled={loadingFeedbacks} className="flex-1 sm:flex-none gap-2">
            <RefreshCw className={`w-4 h-4 ${loadingFeedbacks ? 'animate-spin' : ''}`} />
            <span className="sm:hidden lg:inline">{t('common.refresh')}</span>
          </Button>
          <Button
            variant="outline"
            onClick={handleResetFeedbacks}
            disabled={loadingFeedbacks || resettingFeedbacks}
            className="flex-1 sm:flex-none gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
          >
            <Trash2 className={`w-4 h-4 ${resettingFeedbacks ? 'animate-pulse' : ''}`} />
            <span className="sm:hidden lg:inline">{t('settings.feedbackTab.resetAll')}</span>
          </Button>
        </div>
      </div>

      {feedbackError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {feedbackError}
        </div>
      )}

      {/* Compact Filters & Actions Bar */}
      <div className="mb-6 p-4 bg-gray-50/80 border border-gray-100 rounded-xl">
         <div className="flex flex-col xl:flex-row gap-4 xl:items-end justify-between">
            {/* Left: Filters Group */}
            <div className="flex flex-col md:flex-row gap-4 flex-1">
                <div className="w-full md:w-48 space-y-1.5">
                    <Label className="text-xs font-medium text-gray-500 uppercase tracking-wider ml-0.5">{t('common.type')}</Label>
                    <Select
                        value={feedbackTypeFilter || ''}
                        onChange={(val) => { setFeedbackTypeFilter(val ? val as 'thumbs_up' | 'thumbs_down' : null); setFeedbackPage(0) }}
                        options={[
                        { value: '', label: t('settings.feedbackTab.allTypes') },
                        { value: 'thumbs_up', label: t('settings.feedbackTab.thumbsUp') },
                        { value: 'thumbs_down', label: t('settings.feedbackTab.thumbsDown') }
                        ]}
                    />
                </div>
                <div className="w-full md:w-48 space-y-1.5">
                    <Label className="text-xs font-medium text-gray-500 uppercase tracking-wider ml-0.5">{t('settings.feedbackTab.helpfulness')}</Label>
                    <Select
                        value={helpfulnessFilter || ''}
                        onChange={(val) => { setHelpfulnessFilter(val ? val as 'helpful' | 'not_helpful' : null); setFeedbackPage(0) }}
                        options={[
                        { value: '', label: t('settings.feedbackTab.allRatings') },
                        { value: 'helpful', label: t('settings.feedbackTab.helpful') },
                        { value: 'not_helpful', label: t('settings.feedbackTab.notHelpful') }
                        ]}
                    />
                </div>
            </div>

            {/* Right: Date & Export Group */}
            <div className="flex flex-col md:flex-row gap-4 pt-4 xl:pt-0 border-t xl:border-t-0 border-gray-200 xl:border-l xl:pl-6">
                 <div className="space-y-1.5 flex-grow sm:flex-grow-0">
                     <Label className="text-xs font-medium text-gray-500 uppercase tracking-wider ml-0.5">{t('settings.feedbackTab.dateRange')}</Label>
                     <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
                        <div className="relative flex-1 w-full sm:w-36">
                            <input
                              type="date"
                              value={exportDateFrom}
                              onChange={(e) => setExportDateFrom(e.target.value)}
                              className="w-full h-9 pl-8 pr-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                            />
                            <Calendar className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-2.5 pointer-events-none" />
                        </div>
                        <span className="hidden sm:inline text-gray-400 text-sm">–</span>
                        <div className="relative flex-1 w-full sm:w-36">
                            <input
                              type="date"
                              value={exportDateTo}
                              onChange={(e) => setExportDateTo(e.target.value)}
                              className="w-full h-9 pl-8 pr-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500"
                            />
                            <Calendar className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-2.5 pointer-events-none" />
                        </div>
                        {(exportDateFrom || exportDateTo) && (
                            <button
                                onClick={() => { setExportDateFrom(''); setExportDateTo('') }}
                                className="hidden sm:block p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded transition-colors"
                                title={t('settings.feedbackTab.clearDates')}
                            >
                                <X className="w-4 h-4" />
                            </button>
                        )}
                        {/* Mobile clear button */}
                        {(exportDateFrom || exportDateTo) && (
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => { setExportDateFrom(''); setExportDateTo('') }}
                                className="sm:hidden h-8 w-full text-gray-500 border border-dashed border-gray-300"
                            >
                                <X className="w-3.5 h-3.5 mr-1.5" /> {t('settings.feedbackTab.clearDates')}
                            </Button>
                        )}
                     </div>
                 </div>

                 <div className="space-y-1.5 flex flex-col justify-end">
                      <div className="h-4 hidden md:block"></div> {/* Spacer to align button bottom with inputs */}
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => handleExportFeedbacks('csv')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 w-full sm:w-auto gap-1.5 bg-white border-gray-200 text-gray-700 hover:bg-gray-50">
                            <Download className="w-3.5 h-3.5" />
                            <span className="text-xs font-medium">CSV</span>
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleExportFeedbacks('json')} disabled={exportingFeedbacks || loadingFeedbacks} className="h-9 w-full sm:w-auto gap-1.5 bg-white border-gray-200 text-gray-700 hover:bg-gray-50">
                            <Download className="w-3.5 h-3.5" />
                            <span className="text-xs font-medium">JSON</span>
                        </Button>
                      </div>
                 </div>
            </div>
         </div>
      </div>

      {loadingFeedbacks ? (
        <div className="flex flex-col items-center justify-center py-12 text-gray-500">
           <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mb-3"></div>
           <p className="text-sm">{t('settings.feedbackTab.loading')}</p>
        </div>
      ) : feedbacks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-gray-400 bg-gray-50/30 rounded-lg border border-dashed border-gray-200">
          <div className="bg-gray-50 p-3 rounded-full mb-3">
             <MessageSquare className="w-6 h-6 text-gray-300" />
          </div>
          <p className="font-medium text-gray-600">{t('settings.feedbackTab.noData')}</p>
          <p className="text-sm mt-1">{t('settings.feedbackTab.tryAdjustingFilters')}</p>
        </div>
      ) : (
        <>
          {/* Mobile Card View */}
          <div className="block sm:hidden space-y-4">
            {feedbacks.map((feedback) => (
              <div key={feedback.id} className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm space-y-3">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-400">#{feedback.id}</span>
                    <span className="text-sm font-medium text-gray-900">
                      {feedback.username || <span className="font-mono text-gray-400">{feedback.user_id.slice(0, 6)}</span>}
                    </span>
                  </div>
                  <span className="text-xs text-gray-500">{new Date(feedback.created_at).toLocaleDateString()}</span>
                </div>
                
                <div className="flex flex-wrap gap-2">
                   {feedback.feedback_type === 'thumbs_up' && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-green-50 text-green-700 border border-green-100">
                      <ThumbsUp className="w-3 h-3" /> Up
                    </span>
                  )}
                  {feedback.feedback_type === 'thumbs_down' && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-red-50 text-red-700 border border-red-100">
                      <ThumbsDown className="w-3 h-3" /> Down
                    </span>
                  )}
                  {feedback.task_helpfulness === 'helpful' && (
                      <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-100">{t('settings.feedbackTab.helpful')}</span>
                  )}
                  {feedback.task_helpfulness === 'not_helpful' && (
                      <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-orange-50 text-orange-700 border border-orange-100">{t('settings.feedbackTab.notHelpful')}</span>
                  )}
                </div>

                <div className="p-3 bg-gray-50 rounded-lg text-sm text-gray-800 leading-relaxed break-words">
                  {feedback.message_content || <span className="text-gray-400 italic">{t('settings.feedbackTab.noContent')}</span>}
                </div>
                
                <div className="flex justify-between items-center text-xs text-gray-500 pt-2 border-t border-gray-100">
                  <div className="flex items-center gap-1">
                    <span className="uppercase tracking-wider">{t('settings.feedbackTab.task')}:</span>
                    <span className="font-mono">{feedback.related_task_id || '-'}</span>
                  </div>
                   {feedback.time_to_action_seconds && (
                    <div className="flex items-center gap-1">
                       <Clock className="w-3 h-3" />
                       <span>{Number(feedback.time_to_action_seconds).toFixed(1)}s</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Desktop Table View */}
          <div className="hidden sm:block overflow-hidden rounded-lg border border-gray-200 shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm table-fixed">
                <thead className="bg-gray-50/80">
                  <tr className="border-b border-gray-200">
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-16">{t('settings.feedbackTab.columnId')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-[40%]">{t('settings.feedbackTab.columnMessageContent')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-[15%]">{t('settings.feedbackTab.columnUser')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-24">{t('common.type')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-24">{t('settings.feedbackTab.helpfulness')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-24">{t('settings.feedbackTab.task')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-24 text-right">{t('settings.feedbackTab.columnDuration')}</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-28 text-right">{t('settings.feedbackTab.columnCreated')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {feedbacks.map((feedback) => (
                    <tr key={feedback.id} className="hover:bg-gray-50/80 transition-colors">
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs align-top pt-3.5">{feedback.id}</td>
                      <td className="px-4 py-3 align-top">
                      <div className="text-gray-900 text-xs leading-relaxed break-words whitespace-normal line-clamp-4 hover:line-clamp-none transition-all duration-200" title={feedback.message_content || ''}>
                              {feedback.message_content ? feedback.message_content.replace(/\s+/g, ' ') : <span className="text-gray-300 italic">{t('settings.feedbackTab.noContent')}</span>}
                          </div>
                      </td>
                      <td className="px-4 py-3 text-gray-700 text-xs font-medium align-top pt-3.5 truncate">
                        {feedback.username || <span className="font-mono text-gray-400">{feedback.user_id.slice(0, 6)}</span>}
                      </td>
                      <td className="px-4 py-3 align-top pt-3.5">
                        {feedback.feedback_type === 'thumbs_up' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-green-50 text-green-700 border border-green-100">
                            <ThumbsUp className="w-3 h-3" /> Up
                          </span>
                        )}
                        {feedback.feedback_type === 'thumbs_down' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-red-50 text-red-700 border border-red-100">
                            <ThumbsDown className="w-3 h-3" /> Down
                          </span>
                        )}
                        {!feedback.feedback_type && <span className="text-gray-300">-</span>}
                      </td>
                      <td className="px-4 py-3 align-top pt-3.5">
                        {feedback.task_helpfulness === 'helpful' && (
                           <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-100">{t('settings.feedbackTab.helpful')}</span>
                        )}
                        {feedback.task_helpfulness === 'not_helpful' && (
                           <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-50 text-orange-700 border border-orange-100">{t('settings.feedbackTab.notHelpful')}</span>
                        )}
                        {!feedback.task_helpfulness && <span className="text-gray-300 text-xs">-</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs truncate max-w-[100px] align-top pt-3.5" title={feedback.related_task_id || ''}>
                          {feedback.related_task_id || '-'}
                      </td>
                      <td className="px-4 py-3 text-right align-top pt-3.5">
                          {feedback.time_to_action_seconds ? (
                              <span className="font-mono text-xs text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
                                  {Number(feedback.time_to_action_seconds).toFixed(1)}s
                              </span>
                          ) : (
                              <span className="text-gray-300 text-xs">-</span>
                          )}
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap text-xs text-gray-500 align-top pt-3.5">
                         {new Date(feedback.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </Card>
  )
}
