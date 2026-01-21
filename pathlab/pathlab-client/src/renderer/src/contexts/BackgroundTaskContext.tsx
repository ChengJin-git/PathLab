/**
 * Background Task Context for PathLab Client
 *
 * Manages background tasks (uploads, deletes) globally, allowing users to
 * navigate away from pages while tasks continue in the background.
 * Shows progress and status in a floating panel.
 *
 * Also subscribes to backend SSE for Training tasks to display them in the same panel.
 */

import React, { createContext, useContext, useState, useCallback, ReactNode, useRef, useEffect } from 'react'
import { uploadWSIFile, uploadWSIByPath, deleteWSI, deleteTrainingTask, getDiskSpace, checkUploadSpace, cancelQueueTask } from '../api'
import { API_BASE } from '../config'

// Task types - includes server-side training tasks
export type TaskType = 'upload' | 'delete_wsi' | 'delete_task' | 'training'
export type TaskStatus = 'pending' | 'running' | 'success' | 'error' | 'cancelled'

// Training task status from backend (more granular)
export type TrainingTaskStatus = 'pending' | 'preprocessing' | 'extracting' | 'training' | 'completed' | 'failed'

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
  // For server-side tasks (training/inference)
  isServerTask?: boolean
  serverTaskStatus?: TrainingTaskStatus  // Original status from server
  taskName?: string  // Task name for training tasks
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
  isProcessing: boolean
  isPanelExpanded: boolean
  diskSpace: DiskSpaceInfo | null

  // Actions
  addUploadTask: (files: UploadTaskFile[], options?: UploadTaskOptions) => Promise<string>
  addDeleteWSITask: (wsiIds: string[], mode: 'standard' | 'complete') => Promise<string>
  addDeleteTrainingTask: (taskIds: string[], mode: 'standard' | 'complete') => Promise<string>
  cancelTask: (taskId: string) => void
  cancelServerTask: (taskId: string) => Promise<boolean>  // Cancel training/inference task on server
  clearCompletedTasks: () => void
  removeTask: (taskId: string) => void
  togglePanel: () => void
  refreshDiskSpace: () => Promise<void>
}

// Upload task file configuration
export interface UploadTaskFile {
  key: string
  name: string
  file?: File
  path?: string  // For local path upload
  metadata?: {
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
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
  const [isPanelExpanded, setIsPanelExpanded] = useState(false)
  const [diskSpace, setDiskSpace] = useState<DiskSpaceInfo | null>(null)

  // Ref to track cancelled tasks
  const cancelledTasksRef = useRef<Set<string>>(new Set())

  // Ref to track dismissed server tasks (user manually closed)
  const dismissedServerTasksRef = useRef<Set<string>>(new Set())

  // Combine local and training tasks for display (filter out dismissed server tasks)
  const tasks = [
    ...localTasks,
    ...trainingTasks.filter(t => !dismissedServerTasksRef.current.has(t.id))
  ]
  const isProcessing = tasks.some(t => t.status === 'running' || t.status === 'pending')

  // Generate unique ID
  const generateId = () => `task_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`

  // Convert training task status to our TaskStatus
  const mapTrainingStatus = (status: string): TaskStatus => {
    switch (status) {
      case 'pending':
      case 'preprocessing':
        return 'pending'
      case 'extracting':
      case 'training':
        return 'running'
      case 'completed':
        return 'success'
      case 'failed':
        return 'error'
      default:
        return 'pending'
    }
  }

  // SSE subscription for training tasks
  useEffect(() => {
    const eventSource = new EventSource(`${API_BASE}/tasks/training/stream`)

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
            // Always show non-finished tasks
            if (task.status !== 'completed' && task.status !== 'failed') return true
            // For finished tasks, only show if finished within last 10 minutes
            if (task.finished_at) {
              const finishedAt = new Date(task.finished_at.replace(/\+00:00Z$/, 'Z'))
              return finishedAt > tenMinutesAgo
            }
            return true
          })
          .map((task: { task_id: string; task_name: string; status: string; progress: number; wsi_count?: number; created_at?: string; finished_at?: string }) => ({
            id: `training_${task.task_id}`,
            type: 'training' as TaskType,
            title: task.task_name,
            items: [{
              id: task.task_id,
              name: `Training: ${task.task_name}`,
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
            taskName: task.task_name
          }))

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
  }, [])

  // Refresh disk space
  const refreshDiskSpace = useCallback(async () => {
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

    // Process files sequentially
    for (const file of files) {
      if (cancelledTasksRef.current.has(taskId)) {
        updateTaskItem(taskId, file.key, { status: 'cancelled', progress: 0 })
        continue
      }

      updateTaskItem(taskId, file.key, { status: 'running' })

      try {
        if (file.path) {
          await uploadWSIByPath(file.path, {
            label: file.metadata?.label,
            case_id: file.metadata?.case_id,
            age: file.metadata?.age,
            gender: file.metadata?.gender,
            source: file.metadata?.source
          })
        } else if (file.file) {
          await uploadWSIFile(file.file, {
            label: file.metadata?.label,
            case_id: file.metadata?.case_id,
            age: file.metadata?.age,
            gender: file.metadata?.gender,
            source: file.metadata?.source,
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

    // Process deletes sequentially
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

    return taskId
  }, [updateTaskItem, refreshDiskSpace])

  // Add delete training task
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

    // Dismiss all completed/failed server tasks
    trainingTasks
      .filter(t => t.status === 'success' || t.status === 'error')
      .forEach(t => dismissedServerTasksRef.current.add(t.id))

    // Force re-render by updating trainingTasks state
    setTrainingTasks(prev => [...prev])
  }, [trainingTasks])

  // Remove a specific task (both local and server tasks)
  const removeTask = useCallback((taskId: string) => {
    if (taskId.startsWith('training_') || taskId.startsWith('inference_')) {
      // Server task - add to dismissed set
      dismissedServerTasksRef.current.add(taskId)
      // Force re-render
      setTrainingTasks(prev => [...prev])
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

  // Cancel server-side task (training/inference)
  const cancelServerTask = useCallback(async (taskId: string): Promise<boolean> => {
    try {
      // Extract actual task_id from the BackgroundTask id format (e.g., "training_abc123" -> "abc123")
      let actualTaskId = taskId
      if (taskId.startsWith('training_')) {
        actualTaskId = taskId.replace('training_', '')
      } else if (taskId.startsWith('inference_')) {
        actualTaskId = taskId.replace('inference_', '')
      }

      const result = await cancelQueueTask(actualTaskId)
      return result.cancelled
    } catch (error) {
      console.error('Failed to cancel server task:', error)
      return false
    }
  }, [])

  const value: BackgroundTaskContextType = {
    tasks,
    isProcessing,
    isPanelExpanded,
    diskSpace,
    addUploadTask,
    addDeleteWSITask,
    addDeleteTrainingTask,
    cancelTask,
    cancelServerTask,
    clearCompletedTasks,
    removeTask,
    togglePanel,
    refreshDiskSpace
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
