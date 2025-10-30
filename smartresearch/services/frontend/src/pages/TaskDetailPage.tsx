import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

interface TaskDetail {
  task_id: string
  task_name: string
  task_type: 'classification' | 'segmentation'
  task_description: string
  status: 'pending' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed'
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  config: {
    preprocessing: {
      tile_size: number
      stride: number
      feature_extractor: string
      feature_batch_size: number
      use_gpu: boolean
    }
    model: {
      aggregator: string
      learning_rate: number
      epochs: number
      optimizer: string
      batch_size: number
    }
  }
  logs: string[]
  patch_count?: number
  processed_patches?: number
  current_epoch?: number
}

export default function TaskDetailPage() {
  const { task_id } = useParams<{ task_id: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)

  useEffect(() => {
    loadTaskDetail()
  }, [task_id])

  useEffect(() => {
    if (!autoRefresh || !task || task.status === 'completed' || task.status === 'failed') {
      return
    }

    const interval = setInterval(() => {
      loadTaskDetail()
    }, 3000) // Refresh every 3 seconds

    return () => clearInterval(interval)
  }, [autoRefresh, task])

  const loadTaskDetail = async () => {
    setLoading(true)
    try {
      // TODO: Replace with actual API call
      // const response = await fetch(`/api/tasks/${task_id}`)
      // const data = await response.json()

      // Mock data for now
      const mockTask: TaskDetail = {
        task_id: task_id || 'task_001',
        task_name: 'Prostate Gleason Grading',
        task_type: 'classification',
        task_description: 'Multi-class classification for prostate cancer grading',
        status: 'extracting',
        progress: 42,
        created_at: '2025-10-30T06:00:00Z',
        updated_at: '2025-10-30T10:15:00Z',
        wsi_count: 200,
        config: {
          preprocessing: {
            tile_size: 256,
            stride: 256,
            feature_extractor: 'ctranspath',
            feature_batch_size: 64,
            use_gpu: true
          },
          model: {
            aggregator: 'abmil',
            learning_rate: 0.0001,
            epochs: 75,
            optimizer: 'adam',
            batch_size: 32
          }
        },
        logs: [
          '[10:00:15] Starting patch extraction...',
          '[10:00:16] Tile size: 256x256, Stride: 256',
          '[10:00:16] Processing 200 WSI files...',
          '[10:02:30] Processing slide 1/200...',
          '[10:02:31] Extracted 15000 patches',
          '[10:05:45] Processing slide 50/200...',
          '[10:08:12] Total patches extracted: 3,000,000',
          '[10:08:13] Starting feature extraction with ctranspath...',
          '[10:08:13] Batch size: 64, Device: GPU',
          '[10:08:45] Feature extraction: batch 100/46875 (6,400/3,000,000 patches)',
          '[10:09:12] GPU utilization: 87%',
          '[10:10:30] Feature extraction: batch 5000/46875 (320,000/3,000,000 patches)',
          '[10:12:45] GPU utilization: 92%'
        ],
        patch_count: 3000000,
        processed_patches: 320000
      }

      setTask(mockTask)
    } catch (error) {
      console.error('Failed to load task detail:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadge = (status: TaskDetail['status']) => {
    const badges = {
      pending: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Pending' },
      patching: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Extracting Patches' },
      extracting: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Extracting Features' },
      training: { bg: 'bg-purple-100', text: 'text-purple-800', label: 'Training Model' },
      completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Completed' },
      failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' }
    }
    const badge = badges[status]
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
              <span className="text-gray-600">Epoch {task.current_epoch}/{task.config.model.epochs}</span>
            )}
          </div>
        </div>
      </div>

      {/* Live Logs */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Live Logs</h3>
        <div className="bg-gray-900 rounded-lg p-4 h-96 overflow-y-auto font-mono text-xs text-green-400">
          {task.logs.length === 0 ? (
            <div className="text-gray-500">No logs available yet...</div>
          ) : (
            task.logs.map((log, idx) => (
              <div key={idx}>{log}</div>
            ))
          )}
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
                <span className="ml-2 font-medium text-gray-900">{task.config.preprocessing.tile_size}x{task.config.preprocessing.tile_size}</span>
              </div>
              <div>
                <span className="text-gray-600">Stride:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.preprocessing.stride}</span>
              </div>
              <div>
                <span className="text-gray-600">Feature Extractor:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.preprocessing.feature_extractor}</span>
              </div>
              <div>
                <span className="text-gray-600">Batch Size:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.preprocessing.feature_batch_size}</span>
              </div>
              <div>
                <span className="text-gray-600">Device:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.preprocessing.use_gpu ? 'GPU' : 'CPU'}</span>
              </div>
            </div>
          </div>

          <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
            <h4 className="text-sm font-semibold text-gray-800 mb-3">Model Configuration</h4>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-600">Aggregator:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.model.aggregator.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-gray-600">Learning Rate:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.model.learning_rate}</span>
              </div>
              <div>
                <span className="text-gray-600">Epochs:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.model.epochs}</span>
              </div>
              <div>
                <span className="text-gray-600">Optimizer:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.model.optimizer.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-gray-600">Batch Size:</span>
                <span className="ml-2 font-medium text-gray-900">{task.config.model.batch_size}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

