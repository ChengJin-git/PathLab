import React, { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { CheckCircle2, Loader2, Clock, XCircle, RotateCcw, AlertCircle, StopCircle, User } from 'lucide-react'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { createTrainingTask, getTrainingTask, getAuthToken, cancelQueueTask } from '../api'
import { TASK_DETAIL_STATUS_BADGES, isActiveStatus, TRAINING_CANCELLABLE_STATUSES, VALIDATION_CANCELLABLE_STATUSES, ANALYSIS_CANCELLABLE_STATUSES, CancellableStatus } from '../constants/status'
import { useAuth } from '../contexts/AuthContext'
import { TaskDetail, LogEntry } from '../components/taskDetail/types'
import { parseTaskError } from '../components/taskDetail/parseTaskError'
import { ProgressSection } from '../components/taskDetail/ProgressSection'
import { ConfigurationPanel } from '../components/taskDetail/ConfigurationPanel'
import { LogViewer } from '../components/taskDetail/LogViewer'
export default function TaskDetailPage() {
  const { t } = useTranslation()
  const { task_id } = useParams<{ task_id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { isAdmin } = useAuth()
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const logsContainerRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Load initial task details on mount
  useEffect(() => {
    setLogs([])
    loadTaskDetail()
  }, [task_id])

  // Setup SSE for real-time log streaming and task status updates
  useEffect(() => {
    if (!task_id) return

    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated
    if (!token) {
      return
    }

    const sseUrl = `${API_BASE}/tasks/training/${task_id}/logs/stream?token=${encodeURIComponent(token)}`

    // Create EventSource for SSE
    const eventSource = new EventSource(sseUrl)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        // Check for completion event
        if (data.status === 'complete') {
          console.log('Log stream completed')
          eventSource.close()
          return
        }

        // Check for error event
        if (data.error) {
          console.error('Log stream error:', data.error)
          return
        }

        // Update task status (always present in SSE data)
        // Preserve wsi_ids and username from initial load since SSE doesn't include them
        if (data.task) {
          setTask(prev => ({
            ...data.task,
            wsi_ids: data.task.wsi_ids || prev?.wsi_ids,
            username: data.task.username || prev?.username
          }))
        }

        // Handle log data
        if (data.logs && data.logs.length > 0) {
          setLogs(prev => {
            // Deduplicate logs based on ID
            const existingIds = new Set(prev.map(log => log.id))
            const uniqueNewLogs = data.logs.filter((log: LogEntry) => !existingIds.has(log.id))

            if (uniqueNewLogs.length === 0) {
              return prev
            }
            return [...prev, ...uniqueNewLogs]
          })
        }
      } catch (error) {
        console.error('Failed to parse SSE data:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('SSE stream error:', error)
      // Close the connection on error
      eventSource.close()
    }

    // Cleanup on unmount
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [task_id])

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    // Use requestAnimationFrame to ensure DOM has been painted
    requestAnimationFrame(() => {
      if (logsContainerRef.current) {
        logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight
      }
    })
  }, [logs])

  const loadTaskDetail = async () => {
    if (!task_id) return

    setLoading(true)
    try {
      const data = await getTrainingTask(task_id)
      setTask(data as TaskDetail)
    } catch (error) {
      console.error('Failed to load task detail:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadge = (status: TaskDetail['status'], taskType?: string) => {
    const badge = TASK_DETAIL_STATUS_BADGES[status] || { bg: 'bg-gray-100', text: 'text-gray-800', label: status }

    // Use the same i18n key strategy as TaskListPage for consistency
    let label: string
    if (taskType === 'external_validation') {
      if (status === 'patching') label = t('taskList.progress.patching')
      else if (status === 'extracting') label = t('taskList.progress.extracting')
      else if (status === 'training') label = t('taskList.progress.testing')
      else label = t(`backgroundTask.serverStatus.validation.${status}`, { defaultValue: badge.label })
    } else {
      if (status === 'patching') label = t('taskList.progress.patching')
      else if (status === 'extracting') label = t('taskList.progress.extracting')
      else if (status === 'training') label = t('taskList.progress.training')
      else label = t(`backgroundTask.serverStatus.training.${status}`, { defaultValue: badge.label })
    }

    // Determine icon based on status
    const getIcon = () => {
      if (status === 'pending' || status === 'queued') return <Clock className="w-4 h-4 mr-1.5" />
      if (isActiveStatus(status)) return <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
      if (status === 'completed') return <CheckCircle2 className="w-4 h-4 mr-1.5" />
      return <XCircle className="w-4 h-4 mr-1.5" />
    }

    return (
      <span className={`inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold shadow-sm ${badge.bg} ${badge.text}`}>
        {getIcon()}
        {label}
      </span>
    )
  }

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-'
    // Fix case where both +00:00 and Z might be present from backend
    const sanitizedDate = dateStr.replace(/\+00:00Z$/, 'Z')
    // Ensure the date string is treated as UTC if no timezone is specified
    const normalizedDate = (!sanitizedDate.endsWith('Z') && !sanitizedDate.includes('+')) 
      ? `${sanitizedDate}Z` 
      : sanitizedDate
    const date = new Date(normalizedDate)
    if (isNaN(date.getTime())) return dateStr
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const handleRerun = async () => {
    setRerunError(null)
    if (!task || !task.wsi_ids || task.wsi_ids.length === 0) {
      setRerunError(t('taskDetail.rerunErrorMissingWsi'))
      return
    }

    if (!task.preprocessing_config || !task.model_config) {
      setRerunError(t('taskDetail.rerunErrorMissingConfig'))
      return
    }

    setRerunning(true)
    try {
      const result = await createTrainingTask({
        task_name: `${task.task_name} (rerun)`,
        task_type: task.task_type,
        data_type: task.data_type,
        task_description: task.task_description,
        wsi_ids: task.wsi_ids,
        preprocessing: {
          // Note: tile_size and stride are now auto-determined by PrePATH-style tiling
          feature_extractor: task.preprocessing_config.feature_extractor ?? 'resnet50',
          feature_batch_size: task.preprocessing_config.feature_batch_size ?? 256,
          use_gpu: task.preprocessing_config.use_gpu ?? true,
          // Preserve tissue segmentation parameters
          level: task.preprocessing_config.level,
          sthresh: task.preprocessing_config.sthresh,
          mthresh: task.preprocessing_config.mthresh,
          close: task.preprocessing_config.close,
          use_otsu: task.preprocessing_config.use_otsu,
          contour_fn: task.preprocessing_config.contour_fn,
          use_padding: task.preprocessing_config.use_padding,
          // Preserve filter parameters
          a_t: task.preprocessing_config.a_t,
          a_h: task.preprocessing_config.a_h,
          max_n_holes: task.preprocessing_config.max_n_holes,
        },
        model: {
          aggregator: task.model_config.aggregator ?? 'abmil',
          backbone: task.model_config.backbone,  // For patch-level tasks
          learning_rate: task.model_config.learning_rate ?? 0.0001,
          epochs: task.model_config.epochs ?? 10,
          optimizer: task.model_config.optimizer ?? 'adam',
          batch_size: task.model_config.batch_size ?? (task.data_type === 'patch' ? 64 : 1),
          auto_balance: task.model_config.auto_balance ?? false,
          early_stopping_patience: task.model_config.early_stopping_patience,
        },
        // Preserve the original split configuration for exact rerun
        split_config: task.preprocessing_config.split_config,
      })
      // Navigate to the new task
      navigate(`/task/${result.task_id}`)
    } catch (error: any) {
      console.error('Failed to rerun task:', error)
      const errMsg = error?.message || error?.detail || String(error)
      const parsed = parseTaskError(errMsg)
      if (parsed.isStorageError) {
        setRerunError(parsed.userFriendlyMessage + ' ' + (parsed.suggestion || ''))
      } else {
        setRerunError(t('taskDetail.rerunErrorGeneric'))
      }
    } finally {
      setRerunning(false)
    }
  }

  const handleCancelTask = async () => {
    if (!task_id) return

    setCancelling(true)
    setShowCancelConfirm(false)
    try {
      await cancelQueueTask(task_id)
      // Task status will be updated via SSE
    } catch (error) {
      console.error('Failed to cancel task:', error)
    } finally {
      setCancelling(false)
    }
  }

  if (loading && !task) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (!task) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <AlertCircle className="w-12 h-12 text-red-500" />
        <div className="text-xl font-semibold text-gray-900">{t('taskDetail.taskNotFound')}</div>
        <p className="text-gray-500">{t('taskDetail.taskNotFoundDescription')}</p>
        <Button onClick={() => navigate(fromAIChat ? '/ai-chat' : '/task-list')} variant="outline">
          {fromAIChat ? t('taskDetail.backToChat') : t('taskDetail.backToTaskList')}
        </Button>
      </div>
    )
  }

  const isPatchLevel = task.data_type === 'patch'
  const isExternalValidation = task.task_type === 'external_validation'

  // Calculate display progress for patch-level tasks
  // (map 66% - 100% backend progress to 0% - 100% UI progress)
  // For completed tasks, always show 100%
  // For cancelled/failed tasks, show the mapped progress at the time of cancellation/failure
  // External validation tasks use 0-100 directly regardless of data_type
  const displayProgress = isPatchLevel && !isExternalValidation && task.status !== 'completed'
    ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
    : Math.min(task.progress, 100)  // Cap at 100% for safety

  return (
    <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6 pb-12">
      {/* Header */}
      <div className="mb-4 sm:mb-6">
        <Button
          variant="ghost"
          onClick={() => navigate(fromAIChat ? '/ai-chat' : '/task-list')}
          className="mb-1 sm:mb-2 pl-0 hover:bg-transparent hover:text-gray-900 text-gray-500 text-xs sm:text-base"
        >
          <svg className="w-4 h-4 sm:w-5 sm:h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {fromAIChat ? t('taskDetail.backToChat') : t('taskDetail.tasks')}
        </Button>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl sm:text-3xl font-bold text-gray-900 truncate mb-1" title={task.task_name}>{task.task_name}</h1>
            <p className="text-xs sm:text-sm text-gray-500 line-clamp-2">{task.task_description}</p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {getStatusBadge(task.status, task.task_type)}
            {task.status === 'failed' && (
              <Button
                variant="outline"
                onClick={handleRerun}
                disabled={rerunning}
                className="flex items-center gap-2 h-9 px-4 rounded-full border-gray-200 text-gray-700 font-bold hover:bg-gray-50 hover:text-gray-900 shadow-sm transition-all"
              >
                {rerunning ? (
                  <Loader2 className="w-4 h-4 animate-spin text-gray-500" />
                ) : (
                  <RotateCcw className="w-4 h-4 text-gray-500" />
                )}
                {t('taskDetail.rerun')}
              </Button>
            )}
            {(() => {
              const taskType = isExternalValidation ? 'validation' : 'analysis'
              const cancellableStatuses = 
                taskType === 'validation' ? VALIDATION_CANCELLABLE_STATUSES :
                ANALYSIS_CANCELLABLE_STATUSES
              return cancellableStatuses.includes(task.status as CancellableStatus) && (
                <Button
                variant="outline"
                onClick={() => setShowCancelConfirm(true)}
                disabled={cancelling}
                className="flex items-center gap-2 h-9 px-4 rounded-full border-red-200 text-red-600 font-bold hover:bg-red-50 hover:text-red-700 shadow-sm transition-all"
              >
                {cancelling ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <StopCircle className="w-4 h-4" />
                )}
                {t('common.cancel')}
              </Button>
            )})()}
          </div>
        </div>
        {rerunError && (
          <div className="mt-4 text-[11px] sm:text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2 flex items-center justify-between animate-in fade-in slide-in-from-top-1">
            <span className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {rerunError}
            </span>
            <button onClick={() => setRerunError(null)} className="ml-2 text-red-400 hover:text-red-600">
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>

      {/* Task Info Grid */}
      <Card className="p-4 sm:p-6 overflow-hidden border-gray-100 shadow-sm">
        <div className={`grid grid-cols-2 ${isAdmin && task.username ? 'md:grid-cols-5' : 'md:grid-cols-4'} gap-4 sm:gap-6`}>
          <div className="min-w-0">
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">{t('taskDetail.taskId')}</div>
            <div className="flex items-center gap-1.5 overflow-hidden">
              <div className="font-mono text-[11px] sm:text-sm font-bold text-gray-700 truncate">{task.task_id}</div>
              <button
                onClick={() => {
                  if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(task.task_id)
                  } else {
                    // Fallback for Electron or non-secure contexts
                    const textArea = document.createElement('textarea')
                    textArea.value = task.task_id
                    textArea.style.position = 'fixed'
                    textArea.style.opacity = '0'
                    document.body.appendChild(textArea)
                    textArea.select()
                    document.execCommand('copy')
                    document.body.removeChild(textArea)
                  }
                  setCopySuccess(true)
                  setTimeout(() => setCopySuccess(false), 2000)
                }}
                className="p-1 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-all shrink-0"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>
            {copySuccess && (
              <div className="text-[9px] text-green-600 font-bold mt-1">{t('taskDetail.copied')}</div>
            )}
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">
              {t('taskDetail.data')}
            </div>
            <div className="flex items-end gap-1.5">
              <span className="text-lg sm:text-2xl font-bold text-gray-900 leading-none">{task.wsi_count}</span>
              <span className="text-[10px] sm:text-xs text-gray-500 font-medium mb-0.5">{task.data_type === 'patch' ? t('taskDetail.patches') : t('taskDetail.slides')}</span>
            </div>
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">{t('taskDetail.created')}</div>
            <div className="text-xs sm:text-sm font-bold text-gray-700 truncate">{formatDate(task.created_at)}</div>
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">{t('taskDetail.updated')}</div>
            <div className="text-xs sm:text-sm font-bold text-gray-700 truncate">{formatDate(task.updated_at)}</div>
          </div>
          {isAdmin && task.username && (
            <div>
              <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">{t('taskDetail.creator')}</div>
              <div className="flex items-center gap-1.5">
                <User className="w-3.5 h-3.5 text-gray-400" />
                <div className="text-xs sm:text-sm font-bold text-gray-700 truncate" title={task.username}>{task.username}</div>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Progress Section */}
      <ProgressSection
        task={task}
        displayProgress={displayProgress}
        isPatchLevel={isPatchLevel}
        isExternalValidation={isExternalValidation}
      />

      {/* Error Message Display */}
      {task.status === 'failed' && task.error_message && (() => {
        const errorInfo = parseTaskError(task.error_message)
        return (
          <Card className="p-6 border-red-200 bg-red-50">
            <div className="flex items-start gap-3">
              <XCircle className="w-6 h-6 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-red-800 mb-2">{t('taskDetail.taskFailed')}</h3>
                <p className="text-red-700 mb-3">{errorInfo.userFriendlyMessage}</p>
                {errorInfo.isVRAMError && errorInfo.suggestedBatchSize && (
                  <div className="bg-red-100 border border-red-200 rounded-lg p-3 mb-3">
                    <p className="text-sm text-red-800">
                      <strong>{t('taskDetail.suggestion')}:</strong> {t('taskDetail.vramSuggestion', { batchSize: errorInfo.suggestedBatchSize })}
                    </p>
                  </div>
                )}
                {errorInfo.isStorageError && errorInfo.suggestion && (
                  <div className="bg-red-100 border border-red-200 rounded-lg p-3 mb-3">
                    <p className="text-sm text-red-800">
                      <strong>💡 {t('taskDetail.suggestion')}:</strong> {errorInfo.suggestion}
                    </p>
                  </div>
                )}
                <details className="text-sm">
                  <summary className="text-red-600 cursor-pointer hover:text-red-800">
                    {t('taskDetail.showTechnicalDetails')}
                  </summary>
                  <pre className="mt-2 p-3 bg-red-100 rounded text-xs text-red-800 overflow-x-auto whitespace-pre-wrap">
                    {task.error_message}
                  </pre>
                </details>
              </div>
            </div>
          </Card>
        )
      })()}

      {/* Live Logs */}
      <LogViewer
        logs={logs}
        logsContainerRef={logsContainerRef}
        logsEndRef={logsEndRef}
      />

      {/* Configuration */}
      <ConfigurationPanel task={task} />

      {/* Cancel Confirmation Modal */}
      {showCancelConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6">
            {/* Header */}
            <div className="text-center mb-4 sm:mb-6">
              <div className="w-12 h-12 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-3 sm:mb-4">
                <AlertCircle className="w-7 h-7 sm:w-10 sm:h-10 text-red-600" />
              </div>
              <h2 className="text-lg sm:text-2xl font-bold text-gray-900 leading-tight">
                {t('taskDetail.cancelModalTitle')}
              </h2>
              <p className="text-sm text-gray-500 mt-2">
                {t('taskDetail.cancelModalSubtitle')}
              </p>
            </div>

            {/* Warning Message */}
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
              <p className="text-sm text-red-800">
                {t('taskDetail.cancelModalWarning')}
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => setShowCancelConfirm(false)}
                className="flex-1 h-11"
              >
                {t('taskDetail.keepRunning')}
              </Button>
              <Button
                onClick={handleCancelTask}
                className="flex-1 h-11 bg-red-600 hover:bg-red-700 text-white"
              >
                {t('taskDetail.cancelTask')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
