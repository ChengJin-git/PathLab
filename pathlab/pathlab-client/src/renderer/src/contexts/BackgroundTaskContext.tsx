/**
 * Background Task Context for PathLab Client
 *
 * Manages background tasks (uploads, deletes) globally, allowing users to
 * navigate away from pages while tasks continue in the background.
 * Shows progress and status in a floating panel.
 *
 * Also subscribes to backend SSE for Training tasks to display them in the same panel.
 */

import React, { createContext, useContext, useState, useCallback, ReactNode, useRef, useEffect, useMemo } from 'react'
import { uploadWSIFile, uploadWSIByPath, deleteWSI, deleteTrainingTask, getDiskSpace, checkUploadSpace, cancelQueueTask, cancelStorageTask, startMigration, getMigrationStatus, getAuthToken } from '../api'
import { API_BASE } from '../config'
import { useAuth } from './AuthContext'

// Task types - includes server-side training tasks and storage tasks
export type TaskType = 'upload' | 'delete_wsi' | 'delete_task' | 'training' | 'external_validation' | 'analysis' | 'migration' | 'batch_import' | 'delete_external' | 'batch_update_metadata'
export type TaskStatus = 'pending' | 'running' | 'success' | 'error' | 'cancelled'

// Storage task type from backend
export type StorageTaskType = 'batch_import' | 'delete_external' | 'batch_update_metadata'

// Training task status from backend (more granular)
export type TrainingTaskStatus = 'pending' | 'queued' | 'preprocessing' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled' | 'running'

// Server task type from backend
export type ServerTaskType = 'classification' | 'survival_prediction' | 'external_validation'

// Individual task item (e.g., one file in a batch)
export interface TaskItem {
  id: string
  name: string
  status: TaskStatus
  progress: number  // 0-100
  error?: string
}

// A batch task containing multiple items
export interface BackgroundTask {
  id: string
  type: TaskType
  title: string
  items: TaskItem[]
  status: TaskStatus
  createdAt: Date
  completedAt?: Date
  totalProgress: number  // 0-100, calculated from items
  successCount: number
  failedCount: number
  skippedCount?: number
  // For server-side tasks (training/inference)
  isServerTask?: boolean
  serverTaskStatus?: TrainingTaskStatus  // Original status from server
  taskName?: string  // Task name for training tasks
  dataLevel?: 'wsi' | 'patch' // For progress calculation
  // For analysis tasks
  analysisType?: 'internal' | 'external'  // Type of analysis
  trainingTaskId?: string  // The training task ID this analysis belongs to (for merging external validation)
}

// Disk space info
export interface DiskSpaceInfo {
  free_gb: number
  warning: boolean
  critical: boolean
}

interface BackgroundTaskContextType {
  // State
  tasks: BackgroundTask[]
  analysisTasks: BackgroundTask[]  // Expose analysis tasks for monitoring completion
  isProcessing: boolean
  isPanelExpanded: boolean
  diskSpace: DiskSpaceInfo | null

  // Actions
  addUploadTask: (files: UploadTaskFile[], options?: UploadTaskOptions) => Promise<string>
  addDeleteWSITask: (wsiIds: string[], mode: 'standard' | 'complete') => Promise<string>
  addDeleteTrainingTask: (taskIds: string[], mode: 'standard' | 'complete') => Promise<string>

  addMigrationTask: (targetPath: string, deleteSource: boolean) => Promise<string>
  cancelTask: (taskId: string) => void
  cancelServerTask: (task: BackgroundTask) => Promise<boolean>  // Cancel training/inference task on server
  clearCompletedTasks: () => void
  removeTask: (taskId: string) => void
  togglePanel: () => void
  refreshDiskSpace: () => Promise<void>

  // Validation
  hasUploadingTasks: () => boolean  // Check if there are any uploading tasks (upload or batch_import)
}

// Upload task file configuration
export interface UploadTaskFile {
  key: string
  name: string
  file?: File
  path?: string  // For local path upload
  metadata?: {
    dataset_id?: string  // Dataset UUID (for existing dataset)
    dataset_name?: string  // Dataset display name (for creating new dataset)
    data_level?: 'case' | 'file'  // Aggregation level for new dataset
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    // Survival analysis fields
    event_time?: number
    event_status?: number
  }
  associatedFiles?: File[]
}

export interface UploadTaskOptions {
  onComplete?: () => void
}

const BackgroundTaskContext = createContext<BackgroundTaskContextType | undefined>(undefined)

interface BackgroundTaskProviderProps {
  children: ReactNode
}

