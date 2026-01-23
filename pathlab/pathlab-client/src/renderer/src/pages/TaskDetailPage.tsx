import React, { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { CheckCircle2, Circle, Loader2, Clock, XCircle, RotateCcw, AlertCircle, Activity, ClipboardList, Layers, Brain } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'
import { createTrainingTask } from '../api'

interface LogEntry {
  id: number
  task_id: string
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
  message: string
  sequence: number
  metadata?: Record<string, any>
  created_at: string
}

interface TaskDetail {
  task_id: string
  task_name: string
  task_type: 'classification' | 'survival_prediction' | 'segmentation'
  data_level: 'wsi' | 'patch'
  task_description: string
  status: 'pending' | 'running' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled'
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  wsi_ids?: string[]
  preprocessing_config: {
    tile_size?: number
    stride?: number
    feature_extractor?: string
    feature_batch_size?: number
    use_gpu?: boolean
  }
  model_config: {
    aggregator?: string
    learning_rate?: number
    epochs?: number
    optimizer?: string
    batch_size?: number
  }
  classes?: string[]
  error_message?: string
  patch_count?: number
  processed_patches?: number
  current_epoch?: number
}

/**
 * Parse VRAM-related error messages and extract suggested batch_size.
 * Returns structured error info for better user feedback.
 */
function parseVRAMError(errorMessage: string): {
  isVRAMError: boolean
  suggestedBatchSize: number | null
  originalMessage: string
  userFriendlyMessage: string
} {
  const result = {
    isVRAMError: false,
    suggestedBatchSize: null as number | null,
    originalMessage: errorMessage,
    userFriendlyMessage: errorMessage,
  }

  // Check if this is a VRAM protection error
  if (errorMessage.toLowerCase().includes('vram') ||
      errorMessage.toLowerCase().includes('gpu memory') ||
      errorMessage.toLowerCase().includes('out of memory') ||
      errorMessage.toLowerCase().includes('oom')) {
    result.isVRAMError = true

    // Try to extract suggested batch_size from error message
    // Pattern: "suggested safe batch_size: 123" or "reduce batch_size to 123"
    const batchSizeMatch = errorMessage.match(/batch_size[:\s]+(\d+)|batch_size to (\d+)/i)
    if (batchSizeMatch) {
      result.suggestedBatchSize = parseInt(batchSizeMatch[1] || batchSizeMatch[2], 10)
    }

    // Create user-friendly message
    result.userFriendlyMessage = result.suggestedBatchSize
      ? `GPU memory exceeded. Please reduce the batch size to ${result.suggestedBatchSize} or lower and try again.`
      : 'GPU memory exceeded. Please reduce the batch size and try again.'
  }

  return result
}

export default function TaskDetailPage() {
  const { task_id } = useParams<{ task_id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState(false)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Load initial task details on mount
  useEffect(() => {
    setLogs([])
    loadTaskDetail()
  }, [task_id])

  // Setup SSE for real-time log streaming and task status updates
  useEffect(() => {
    if (!task_id) return

    // Create EventSource for SSE
    const eventSource = new EventSource(`${API_BASE}/tasks/training/${task_id}/logs/stream`)
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
        // Preserve wsi_ids from initial load since SSE doesn't include them
        if (data.task) {
          setTask(prev => ({
            ...data.task,
            wsi_ids: data.task.wsi_ids || prev?.wsi_ids
          }))
        }

        // Handle log data
        if (data.logs && data.logs.length > 0) {
          setLogs(prev => {
            // Deduplicate logs based on ID
            const existingIds = new Set(prev.map(log => log.id))
            const uniqueNewLogs = data.logs.filter(log => !existingIds.has(log.id))

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
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const loadTaskDetail = async () => {
    if (!task_id) return

    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/tasks/training/${task_id}`)
      if (!response.ok) {
        throw new Error('Failed to load task details')
      }
      const data = await response.json()
      setTask(data)
    } catch (error) {
      console.error('Failed to load task detail:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadge = (status: TaskDetail['status']) => {
    const badges: Record<string, { bg: string; text: string; label: string; icon: React.ReactNode }> = {
      pending: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Pending', icon: <Clock className="w-4 h-4 mr-1.5" /> },
      running: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Running', icon: <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> },
      extracting: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Extracting Features', icon: <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> },
      training: { bg: 'bg-purple-100', text: 'text-purple-800', label: 'Training Model', icon: <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> },
      completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Success', icon: <CheckCircle2 className="w-4 h-4 mr-1.5" /> },
      failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed', icon: <XCircle className="w-4 h-4 mr-1.5" /> },
      cancelled: { bg: 'bg-gray-100', text: 'text-gray-600', label: 'Cancelled', icon: <XCircle className="w-4 h-4 mr-1.5" /> }
    }
    const badge = badges[status] || { bg: 'bg-gray-100', text: 'text-gray-800', label: status, icon: null }
    return (
      <span className={`inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold shadow-sm ${badge.bg} ${badge.text}`}>
        {badge.icon}
        {badge.label}
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
      setRerunError('Cannot rerun: missing WSI IDs')
      return
    }

    if (!task.preprocessing_config || !task.model_config) {
      setRerunError('Cannot rerun: missing configuration')
      return
    }

    setRerunning(true)
    try {
      const result = await createTrainingTask({
        task_name: `${task.task_name} (rerun)`,
        task_type: task.task_type,
        data_level: task.data_level,
        task_description: task.task_description,
        wsi_ids: task.wsi_ids,
        preprocessing: {
          tile_size: task.preprocessing_config.tile_size ?? 512,
          stride: task.preprocessing_config.stride ?? 512,
          feature_extractor: task.preprocessing_config.feature_extractor ?? 'resnet50',
          feature_batch_size: task.preprocessing_config.feature_batch_size ?? 256,
          use_gpu: task.preprocessing_config.use_gpu ?? true,
        },
        model: {
          aggregator: task.model_config.aggregator ?? 'abmil',
          learning_rate: task.model_config.learning_rate ?? 0.0001,
          epochs: task.model_config.epochs ?? 10,
          optimizer: task.model_config.optimizer ?? 'adam',
          batch_size: task.model_config.batch_size ?? 1,
        },
      })
      // Navigate to the new task
      navigate(`/task/${result.task_id}`)
    } catch (error) {
      console.error('Failed to rerun task:', error)
      setRerunError('Failed to rerun task. Please try again.')
    } finally {
      setRerunning(false)
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
        <div className="text-xl font-semibold text-gray-900">Task Not Found</div>
        <p className="text-gray-500">The task you are looking for does not exist or could not be loaded.</p>
        <Button onClick={() => navigate('/task-list')} variant="outline">
          Back to Task List
        </Button>
      </div>
    )
  }

  const isPatchLevel = task.data_level === 'patch'

  // Calculate display progress for patch-level tasks
  // (map 66% - 100% backend progress to 0% - 100% UI progress)
  // For completed tasks, always show 100%
  // For cancelled/failed tasks, show the mapped progress at the time of cancellation/failure
  const displayProgress = isPatchLevel && task.status !== 'completed'
    ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
    : task.progress

  return (
    <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6 pb-12">
      {/* Header */}
      <div className="mb-4 sm:mb-6">
        <Button
          variant="ghost"
          onClick={() => navigate('/task-list')}
          className="mb-1 sm:mb-2 pl-0 hover:bg-transparent hover:text-gray-900 text-gray-500 text-xs sm:text-base"
        >
          <svg className="w-4 h-4 sm:w-5 sm:h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Tasks
        </Button>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl sm:text-3xl font-bold text-gray-900 truncate mb-1" title={task.task_name}>{task.task_name}</h1>
            <p className="text-xs sm:text-sm text-gray-500 line-clamp-2">{task.task_description}</p>
          </div>
          <div className="flex flex-row sm:flex-col items-center sm:items-end gap-2 shrink-0">
            {getStatusBadge(task.status)}
            {task.status === 'failed' && (
              <Button
                onClick={handleRerun}
                disabled={rerunning}
                size="sm"
                className="flex items-center gap-1.5 h-8 px-3 text-xs font-bold"
              >
                {rerunning ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="w-3.5 h-3.5" />
                )}
                Rerun
              </Button>
            )}
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 sm:gap-6">
          <div className="min-w-0">
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">Task ID</div>
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
              <div className="text-[9px] text-green-600 font-bold mt-1">Copied!</div>
            )}
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">
              {task.data_level === 'patch' ? 'Data' : 'Slides'}
            </div>
            <div className="flex items-end gap-1.5">
              <span className="text-lg sm:text-2xl font-bold text-gray-900 leading-none">{task.wsi_count}</span>
              <span className="text-[10px] sm:text-xs text-gray-500 font-medium mb-0.5">{task.data_level === 'patch' ? 'patches' : 'files'}</span>
            </div>
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">Created</div>
            <div className="text-xs sm:text-sm font-bold text-gray-700 truncate">{formatDate(task.created_at)}</div>
          </div>
          <div>
            <div className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-1.5">Updated</div>
            <div className="text-xs sm:text-sm font-bold text-gray-700 truncate">{formatDate(task.updated_at)}</div>
          </div>
        </div>
      </Card>

      {/* Progress Section */}
      <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
        <h3 className="text-sm sm:text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <Activity className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
          Execution Progress
        </h3>

        {/* Overall Progress */}
        <div className="mb-6 bg-gray-50/50 p-3 sm:p-4 rounded-xl border border-gray-100">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs sm:text-sm font-bold text-gray-600 uppercase tracking-wide">Overall Completion</span>
            <span className="text-sm sm:text-lg font-black text-primary-600">{displayProgress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2 sm:h-3 overflow-hidden">
            <div
              className="bg-primary-600 h-full rounded-full transition-all duration-1000 ease-out shadow-sm"
              style={{ width: `${displayProgress}%` }}
            />
          </div>
        </div>

        {/* Stage Progress */}
        <div className="space-y-3">
          {!isPatchLevel ? (
            <>
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-2">
                  <span className={
                    (task.status === 'running') ? 'text-blue-600' :
                    (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                    (task.status === 'failed' && task.progress < 30) ? 'text-red-600' : 'text-gray-400'
                  }>
                    { (task.status === 'running') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                      (task.status === 'extracting' || task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                      (task.status === 'failed' && task.progress < 30) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
                  </span>
                  <span className={task.status !== 'pending' ? 'text-gray-900' : 'text-gray-500'}>
                    Patch Extraction
                  </span>
                </div>
                {task.patch_count && task.patch_count > 0 && (
                  <span className="text-gray-600">{task.patch_count.toLocaleString()} patches</span>
                )}
              </div>

              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-2">
                  <span className={
                    (task.status === 'training' || task.status === 'completed') ? 'text-green-600' :
                    (task.status === 'extracting') ? 'text-blue-600' :
                    (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? 'text-red-600' : 'text-gray-400'
                  }>
                    { (task.status === 'training' || task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                      (task.status === 'extracting') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                      (task.status === 'failed' && task.progress >= 30 && task.progress < 70) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
                  </span>
                  <span className={(task.status === 'training' || task.status === 'completed' || task.status === 'extracting') ? 'text-gray-900' : 'text-gray-500'}>
                    Feature Extraction
                  </span>
                </div>
                {task.processed_patches && task.patch_count && (
                  <span className="text-gray-600">{task.processed_patches.toLocaleString()}/{task.patch_count.toLocaleString()}</span>
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center space-x-2">
                <span className="text-green-600">
                  <CheckCircle2 className="w-4 h-4" />
                </span>
                <span className="text-gray-900">
                  Data Loading
                </span>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={
                (task.status === 'completed') ? 'text-green-600' :
                (task.status === 'training') ? 'text-purple-600' :
                (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? 'text-red-600' : 'text-gray-400'
              }>
                { (task.status === 'completed') ? <CheckCircle2 className="w-4 h-4" /> :
                  (task.status === 'training') ? <Loader2 className="w-4 h-4 animate-spin" /> :
                  (task.status === 'failed' && (isPatchLevel || task.progress >= 70)) ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" /> }
              </span>
              <span className={(task.status === 'completed' || task.status === 'training') ? 'text-gray-900' : 'text-gray-500'}>
                Model Training
              </span>
            </div>
            {task.status === 'training' && task.current_epoch && (
              <span className="text-gray-600">Epoch {task.current_epoch}/{task.model_config.epochs}</span>
            )}
          </div>
        </div>
      </Card>

      {/* Error Message Display */}
      {task.status === 'failed' && task.error_message && (() => {
        const errorInfo = parseVRAMError(task.error_message)
        return (
          <Card className="p-6 border-red-200 bg-red-50">
            <div className="flex items-start gap-3">
              <XCircle className="w-6 h-6 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-red-800 mb-2">Task Failed</h3>
                <p className="text-red-700 mb-3">{errorInfo.userFriendlyMessage}</p>
                {errorInfo.isVRAMError && errorInfo.suggestedBatchSize && (
                  <div className="bg-red-100 border border-red-200 rounded-lg p-3 mb-3">
                    <p className="text-sm text-red-800">
                      <strong>Suggestion:</strong> When creating a new task, set the Feature Batch Size to{' '}
                      <span className="font-mono font-bold">{errorInfo.suggestedBatchSize}</span> or lower.
                    </p>
                  </div>
                )}
                <details className="text-sm">
                  <summary className="text-red-600 cursor-pointer hover:text-red-800">
                    Show technical details
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
      <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm sm:text-lg font-bold text-gray-900 flex items-center gap-2">
            <ClipboardList className="w-4 h-4 sm:w-5 sm:h-5 text-gray-700" />
            Live Logs
          </h3>
          <div className="flex items-center space-x-1.5 sm:space-x-2 text-[10px] sm:text-xs text-gray-400 font-medium">
            <span className="inline-block w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
            <span>Live Stream</span>
          </div>
        </div>
        <div className="bg-gray-950 rounded-xl p-3 sm:p-4 h-[300px] sm:h-[450px] overflow-y-auto font-mono text-[10px] sm:text-xs leading-relaxed border border-gray-800 shadow-inner scrollbar-thin scrollbar-track-gray-900 scrollbar-thumb-gray-700">
          {logs.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-600 italic">
              Connecting to task stream...
            </div>
          ) : (
            logs.map((log) => (
              <div
                key={log.id}
                className={`mb-1.5 break-words ${
                  log.level === 'ERROR' ? 'text-red-400' :
                  log.level === 'WARNING' ? 'text-yellow-400/90' :
                  log.level === 'DEBUG' ? 'text-gray-500' :
                  'text-emerald-400/90'
                }`}
              >
                <span className="text-gray-600 whitespace-nowrap">[{new Date(log.created_at).toLocaleTimeString([], { hour12: false })}]</span>
                {' '}
                <span className={`font-bold uppercase tracking-wider ${
                  log.level === 'ERROR' ? 'text-red-500' :
                  log.level === 'WARNING' ? 'text-yellow-500' :
                  log.level === 'DEBUG' ? 'text-gray-600' :
                  'text-blue-500'
                }`}>
                  {log.level}
                </span>
                {' '}
                <span className="text-gray-300">{log.message}</span>
                {/* Display metadata for errors/warnings */}
                {log.metadata && Object.keys(log.metadata).length > 0 && (
                  <div className="ml-4 mt-1 bg-white/5 p-2 rounded border border-white/5">
                    {log.metadata.error && (
                      <div className="text-red-300 font-bold">Error: {log.metadata.error}</div>
                    )}
                    {log.metadata.traceback && (
                      <pre className="mt-1 whitespace-pre-wrap text-red-300/60 overflow-x-auto text-[9px] sm:text-[10px]">
                        {log.metadata.traceback}
                      </pre>
                    )}
                    {/* Display other metadata excluding error/traceback */}
                    {Object.entries(log.metadata)
                      .filter(([key]) => !['error', 'traceback'].includes(key))
                      .length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 opacity-60">
                        {Object.entries(log.metadata)
                          .filter(([key]) => !['error', 'traceback'].includes(key))
                          .map(([key, value]) => (
                            <span key={key} className="text-[9px] sm:text-[10px]">
                              <span className="text-gray-400 uppercase mr-1">{key}:</span>
                              <span className="text-gray-200">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </Card>

      {/* Configuration */}
      <Card className="p-4 sm:p-6 border-gray-100 shadow-sm overflow-hidden">
        <h3 className="text-sm sm:text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <Layers className="w-4 h-4 sm:w-5 sm:h-5 text-gray-700" />
          Configuration
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-blue-600" />
              Preprocessing
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Tile Size</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.tile_size
                    ? `${task.preprocessing_config.tile_size}px`
                    : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Stride</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.stride ? `${task.preprocessing_config.stride}px` : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Extractor</span>
                <span className="font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 shadow-sm">
                  {task.preprocessing_config.feature_extractor || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Batch Size</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.preprocessing_config.feature_batch_size ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-gray-50/80 rounded-xl p-4 border border-gray-100">
            <h4 className="text-xs sm:text-sm font-bold text-gray-900 mb-3 flex items-center gap-2">
              <Brain className="w-3.5 h-3.5 text-purple-600" />
              Model & Training
            </h4>
            <div className="space-y-3">
              {task.data_level === 'wsi' && (
                <div className="flex justify-between items-center text-[11px] sm:text-sm">
                  <span className="text-gray-500 font-medium">Aggregator</span>
                  <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100 shadow-sm">
                    {task.model_config.aggregator?.toUpperCase() || 'N/A'}
                  </span>
                </div>
              )}
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Learn Rate</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.learning_rate ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Epochs</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.epochs ?? 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Optimizer</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm uppercase">
                  {task.model_config.optimizer || 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center text-[11px] sm:text-sm">
                <span className="text-gray-500 font-medium">Train Batch</span>
                <span className="font-bold text-gray-900 bg-white px-2 py-0.5 rounded border border-gray-100 shadow-sm">
                  {task.model_config.batch_size ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}

