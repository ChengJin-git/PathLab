/**
 * SSE subscription hook for storage tasks (batch import, dataset deletion, metadata update, etc.)
 */

import { useState, useEffect, useRef } from 'react'
import { getAuthToken } from '../../api/client'
import { getCurrentUser } from '../../api/auth'
import { API_BASE } from '../../config'
import type { BackgroundTask, TaskType, TaskStatus, StorageTaskType } from './types'

interface InterpState {
  displayed: number
  target: number
  total: number
}

const INTERP_INTERVAL_MS = 100
const INTERP_STEP = 25

function shouldInterpolate(taskType: StorageTaskType, total: number, rawProcessed: number, status: string): boolean {
  if (taskType !== 'delete_dataset' && taskType !== 'delete_wsis') return false
  if (total < 1000) return false
  if (rawProcessed <= 0) return false
  if (rawProcessed >= total) return false
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return false
  return true
}

function computeNextDisplayed(current: number, target: number): number {
  if (current >= target) return target
  return Math.min(target, current + INTERP_STEP)
}

/**
 * Custom hook that manages the storage SSE connection and owns the storage tasks state.
 * Connects for authenticated users and returns only their own storage tasks.
 */
export function useStorageSSE(isAdmin: boolean, isLoggedIn: boolean, enabled: boolean) {
  const [storageTasks, setStorageTasks] = useState<BackgroundTask[]>([])
  const interpRef = useRef<Map<string, InterpState>>(new Map())
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const token = getAuthToken()

    if (!token || !isLoggedIn || !enabled) {
      return
    }

    const sseUrl = `${API_BASE}/storage/tasks/stream?token=${encodeURIComponent(token)}`

    const eventSource = new EventSource(sseUrl)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const serverTasks = data.items || []

        const now = new Date()
        const tenMinutesAgo = new Date(now.getTime() - 10 * 60 * 1000)

        const convertedTasks: BackgroundTask[] = serverTasks
          .filter((task: { status: string; completed_at?: string }) => {
            if (task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled') return true
            if (task.completed_at) {
              const completedAt = new Date(task.completed_at.replace(/\+00:00Z$/, 'Z'))
              return completedAt > tenMinutesAgo
            }
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
            params?: { dataset_id?: string; dataset_name?: string };
          }) => {
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

            const totalItems = typeof task.total_items === 'number' ? task.total_items : 0
            const rawProcessed = task.processed_items || 0
            const hasKnownTotal = totalItems > 0
            const taskKey = `${taskPrefix}_${task.task_id}`
            const prev = interpRef.current.get(taskKey)

            let displayProcessed: number
            let isInterpolatedDelete = false
            if (shouldInterpolate(task.task_type, totalItems, rawProcessed, task.status)) {
              const target = rawProcessed
              displayProcessed = Math.min(target, (prev?.displayed ?? 0) + INTERP_STEP)
              interpRef.current.set(taskKey, { displayed: displayProcessed, target, total: totalItems })
              isInterpolatedDelete = true
            } else {
              displayProcessed = rawProcessed
              if (prev) {
                interpRef.current.delete(taskKey)
              }
            }

            const displayName = hasKnownTotal
              ? `${displayBaseName} (${displayProcessed}/${totalItems})`
              : displayBaseName

            return {
              id: taskKey,
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
              successCount: isInterpolatedDelete ? displayProcessed : (task.success_count || 0),
              failedCount: task.failed_count || 0,
              skippedCount: task.skipped_count || 0,
              isServerTask: true,
              datasetId: task.task_type === 'batch_import'
                ? task.params?.dataset_id
                : undefined,
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
        getCurrentUser().catch(() => {})
      }
    }

    intervalRef.current = setInterval(() => {
      setStorageTasks((prevTasks) => {
        let changed = false
        const next = prevTasks.map((t) => {
          const state = interpRef.current.get(t.id)
          if (!state) return t
          if (state.displayed >= state.target) return t
          const nextDisplayed = computeNextDisplayed(state.displayed, state.target)
          if (nextDisplayed === state.displayed) return t
          changed = true
          interpRef.current.set(t.id, { ...state, displayed: nextDisplayed })
          const newName = t.title.replace(/\(\d+\//, `(${nextDisplayed}/`)
          return {
            ...t,
            title: newName,
            items: t.items.map((item) => ({ ...item, name: newName })),
            successCount: nextDisplayed,
          }
        })
        return changed ? next : prevTasks
      })
    }, INTERP_INTERVAL_MS)

    return () => {
      eventSource.close()
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [isAdmin, isLoggedIn, enabled])

  return { storageTasks }
}
