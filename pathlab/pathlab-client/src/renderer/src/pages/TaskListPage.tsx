import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTrainingTasks, deleteTrainingTask, getTrainingTaskStorageInfo, TrainingTaskStorageInfo } from '../api'
import { API_BASE } from '../config'
import { ClipboardList, BarChart3, Microscope, Brain, Search, Clock, Loader2, CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'

interface Task {
  task_id: string
  task_name: string
  task_type: 'classification' | 'segmentation'
  data_level: 'wsi' | 'patch'
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  preprocessing_config?: {
    feature_extractor?: string
    tile_size?: number
    stride?: number
  }
  model_config?: {
    aggregator?: string
    epochs?: number
    learning_rate?: number
  }
}

export default function TaskListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed'>('all')
  const [sortBy, setSortBy] = useState<'created' | 'updated' | 'name'>('updated')
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteMode, setDeleteMode] = useState<'standard' | 'complete'>('standard')
  const [taskStorageInfo, setTaskStorageInfo] = useState<TrainingTaskStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Setup Server-Sent Events for real-time updates
  useEffect(() => {
    // Initial load
    loadTasks()

    // Setup SSE connection
    const eventSource = new EventSource(`${API_BASE}/tasks/training/stream`)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setTasks(data.items || [])
        setLoading(false)
      } catch (error) {
        console.error('Failed to parse SSE data:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('SSE connection error:', error)
      // Fallback to manual loading on error
      eventSource.close()
      loadTasks()
    }

    // Cleanup on unmount
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [])

  const loadTasks = async () => {
    setLoading(true)
    try {
      const tasks = await getTrainingTasks()
      setTasks(tasks)
    } catch (error) {
      console.error('Failed to load tasks:', error)
      // Set empty array on error so UI shows "No tasks found"
      setTasks([])
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteTask = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click
    setTaskToDelete(taskId)
    setTaskStorageInfo(null)
    setDeleteMode('standard')
    setShowDeleteModal(true)

    // Load storage info
    setLoadingStorageInfo(true)
    try {
      const info = await getTrainingTaskStorageInfo(taskId)
      setTaskStorageInfo(info)
    } catch (err) {
      console.error('Failed to load storage info:', err)
    } finally {
      setLoadingStorageInfo(false)
    }
  }

  const confirmDelete = async () => {
    if (!taskToDelete) return

    setDeleting(true)
    try {
      await deleteTrainingTask(taskToDelete, deleteMode)

      // Remove from local state
      setTasks(tasks.filter(t => t.task_id !== taskToDelete))
      setShowDeleteModal(false)
      setTaskToDelete(null)
      setTaskStorageInfo(null)
      setDeleteMode('standard')
    } catch (error) {
      console.error('Failed to delete task:', error)
      alert('Failed to delete task')
    } finally {
      setDeleting(false)
    }
  }

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const getStatusBadge = (status: Task['status']) => {
    const badges = {
      pending: { color: 'bg-gray-100 text-gray-800', icon: <Clock className="w-3.5 h-3.5 mr-1" />, label: 'Pending' },
      running: { color: 'bg-blue-100 text-blue-800', icon: <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />, label: 'Running' },
      completed: { color: 'bg-green-100 text-green-800', icon: <CheckCircle2 className="w-3.5 h-3.5 mr-1" />, label: 'Success' },
      failed: { color: 'bg-red-100 text-red-800', icon: <XCircle className="w-3.5 h-3.5 mr-1" />, label: 'Failed' }
    }

    const badge = badges[status] || badges.pending

    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.color}`}>
        {badge.icon}
        {badge.label}
      </span>
    )
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const filteredTasks = tasks.filter(task => {
    // Filter by status
    let statusMatch = true
    if (filter === 'running') statusMatch = task.status === 'running'
    else if (filter === 'completed') statusMatch = task.status === 'completed'
    else if (filter === 'failed') statusMatch = task.status === 'failed'

    // Filter by search query (task name or task ID)
    let searchMatch = true
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase().trim()
      searchMatch =
        task.task_name.toLowerCase().includes(query) ||
        task.task_id.toLowerCase().includes(query)
    }

    return statusMatch && searchMatch
  })

  const sortedTasks = [...filteredTasks].sort((a, b) => {
    if (sortBy === 'created') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    if (sortBy === 'updated') return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    if (sortBy === 'name') return a.task_name.localeCompare(b.task_name)
    return 0
  })

  const stats = {
    total: tasks.length,
    running: tasks.filter(t => t.status === 'running').length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length
  }

  return (
    <div className="w-full">
      {/* Header */}
      <PageHeader
        title="Task Browser"
        description="Monitor and manage your analysis tasks"
      />

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="p-4 overflow-visible">
          <div className="text-sm font-medium text-gray-600 mb-1">Total Tasks</div>
          <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
        </Card>
        <Card className="p-4 overflow-visible">
          <div className="text-sm font-medium text-gray-600 mb-1">Running</div>
          <div className="text-2xl font-bold text-purple-600">{stats.running}</div>
        </Card>
        <Card className="p-4 overflow-visible">
          <div className="text-sm font-medium text-gray-600 mb-1">Completed</div>
          <div className="text-2xl font-bold text-green-600">{stats.completed}</div>
        </Card>
        <Card className="p-4 overflow-visible">
          <div className="text-sm font-medium text-gray-600 mb-1">Failed</div>
          <div className="text-2xl font-bold text-red-600">{stats.failed}</div>
        </Card>
      </div>

      {/* Search Bar */}
      <Card className="p-4 mb-4 overflow-visible">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by task name or task ID..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title="Clear search"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </Card>

      {/* Filters and Sort */}
      <Card className="p-4 mb-6 overflow-visible">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <span className="text-sm font-medium text-gray-700">Filter:</span>
            <div className="flex space-x-2">
              {(['all', 'running', 'completed', 'failed'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${filter === f
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-sm font-medium text-gray-700">Sort by:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            >
              <option value="updated">Last Updated</option>
              <option value="created">Created Date</option>
              <option value="name">Task Name</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Task List */}
      {loading ? (
        <Card className="p-12 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading tasks...</p>
        </Card>
      ) : sortedTasks.length === 0 ? (
        <Card className="p-12 text-center">
          <ClipboardList className="w-16 h-16 mx-auto mb-4 text-gray-400" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No tasks found</h3>
          <p className="text-gray-600 mb-6">
            {filter === 'all'
              ? 'Create your first analysis task to get started'
              : `No ${filter} tasks found`}
          </p>
          <button
            onClick={() => navigate('/ai-chat')}
            className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            Create New Task
          </button>
        </Card>
      ) : (
        <div className="space-y-4">
          {sortedTasks.map(task => (
            <Card
              key={task.task_id}
              className="p-6 hover:shadow-md transition-shadow cursor-pointer overflow-visible"
              onClick={() => navigate(`/task/${task.task_id}`)}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center space-x-3 mb-2">
                    <h3 className="text-lg font-semibold text-gray-900">{task.task_name}</h3>
                    {getStatusBadge(task.status)}
                  </div>
                  <div className="flex items-center space-x-4 text-sm text-gray-600 mb-2">
                    <span className="flex items-center gap-1">
                      <BarChart3 className="w-4 h-4" />
                      {task.wsi_count} {task.data_level === 'patch' ? 'patches' : 'slides'}
                    </span>
                    <span className="flex items-center gap-1">
                      <Microscope className="w-4 h-4" />
                      {task.preprocessing_config?.feature_extractor || 'N/A'}
                    </span>
                    <span className="flex items-center gap-1">
                      <Brain className="w-4 h-4" />
                      {task.model_config?.aggregator?.toUpperCase() || 'N/A'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="font-mono">{task.task_id}</span>
                    <div className="group relative">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          navigator.clipboard.writeText(task.task_id)
                          alert('Task ID copied to clipboard!')
                        }}
                        className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                      </button>
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-50">
                        Copy Task ID
                      </div>
                    </div>
                  </div>
                </div>
                <div className="flex items-start space-x-3">
                  <div className="text-right text-sm text-gray-600">
                    <div>Created: {formatDate(task.created_at)}</div>
                    <div>Updated: {formatDate(task.updated_at)}</div>
                  </div>
                  <div className="group relative">
                    <button
                      onClick={(e) => handleDeleteTask(task.task_id, e)}
                      className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                    <div className="absolute bottom-full right-0 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-50">
                      Delete Task
                    </div>
                  </div>
                </div>
              </div>

              {/* Progress Bar */}
              {task.status !== 'completed' && task.status !== 'failed' && (
                <div className="mb-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-gray-700">Progress</span>
                    <span className="text-sm font-medium text-gray-900">{task.progress}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-primary-600 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${task.progress}%` }}
                    />
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <AlertCircle className="w-8 h-8 text-red-600" />
              </div>
              <h2 className="text-2xl font-bold text-gray-900">Delete Task?</h2>
              <p className="text-gray-500 mt-2">This action cannot be undone</p>
            </div>

            {/* Storage Info */}
            {loadingStorageInfo && (
              <div className="flex items-center justify-center py-4 mb-4">
                <Loader2 className="w-5 h-5 animate-spin text-blue-600 mr-2" />
                <span className="text-gray-600">Loading storage info...</span>
              </div>
            )}

            {taskStorageInfo && !loadingStorageInfo && (() => {
              // Calculate size and file count based on delete mode
              const modelsSize = taskStorageInfo.models.reduce((sum, m) => sum + m.size, 0)
              const modelsCount = taskStorageInfo.models.reduce((sum, m) => sum + m.file_count, 0)
              const displaySize = deleteMode === 'complete' ? taskStorageInfo.total_size : taskStorageInfo.total_size - modelsSize
              const displayFiles = deleteMode === 'complete' ? taskStorageInfo.total_files : taskStorageInfo.total_files - modelsCount
              return (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-semibold text-blue-900">Storage to be freed:</span>
                  <span className="text-lg font-bold text-blue-900">
                    {formatBytes(displaySize)}
                  </span>
                </div>
                <details className="text-sm">
                  <summary className="cursor-pointer text-blue-800 hover:text-blue-900 font-medium">
                    Files to be deleted ({displayFiles})
                  </summary>
                  <ul className="mt-2 space-y-1 text-blue-700 ml-4">
                    {taskStorageInfo.training_dir.exists && (
                      <li>• Training directory ({taskStorageInfo.training_dir.file_count} files, {formatBytes(taskStorageInfo.training_dir.size)})</li>
                    )}
                    {taskStorageInfo.log_file.exists && (
                      <li>• Log file ({formatBytes(taskStorageInfo.log_file.size)})</li>
                    )}
                    {deleteMode === 'complete' && taskStorageInfo.models.length > 0 && (
                      <li>• Models ({taskStorageInfo.models.length} models, {formatBytes(modelsSize)})</li>
                    )}
                  </ul>
                </details>
              </div>
              )})()}

            {/* Delete Mode Selection */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Deletion Mode
              </label>
              <div className="space-y-2">
                <label className="flex items-start gap-3 p-3 border-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
                  style={{ borderColor: deleteMode === 'standard' ? '#3b82f6' : '#e5e7eb' }}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="standard"
                    checked={deleteMode === 'standard'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-blue-600"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">Standard Delete (Recommended)</div>
                    <div className="text-sm text-gray-600 mt-1">
                      Deletes training directory and logs.
                      <span className="text-blue-600"> Keeps trained models</span> for future use.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 border-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
                  style={{ borderColor: deleteMode === 'complete' ? '#3b82f6' : '#e5e7eb' }}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="complete"
                    checked={deleteMode === 'complete'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-blue-600"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">Complete Delete</div>
                    <div className="text-sm text-gray-600 mt-1">
                      Deletes all files including trained models.
                      <strong className="text-red-600"> Cannot be recovered.</strong>
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {/* Warning */}
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-6">
              <p className="text-sm text-yellow-800">
                <strong>Warning:</strong> This action cannot be undone. All selected files will be permanently deleted.
              </p>
            </div>

            {/* Actions */}
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setTaskToDelete(null)
                  setTaskStorageInfo(null)
                  setDeleteMode('standard')
                }}
                disabled={deleting}
                className="px-4 py-2 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

