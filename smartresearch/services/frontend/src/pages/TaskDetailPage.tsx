import React, { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

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
  task_type: 'classification' | 'segmentation'
  task_description: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  preprocessing_config: {
    tile_size: number
    stride: number
    feature_extractor: string
    feature_batch_size: number
    use_gpu: boolean
  }
  model_config: {
    aggregator: string
    learning_rate: number
    epochs: number
    optimizer: string
    batch_size: number
  }
  classes?: string[]
  error_message?: string
  patch_count?: number
  processed_patches?: number
  current_epoch?: number
}

export default function TaskDetailPage() {
  const { task_id } = useParams<{ task_id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastSequence, setLastSequence] = useState(0)
  const logsEndRef = useRef<HTMLDivElement>(null)

  // Load task details on mount
  useEffect(() => {
    loadTaskDetail()
    loadLogs()
  }, [task_id])

  // Auto-refresh task status
  useEffect(() => {
    if (!autoRefresh || !task || task.status === 'completed' || task.status === 'failed') {
      return
    }

    const interval = setInterval(() => {
      loadTaskDetail()
    }, 3000) // Refresh every 3 seconds

    return () => clearInterval(interval)
  }, [autoRefresh, task])

  // Poll for new logs
  useEffect(() => {
    if (!task_id) return

    const interval = setInterval(() => {
      pollNewLogs()
    }, 2000) // Poll every 2 seconds

    return () => clearInterval(interval)
  }, [task_id, lastSequence])

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const loadTaskDetail = async () => {
    if (!task_id) return

    setLoading(true)
    try {
      const response = await fetch(`/tasks/training/${task_id}`)
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

  const loadLogs = async () => {
    if (!task_id) return

    try {
      const response = await fetch(`/tasks/training/${task_id}/logs/recent?count=100`)
      if (!response.ok) {
        throw new Error('Failed to load logs')
      }
      const data = await response.json()
      setLogs(data.logs || [])

      // Set last sequence for polling
      if (data.logs && data.logs.length > 0) {
        setLastSequence(data.logs[data.logs.length - 1].sequence)
      }
    } catch (error) {
      console.error('Failed to load logs:', error)
    }
  }

  const pollNewLogs = async () => {
    if (!task_id) return

    try {
      const response = await fetch(`/tasks/training/${task_id}/logs/stream?after_sequence=${lastSequence}`)
      if (!response.ok) {
        return
      }
      const data = await response.json()

      if (data.logs && data.logs.length > 0) {
        setLogs(prev => [...prev, ...data.logs])
        setLastSequence(data.last_sequence)
      }
    } catch (error) {
      // Silently fail for polling errors
      console.debug('Failed to poll logs:', error)
    }
  }

  const getStatusBadge = (status: TaskDetail['status']) => {
    const badges: Record<string, { bg: string; text: string; label: string }> = {
      pending: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Pending' },
      running: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Running' },
      patching: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Extracting Patches' },
      extracting: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Extracting Features' },
      training: { bg: 'bg-purple-100', text: 'text-purple-800', label: 'Training Model' },
      completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Completed' },
      failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' }
    }
    const badge = badges[status] || { bg: 'bg-gray-100', text: 'text-gray-800', label: status }
    return (
      <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${badge.bg} ${badge.text}`}>
        {badge.label}
      </span>
    )
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
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
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">Task Not Found</h2>
        <button
          onClick={() => navigate('/task-list')}
          className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
        >
          Back to Task List
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/task-list')}
            className="flex items-center text-gray-600 hover:text-gray-900 mb-2"
          >
            <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back to Task List
          </button>
          <h1 className="text-3xl font-bold text-gray-900">{task.task_name}</h1>
          <p className="text-gray-600 mt-1">{task.task_description}</p>
        </div>
        <div className="flex items-center space-x-3">
          <label className="flex items-center space-x-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            <span>Auto-refresh</span>
          </label>
          {getStatusBadge(task.status)}
        </div>
      </div>

      {/* Task Info */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-sm text-gray-600 mb-1">Task ID</div>
            <div className="font-mono text-sm font-medium text-gray-900">{task.task_id}</div>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">WSI Slides</div>
            <div className="text-lg font-semibold text-gray-900">{task.wsi_count}</div>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">Created</div>
            <div className="text-sm font-medium text-gray-900">{formatDate(task.created_at)}</div>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">Last Updated</div>
            <div className="text-sm font-medium text-gray-900">{formatDate(task.updated_at)}</div>
          </div>
        </div>
      </div>

      {/* Progress Section */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Training Progress</h3>

        {/* Overall Progress */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Overall Progress</span>
            <span className="text-sm font-medium text-gray-900">{task.progress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3">
            <div
              className="bg-primary-600 h-3 rounded-full transition-all duration-300"
              style={{ width: `${task.progress}%` }}
            />
          </div>
        </div>

        {/* Stage Progress */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={task.status !== 'pending' ? 'text-green-600' : 'text-gray-400'}>
                {task.status !== 'pending' ? '✓' : '○'}
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
              <span className={task.status === 'training' || task.status === 'completed' ? 'text-green-600' : task.status === 'extracting' ? 'text-blue-600' : 'text-gray-400'}>
                {task.status === 'training' || task.status === 'completed' ? '✓' : task.status === 'extracting' ? '⏳' : '○'}
              </span>
              <span className={task.status === 'training' || task.status === 'completed' || task.status === 'extracting' ? 'text-gray-900' : 'text-gray-500'}>
                Feature Extraction
              </span>
            </div>
            {task.processed_patches && task.patch_count && (
              <span className="text-gray-600">{task.processed_patches.toLocaleString()}/{task.patch_count.toLocaleString()}</span>
            )}
          </div>

          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center space-x-2">
              <span className={task.status === 'completed' ? 'text-green-600' : task.status === 'training' ? 'text-purple-600' : 'text-gray-400'}>
                {task.status === 'completed' ? '✓' : task.status === 'training' ? '⏳' : '○'}
              </span>
              <span className={task.status === 'completed' || task.status === 'training' ? 'text-gray-900' : 'text-gray-500'}>
                Model Training
              </span>
            </div>
            {task.status === 'training' && task.current_epoch && (
              <span className="text-gray-600">Epoch {task.current_epoch}/{task.model_config.epochs}</span>
            )}
          </div>
        </div>
      </div>

      {/* Live Logs */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">Live Logs</h3>
          <div className="flex items-center space-x-2 text-xs text-gray-500">
            <span className="inline-block w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
            <span>Real-time updates</span>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg p-4 h-96 overflow-y-auto font-mono text-xs">
          {logs.length === 0 ? (
            <div className="text-gray-500">No logs available yet...</div>
          ) : (
            logs.map((log) => (
              <div
                key={log.id}
                className={`mb-1 ${
                  log.level === 'ERROR' ? 'text-red-400' :
                  log.level === 'WARNING' ? 'text-yellow-400' :
                  log.level === 'DEBUG' ? 'text-gray-500' :
                  'text-green-400'
                }`}
              >
                <span className="text-gray-600">[{new Date(log.created_at).toLocaleTimeString()}]</span>
                {' '}
                <span className={`font-semibold ${
                  log.level === 'ERROR' ? 'text-red-500' :
                  log.level === 'WARNING' ? 'text-yellow-500' :
                  log.level === 'DEBUG' ? 'text-gray-600' :
                  'text-blue-500'
                }`}>
                  [{log.level}]
                </span>
                {' '}
                {log.message}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>

      {/* Configuration */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Task Configuration</h3>

        <div className="space-y-4">
          <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
            <h4 className="text-sm font-semibold text-gray-800 mb-3">Preprocessing</h4>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-600">Tile Size:</span>
                <span className="ml-2 font-medium text-gray-900">{task.preprocessing_config.tile_size}x{task.preprocessing_config.tile_size}</span>
              </div>
              <div>
                <span className="text-gray-600">Stride:</span>
                <span className="ml-2 font-medium text-gray-900">{task.preprocessing_config.stride}</span>
              </div>
              <div>
                <span className="text-gray-600">Feature Extractor:</span>
                <span className="ml-2 font-medium text-gray-900">{task.preprocessing_config.feature_extractor}</span>
              </div>
              <div>
                <span className="text-gray-600">Batch Size:</span>
                <span className="ml-2 font-medium text-gray-900">{task.preprocessing_config.feature_batch_size}</span>
              </div>
              <div>
                <span className="text-gray-600">Device:</span>
                <span className="ml-2 font-medium text-gray-900">{task.preprocessing_config.use_gpu ? 'GPU' : 'CPU'}</span>
              </div>
            </div>
          </div>

          <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
            <h4 className="text-sm font-semibold text-gray-800 mb-3">Model Configuration</h4>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-600">Aggregator:</span>
                <span className="ml-2 font-medium text-gray-900">{task.model_config.aggregator.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-gray-600">Learning Rate:</span>
                <span className="ml-2 font-medium text-gray-900">{task.model_config.learning_rate}</span>
              </div>
              <div>
                <span className="text-gray-600">Epochs:</span>
                <span className="ml-2 font-medium text-gray-900">{task.model_config.epochs}</span>
              </div>
              <div>
                <span className="text-gray-600">Optimizer:</span>
                <span className="ml-2 font-medium text-gray-900">{task.model_config.optimizer.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-gray-600">Batch Size:</span>
                <span className="ml-2 font-medium text-gray-900">{task.model_config.batch_size}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

