/**
 * Task action callbacks for Background Task Context
 *
 * Extracted from BackgroundTaskProvider to keep the Provider focused on
 * state composition and context assembly.
 */

import React, { useCallback } from 'react'
import {
  uploadWSIFile, uploadWSIByPath, deleteWSI, deleteTrainingTask,
  checkUploadSpace, cancelQueueTask, cancelStorageTask,
  startMigration, getMigrationStatus,
  fetchDatasets, uploadDatasetSplits
} from '../../api'
import { getExtractProgressSSEUrl } from '../../api/annotation'
import { generateId } from './helpers'
import type {
  BackgroundTask, TaskItem, TaskStatus,
  UploadTaskFile, UploadTaskOptions,
  MetadataUploadTaskConfig, MetadataUploadResult
} from './types'

/** Shared state/refs that task actions need from the Provider */
export interface TaskActionsParams {
  setLocalTasks: React.Dispatch<React.SetStateAction<BackgroundTask[]>>
  setIsPanelExpanded: React.Dispatch<React.SetStateAction<boolean>>
  setDismissedServerTasks: React.Dispatch<React.SetStateAction<Set<string>>>
  setMetadataUploadResults: React.Dispatch<React.SetStateAction<Map<string, MetadataUploadResult>>>
  cancelledTasksRef: React.MutableRefObject<Set<string>>
  abortControllersRef: React.MutableRefObject<Map<string, AbortController>>
  trainingTasks: BackgroundTask[]
  analysisTasks: BackgroundTask[]
  storageTasks: BackgroundTask[]
  tasks: BackgroundTask[]
  refreshDiskSpace: () => Promise<void>
  metadataUploadResults: Map<string, MetadataUploadResult>
}

