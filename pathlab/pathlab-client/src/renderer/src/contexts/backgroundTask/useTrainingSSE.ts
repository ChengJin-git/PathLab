/**
 * SSE subscription hook for training tasks
 */

import { useState, useEffect } from 'react'
import { getAuthToken, getCurrentUser, TrainingTaskDetail } from '../../api'
import { API_BASE } from '../../config'
import { mapTrainingStatus } from './helpers'
import type { BackgroundTask, TaskType, TrainingTaskStatus, ServerTaskType } from './types'

/**
 * Custom hook that manages the training SSE connection and owns the training tasks state.
 * Returns the converted BackgroundTask[] and raw TrainingTaskDetail[] for downstream consumers.
 */
export function useTrainingSSE(isLoggedIn: boolean, enabled: boolean) {
  const [trainingTasks, setTrainingTasks] = useState<BackgroundTask[]>([])
  const [rawTrainingTasks, setRawTrainingTasks] = useState<TrainingTaskDetail[] | null>(null)

  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated or no subscribers
    if (!token || !enabled) {
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
            data_type?: 'wsi' | 'patch';
            wsi_count?: number;
            created_at?: string;
            finished_at?: string
          }) => {
            // Determine if this is an external validation task
            const isExternalValidation = task.task_type === 'external_validation'

            // Cap progress to the standard 0-100 range for display.
            let displayProgress = Math.max(0, Math.min(task.progress, 100))
            if (task.status === 'completed') {
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
              dataLevel: task.data_type
            }
          })

        setTrainingTasks(convertedTasks)
        // Also store raw training tasks data for TaskListPage to consume (avoids duplicate SSE connection)
        setRawTrainingTasks(serverTasks as TrainingTaskDetail[])
      } catch (error) {
        console.error('Failed to parse training SSE data:', error)
      }
    }

    eventSource.onerror = () => {
      console.error('Training SSE connection error')
      if (eventSource.readyState === EventSource.CLOSED) {
        // Connection was rejected by server (possibly 401 auth failure).
        // Verify auth status - if 401, apiFetch will dispatch SESSION_EXPIRED_EVENT → redirect to login.
        getCurrentUser().catch(() => {})
      }
      // If readyState is CONNECTING, EventSource will auto-reconnect
    }

    return () => {
      eventSource.close()
    }
  }, [isLoggedIn, enabled])  // Re-connect SSE when login state or subscription changes

  return { trainingTasks, rawTrainingTasks }
}

