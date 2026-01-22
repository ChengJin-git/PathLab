import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTrainingTasks, getTrainingTaskStorageInfo, TrainingTaskStorageInfo } from '../api'
import { API_BASE } from '../config'
import { ClipboardList, BarChart3, Microscope, Brain, Search, Clock, Loader2, CheckCircle2, XCircle, AlertCircle, Trash2, Copy, Layers, Timer, Activity, ArrowLeft } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { Checkbox } from '../components/ui/checkbox'

interface Task {
  task_id: string
  task_name: string
  task_type: string
  data_level: string
  status: string
  progress: number
  created_at: string | null
  updated_at: string | null
  wsi_count?: number
  preprocessing_config?: any
  model_config?: any
}

export default function TaskListPage() {
  const navigate = useNavigate()
  const { addDeleteTrainingTask } = useBackgroundTask()

  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'running' | 'completed' | 'failed'>('all')
  const [sortBy, setSortBy] = useState<'created' | 'updated' | 'name'>('updated')
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<string | null>(null)
  const [deleteMode, setDeleteMode] = useState<'standard' | 'complete'>('standard')
  const [taskStorageInfo, setTaskStorageInfo] = useState<TrainingTaskStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
  const [selectedTasks, setSelectedTasks] = useState<string[]>([])
  const [isBatchDelete, setIsBatchDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
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
    setDeleteError(null)
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

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedTasks(filteredTasks.map(t => t.task_id))
    } else {
      setSelectedTasks([])
    }
  }

  const toggleSelectTask = (taskId: string, checked: boolean) => {
    if (checked) {
      setSelectedTasks(prev => [...prev, taskId])
    } else {
      setSelectedTasks(prev => prev.filter(id => id !== taskId))
    }
  }

  const handleBatchDeleteClick = () => {
    if (selectedTasks.length === 0) return
    setIsBatchDelete(true)
    setTaskToDelete(null)
    setTaskStorageInfo(null)
    setDeleteError(null)
    setDeleteMode('standard')
    setShowDeleteModal(true)
  }

  const confirmDelete = async () => {
    if (!taskToDelete && !isBatchDelete) return

    try {
      if (isBatchDelete) {
        addDeleteTrainingTask(selectedTasks, deleteMode)
        setSelectedTasks([])
        setIsBatchDelete(false)
      } else if (taskToDelete) {
        addDeleteTrainingTask([taskToDelete], deleteMode)
        setTaskToDelete(null)
      }

      setShowDeleteModal(false)
      setTaskStorageInfo(null)
      setDeleteMode('standard')
      setDeleteError(null)
      // Delayed refresh since deletion happens in background
      setTimeout(() => loadTasks(), 500)
    } catch (error) {
      console.error('Failed to add delete task:', error)
      setDeleteError('Failed to add delete task. Please try again.')
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
    const badges: Record<Task['status'], { color: string; icon: React.ReactNode; label: string }> = {
      pending: { color: 'bg-gray-100 text-gray-800', icon: <Clock className="w-3.5 h-3.5 mr-1" />, label: 'Pending' },
      running: { color: 'bg-blue-100 text-blue-800', icon: <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />, label: 'Patching' },
      extracting: { color: 'bg-purple-100 text-purple-800', icon: <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />, label: 'Extracting' },
      training: { color: 'bg-orange-100 text-orange-800', icon: <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />, label: 'Training' },
      completed: { color: 'bg-green-100 text-green-800', icon: <CheckCircle2 className="w-3.5 h-3.5 mr-1" />, label: 'Success' },
      failed: { color: 'bg-red-100 text-red-800', icon: <XCircle className="w-3.5 h-3.5 mr-1" />, label: 'Failed' }
    }

    const badge = badges[status] ?? badges.pending

    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.color}`}>
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
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  // Helper to check if task is in a "running" state (any active processing)
  const isRunningStatus = (status: Task['status']) =>
    status === 'running' || status === 'extracting' || status === 'training'

  const filteredTasks = tasks.filter(task => {
    // Filter by status
    let statusMatch = true
    if (filter === 'running') statusMatch = isRunningStatus(task.status)
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

  const calculateDuration = (start: string | null, end: string | null, status: Task['status']) => {
    if (!start || !end) return 'N/A'
    if (isRunningStatus(status) || status === 'pending') return 'In Progress'
    const duration = new Date(end).getTime() - new Date(start).getTime()
    const hours = Math.floor(duration / (1000 * 60 * 60))
    const minutes = Math.floor((duration % (1000 * 60 * 60)) / (1000 * 60))
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m ${Math.floor((duration % (1000 * 60)) / 1000)}s`
  }

  const sortedTasks = [...filteredTasks].sort((a, b) => {
    if (sortBy === 'created') return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
    if (sortBy === 'updated') return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
    if (sortBy === 'name') return a.task_name.localeCompare(b.task_name)
    return 0
  })

  const stats = {
    total: tasks.length,
    running: tasks.filter(t => isRunningStatus(t.status)).length,
    completed: tasks.filter(t => t.status === 'completed').length,
    failed: tasks.filter(t => t.status === 'failed').length
  }

  return (
    <div className="w-full">
      {/* Header */}
      <PageHeader
        title="Task Browser"
        description="Monitor and manage your analysis tasks"
      >
        <Button
          variant="outline"
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Button>
      </PageHeader>

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <Card className="p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-sm font-medium text-gray-500 mb-2">Total Tasks</div>
          <div className="text-3xl font-semibold text-gray-900">{stats.total}</div>
        </Card>
        <Card className="p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-sm font-medium text-gray-500 mb-2">Running</div>
          <div className="text-3xl font-semibold text-purple-600">{stats.running}</div>
        </Card>
        <Card className="p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-sm font-medium text-gray-500 mb-2">Completed</div>
          <div className="text-3xl font-semibold text-green-600">{stats.completed}</div>
        </Card>
        <Card className="p-6 overflow-visible shadow-sm border-gray-100">
          <div className="text-sm font-medium text-gray-500 mb-2">Failed</div>
          <div className="text-3xl font-semibold text-red-600">{stats.failed}</div>
        </Card>
      </div>

      {/* Search Bar */}
      <div className="mb-6">
        <div className="relative max-w-2xl">
          <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by task name or task ID..."
            className="w-full pl-12 pr-4 py-3 bg-white border border-gray-200 rounded-xl shadow-sm focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-base transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title="Clear search"
            >
              <XCircle className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      {/* Filters and Sort */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-40 bg-gray-50/95 backdrop-blur py-2">
        <div className="flex items-center space-x-2 bg-white p-1 rounded-lg border border-gray-200 shadow-sm">
          {(['all', 'running', 'completed', 'failed'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filter === f
                  ? 'bg-gray-900 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={filteredTasks.length > 0 && selectedTasks.length === filteredTasks.length}
                onCheckedChange={toggleSelectAll}
                id="select-all"
                className="data-[state=checked]:bg-gray-900 data-[state=checked]:border-gray-900"
              />
              <label htmlFor="select-all" className="text-sm font-medium text-gray-600 cursor-pointer select-none">
                Select All
              </label>
            </div>

            {selectedTasks.length > 0 && (
              <>
                <div className="w-px h-4 bg-gray-300"></div>
                <div className="flex items-center gap-2 animate-in fade-in slide-in-from-right-4 duration-200">
                  <span className="text-sm font-medium text-gray-600">{selectedTasks.length} selected</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleBatchDeleteClick}
                    className="text-red-600 hover:text-red-700 hover:bg-red-50 h-8 px-2"
                  >
                    Delete Selected
                  </Button>
                </div>
              </>
            )}
            
            <div className="w-px h-4 bg-gray-300"></div>

            <div className="flex items-center space-x-2">
              <span className="text-sm font-medium text-gray-500">Sort by:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                className="pl-2 pr-8 py-1.5 text-sm font-medium border-none bg-transparent focus:ring-0 text-gray-900 cursor-pointer hover:bg-white rounded-md transition-colors"
                style={{ backgroundImage: 'none' }} // Custom arrow implied or simple text
              >
                <option value="updated">Last Updated</option>
                <option value="created">Created Date</option>
                <option value="name">Name</option>
              </select>
            </div>
        </div>
      </div>

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
        <div className="space-y-3">
          {sortedTasks.map(task => (
            <Card
              key={task.task_id}
              className={`group p-6 hover:shadow-lg transition-all cursor-pointer overflow-visible border-gray-100 ${
                selectedTasks.includes(task.task_id) ? 'ring-2 ring-gray-900 bg-gray-50' : 'bg-white'
              }`}
              onClick={() => navigate(`/task/${task.task_id}`)}
              style={{ borderRadius: '16px' }}
            >
              <div className="flex flex-col xl:flex-row xl:items-center gap-6">
                <div className="flex items-start gap-4 xl:w-1/4 min-w-[240px]">
                  <div className="flex-shrink-0 pt-1" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selectedTasks.includes(task.task_id)}
                      onCheckedChange={(checked) => toggleSelectTask(task.task_id, checked as boolean)}
                      className="data-[state=checked]:bg-gray-900 data-[state=checked]:border-gray-900"
                    />
                  </div>
                  
                  <div className="flex flex-col gap-1.5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-base font-semibold text-gray-900 truncate" title={task.task_name}>{task.task_name}</h3>
                      {getStatusBadge(task.status)}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-400 group/id">
                        <span className="font-mono truncate hover:text-gray-600 transition-colors" title={task.task_id}>
                          {task.task_id}
                        </span>
                        <div className="relative">
                         <button
                           onClick={(e) => {
                             e.stopPropagation()
                             navigator.clipboard.writeText(task.task_id)
                             setCopiedId(task.task_id)
                             setTimeout(() => setCopiedId(null), 2000)
                           }}
                           className="opacity-0 group-hover/id:opacity-100 p-1 hover:bg-gray-100 rounded"
                           title="Copy ID"
                         >
                           <Copy className="w-3 h-3" />
                         </button>
                         {copiedId === task.task_id && (
                           <div className="absolute left-1/2 -translate-x-1/2 -top-8 px-2 py-1 bg-gray-900 text-white text-[10px] rounded shadow-lg animate-in fade-in slide-in-from-bottom-1 duration-200 z-10">
                              Copied!
                           </div>
                         )}
                        </div>
                    </div>
                  </div>
                </div>

                <div className="flex-1 min-w-0 border-l border-gray-100 pl-0 xl:pl-6 xl:ml-0 -ml-2">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-y-4 gap-x-8 text-sm text-gray-600">
                      
                      <div className="flex flex-col gap-0.5" title="Dataset Size">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Data</span>
                        <div className="flex items-center gap-2">
                            <BarChart3 className="w-4 h-4 text-gray-400" />
                            <span className="text-base font-medium text-gray-900">{task.wsi_count}</span>
                            <span className="text-sm text-gray-600">{task.data_level === 'patch' ? 'patches' : 'slides'}</span>
                        </div>
                      </div>
                      
                      <div className="flex flex-col gap-0.5" title="Feature Extractor">
                         <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Extractor</span>
                         <div className="flex items-center gap-2">
                            <Microscope className="w-4 h-4 text-gray-400" />
                            <span className="text-base font-medium truncate text-gray-900">{task.preprocessing_config?.feature_extractor || 'N/A'}</span>
                         </div>
                      </div>

                      <div className="flex flex-col gap-0.5" title="Model">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Model</span>
                        <div className="flex items-center gap-2">
                             <Brain className="w-4 h-4 text-gray-400" />
                             <span className="text-base font-medium truncate text-gray-900">
                               {task.data_level === 'patch'
                                 ? 'Linear Probe'
                                 : (task.model_config?.aggregator?.toUpperCase() || 'N/A')}
                             </span>
                        </div>
                      </div>

                      {(task.status === 'completed' || task.status === 'failed') ? (
                         <div className="flex flex-col gap-0.5" title="Duration">
                           <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Duration</span>
                           <div className="flex items-center gap-2">
                               <Timer className="w-4 h-4 text-gray-400" />
                               <span className="text-base font-medium text-gray-900">{calculateDuration(task.created_at, task.updated_at, task.status)}</span>
                           </div>
                         </div>
                      ) : (
                        <div className="flex flex-col gap-0.5 w-full">
                           <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                             {task.status === 'running' ? 'Patching' :
                              task.status === 'extracting' ? 'Extracting' :
                              task.status === 'training' ? 'Training' : 'Progress'}
                           </span>
                           <div className="flex items-center gap-2 w-full mt-1">
                              <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden flex-1">
                                <div
                                  className="bg-gray-900 h-full rounded-full transition-all duration-300"
                                  style={{ 
                                    width: `${task.data_level === 'patch' && task.status !== 'completed' && task.status !== 'failed'
                                      ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
                                      : task.progress}%` 
                                  }}
                                />
                              </div>
                              <span className="text-sm font-semibold text-gray-900 w-10 text-right">
                                {task.data_level === 'patch' && task.status !== 'completed' && task.status !== 'failed'
                                  ? Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
                                  : task.progress}%
                              </span>
                           </div>
                        </div>
                      )}
                    </div>
                </div>

                <div className="flex xl:flex-col items-center xl:items-end justify-between xl:justify-center gap-4 xl:w-32 xl:border-l xl:border-gray-100 xl:pl-6 pt-4 xl:pt-0 border-t xl:border-t-0 border-gray-50 mt-2 xl:mt-0">
                     <div className="flex flex-col text-xs text-gray-400 text-left xl:text-right">
                        <span>{task.updated_at ? new Date(task.updated_at).toLocaleDateString() : 'N/A'}</span>
                        <span className="text-[10px] text-gray-300">Updated</span>
                     </div>
                    
                    <button
                      onClick={(e) => handleDeleteTask(task.task_id, e)}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-full transition-colors group/delete"
                      title="Delete Task"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                </div>
              </div>
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
              <h2 className="text-2xl font-bold text-gray-900">
                {isBatchDelete ? `Delete ${selectedTasks.length} Tasks?` : 'Delete Task?'}
              </h2>
              <p className="text-gray-500 mt-2">This action cannot be undone</p>
            </div>

            {/* Batch Delete Warning */}
            {isBatchDelete && (
              <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-4">
                <p className="text-sm text-orange-800">
                  You are about to delete <strong>{selectedTasks.length}</strong> tasks. All associated data will be removed according to the selected mode.
                </p>
              </div>
            )}

            {/* Storage Info (Single Task Only) */}
            {!isBatchDelete && loadingStorageInfo && (
              <div className="flex items-center justify-center py-4 mb-4">
                <Loader2 className="w-5 h-5 animate-spin text-blue-600 mr-2" />
                <span className="text-gray-600">Loading storage info...</span>
              </div>
            )}

            {!isBatchDelete && taskStorageInfo && !loadingStorageInfo && (() => {
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
                    {taskStorageInfo.training_logs.exists && (
                      <li>• Training logs ({taskStorageInfo.training_logs.file_count} files, {formatBytes(taskStorageInfo.training_logs.size)})</li>
                    )}
                    {taskStorageInfo.analysis_logs.exists && (
                      <li>• Analysis logs ({taskStorageInfo.analysis_logs.file_count} files, {formatBytes(taskStorageInfo.analysis_logs.size)})</li>
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

            {/* Error Message */}
            {deleteError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-800">{deleteError}</p>
                </div>
              </div>
            )}

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
                  setIsBatchDelete(false)
                  setDeleteMode('standard')
                  setDeleteError(null)
                }}
                className="px-4 py-2 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                className="px-4 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

