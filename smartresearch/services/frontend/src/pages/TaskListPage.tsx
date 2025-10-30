import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

interface Task {
  task_id: string
  task_name: string
  task_type: 'classification' | 'segmentation'
  status: 'pending' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed'
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  config?: {
    feature_extractor?: string
    aggregator?: string
    epochs?: number
  }
}

export default function TaskListPage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed'>('all')
  const [sortBy, setSortBy] = useState<'created' | 'updated' | 'name'>('updated')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    loadTasks()
  }, [])

  const loadTasks = async () => {
    setLoading(true)
    try {
      // TODO: Replace with actual API call
      // const response = await fetch('/api/tasks')
      // const data = await response.json()
      
      // Mock data for now
      const mockTasks: Task[] = [
        {
          task_id: 'task_001',
          task_name: 'Lung Cancer Classification',
          task_type: 'classification',
          status: 'completed',
          progress: 100,
          created_at: '2025-10-28T10:30:00Z',
          updated_at: '2025-10-28T14:45:00Z',
          wsi_count: 120,
          config: {
            feature_extractor: 'ctranspath',
            aggregator: 'abmil',
            epochs: 50
          }
        },
        {
          task_id: 'task_002',
          task_name: 'Breast Cancer Subtyping',
          task_type: 'classification',
          status: 'training',
          progress: 65,
          created_at: '2025-10-29T08:15:00Z',
          updated_at: '2025-10-30T09:20:00Z',
          wsi_count: 85,
          config: {
            feature_extractor: 'uni',
            aggregator: 'abmil',
            epochs: 100
          }
        },
        {
          task_id: 'task_003',
          task_name: 'Prostate Gleason Grading',
          task_type: 'classification',
          status: 'extracting',
          progress: 42,
          created_at: '2025-10-30T06:00:00Z',
          updated_at: '2025-10-30T10:15:00Z',
          wsi_count: 200,
          config: {
            feature_extractor: 'ctranspath',
            aggregator: 'abmil',
            epochs: 75
          }
        },
        {
          task_id: 'task_004',
          task_name: 'Cervical Cancer Detection',
          task_type: 'classification',
          status: 'failed',
          progress: 28,
          created_at: '2025-10-27T14:20:00Z',
          updated_at: '2025-10-27T16:30:00Z',
          wsi_count: 50,
          config: {
            feature_extractor: 'resnet50',
            aggregator: 'mean',
            epochs: 30
          }
        }
      ]
      
      setTasks(mockTasks)
    } catch (error) {
      console.error('Failed to load tasks:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteTask = (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent card click
    setTaskToDelete(taskId)
    setShowDeleteModal(true)
  }

  const confirmDelete = async () => {
    if (!taskToDelete) return

    setDeleting(true)
    try {
      // TODO: Replace with actual API call
      // await deleteTask(taskToDelete)

      // Remove from local state
      setTasks(tasks.filter(t => t.task_id !== taskToDelete))
      setShowDeleteModal(false)
      setTaskToDelete(null)
    } catch (error) {
      console.error('Failed to delete task:', error)
      alert('Failed to delete task')
    } finally {
      setDeleting(false)
    }
  }

  const getStatusBadge = (status: Task['status']) => {
    const badges = {
      pending: 'bg-gray-100 text-gray-800',
      patching: 'bg-yellow-100 text-yellow-800',
      extracting: 'bg-blue-100 text-blue-800',
      training: 'bg-purple-100 text-purple-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800'
    }
    
    const labels = {
      pending: 'Pending',
      patching: 'Patching',
      extracting: 'Extracting',
      training: 'Training',
      completed: 'Completed',
      failed: 'Failed'
    }
    
    return (
      <span className={`px-3 py-1 rounded-full text-xs font-medium ${badges[status]}`}>
        {labels[status]}
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
    if (filter === 'all') return true
    if (filter === 'running') return ['patching', 'extracting', 'training'].includes(task.status)
    if (filter === 'completed') return task.status === 'completed'
    if (filter === 'failed') return task.status === 'failed'
    return true
  })

  const sortedTasks = [...filteredTasks].sort((a, b) => {
    if (sortBy === 'created') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    if (sortBy === 'updated') return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    if (sortBy === 'name') return a.task_name.localeCompare(b.task_name)
    return 0
  })

  const stats = {
    total: tasks.length,
    running: tasks.filter(t => ['patching', 'extracting', 'training'].includes(t.status)).length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length
  }

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Task Browser</h1>
        <p className="text-gray-600">Monitor and manage your analysis tasks</p>
      </div>

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="text-sm font-medium text-gray-600 mb-1">Total Tasks</div>
          <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="text-sm font-medium text-gray-600 mb-1">Running</div>
          <div className="text-2xl font-bold text-purple-600">{stats.running}</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="text-sm font-medium text-gray-600 mb-1">Completed</div>
          <div className="text-2xl font-bold text-green-600">{stats.completed}</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="text-sm font-medium text-gray-600 mb-1">Failed</div>
          <div className="text-2xl font-bold text-red-600">{stats.failed}</div>
        </div>
      </div>

      {/* Filters and Sort */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-2">
            <span className="text-sm font-medium text-gray-700">Filter:</span>
            <div className="flex space-x-2">
              {(['all', 'running', 'completed', 'failed'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                    filter === f
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
      </div>

      {/* Task List */}
      {loading ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading tasks...</p>
        </div>
      ) : sortedTasks.length === 0 ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
          <div className="text-6xl mb-4">📋</div>
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
        </div>
      ) : (
        <div className="space-y-4">
          {sortedTasks.map(task => (
            <div
              key={task.task_id}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow cursor-pointer"
              onClick={() => navigate(`/task/${task.task_id}`)}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center space-x-3 mb-2">
                    <h3 className="text-lg font-semibold text-gray-900">{task.task_name}</h3>
                    {getStatusBadge(task.status)}
                  </div>
                  <div className="flex items-center space-x-4 text-sm text-gray-600">
                    <span className="flex items-center">
                      <span className="mr-1">📊</span>
                      {task.wsi_count} slides
                    </span>
                    <span className="flex items-center">
                      <span className="mr-1">🔬</span>
                      {task.config?.feature_extractor || 'N/A'}
                    </span>
                    <span className="flex items-center">
                      <span className="mr-1">🧠</span>
                      {task.config?.aggregator?.toUpperCase() || 'N/A'}
                    </span>
                  </div>
                </div>
                <div className="flex items-start space-x-3">
                  <div className="text-right text-sm text-gray-600">
                    <div>Created: {formatDate(task.created_at)}</div>
                    <div>Updated: {formatDate(task.updated_at)}</div>
                  </div>
                  <button
                    onClick={(e) => handleDeleteTask(task.task_id, e)}
                    className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    title="Delete task"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
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
            </div>
          ))}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6">
            <h3 className="text-xl font-bold text-gray-900 mb-4">Delete Task</h3>
            <p className="text-gray-600 mb-6">
              Are you sure you want to delete this task? This action cannot be undone.
            </p>
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setTaskToDelete(null)
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