export function useTaskActions(params: TaskActionsParams) {
  const {
    setLocalTasks, setIsPanelExpanded, setDismissedServerTasks,
    setMetadataUploadResults, cancelledTasksRef, abortControllersRef,
    trainingTasks, analysisTasks, storageTasks, tasks,
    refreshDiskSpace, metadataUploadResults
  } = params

  // Update a task (local tasks only)
  const updateTask = useCallback((taskId: string, updates: Partial<BackgroundTask>) => {
    setLocalTasks(prev => prev.map(t => t.id === taskId ? { ...t, ...updates } : t))
  }, [setLocalTasks])

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
  }, [setLocalTasks])

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

    // Create AbortController for this task
    const abortController = new AbortController()
    abortControllersRef.current.set(taskId, abortController)

    // Process files sequentially (background)
    const processFiles = async () => {
      for (const file of files) {
        // Check if task was cancelled
        if (cancelledTasksRef.current.has(taskId) || abortController.signal.aborted) {
          updateTaskItem(taskId, file.key, { status: 'cancelled', progress: 0 })
          continue
        }

        updateTaskItem(taskId, file.key, { status: 'running' })

        try {
          if (file.path) {
            await uploadWSIByPath(file.path, {
              dataset_id: file.metadata?.dataset_id,
              dataset_name: file.metadata?.dataset_name,
              aggregation_level: file.metadata?.aggregation_level,
              task_type: file.metadata?.task_type,
              label: file.metadata?.label,
              case_id: file.metadata?.case_id,
              age: file.metadata?.age,
              gender: file.metadata?.gender,
              event_time: file.metadata?.event_time,
              event_status: file.metadata?.event_status,
              signal: abortController.signal
            })
          } else if (file.file) {
            await uploadWSIFile(file.file, {
              dataset_id: file.metadata?.dataset_id,
              dataset_name: file.metadata?.dataset_name,
              aggregation_level: file.metadata?.aggregation_level,
              task_type: file.metadata?.task_type,
              label: file.metadata?.label,
              case_id: file.metadata?.case_id,
              age: file.metadata?.age,
              gender: file.metadata?.gender,
              event_time: file.metadata?.event_time,
              event_status: file.metadata?.event_status,
              associatedFiles: file.associatedFiles,
              onProgress: (progress) => {
                updateTaskItem(taskId, file.key, { progress })
              },
              signal: abortController.signal
            })
          }
          updateTaskItem(taskId, file.key, { status: 'success', progress: 100 })
        } catch (err) {
          // If aborted, mark as cancelled instead of error
          const isAborted = err instanceof Error && (err.message.includes('aborted') || err.message.includes('abort'))
          if (isAborted || cancelledTasksRef.current.has(taskId)) {
            updateTaskItem(taskId, file.key, { status: 'cancelled', progress: 0 })
          } else {
            updateTaskItem(taskId, file.key, {
              status: 'error',
              progress: 0,
              error: err instanceof Error ? err.message : String(err)
            })
          }
        }
      }

      // Cleanup AbortController
      abortControllersRef.current.delete(taskId)

      // Refresh disk space after upload
      refreshDiskSpace()

      // Call completion callback
      options?.onComplete?.()
    }

    processFiles()

    return taskId
  }, [updateTaskItem, refreshDiskSpace, setLocalTasks, setIsPanelExpanded, cancelledTasksRef, abortControllersRef])

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
  }, [updateTaskItem, refreshDiskSpace, setLocalTasks, setIsPanelExpanded, cancelledTasksRef])

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
  }, [updateTaskItem, refreshDiskSpace, setLocalTasks, setIsPanelExpanded, cancelledTasksRef])

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
  }, [updateTaskItem, refreshDiskSpace, setLocalTasks, setIsPanelExpanded, cancelledTasksRef])

  // Cancel a running task
  const cancelTask = useCallback((taskId: string) => {
    cancelledTasksRef.current.add(taskId)

    // Abort any in-flight upload requests
    const abortController = abortControllersRef.current.get(taskId)
    if (abortController) {
      abortController.abort()
      abortControllersRef.current.delete(taskId)
    }

    // Update task status to cancelled
    updateTask(taskId, { status: 'cancelled' })

    // Also mark any running items as cancelled immediately
    setLocalTasks(prev => prev.map(task => {
      if (task.id === taskId) {
        return {
          ...task,
          status: 'cancelled' as TaskStatus,
          items: task.items.map(item =>
            item.status === 'running' || item.status === 'pending'
              ? { ...item, status: 'cancelled' as TaskStatus, progress: 0 }
              : item
          )
        }
      }
      return task
    }))
  }, [updateTask, setLocalTasks, cancelledTasksRef, abortControllersRef])

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
  }, [trainingTasks, analysisTasks, storageTasks, setLocalTasks, setDismissedServerTasks])

  // Remove a specific task (both local and server tasks)
  const removeTask = useCallback((task: BackgroundTask) => {
    if (task.isServerTask) {
      // Server task - add to dismissed set (will be persisted to localStorage via useEffect)
      setDismissedServerTasks(prev => {
        const next = new Set(prev)
        next.add(task.id)

        // For merged external validation tasks in analysis phase, also dismiss the linked analysis task
        const analysisTaskId = (task as BackgroundTask & { _analysisTaskId?: string })._analysisTaskId
        if (analysisTaskId) {
          next.add(analysisTaskId)
        }

        return next
      })
    } else {
      // Local task - remove from array
      setLocalTasks(prev => prev.filter(t => t.id !== task.id))
      cancelledTasksRef.current.delete(task.id)
    }
  }, [setLocalTasks, setDismissedServerTasks, cancelledTasksRef])

  // Toggle panel visibility
  const togglePanel = useCallback(() => {
    setIsPanelExpanded(prev => !prev)
  }, [setIsPanelExpanded])

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
      } else if (taskId.startsWith('delete_dataset_')) {
        // Storage task: delete_dataset
        actualTaskId = taskId.replace('delete_dataset_', '')
        isStorageTask = true
      } else if (taskId.startsWith('cleanup_empty_')) {
        // Storage task: cleanup_empty_datasets
        actualTaskId = taskId.replace('cleanup_empty_', '')
        isStorageTask = true
      } else if (taskId.startsWith('unbind_dataset_')) {
        // Storage task: unbind_dataset
        actualTaskId = taskId.replace('unbind_dataset_', '')
        isStorageTask = true
      } else if (taskId.startsWith('reset_')) {
        // Storage task: reset_derived_data
        actualTaskId = taskId.replace('reset_', '')
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

  // Add metadata upload task (polls for dataset, then uploads CSV)
  const addMetadataUploadTask = useCallback((config: MetadataUploadTaskConfig): string => {
    const taskId = generateId()
    const task: BackgroundTask = {
      id: taskId,
      type: 'metadata_upload',
      title: `Metadata: ${config.datasetName}`,
      items: [{
        id: 'metadata_main',
        name: config.datasetId ? 'Uploading metadata...' : 'Waiting for dataset...',
        status: 'running' as TaskStatus,
        progress: config.datasetId ? 50 : 10
      }],
      status: 'running',
      createdAt: new Date(),
      totalProgress: config.datasetId ? 50 : 10,
      successCount: 0,
      failedCount: 0
    }

    setLocalTasks(prev => [task, ...prev])
    setIsPanelExpanded(true)

    // Background process: poll for dataset → upload CSV
    const processMetadataUpload = async () => {
      let datasetId = config.datasetId

      // If no datasetId, poll for it
      if (!datasetId) {
        let attempts = 0
        const maxAttempts = 60 // 5 minutes (every 5s)

        while (attempts < maxAttempts) {
          if (cancelledTasksRef.current.has(taskId)) {
            updateTaskItem(taskId, 'metadata_main', { status: 'cancelled', progress: 0, name: 'Cancelled' })
            return
          }

          attempts++
          try {
            const data = await fetchDatasets()
            const found = data.items.find(d =>
              d.dataset_name === config.datasetName && d.dataset_id
            )
            if (found && found.dataset_id) {
              datasetId = found.dataset_id
              updateTaskItem(taskId, 'metadata_main', {
                name: 'Uploading metadata...',
                progress: 50
              })
              break
            }
          } catch (err) {
            console.error('Failed to poll datasets for metadata upload:', err)
          }

          // Wait 5 seconds before next poll
          await new Promise(resolve => setTimeout(resolve, 5000))
          // Update progress slowly while polling (10 → 40 over 60 attempts)
          const pollProgress = Math.min(40, 10 + Math.round((attempts / maxAttempts) * 30))
          updateTaskItem(taskId, 'metadata_main', { progress: pollProgress })
        }

        if (!datasetId) {
          updateTaskItem(taskId, 'metadata_main', {
            status: 'error',
            progress: 0,
            name: 'Dataset not found',
            error: 'Could not find dataset after 5 minutes of polling'
          })
          return
        }
      }

      // Check if cancelled
      if (cancelledTasksRef.current.has(taskId)) {
        updateTaskItem(taskId, 'metadata_main', { status: 'cancelled', progress: 0, name: 'Cancelled' })
        return
      }

      // Upload CSV
      try {
        updateTaskItem(taskId, 'metadata_main', { name: 'Uploading metadata...', progress: 70 })
        const result = await uploadDatasetSplits(datasetId, config.csvFile)

        // Store result for retrieval by MetadataUploadCard
        setMetadataUploadResults(prev => {
          const next = new Map(prev)
          next.set(config.datasetName, { result, datasetId: datasetId! })
          return next
        })

        updateTaskItem(taskId, 'metadata_main', {
          status: 'success',
          progress: 100,
          name: `Updated ${result.updated_count} files`
        })
      } catch (err) {
        updateTaskItem(taskId, 'metadata_main', {
          status: 'error',
          progress: 0,
          name: 'Upload failed',
          error: err instanceof Error ? err.message : String(err)
        })
      }
    }

    processMetadataUpload()
    return taskId
  }, [updateTaskItem, setLocalTasks, setIsPanelExpanded, cancelledTasksRef, setMetadataUploadResults])

  // Add extraction task (per-task SSE for annotation ROI extraction progress)
  const addExtractionTask = useCallback((serverTaskId: string, datasetName: string): string => {
    const taskId = generateId()
    const task: BackgroundTask = {
      id: taskId,
      type: 'extraction',
      title: datasetName,
      items: [{
        id: 'extraction_main',
        name: datasetName,
        status: 'running' as TaskStatus,
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

    // Connect to per-task SSE for progress updates
    const sseUrl = getExtractProgressSSEUrl(serverTaskId)
    if (!sseUrl) {
      updateTaskItem(taskId, 'extraction_main', {
        status: 'error',
        progress: 0,
        error: 'Not authenticated'
      })
      return taskId
    }

    const eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const progress = data.progress

        if (cancelledTasksRef.current.has(taskId)) {
          eventSource.close()
          return
        }

        if (progress === null || data.done) {
          // Task finished (cleared from Redis)
          eventSource.close()
          updateTaskItem(taskId, 'extraction_main', { status: 'success', progress: 100 })
        } else if (progress < 0) {
          // Error
          eventSource.close()
          updateTaskItem(taskId, 'extraction_main', {
            status: 'error',
            progress: 0,
            error: 'Extraction failed'
          })
        } else if (progress === 100) {
          // Completed
          eventSource.close()
          updateTaskItem(taskId, 'extraction_main', { status: 'success', progress: 100 })
        } else {
          // In progress
          updateTaskItem(taskId, 'extraction_main', { status: 'running', progress })
        }
      } catch (error) {
        console.error('Failed to parse extraction SSE data:', error)
      }
    }

    eventSource.onerror = () => {
      console.error('Extraction SSE connection error')
      eventSource.close()
      // Don't immediately mark as error - the task may have completed
      // and the SSE connection was closed by the server
    }

    return taskId
  }, [updateTaskItem, setLocalTasks, setIsPanelExpanded, cancelledTasksRef])

  // Get metadata upload result by dataset name
  const getMetadataUploadResult = useCallback((datasetName: string): MetadataUploadResult | undefined => {
    return metadataUploadResults.get(datasetName)
  }, [metadataUploadResults])

  return {
    updateTask,
    updateTaskItem,
    addUploadTask,
    addDeleteWSITask,
    addMigrationTask,
    addDeleteTrainingTask,
    addExtractionTask,
    cancelTask,
    clearCompletedTasks,
    removeTask,
    togglePanel,
    cancelServerTask,
    hasUploadingTasks,
    addMetadataUploadTask,
    getMetadataUploadResult
  }
}