export function BackgroundTaskProvider({ children }: BackgroundTaskProviderProps): React.ReactElement {
  const [localTasks, setLocalTasks] = useState<BackgroundTask[]>([])  // Upload/Delete tasks
  const [trainingTasks, setTrainingTasks] = useState<BackgroundTask[]>([])  // Training tasks from SSE
  const [analysisTasks, setAnalysisTasks] = useState<BackgroundTask[]>([])  // Analysis tasks from SSE
  const [storageTasks, setStorageTasks] = useState<BackgroundTask[]>([])  // Storage tasks from SSE (batch import, delete external)
  const [isPanelExpanded, setIsPanelExpanded] = useState(false)
  const [diskSpace, setDiskSpace] = useState<DiskSpaceInfo | null>(null)

  // Get auth context for role checks and login state
  const { isAdmin, isLoggedIn } = useAuth()

  // Ref to track cancelled tasks
  const cancelledTasksRef = useRef<Set<string>>(new Set())

  // Dismissed server tasks - persisted to localStorage so they stay dismissed after refresh
  const DISMISSED_TASKS_KEY = 'pathlab_dismissed_tasks'
  const [dismissedServerTasks, setDismissedServerTasks] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(DISMISSED_TASKS_KEY)
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch {
      return new Set()
    }
  })

  // Persist dismissed tasks to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(DISMISSED_TASKS_KEY, JSON.stringify([...dismissedServerTasks]))
    } catch {
      // Ignore localStorage errors
    }
  }, [dismissedServerTasks])

  // Combine local, training, analysis, and storage tasks for display (filter out dismissed server tasks)
  // For External Validation: merge the analysis phase into the validation task instead of showing separately
  const tasks = useMemo(() => {
    const filteredTrainingTasks = trainingTasks.filter(t => !dismissedServerTasks.has(t.id))
    const filteredAnalysisTasks = analysisTasks.filter(t => !dismissedServerTasks.has(t.id))
    const filteredStorageTasks = storageTasks.filter(t => !dismissedServerTasks.has(t.id))

    // Find external analysis tasks and their corresponding external validation tasks
    const externalAnalysisByTaskId = new Map<string, BackgroundTask>()
    const internalAnalysisTasks: BackgroundTask[] = []

    for (const task of filteredAnalysisTasks) {
      if (task.analysisType === 'external' && task.trainingTaskId) {
        externalAnalysisByTaskId.set(task.trainingTaskId, task)
      } else {
        internalAnalysisTasks.push(task)
      }
    }

    // Merge external analysis into corresponding external validation tasks
    const mergedTrainingTasks = filteredTrainingTasks.map(task => {
      // Check if this is an external validation task with a corresponding analysis
      if (task.type === 'external_validation') {
        // Extract the actual task_id from the BackgroundTask id (e.g., "extval_abc123" -> "abc123")
        const actualTaskId = task.id.replace('extval_', '')
        const analysisTask = externalAnalysisByTaskId.get(actualTaskId)

        if (analysisTask) {
          // Merge: show analysis status/progress on the validation task
          // The validation inference is complete, now showing analysis progress
          return {
            ...task,
            // Update status and progress to reflect analysis phase
            status: analysisTask.status,
            totalProgress: analysisTask.totalProgress,
            serverTaskStatus: analysisTask.serverTaskStatus,
            // Update items to show analysis phase
            items: [{
              ...task.items[0],
              name: `Analyzing: ${task.title}`,
              status: analysisTask.status,
              progress: analysisTask.totalProgress
            }],
            // Keep track of analysis task ID for cancellation
            _analysisTaskId: analysisTask.id
          }
        }
      }
      return task
    })

    // External analysis tasks that have been merged should not be shown separately
    // (they are already merged into their validation tasks)

    return [
      ...localTasks,
      ...mergedTrainingTasks,
      ...internalAnalysisTasks,
      ...filteredStorageTasks
    ]
  }, [localTasks, trainingTasks, analysisTasks, storageTasks, dismissedServerTasks])

  const isProcessing = tasks.some(t => t.status === 'running' || t.status === 'pending')

  // Generate unique ID
  const generateId = () => `task_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`

  // Convert training task status to our TaskStatus
  const mapTrainingStatus = (status: string): TaskStatus => {
    switch (status) {
      case 'pending':
      case 'queued':  // Task is queued in GPU queue
      case 'preprocessing':
      case 'resuming':  // Task is being resumed after system restart
        return 'pending'
      case 'extracting':
      case 'training':
      case 'running':
        return 'running'
      case 'completed':
        return 'success'
      case 'failed':
        return 'error'
      case 'cancelled':
        return 'cancelled'
      default:
        return 'pending'
    }
  }

  // SSE subscription for training tasks
  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated
    if (!token) {
      return
    }

    const sseUrl = `${API_BASE}/tasks/training/stream?token=${encodeURIComponent(token)}`

    const eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const serverTasks = data.items || []

        // Convert server training tasks to BackgroundTask format
        // Only show active tasks (not completed/failed older than 10 minutes)
        const now = new Date()
        const tenMinutesAgo = new Date(now.getTime() - 10 * 60 * 1000)

        const convertedTasks: BackgroundTask[] = serverTasks
          .filter((task: { status: string; finished_at?: string }) => {
            // Always show non-finished tasks (pending, running, extracting, training, etc.)
            const finishedStatuses = ['completed', 'failed', 'cancelled']
            if (!finishedStatuses.includes(task.status)) return true
            // For finished/failed/cancelled tasks, only show if finished within last 10 minutes
            if (task.finished_at) {
              const finishedAt = new Date(task.finished_at.replace(/\+00:00Z$/, 'Z'))
              return finishedAt > tenMinutesAgo
            }
            return true
          })
          .map((task: {
            task_id: string;
            task_name: string;
            task_type?: ServerTaskType;
            status: string;
            progress: number;
            data_level?: 'wsi' | 'patch';
            wsi_count?: number;
            created_at?: string;
            finished_at?: string
          }) => {
            // Determine if this is an external validation task
            const isExternalValidation = task.task_type === 'external_validation'

            // Adjust progress for patch-level tasks (skip 66% baseline)
            let displayProgress = task.progress
            if (task.data_level === 'patch' && task.status !== 'completed' && task.status !== 'failed') {
              // Backend starts patch tasks at ~66% (after skipping patching & feature extraction)
              // We map 66-100% backend range to 0-100% UI range
              displayProgress = Math.max(0, Math.min(100, Math.round(((task.progress - 66) / (100 - 66)) * 100)))
            } else if (task.status === 'completed') {
              displayProgress = 100
            }

            // Use appropriate prefix based on task type
            const taskPrefix = isExternalValidation ? 'extval' : 'training'
            const itemNamePrefix = isExternalValidation ? 'Validation' : 'Training'

            return {
              id: `${taskPrefix}_${task.task_id}`,
              type: isExternalValidation ? 'external_validation' as TaskType : 'training' as TaskType,
              title: task.task_name,
              items: [{
                id: task.task_id,
                name: `${itemNamePrefix}: ${task.task_name}`,
                status: mapTrainingStatus(task.status),
                progress: displayProgress
              }],
              status: mapTrainingStatus(task.status),
              createdAt: task.created_at ? new Date(task.created_at.replace(/\+00:00Z$/, 'Z')) : new Date(),
              completedAt: task.finished_at ? new Date(task.finished_at.replace(/\+00:00Z$/, 'Z')) : undefined,
              totalProgress: displayProgress,
              successCount: task.status === 'completed' ? 1 : 0,
              failedCount: task.status === 'failed' ? 1 : 0,
              isServerTask: true,
              serverTaskStatus: task.status as TrainingTaskStatus,
              taskName: task.task_name,
              dataLevel: task.data_level
            }
          })

        setTrainingTasks(convertedTasks)
      } catch (error) {
        console.error('Failed to parse training SSE data:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('Training SSE connection error:', error)
      // Don't close - EventSource will auto-reconnect
    }

    return () => {
      eventSource.close()
    }
  }, [isLoggedIn])  // Re-connect SSE when login state changes

  // SSE subscription for analysis tasks
  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated
    if (!token) {
      return
    }

    const sseUrl = `${API_BASE}/results/analysis/stream?token=${encodeURIComponent(token)}`

    const eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const serverTasks = data.items || []

        // Convert server analysis tasks to BackgroundTask format
        const convertedTasks: BackgroundTask[] = serverTasks.map((task: {
          analysis_id: string;
          task_id: string;  // training_task_id
          title?: string;  // Human-readable title from backend
          analysis_type?: string;  // "internal" or "external"
          status: string;
          progress: number;
          created_at?: string;
          finished_at?: string;
          error_message?: string;
        }) => {
          // Use backend-provided title, or fallback to task_id
          const displayTitle = task.title || task.task_id
          const isExternal = task.analysis_type === 'external'
          const typePrefix = isExternal ? 'External Analysis' : 'Internal Analysis'

          return {
            id: `analysis_${task.analysis_id}`,
            type: 'analysis' as TaskType,
            title: displayTitle,
            items: [{
              id: task.analysis_id,
              name: `${typePrefix}: ${displayTitle}`,
              status: mapTrainingStatus(task.status),
              progress: task.progress
            }],
            status: mapTrainingStatus(task.status),
            createdAt: task.created_at ? new Date(task.created_at.replace(/\+00:00Z$/, 'Z')) : new Date(),
            completedAt: task.finished_at ? new Date(task.finished_at.replace(/\+00:00Z$/, 'Z')) : undefined,
            totalProgress: task.progress,
            successCount: task.status === 'completed' ? 1 : 0,
            failedCount: task.status === 'failed' ? 1 : 0,
            isServerTask: true,
            serverTaskStatus: task.status as TrainingTaskStatus,
            // Store analysis_type and training task ID for merging external validation
            analysisType: task.analysis_type,
            trainingTaskId: task.task_id
          }
        })

        setAnalysisTasks(convertedTasks)
      } catch (error) {
        console.error('Failed to parse analysis SSE data:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('Analysis SSE connection error:', error)
      // Don't close - EventSource will auto-reconnect
    }

    return () => {
      eventSource.close()
    }
  }, [isLoggedIn])  // Re-connect SSE when login state changes

  // SSE subscription for storage tasks (batch import, delete external) - admin only
  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated or not admin
    if (!token || !isAdmin) {
      return
    }

    const sseUrl = `${API_BASE}/storage/tasks/stream?token=${encodeURIComponent(token)}`

    const eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const serverTasks = data.items || []

        // Convert server storage tasks to BackgroundTask format
        // Only show active tasks (not completed/failed older than 10 minutes)
        const now = new Date()
        const tenMinutesAgo = new Date(now.getTime() - 10 * 60 * 1000)

        const convertedTasks: BackgroundTask[] = serverTasks
          .filter((task: { status: string; completed_at?: string }) => {
            // Always show non-finished tasks
            if (task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled') return true
            // For finished tasks (completed/failed/cancelled), only show if finished within last 10 minutes
            if (task.completed_at) {
              const completedAt = new Date(task.completed_at.replace(/\+00:00Z$/, 'Z'))
              return completedAt > tenMinutesAgo
            }
            // If no completed_at for a finished task, don't show it (stale/zombie task)
            return false
          })
          .map((task: {
            task_id: string;
            task_type: StorageTaskType;
            status: string;
            progress: number;
            total_items?: number;
            processed_items?: number;
            success_count?: number;
            failed_count?: number;
            skipped_count?: number;
            created_at?: string;
            completed_at?: string;
            params?: { dataset_name?: string };
          }) => {
            // Determine task type for display
            let taskTypeDisplay: TaskType
            let taskPrefix: string
            let itemNamePrefix: string

            if (task.task_type === 'batch_import') {
              taskTypeDisplay = 'batch_import'
              taskPrefix = 'import'
              itemNamePrefix = 'Batch Import'
            } else if (task.task_type === 'batch_update_metadata') {
              taskTypeDisplay = 'batch_update_metadata'
              taskPrefix = 'update'
              itemNamePrefix = 'Metadata Update'
            } else {
              taskTypeDisplay = 'delete_external'
              taskPrefix = 'delete_ext'
              itemNamePrefix = 'Delete External'
            }

            // Map storage task status to our TaskStatus
            let taskStatus: TaskStatus
            switch (task.status) {
              case 'pending':
                taskStatus = 'pending'
                break
              case 'processing':
                taskStatus = 'running'
                break
              case 'completed':
                taskStatus = 'success'
                break
              case 'failed':
                taskStatus = 'error'
                break
              case 'cancelled':
                taskStatus = 'cancelled'
                break
              default:
                taskStatus = 'pending'
            }

            const displayName = task.task_type === 'batch_import'
              ? `${task.params?.dataset_name || 'Dataset'} (${task.processed_items || 0}/${task.total_items || 0})`
              : `${itemNamePrefix} (${task.processed_items || 0}/${task.total_items || 0})`

            return {
              id: `${taskPrefix}_${task.task_id}`,
              type: taskTypeDisplay,
              title: displayName,
              items: [{
                id: task.task_id,
                name: displayName,
                status: taskStatus,
                progress: task.progress
              }],
              status: taskStatus,
              createdAt: task.created_at ? new Date(task.created_at.replace(/\+00:00Z$/, 'Z')) : new Date(),
              completedAt: task.completed_at ? new Date(task.completed_at.replace(/\+00:00Z$/, 'Z')) : undefined,
              totalProgress: task.progress,
              successCount: task.success_count || 0,
              failedCount: task.failed_count || 0,
              skippedCount: task.skipped_count || 0,
              isServerTask: true
            }
          })

        setStorageTasks(convertedTasks)
      } catch (error) {
        console.error('Failed to parse storage SSE data:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('Storage SSE connection error:', error)
      // Don't close - EventSource will auto-reconnect
    }

    return () => {
      eventSource.close()
    }
  }, [isAdmin, isLoggedIn])  // Re-connect SSE when login state or admin status changes

  // Refresh disk space
  const refreshDiskSpace = useCallback(async () => {
    // Only fetch disk space if authenticated
    const token = getAuthToken()
    if (!token) {
      return
    }

    try {
      const space = await getDiskSpace()
      setDiskSpace({
        free_gb: space.free_gb,
        warning: space.warning,
        critical: space.critical
      })
    } catch (err) {
      console.error('Failed to get disk space:', err)
    }
  }, [])

  // Check for active migration on mount (admin only)
  useEffect(() => {
    const checkActiveMigration = async () => {
      // Only check migration status if authenticated AND admin
      const token = getAuthToken()
      if (!token || !isAdmin) {
        return
      }

      try {
        const status = await getMigrationStatus()
        if (status.status === 'running') {
          // Restore task
          const taskId = generateId()
          const destName = status.destination ? (status.destination.split(/[\\/]/).filter(Boolean).pop() || 'Storage') : 'Storage'
          const task: BackgroundTask = {
            id: taskId,
            type: 'migration',
            title: `Relocating to ${destName}`,
            items: [{
              id: 'migration_main',
              name: `Moving data to ${status.destination}`,
              status: 'running',
              progress: Math.round(status.progress)
            }],
            status: 'running',
            createdAt: new Date(), // We don't know exact start time, use now
            totalProgress: Math.round(status.progress),
            successCount: 0,
            failedCount: 0
          }

          setLocalTasks(prev => {
            // Avoid duplicate if already exists (unlikely on fresh mount but good practice)
            if (prev.some(t => t.type === 'migration')) return prev
            return [task, ...prev]
          })
          setIsPanelExpanded(true)

          // Resume polling
          const pollInterval = setInterval(async () => {
            // Check if task was cancelled locally (removed from UI)
            // We can't easily check cancelledTasksRef for a resumed task unless we sync IDs, 
            // but here we just generated a new ID. 
            // Ideally we should store the backend ID if available, but MigrationManager is singleton.
            // So we just rely on component unmount or manual cancellation to stop polling.

            try {
              const currentStatus = await getMigrationStatus()

              setLocalTasks(prev => {
                return prev.map(t => {
                  if (t.id !== taskId) return t

                  if (currentStatus.status === 'completed') {
                    clearInterval(pollInterval)
                    refreshDiskSpace()
                    return {
                      ...t,
                      status: 'success',
                      completedAt: new Date(),
                      totalProgress: 100,
                      successCount: 1,
                      items: t.items.map(i => ({ ...i, status: 'success', progress: 100 }))
                    }
                  } else if (currentStatus.status === 'failed') {
                    clearInterval(pollInterval)
                    return {
                      ...t,
                      status: 'error',
                      completedAt: new Date(),
                      failedCount: 1,
                      items: t.items.map(i => ({
                        ...i,
                        status: 'error',
                        error: currentStatus.error || 'Migration failed'
                      }))
                    }
                  } else {
                    // Still running
                    const progress = Math.round(currentStatus.progress)
                    return {
                      ...t,
                      totalProgress: progress,
                      items: t.items.map(i => ({ ...i, progress }))
                    }
                  }
                })
              })

              if (currentStatus.status !== 'running') {
                clearInterval(pollInterval)
              }

            } catch (err) {
              console.error('Migration polling error:', err)
            }
          }, 2000)
        }
      } catch (err) {
        console.error('Failed to check active migration:', err)
      }
    }

    checkActiveMigration()
  }, [refreshDiskSpace, isAdmin])



  // Update a task (local tasks only)
  const updateTask = useCallback((taskId: string, updates: Partial<BackgroundTask>) => {
    setLocalTasks(prev => prev.map(t => t.id === taskId ? { ...t, ...updates } : t))
  }, [])

  // Update a task item (local tasks only)
  const updateTaskItem = useCallback((taskId: string, itemId: string, updates: Partial<TaskItem>) => {
    setLocalTasks(prev => prev.map(task => {
      if (task.id !== taskId) return task

      const updatedItems = task.items.map(item =>
        item.id === itemId ? { ...item, ...updates } : item
      )

      // Calculate overall progress and counts
      const successCount = updatedItems.filter(i => i.status === 'success').length
      const failedCount = updatedItems.filter(i => i.status === 'error').length
      const totalProgress = Math.round(
        updatedItems.reduce((sum, i) => sum + i.progress, 0) / updatedItems.length
      )

      // Determine task status
      let status: TaskStatus = task.status
      if (updatedItems.every(i => i.status === 'success' || i.status === 'error' || i.status === 'cancelled')) {
        status = failedCount === updatedItems.length ? 'error' :
          successCount === updatedItems.length ? 'success' : 'success'  // Partial success
      }

      return {
        ...task,
        items: updatedItems,
        totalProgress,
        successCount,
        failedCount,
        status,
        completedAt: status !== 'running' && status !== 'pending' ? new Date() : undefined
      }
    }))
  }, [])

  // Add upload task
  const addUploadTask = useCallback(async (files: UploadTaskFile[], options?: UploadTaskOptions): Promise<string> => {
    // Check disk space first
    const totalSize = files.reduce((sum, f) => sum + (f.file?.size || 0), 0)
    if (totalSize > 0) {
      try {
        const spaceCheck = await checkUploadSpace(totalSize)
        if (!spaceCheck.can_upload) {
          throw new Error(spaceCheck.message)
        }
      } catch (err) {
        throw err
      }
    }

    const taskId = generateId()
    const task: BackgroundTask = {
      id: taskId,
      type: 'upload',
      title: `Uploading ${files.length} file${files.length > 1 ? 's' : ''}`,
      items: files.map(f => ({
        id: f.key,
        name: f.name,
        status: 'pending' as TaskStatus,
        progress: 0
      })),
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0
    }

    setLocalTasks(prev => [task, ...prev])
    setIsPanelExpanded(true)

    // Process files sequentially (background)
    const processFiles = async () => {
      for (const file of files) {
        if (cancelledTasksRef.current.has(taskId)) {
          updateTaskItem(taskId, file.key, { status: 'cancelled', progress: 0 })
          continue
        }

        updateTaskItem(taskId, file.key, { status: 'running' })

        try {
          if (file.path) {
            await uploadWSIByPath(file.path, {
              dataset_id: file.metadata?.dataset_id,
              dataset_name: file.metadata?.dataset_name,
              data_level: file.metadata?.data_level,
              label: file.metadata?.label,
              case_id: file.metadata?.case_id,
              age: file.metadata?.age,
              gender: file.metadata?.gender,
              source: file.metadata?.source,
              event_time: file.metadata?.event_time,
              event_status: file.metadata?.event_status
            })
          } else if (file.file) {
            await uploadWSIFile(file.file, {
              dataset_id: file.metadata?.dataset_id,
              dataset_name: file.metadata?.dataset_name,
              data_level: file.metadata?.data_level,
              label: file.metadata?.label,
              case_id: file.metadata?.case_id,
              age: file.metadata?.age,
              gender: file.metadata?.gender,
              source: file.metadata?.source,
              event_time: file.metadata?.event_time,
              event_status: file.metadata?.event_status,
              associatedFiles: file.associatedFiles,
              onProgress: (progress) => {
                updateTaskItem(taskId, file.key, { progress })
              }
            })
          }
          updateTaskItem(taskId, file.key, { status: 'success', progress: 100 })
        } catch (err) {
          updateTaskItem(taskId, file.key, {
            status: 'error',
            progress: 0,
            error: err instanceof Error ? err.message : String(err)
          })
        }
      }

      // Refresh disk space after upload
      refreshDiskSpace()

      // Call completion callback
      options?.onComplete?.()
    }

    processFiles()

    return taskId
  }, [updateTaskItem, refreshDiskSpace])

  // Add delete WSI task
  const addDeleteWSITask = useCallback(async (wsiIds: string[], mode: 'standard' | 'complete'): Promise<string> => {
    const taskId = generateId()
    const task: BackgroundTask = {
      id: taskId,
      type: 'delete_wsi',
      title: `Deleting ${wsiIds.length} file${wsiIds.length > 1 ? 's' : ''}`,
      items: wsiIds.map(id => ({
        id,
        name: id,
        status: 'pending' as TaskStatus,
        progress: 0
      })),
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0
    }

    setLocalTasks(prev => [task, ...prev])
    setIsPanelExpanded(true)

    // Process deletes sequentially (background)
    const processDeletes = async () => {
      for (const wsiId of wsiIds) {
        if (cancelledTasksRef.current.has(taskId)) {
          updateTaskItem(taskId, wsiId, { status: 'cancelled', progress: 0 })
          continue
        }

        updateTaskItem(taskId, wsiId, { status: 'running', progress: 50 })

        try {
          await deleteWSI(wsiId, mode)
          updateTaskItem(taskId, wsiId, { status: 'success', progress: 100 })
        } catch (err) {
          updateTaskItem(taskId, wsiId, {
            status: 'error',
            progress: 0,
            error: err instanceof Error ? err.message : String(err)
          })
        }
      }

      // Refresh disk space after delete
      refreshDiskSpace()
    }

    processDeletes()

    return taskId
  }, [updateTaskItem, refreshDiskSpace])

  // Add migration task
  const addMigrationTask = useCallback(async (targetPath: string, deleteSource: boolean): Promise<string> => {
    const taskId = generateId()
    const targetDirName = targetPath.split(/[\\/]/).filter(Boolean).pop() || 'Storage'
    const task: BackgroundTask = {
      id: taskId,
      type: 'migration',
      title: `Relocating to ${targetDirName}`,
      items: [{
        id: 'migration_main',
        name: `Moving data to ${targetPath}`,
        status: 'pending' as TaskStatus,
        progress: 0
      }],
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0
    }

    setLocalTasks(prev => [task, ...prev])
    setIsPanelExpanded(true)

    try {
      // Start migration on backend
      await startMigration(targetPath, deleteSource)
      updateTaskItem(taskId, 'migration_main', { status: 'running', progress: 0 })

      // Poll status
      const pollInterval = setInterval(async () => {
        if (cancelledTasksRef.current.has(taskId)) {
          clearInterval(pollInterval)
          updateTaskItem(taskId, 'migration_main', { status: 'cancelled' })
          return
        }

        try {
          const status = await getMigrationStatus()

          if (status.status === 'completed') {
            clearInterval(pollInterval)
            updateTaskItem(taskId, 'migration_main', { status: 'success', progress: 100 })
            // Refresh disk space after migration (might be different volume)
            refreshDiskSpace()
            // Could add a toast or notification here
          } else if (status.status === 'failed') {
            clearInterval(pollInterval)
            updateTaskItem(taskId, 'migration_main', {
              status: 'error',
              error: status.error || 'Migration failed'
            })
          } else {
            // Running
            updateTaskItem(taskId, 'migration_main', {
              status: 'running',
              progress: Math.round(status.progress)
            })
          }
        } catch (err) {
          console.error('Migration polling error:', err)
          // Don't fail immediately on network error, keep polling
        }
      }, 2000)

    } catch (err) {
      updateTaskItem(taskId, 'migration_main', {
        status: 'error',
        error: err instanceof Error ? err.message : String(err)
      })
      // If start failed, we mark as error immediately
    }

    return taskId
  }, [updateTaskItem, refreshDiskSpace])

  // Add delete delete training task
  const addDeleteTrainingTask = useCallback(async (taskIds: string[], mode: 'standard' | 'complete'): Promise<string> => {
    const taskId = generateId()
    const task: BackgroundTask = {
      id: taskId,
      type: 'delete_task',
      title: `Deleting ${taskIds.length} training task${taskIds.length > 1 ? 's' : ''}`,
      items: taskIds.map(id => ({
        id,
        name: id,
        status: 'pending' as TaskStatus,
        progress: 0
      })),
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0
    }

    setLocalTasks(prev => [task, ...prev])
    setIsPanelExpanded(true)

    // Process deletes sequentially
    for (const trainingTaskId of taskIds) {
      if (cancelledTasksRef.current.has(taskId)) {
        updateTaskItem(taskId, trainingTaskId, { status: 'cancelled', progress: 0 })
        continue
      }

      updateTaskItem(taskId, trainingTaskId, { status: 'running', progress: 50 })

      try {
        await deleteTrainingTask(trainingTaskId, mode)
        updateTaskItem(taskId, trainingTaskId, { status: 'success', progress: 100 })
      } catch (err) {
        updateTaskItem(taskId, trainingTaskId, {
          status: 'error',
          progress: 0,
          error: err instanceof Error ? err.message : String(err)
        })
      }
    }

    // Refresh disk space after delete
    refreshDiskSpace()

    return taskId
  }, [updateTaskItem, refreshDiskSpace])

  // Cancel a running task
  const cancelTask = useCallback((taskId: string) => {
    cancelledTasksRef.current.add(taskId)
    updateTask(taskId, { status: 'cancelled' })
  }, [updateTask])

  // Clear all completed tasks (both local and server tasks)
  const clearCompletedTasks = useCallback(() => {
    // Clear local completed tasks
    setLocalTasks(prev => prev.filter(t => t.status === 'running' || t.status === 'pending'))

    // Collect all completed/failed/cancelled server task IDs
    const toDismiss = new Set<string>()

    // Dismiss all completed/failed/cancelled training tasks
    trainingTasks
      .filter(t => t.status === 'success' || t.status === 'error' || t.status === 'cancelled')
      .forEach(t => toDismiss.add(t.id))

    // Dismiss all completed/failed/cancelled analysis tasks
    analysisTasks
      .filter(t => t.status === 'success' || t.status === 'error' || t.status === 'cancelled')
      .forEach(t => toDismiss.add(t.id))

    // Dismiss all completed/failed/cancelled storage tasks
    storageTasks
      .filter(t => t.status === 'success' || t.status === 'error' || t.status === 'cancelled')
      .forEach(t => toDismiss.add(t.id))

    // Update dismissed tasks state (will be persisted to localStorage via useEffect)
    if (toDismiss.size > 0) {
      setDismissedServerTasks(prev => new Set([...prev, ...toDismiss]))
    }
  }, [trainingTasks, analysisTasks, storageTasks])

  // Remove a specific task (both local and server tasks)
  const removeTask = useCallback((taskId: string) => {
    if (taskId.startsWith('training_') || taskId.startsWith('inference_') || taskId.startsWith('extval_') || taskId.startsWith('analysis_')) {
      // Server task - add to dismissed set (will be persisted to localStorage via useEffect)
      setDismissedServerTasks(prev => new Set([...prev, taskId]))
    } else {
      // Local task - remove from array
      setLocalTasks(prev => prev.filter(t => t.id !== taskId))
      cancelledTasksRef.current.delete(taskId)
    }
  }, [])

  // Toggle panel visibility
  const togglePanel = useCallback(() => {
    setIsPanelExpanded(prev => !prev)
  }, [])

  // Cancel server-side task (training/inference/external_validation/storage tasks)
  // For merged external validation tasks in analysis phase, cancel the analysis task instead
  const cancelServerTask = useCallback(async (task: BackgroundTask): Promise<boolean> => {
    try {
      // Check if this is a merged external validation task in analysis phase
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const analysisTaskId = (task as any)._analysisTaskId as string | undefined
      const taskId = analysisTaskId || task.id

      // Extract actual task_id from the BackgroundTask id format (e.g., "training_abc123" -> "abc123")
      let actualTaskId = taskId
      let isStorageTask = false

      if (taskId.startsWith('training_')) {
        actualTaskId = taskId.replace('training_', '')
      } else if (taskId.startsWith('inference_')) {
        actualTaskId = taskId.replace('inference_', '')
      } else if (taskId.startsWith('extval_')) {
        actualTaskId = taskId.replace('extval_', '')
      } else if (taskId.startsWith('analysis_')) {
        actualTaskId = taskId.replace('analysis_', '')
      } else if (taskId.startsWith('import_')) {
        // Storage task: batch_import
        actualTaskId = taskId.replace('import_', '')
        isStorageTask = true
      } else if (taskId.startsWith('delete_ext_')) {
        // Storage task: delete_external
        actualTaskId = taskId.replace('delete_ext_', '')
        isStorageTask = true
      } else if (taskId.startsWith('update_')) {
        // Storage task: batch_update_metadata
        actualTaskId = taskId.replace('update_', '')
        isStorageTask = true
      }

      // Use different API for storage tasks vs training tasks
      if (isStorageTask) {
        const result = await cancelStorageTask(actualTaskId)
        return result.cancelled
      } else {
        const result = await cancelQueueTask(actualTaskId)
        return result.cancelled
      }
    } catch (error) {
      console.error('Failed to cancel server task:', error)
      return false
    }
  }, [])

  // Check if there are any uploading tasks (upload or batch_import)
  const hasUploadingTasks = useCallback((): boolean => {
    return tasks.some(task => {
      // Check for upload or batch_import tasks that are pending or running
      const isUploadType = task.type === 'upload' || task.type === 'batch_import'
      const isActiveStatus = task.status === 'pending' || task.status === 'running'
      return isUploadType && isActiveStatus
    })
  }, [tasks])

  const value: BackgroundTaskContextType = {
    tasks,
    analysisTasks,
    isProcessing,
    isPanelExpanded,
    diskSpace,
    addUploadTask,
    addDeleteWSITask,
    addDeleteTrainingTask,

    addMigrationTask,
    cancelTask,
    cancelServerTask,
    clearCompletedTasks,
    removeTask,
    togglePanel,
    refreshDiskSpace,
    hasUploadingTasks
  }

  return (
    <BackgroundTaskContext.Provider value={value}>
      {children}
    </BackgroundTaskContext.Provider>
  )
}

export function useBackgroundTask(): BackgroundTaskContextType {
  const context = useContext(BackgroundTaskContext)
  if (context === undefined) {
    throw new Error('useBackgroundTask must be used within a BackgroundTaskProvider')
  }
  return context
}
