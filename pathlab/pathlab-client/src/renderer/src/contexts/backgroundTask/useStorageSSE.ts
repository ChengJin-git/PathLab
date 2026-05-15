/**
 * SSE subscription hook for storage tasks (batch import, dataset deletion, metadata update, etc.)
 */

import { useState, useEffect } from 'react'
import { getAuthToken } from '../../api/client'
import { getCurrentUser } from '../../api/auth'
import { API_BASE } from '../../config'
import type { BackgroundTask, TaskType, TaskStatus, StorageTaskType } from './types'

/**
 * Custom hook that manages the storage SSE connection and owns the storage tasks state.
 * Connects for authenticated users and returns only their own storage tasks.
 */
export function useStorageSSE(isAdmin: boolean, isLoggedIn: boolean, enabled: boolean) {
  const [storageTasks, setStorageTasks] = useState<BackgroundTask[]>([])

  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated or if there are no subscribers
    if (!token || !isLoggedIn || !enabled) {
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
            } else if (task.task_type === 'delete_dataset') {
              taskTypeDisplay = 'delete_dataset'
              taskPrefix = 'delete_dataset'
              itemNamePrefix = 'Delete Dataset'
            } else if (task.task_type === 'cleanup_empty_datasets') {
              taskTypeDisplay = 'cleanup_empty_datasets'
              taskPrefix = 'cleanup_empty'
              itemNamePrefix = 'Cleanup Empty Datasets'
            } else if (task.task_type === 'unbind_dataset') {
              taskTypeDisplay = 'unbind_dataset'
              taskPrefix = 'unbind_dataset'
              itemNamePrefix = 'Unbind Dataset'
            } else if (task.task_type === 'reset_derived_data') {
              taskTypeDisplay = 'reset_derived_data'
              taskPrefix = 'reset'
              itemNamePrefix = 'Reset Derived Data'
            } else if (task.task_type === 'scan_directory') {
              taskTypeDisplay = 'scan_directory'
              taskPrefix = 'scan'
              itemNamePrefix = 'Scan Directory'
            } else if (task.task_type === 'delete_wsis') {
              taskTypeDisplay = 'delete_wsi'
              taskPrefix = 'delete_wsis'
              itemNamePrefix = 'Delete WSI'
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

            const displayBaseName = task.task_type === 'batch_import' || task.task_type === 'delete_dataset'
              ? task.params?.dataset_name || 'Dataset'
              : itemNamePrefix

            const displayName = `${displayBaseName} (${task.processed_items || 0}/${task.total_items || 0})`

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
              isServerTask: true,
              datasetName: (task.task_type === 'delete_dataset' || task.task_type === 'batch_import')
                ? task.params?.dataset_name
                : undefined,
            }
          })

        setStorageTasks(convertedTasks)
      } catch (error) {
        console.error('Failed to parse storage SSE data:', error)
      }
    }

    eventSource.onerror = () => {
      console.error('Storage SSE connection error')
      if (eventSource.readyState === EventSource.CLOSED) {
        // Connection was rejected by server (possibly 401 auth failure).
        // Verify auth status - if 401, apiFetch will dispatch SESSION_EXPIRED_EVENT → redirect to login.
        getCurrentUser().catch(() => {})
      }
    }

    return () => {
      eventSource.close()
    }
  }, [isAdmin, isLoggedIn, enabled])

  return { storageTasks }
}
