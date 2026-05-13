import { useState, useEffect, useRef } from 'react'
import { useAsyncAction } from '../lib/useAsyncAction'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { CheckCircle2, Loader2, Clock, XCircle, RotateCcw, AlertCircle, StopCircle, User, BarChart3, Download, Table2, Cpu } from 'lucide-react'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { createTrainingTask, getTrainingTask, getAuthToken, cancelQueueTask, ApiError, withAuthTokenQuery, startExternalValidation } from '../api'
import { TASK_DETAIL_STATUS_BADGES, isActiveStatus, VALIDATION_CANCELLABLE_STATUSES, ANALYSIS_CANCELLABLE_STATUSES } from '../constants/status'
import { useAuth } from '../contexts/AuthContext'
import { TaskDetail, LogEntry } from '../components/taskDetail/types'
import { parseTaskError } from '../components/taskDetail/parseTaskError'
import { ProgressSection } from '../components/taskDetail/ProgressSection'
import { ConfigurationPanel } from '../components/taskDetail/ConfigurationPanel'
import { LogViewer } from '../components/taskDetail/LogViewer'
import {
  clearTrainingSubmissionRecord,
  getTrainingSubmissionRecord,
  markTrainingSubmissionCancelled,
  markTrainingSubmissionCreated,
  markTrainingSubmissionFailed,
  markTrainingSubmissionPending,
} from '../lib/trainingSubmissionTracker'
import { formatDateTime } from '../lib/utils'
import { getBatchInferenceSummary, getBatchInferenceResults, exportBatchInferenceCsv } from '../api/batchInference'
import type { BatchInferenceSummary, BatchInferenceResult } from '../api/batchInference'
import { isCanonicalTaskType, isSegmentationTask } from '../constants/training'

const makeSyntheticTask = (
  taskId: string,
  options?: { taskName?: string; status?: TaskDetail['status']; errorMessage?: string; dataType?: TaskDetail['data_type'] }
): TaskDetail => ({
  task_id: taskId,
  task_name: options?.taskName || taskId,
  task_type: 'wsi_classification',
  data_type: options?.dataType || 'wsi',
  task_description: '',
  status: options?.status || 'creating',
  progress: 0,
  error_message: options?.errorMessage,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  wsi_count: 0,
  preprocessing_config: {},
  model_config: {},
})

const CREATING_LOG_ID = -1
const SYNTHETIC_FAILURE_LOG_ID = -2
const SYNTHETIC_CANCELLED_LOG_ID = -3

const makeCreatingLogEntry = (taskId: string): LogEntry => ({
  id: CREATING_LOG_ID,
  task_id: taskId,
  level: 'INFO',
  message: 'Creating task record...',
  sequence: -1,
  created_at: new Date().toISOString(),
})

const makeSyntheticFailureLogEntry = (taskId: string, message: string): LogEntry => ({
  id: SYNTHETIC_FAILURE_LOG_ID,
  task_id: taskId,
  level: 'ERROR',
  message,
  sequence: -2,
  created_at: new Date().toISOString(),
})

const makeSyntheticCancelledLogEntry = (taskId: string, message: string): LogEntry => ({
  id: SYNTHETIC_CANCELLED_LOG_ID,
  task_id: taskId,
  level: 'WARNING',
  message,
  sequence: -3,
  created_at: new Date().toISOString(),
})

const isExternalValidationTaskId = (taskId: string | undefined): boolean => Boolean(taskId?.startsWith('extval_'))

