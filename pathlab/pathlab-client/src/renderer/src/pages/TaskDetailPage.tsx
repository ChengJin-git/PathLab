import React, { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { API_BASE } from '../config'

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
  data_level: 'wsi' | 'patch'
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
  const logsEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Load initial task details on mount
  useEffect(() => {
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
        if (data.task) {
          setTask(data.task)
        }

        // Handle log data
        if (data.logs && data.logs.length > 0) {
          setLogs(prev => {
            // If this is the initial batch, replace all logs
            if (prev.length === 0) {
              return data.logs
            }
            // Otherwise, append new logs
            return [...prev, ...data.logs]
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
      <div className="mb-6">
        <Button
          variant="ghost"
          onClick={() => navigate('/task-list')}
          className="mb-2 pl-0 hover:bg-transparent hover:text-gray-900 text-gray-600"
        >
          <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Task List
        </Button>
        <PageHeader
          title={task.task_name}
          description={task.task_description}
          className="mb-0"
        >
          {getStatusBadge(task.status)}
        </PageHeader>
      </div>

      {/* Task Info */}
      <Card className="p-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-sm text-gray-600 mb-1">Task ID</div>
            <div className="flex items-center gap-2">
              <div className="font-mono text-sm font-medium text-gray-900">{task.task_id}</div>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(task.task_id)
                  alert('Task ID copied to clipboard!')
                }}
                className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
                title="Copy Task ID"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </button>
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-600 mb-1">
              {task.data_level === 'patch' ? 'Patches' : 'WSI Slides'}
            </div>
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
      </Card>

      {/* Progress Section */}
      <Card className="p-6">
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
      </Card>

      {/* Live Logs */}
      <Card className="p-6">
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
      </Card>

      {/* Configuration */}
      <Card className="p-6">
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
      </Card>
    </div>
  )
}

