/**
 * SSE subscription hook for analysis tasks
 */

import { useState, useEffect } from 'react'
import { getAuthToken, getCurrentUser } from '../../api'
import { API_BASE } from '../../config'
import { mapTrainingStatus } from './helpers'
import type { BackgroundTask, TaskType, TrainingTaskStatus } from './types'

/**
 * Custom hook that manages the analysis SSE connection and owns the analysis tasks state.
 * Returns the converted BackgroundTask[] for downstream consumers.
 */
export function useAnalysisSSE(isLoggedIn: boolean, enabled: boolean) {
  const [analysisTasks, setAnalysisTasks] = useState<BackgroundTask[]>([])

  useEffect(() => {
    // Get auth token for SSE (EventSource doesn't support custom headers)
    const token = getAuthToken()

    // Don't connect SSE if not authenticated or no subscribers
    if (!token || !enabled) {
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
          task_category?: string;  // "classification" or "survival" (internal analysis only)
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
            taskCategory: task.task_category as 'classification' | 'survival' | 'segmentation' | undefined,
            trainingTaskId: task.task_id
          }
        })

        setAnalysisTasks(convertedTasks)
      } catch (error) {
        console.error('Failed to parse analysis SSE data:', error)
      }
    }

    eventSource.onerror = () => {
      console.error('Analysis SSE connection error')
      if (eventSource.readyState === EventSource.CLOSED) {
        // Connection was rejected by server (possibly 401 auth failure).
        // Verify auth status - if 401, apiFetch will dispatch SESSION_EXPIRED_EVENT → redirect to login.
        getCurrentUser().catch(() => {})
      }
    }

    return () => {
      eventSource.close()
    }
  }, [isLoggedIn, enabled])  // Re-connect SSE when login state or subscription changes

  return { analysisTasks }
}