export default function TaskDetailPage() {
  const { t } = useTranslation()
  const { task_id } = useParams<{ task_id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { isAdmin, canUseGpu } = useAuth()
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [waitingForCreation, setWaitingForCreation] = useState(false)
  const [creationSlow, setCreationSlow] = useState(false)
  const [creationIssue, setCreationIssue] = useState<{ kind: 'failed' | 'cancelled'; message: string } | null>(null)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState(false)
  const [cancelling, runCancelling] = useAsyncAction()
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [batchSummary, setBatchSummary] = useState<BatchInferenceSummary | null>(null)
  const [batchResults, setBatchResults] = useState<BatchInferenceResult[]>([])
  const [batchResultsTotal, setBatchResultsTotal] = useState(0)
  const [batchResultsPage, setBatchResultsPage] = useState(0)
  const batchResultsLimit = 50
  const [batchResultsLoading, setBatchResultsLoading] = useState(false)
  const [batchExporting, setBatchExporting] = useState(false)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const logsContainerRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const resolveTrackedCreationIssue = (id: string) => {
    const tracked = getTrainingSubmissionRecord(id)
    if (tracked?.state === 'failed') {
      return { kind: 'failed' as const, message: tracked.error || t('taskDetail.creatingTaskFailedDescription') }
    }
    if (tracked?.state === 'cancelled') {
      return { kind: 'cancelled' as const, message: tracked.error || t('backgroundTask.serverStatus.training.cancelled') }
    }
    return null
  }

  // Load initial task details on mount
  useEffect(() => {
    setLogs([])
    setTask(null)
    setWaitingForCreation(false)
    setCreationSlow(false)
    setCreationIssue(null)
    loadTaskDetail()
  }, [task_id])

  useEffect(() => {
    if (!task_id) return

    setLogs(prev => {
      let next = prev

      if (waitingForCreation) {
        if (!next.some(log => log.id === CREATING_LOG_ID)) {
          next = [makeCreatingLogEntry(task_id), ...next]
        }
      }

      if (creationIssue?.kind === 'failed') {
        const failureMessage = creationIssue.message || 'Task creation failed.'
        if (!next.some(log => log.id === SYNTHETIC_FAILURE_LOG_ID)) {
          next = [...next, makeSyntheticFailureLogEntry(task_id, failureMessage)]
        }
      } else {
        next = next.filter(log => log.id !== SYNTHETIC_FAILURE_LOG_ID)
      }

      if (creationIssue?.kind === 'cancelled') {
        const cancelledMessage = creationIssue.message || 'Task creation was cancelled.'
        if (!next.some(log => log.id === SYNTHETIC_CANCELLED_LOG_ID)) {
          next = [...next, makeSyntheticCancelledLogEntry(task_id, cancelledMessage)]
        }
      } else {
        next = next.filter(log => log.id !== SYNTHETIC_CANCELLED_LOG_ID)
      }

      return next
    })
  }, [waitingForCreation, creationIssue, task_id])

  // Setup SSE for real-time log streaming and task status updates
  useEffect(() => {
    if (!task_id || !task) return

    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated
    if (!token) {
      return
    }

    const sseUrl = withAuthTokenQuery(`${API_BASE}/tasks/training/${task_id}/logs/stream`)

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
  }, [task_id, task?.task_id])

  // Load batch inference data when task is batch_inference type
  useEffect(() => {
    if (!task || task.task_type !== 'batch_inference') return
    const loadBatchData = async () => {
      setBatchResultsLoading(true)
      try {
        const [summary, results] = await Promise.all([
          getBatchInferenceSummary(task.task_id),
          getBatchInferenceResults(task.task_id, batchResultsPage * batchResultsLimit, batchResultsLimit),
        ])
        setBatchSummary(summary)
        setBatchResults(results.items)
        setBatchResultsTotal(results.total)
      } catch (error) {
        console.error('Failed to load batch inference data:', error)
      } finally {
        setBatchResultsLoading(false)
      }
    }
    void loadBatchData()
  }, [task?.task_id, task?.task_type, task?.status, batchResultsPage, batchResultsLimit])

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
      setWaitingForCreation(false)
      setCreationSlow(false)
      setCreationIssue(null)
      markTrainingSubmissionCreated(task_id)
    } catch (error) {
      // If task not found (404), it may still be creating on the backend
      // (fire-and-forget submission). Start polling instead of showing error immediately.
      if (error instanceof ApiError && error.isNotFound()) {
        const tracked = getTrainingSubmissionRecord(task_id)
        const trackedIssue = resolveTrackedCreationIssue(task_id)
        if (trackedIssue) {
          setCreationIssue(trackedIssue)
          setCreationSlow(false)
          setWaitingForCreation(false)
        } else if (tracked?.state === 'pending' || tracked?.state === 'created') {
          setCreationIssue(null)
          setWaitingForCreation(true)
        } else {
          setCreationIssue(null)
          setWaitingForCreation(false)
        }
      } else {
        console.error('Failed to load task detail:', error)
        const tracked = getTrainingSubmissionRecord(task_id)
        if (tracked?.state === 'pending' || tracked?.state === 'created') {
          setCreationIssue(null)
          setWaitingForCreation(true)
        }
      }
    } finally {
      setLoading(false)
    }
  }

  // Poll for task creation when task is not found yet (fire-and-forget submission)
  useEffect(() => {
    if (!waitingForCreation || !task_id || task) return

    let attempts = 0
    const intervalId = setInterval(async () => {
      attempts++
      try {
        const data = await getTrainingTask(task_id)
        setTask(data as TaskDetail)
        setWaitingForCreation(false)
        setCreationSlow(false)
        setCreationIssue(null)
        markTrainingSubmissionCreated(task_id)
        clearInterval(intervalId)
      } catch (error) {
        const trackedIssue = resolveTrackedCreationIssue(task_id)
        if (trackedIssue) {
          setCreationIssue(trackedIssue)
          setWaitingForCreation(false)
          clearInterval(intervalId)
          return
        }

        if (error instanceof ApiError && error.isNotFound()) {
          if (attempts >= 30) {
            setCreationSlow(true)
          }
          return
        }

        console.error('Failed while waiting for task creation:', error)
        const tracked = getTrainingSubmissionRecord(task_id)
        if (tracked?.state === 'pending') {
          return
        }
      }
    }, 2000)

    return () => clearInterval(intervalId)
  }, [waitingForCreation, task_id, task])

  const getStatusBadge = (status: TaskDetail['status'], taskType?: string) => {
    const badge = TASK_DETAIL_STATUS_BADGES[status] || { bg: 'bg-gray-100', text: 'text-gray-800', label: status }

    // Use the same i18n key strategy as TaskListPage for consistency
    let label: string
    if (isExternalValidationTaskId(task_id)) {
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
      if (status === 'creating' || status === 'pending' || status === 'queued') return <Clock className="w-4 h-4 mr-1.5" />
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

  const handleRerun = async () => {
    setRerunError(null)

    if (task && isExternalValidationTaskId(task.task_id)) {
      const modelId = task.model_config?.model_id
      const datasetId = task.model_config?.dataset_id
      if (!modelId || !datasetId) {
        setRerunError(t('taskDetail.rerunErrorMissingConfig'))
        return
      }
      setRerunning(true)
      try {
        const syntheticTaskId = `extval_${crypto.randomUUID().replace(/-/g, '').substring(0, 16)}`
        markTrainingSubmissionPending(syntheticTaskId, `${task.task_name} (rerun)`, task.data_type)
        navigate(`/task/${syntheticTaskId}`)

        void startExternalValidation(
          modelId,
          datasetId,
          task.model_config.analysis_metrics,
          task.model_config.analysis_charts,
          (task.model_config.bootstrap_ci_metrics?.length ?? 0) > 0,
          isAdmin ? task.task_id : undefined
        ).then(result => {
          clearTrainingSubmissionRecord(syntheticTaskId)
          markTrainingSubmissionCreated(result.task_id)
          navigate(`/task/${result.task_id}`, { replace: true })
        }).catch((error: any) => {
          const message = error?.message || error?.detail || String(error)
          markTrainingSubmissionFailed(syntheticTaskId, message)
          console.error('Failed to rerun external validation in background:', error)
        })
      } catch (error: any) {
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
      return
    }

    if (task?.task_type === 'batch_inference') {
      setRerunError(t('taskDetail.rerunErrorGeneric'))
      return
    }

    if (!task || !task.wsi_ids || task.wsi_ids.length === 0) {
      setRerunError(t('taskDetail.rerunErrorMissingWsi'))
      return
    }

    if (!isCanonicalTaskType(task.task_type)) {
      setRerunError(t('taskDetail.rerunErrorGeneric'))
      return
    }
    const canonicalTaskType = task.task_type

    if (!task.preprocessing_config || !task.model_config) {
      setRerunError(t('taskDetail.rerunErrorMissingConfig'))
      return
    }

    setRerunning(true)
    try {
      const taskId = `train_${crypto.randomUUID().replace(/-/g, '').substring(0, 16)}`
      markTrainingSubmissionPending(taskId, `${task.task_name} (rerun)`, task.data_type)
      void createTrainingTask({
        task_id: taskId,
        rerun_from_task_id: isAdmin ? task.task_id : undefined,
        task_name: `${task.task_name} (rerun)`,
        task_type: canonicalTaskType,
        data_type: task.data_type,
        task_description: task.task_description,
        wsi_ids: task.wsi_ids,
        preprocessing: {
          // Note: tile_size and stride are now auto-determined by PrePATH-style tiling
          feature_extractor: task.preprocessing_config.feature_extractor ?? 'resnet50',
          feature_batch_size: task.preprocessing_config.feature_batch_size ?? 256,
          use_gpu: (task.preprocessing_config.use_gpu ?? false) && canUseGpu,
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
          classifier: task.model_config.classifier,
          learning_rate: task.model_config.learning_rate ?? 0.0001,
          epochs: task.model_config.epochs ?? 10,
          optimizer: task.model_config.optimizer ?? 'adam',
          batch_size: task.model_config.batch_size ?? (task.data_type === 'patch' ? 64 : 1),
          auto_balance: task.model_config.auto_balance ?? false,
          early_stopping_patience: task.model_config.early_stopping_patience,
          // Segmentation-specific fields
          ...(isSegmentationTask(task.task_type) ? {
            architecture: task.model_config.architecture,
            loss_names: task.model_config.loss_names,
            loss_weights: task.model_config.loss_weights,
          } : {}),
        },
        // Preserve the original split configuration for exact rerun
        split_config: task.preprocessing_config.split_config,
      }).then(() => {
        markTrainingSubmissionCreated(taskId)
      }).catch((error: any) => {
        const message = error?.message || error?.detail || String(error)
        markTrainingSubmissionFailed(taskId, message)
        console.error('Failed to rerun task in background:', error)
      })
      // Navigate to the new task
      navigate(`/task/${taskId}`)
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

  const handleCancelTask = () => {
    if (!task_id) return
    setShowCancelConfirm(false)
    return runCancelling(async () => {
      await cancelQueueTask(task_id)
      // Task status will be updated via SSE
    })
  }

  if (loading && !task) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  const trackedSubmission = task_id ? getTrainingSubmissionRecord(task_id) : null
  const syntheticStatus = creationIssue?.kind === 'failed'
    ? 'failed'
    : creationIssue?.kind === 'cancelled'
      ? 'cancelled'
      : waitingForCreation
        ? 'creating'
        : null
  const displayTask = (!task && task_id && syntheticStatus)
    ? makeSyntheticTask(task_id, {
      taskName: trackedSubmission?.taskName,
      status: syntheticStatus,
      errorMessage: creationIssue?.message,
      dataType: (trackedSubmission?.dataType as TaskDetail['data_type']) ?? 'wsi',
    })
    : task

  if (!displayTask) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <AlertCircle className="w-12 h-12 text-red-500" />
        <div className="text-xl font-semibold text-gray-900">{t('taskDetail.taskNotFound')}</div>
        <p className="text-gray-500 text-center max-w-xl">{t('taskDetail.taskNotFoundDescription')}</p>
        <Button onClick={() => navigate(fromAIChat ? '/dashboard' : '/task-list')} variant="outline">
          {fromAIChat ? t('taskDetail.backToChat') : t('taskDetail.backToTaskList')}
        </Button>
        {task_id && (
          <Button
            variant="outline"
            className="text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
            onClick={() => {
              clearTrainingSubmissionRecord(task_id)
              navigate('/task-list')
            }}
          >
            {t('taskList.deleteTask')}
          </Button>
        )}
      </div>
    )
  }

  const isPatchLevel = displayTask.data_type === 'patch'
  const isExternalValidation = isExternalValidationTaskId(displayTask.task_id)
  const isBatchInference = displayTask.task_type === 'batch_inference'
  const batchTaskType = batchSummary?.task_type ?? ''

  // Display task progress directly in the standard 0-100 range.
  const displayProgress = displayTask.status === 'completed'
    ? 100
    : Math.max(0, Math.min(displayTask.progress, 100))

  return (
    <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6 pb-12">
      {/* Header */}
      <div className="mb-4 sm:mb-6">
        <Button
          variant="ghost"
          type="button"
          onClick={() => navigate(fromAIChat ? '/dashboard' : '/task-list')}
          className="mb-1 sm:mb-2 pl-0 hover:bg-transparent hover:text-gray-900 text-gray-500 text-xs sm:text-base"
        >
          <svg aria-hidden="true" className="w-4 h-4 sm:w-5 sm:h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {fromAIChat ? t('taskDetail.backToChat') : t('taskDetail.tasks')}
        </Button>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl sm:text-3xl font-bold text-gray-900 truncate mb-1" title={displayTask.task_name}>{displayTask.task_name}</h1>
            <p className="text-xs sm:text-sm text-gray-500 line-clamp-2">
              {waitingForCreation
                ? (creationSlow ? t('taskDetail.creatingTaskSlowDescription') : t('taskDetail.creatingTaskDescription'))
                : displayTask.task_description}
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {getStatusBadge(displayTask.status, displayTask.task_type)}
            {displayTask.status === 'completed' && !isBatchInference && (
              <Button
                variant="default"
                onClick={() => {
                  const mode = isExternalValidation ? 'external-validation' : 'internal-analysis'
                  navigate('/results', { state: { pageMode: mode, selectedTaskId: displayTask.task_id } })
                }}
                className="flex items-center gap-2 h-9 px-4 rounded-full font-bold shadow-sm transition-all"
              >
                <BarChart3 className="w-4 h-4" />
                {t('taskDetail.viewAnalysis')}
              </Button>
            )}
            {isBatchInference && displayTask.status === 'completed' && (
              <Button
                variant="default"
                onClick={async () => {
                  setBatchExporting(true)
                  try {
                    await exportBatchInferenceCsv(displayTask.task_id)
                  } catch (e) {
                    console.error('Export failed:', e)
                  } finally {
                    setBatchExporting(false)
                  }
                }}
                disabled={batchExporting}
                className="flex items-center gap-2 h-9 px-4 rounded-full font-bold shadow-sm transition-all bg-purple-600 hover:bg-purple-700 text-white"
              >
                {batchExporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                {t('taskDetail.batchInference.exportCsv')}
              </Button>
            )}
            {!waitingForCreation && !isBatchInference && (task?.status === 'failed' || task?.status === 'cancelled') && (
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
              const canCancelCreating = waitingForCreation
              const canCancelServerTask = cancellableStatuses.some(status => status === displayTask.status)
              return (canCancelCreating || canCancelServerTask) && (
                <Button
                variant="outline"
                onClick={() => {
                  if (waitingForCreation) {
                    if (task_id) {
                      markTrainingSubmissionCancelled(task_id)
                    }
                    navigate(fromAIChat ? '/dashboard' : '/task-list')
                    return
                  }
                  setShowCancelConfirm(true)
                }}
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
            <button type="button" onClick={() => setRerunError(null)} className="ml-2 text-red-400 hover:text-red-600">
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>

      {/* Task Info Grid */}
      <Card surface="elevated" className="overflow-hidden border-[color:var(--surface-border)] p-4 shadow-[var(--shadow-elevated)] sm:p-6">
        <div className={`grid grid-cols-2 ${isAdmin && displayTask.username ? 'md:grid-cols-5' : 'md:grid-cols-4'} gap-4 sm:gap-6`}>
          <div className="min-w-0">
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 sm:text-xs">{t('taskDetail.taskId')}</div>
            <div className="flex items-center gap-1.5 overflow-hidden">
              <div className="truncate font-mono text-[11px] font-bold text-slate-700 sm:text-sm">{displayTask.task_id}</div>
              <button
                type="button"
                onClick={() => {
                  if (navigator.clipboard && navigator.clipboard.writeText) {
                      navigator.clipboard.writeText(displayTask.task_id)
                  } else {
                    // Fallback for Electron or non-secure contexts
                    const textArea = document.createElement('textarea')
                    textArea.value = displayTask.task_id
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
                  className="shrink-0 rounded-md p-1 text-slate-400 transition-all hover:bg-[color:var(--surface-muted)] hover:text-slate-900"
              >
                <svg aria-hidden="true" className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>
              {copySuccess && (
                <div className="mt-1 whitespace-nowrap rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold leading-none text-emerald-700 shadow-sm">
                  {t('taskDetail.copied')}
                </div>
              )}
          </div>
          <div>
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 sm:text-xs">
              {t('taskDetail.data')}
            </div>
            <div className="flex items-end gap-1.5">
                  <span className="text-lg font-semibold leading-none tracking-[-0.04em] text-slate-950 sm:text-2xl">{displayTask.wsi_count}</span>
                  <span className="mb-0.5 text-[10px] font-medium text-slate-500 sm:text-xs">{displayTask.data_type === 'patch' ? t('taskDetail.patches') : t('taskDetail.slides')}</span>
            </div>
          </div>
          <div>
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 sm:text-xs">{t('taskDetail.created')}</div>
            <div className="truncate text-xs font-bold text-slate-700 sm:text-sm">{formatDateTime(displayTask.created_at)}</div>
          </div>
          <div>
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 sm:text-xs">{t('taskDetail.updated')}</div>
            <div className="truncate text-xs font-bold text-slate-700 sm:text-sm">{formatDateTime(displayTask.updated_at)}</div>
          </div>
          {isAdmin && displayTask.username && (
            <div>
              <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 sm:text-xs">{t('taskDetail.creator')}</div>
              <div className="flex items-center gap-1.5">
                <User className="h-3.5 w-3.5 text-slate-400" />
                <div className="truncate text-xs font-bold text-slate-700 sm:text-sm" title={displayTask.username}>{displayTask.username}</div>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Progress Section */}
      <ProgressSection
        task={displayTask}
        displayProgress={displayProgress}
        isPatchLevel={isPatchLevel}
        isExternalValidation={isExternalValidation}
      />

      {/* Error Message Display */}
      {displayTask.status === 'failed' && displayTask.error_message && (() => {
        const errorInfo = parseTaskError(displayTask.error_message)
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
                    {displayTask.error_message}
                  </pre>
                </details>
                {!task && task_id && (
                  <div className="mt-4">
                    <Button
                      variant="outline"
                      className="text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                      onClick={() => {
                        clearTrainingSubmissionRecord(task_id)
                        navigate('/task-list')
                      }}
                    >
                      {t('taskList.deleteTask')}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </Card>
        )
      })()}

      {displayTask.status === 'cancelled' && !task && task_id && (
        <Card className="p-6 border-gray-200 bg-gray-50">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-6 h-6 text-gray-500 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-gray-800 mb-2">{t('backgroundTask.serverStatus.training.cancelled')}</h3>
              <p className="text-gray-700 mb-3">{creationIssue?.message || t('backgroundTask.serverStatus.training.cancelled')}</p>
              <Button
                variant="outline"
                className="text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                onClick={() => {
                  clearTrainingSubmissionRecord(task_id)
                  navigate('/task-list')
                }}
              >
                {t('taskList.deleteTask')}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {!isBatchInference && (
        <LogViewer
          logs={logs}
          logsContainerRef={logsContainerRef}
          logsEndRef={logsEndRef}
        />
      )}

      {task && !waitingForCreation && !isBatchInference && <ConfigurationPanel task={task} />}

      {isBatchInference && (
        <div className="space-y-4">
          {batchSummary && (
            <Card className="p-4 sm:p-6 border-purple-100 shadow-sm">
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Cpu className="w-4 h-4 text-purple-500" />
                {t('taskDetail.batchInference.summary')}
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">{t('taskDetail.batchInference.totalSlides')}</div>
                  <div className="text-2xl font-bold text-gray-900">{batchSummary.total_slides}</div>
                </div>
                <div>
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">{t('taskDetail.batchInference.processedSlides')}</div>
                  <div className="text-2xl font-bold text-purple-600">{batchSummary.processed_slides}</div>
                </div>
                {batchSummary.class_distribution && Object.keys(batchSummary.class_distribution).length > 0 && (
                  <div className="col-span-2">
                    <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">{t('taskDetail.batchInference.classDistribution')}</div>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(batchSummary.class_distribution).map(([cls, count]) => (
                        <span key={cls} className="px-2 py-1 bg-purple-50 border border-purple-200 rounded-md text-xs font-medium text-purple-700">
                          {cls}: {count}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider flex items-center gap-2">
                <Table2 className="w-4 h-4 text-gray-400" />
                {t('taskDetail.batchInference.results')}
                {batchResultsTotal > 0 && (
                  <span className="text-gray-400 font-normal normal-case text-xs">({batchResultsTotal})</span>
                )}
              </h3>
            </div>
            {batchResultsLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-purple-500" />
              </div>
            ) : batchResults.length === 0 ? (
              <div className="text-center py-8 text-gray-400 text-sm">{t('taskDetail.batchInference.noResults')}</div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.slideId')}</th>
                        <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.filename')}</th>
                        {batchTaskType.includes('classification') && (
                          <>
                            <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.prediction')}</th>
                            <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.confidence')}</th>
                          </>
                        )}
                        {batchTaskType.includes('survival') && (
                          <>
                            <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.riskScore')}</th>
                            <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.riskGroup')}</th>
                          </>
                        )}
                        {batchTaskType.includes('segmentation') && (
                          <th className="text-left py-2 px-3 text-xs font-bold text-gray-400 uppercase tracking-wider">{t('taskDetail.batchInference.predictionMask')}</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {batchResults.map((result, idx) => {
                        const topProb = result.probs
                          ? Math.max(...Object.values(result.probs))
                          : null
                        const riskScore = result.metadata?.risk_score != null
                          ? Number(result.metadata.risk_score).toFixed(3)
                          : '—'
                        const riskGroup = result.metadata?.risk_group != null
                          ? String(result.metadata.risk_group)
                          : '—'
                        const maskGenerated = result.metadata?.pred_mask_path || result.metadata?.pred_mask_file
                          ? t('taskDetail.batchInference.maskGenerated')
                          : t('taskDetail.batchInference.maskMissing')
                        return (
                          <tr key={result.wsi_id || idx} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                            <td className="py-2 px-3 font-mono text-xs text-gray-600 truncate max-w-[120px]" title={result.wsi_id}>{result.wsi_id}</td>
                            <td className="py-2 px-3 text-gray-700 truncate max-w-[200px]" title={result.original_filename ?? ''}>{result.original_filename ?? '—'}</td>
                            {batchTaskType.includes('classification') && (
                              <>
                                <td className="py-2 px-3">
                                  {result.pred ? (
                                    <span className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs font-medium text-purple-700">{result.pred}</span>
                                  ) : '—'}
                                </td>
                                <td className="py-2 px-3 text-gray-700 text-xs">
                                  {topProb !== null ? `${(topProb * 100).toFixed(1)}%` : '—'}
                                </td>
                              </>
                            )}
                            {batchTaskType.includes('survival') && (
                              <>
                                <td className="py-2 px-3 text-gray-700 text-xs">{riskScore}</td>
                                <td className="py-2 px-3 text-gray-700 text-xs">{riskGroup}</td>
                              </>
                            )}
                            {batchTaskType.includes('segmentation') && (
                              <td className="py-2 px-3 text-gray-700 text-xs">{maskGenerated}</td>
                            )}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                {batchResultsTotal > batchResultsLimit && (
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
                    <span className="text-xs text-gray-400">
                      {t('taskDetail.batchInference.showing', {
                        start: batchResultsPage * batchResultsLimit + 1,
                        end: Math.min((batchResultsPage + 1) * batchResultsLimit, batchResultsTotal),
                        total: batchResultsTotal,
                      })}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setBatchResultsPage(p => Math.max(0, p - 1))}
                        disabled={batchResultsPage === 0}
                        className="px-3 py-1 text-xs font-medium border border-gray-200 rounded-md disabled:opacity-40 hover:bg-gray-50 transition-colors"
                      >
                        {t('taskDetail.batchInference.previous')}
                      </button>
                      <button
                        type="button"
                        onClick={() => setBatchResultsPage(p => p + 1)}
                        disabled={(batchResultsPage + 1) * batchResultsLimit >= batchResultsTotal}
                        className="px-3 py-1 text-xs font-medium border border-gray-200 rounded-md disabled:opacity-40 hover:bg-gray-50 transition-colors"
                      >
                        {t('taskDetail.batchInference.next')}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </Card>
        </div>
      )}

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
