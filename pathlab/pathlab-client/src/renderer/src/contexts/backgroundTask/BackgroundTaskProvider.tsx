/**
 * Background Task Context Provider for PathLab Client
 *
 * Manages background tasks (uploads, deletes) globally, allowing users to
 * navigate away from pages while tasks continue in the background.
 * Shows progress and status in a floating panel.
 *
 * Also subscribes to backend SSE for Training tasks to display them in the same panel.
 */

import React, { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { getAuthToken } from '../../api/client'
import { getDiskSpace, getMigrationStatus } from '../../api/storage'
import { useAuth } from '../AuthContext'
import { DISMISSED_TASKS_KEY, generateId } from './helpers'
import { useTrainingSSE } from './useTrainingSSE'
import { useAnalysisSSE } from './useAnalysisSSE'
import { useStorageSSE } from './useStorageSSE'
import { useTaskActions } from './useTaskActions'
import {
  clearTrainingSubmissionRecord,
  isTrainingSubmissionPendingTimedOut,
  listTrainingSubmissionRecords,
} from '../../lib/trainingSubmissionTracker'
import type {
  BackgroundTask, BackgroundTaskContextType, BackgroundTaskProviderProps,
  DiskSpaceInfo, MetadataUploadResult
} from './types'

const BackgroundTaskContext = createContext<BackgroundTaskContextType | undefined>(undefined)

export function BackgroundTaskProvider({ children }: BackgroundTaskProviderProps): React.ReactElement {
  const [localTasks, setLocalTasks] = useState<BackgroundTask[]>([])
  const [isPanelExpanded, setIsPanelExpanded] = useState(false)
  const [metadataUploadResults, setMetadataUploadResults] = useState<Map<string, MetadataUploadResult>>(new Map())
  const [diskSpace, setDiskSpace] = useState<DiskSpaceInfo | null>(null)

  const { t } = useTranslation()
  // Get auth context for role checks and login state
  const { isAdmin, isLoggedIn } = useAuth()

  // Ref to track cancelled tasks
  const cancelledTasksRef = useRef<Set<string>>(new Set())

  // Ref to store AbortController for each running upload task (key: taskId)
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map())

  const [deletingDatasetNames, setDeletingDatasetNames] = useState<Set<string>>(new Set())
  const deletingTaskNameMapRef = useRef<Map<string, string>>(new Map())

  const addDeletingDatasetName = useCallback((taskId: string, name: string) => {
    deletingTaskNameMapRef.current.set(taskId, name)
    setDeletingDatasetNames(prev => new Set([...prev, name]))
  }, [])

  const removeDeletingDatasetByTaskId = useCallback((taskId: string) => {
    const name = deletingTaskNameMapRef.current.get(taskId)
    if (!name) return
    deletingTaskNameMapRef.current.delete(taskId)
    setDeletingDatasetNames(prev => {
      const next = new Set(prev)
      next.delete(name)
      return next
    })
  }, [])

  // SSE on-demand subscription: subscriber ref counts + enabled states
  const trainingSubCount = useRef(0)
  const analysisSubCount = useRef(0)
  const storageSubCount = useRef(0)
  const [trainingSSEEnabled, setTrainingSSEEnabled] = useState(false)
  const [analysisSSEEnabled, setAnalysisSSEEnabled] = useState(false)
  const [storageSSEEnabled, setStorageSSEEnabled] = useState(false)

  const subscribeTrainingSSE = useCallback(() => {
    trainingSubCount.current++
    setTrainingSSEEnabled(true)
    return () => {
      trainingSubCount.current--
      if (trainingSubCount.current <= 0) {
        trainingSubCount.current = 0
        setTrainingSSEEnabled(false)
      }
    }
  }, [])

  const subscribeAnalysisSSE = useCallback(() => {
    analysisSubCount.current++
    setAnalysisSSEEnabled(true)
    return () => {
      analysisSubCount.current--
      if (analysisSubCount.current <= 0) {
        analysisSubCount.current = 0
        setAnalysisSSEEnabled(false)
      }
    }
  }, [])

  const subscribeStorageSSE = useCallback(() => {
    storageSubCount.current++
    setStorageSSEEnabled(true)
    return () => {
      storageSubCount.current--
      if (storageSubCount.current <= 0) {
        storageSubCount.current = 0
        setStorageSSEEnabled(false)
      }
    }
  }, [])

  const openPanel = useCallback(() => {
    setIsPanelExpanded(true)
  }, [])

  // SSE hooks — each owns its own state
  const { trainingTasks, rawTrainingTasks } = useTrainingSSE(isLoggedIn, trainingSSEEnabled)
  const { analysisTasks } = useAnalysisSSE(isLoggedIn, analysisSSEEnabled)
  const { storageTasks } = useStorageSSE(isAdmin, isLoggedIn, storageSSEEnabled)

  // Dismissed server tasks - persisted to localStorage so they stay dismissed after refresh
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
          return {
            ...task,
            status: analysisTask.status,
            totalProgress: analysisTask.totalProgress,
            serverTaskStatus: analysisTask.serverTaskStatus,
            items: [{
              ...task.items[0],
              name: t('backgroundTask.taskTitles.analyzing', { name: task.title }),
              status: analysisTask.status,
              progress: analysisTask.totalProgress
            }],
            _analysisTaskId: analysisTask.id
          }
        }
      }
      return task
    })

    const serverTaskIdSet = new Set(filteredTrainingTasks.map(t => t.id
      .replace(/^training_/, '')
      .replace(/^extval_/, '')
      .replace(/^batchinf_/, '')))
    const syntheticSubmissionTasks: BackgroundTask[] = listTrainingSubmissionRecords(['pending'])
      .filter(record => {
        if (isTrainingSubmissionPendingTimedOut(record)) {
          clearTrainingSubmissionRecord(record.taskId)
          return false
        }
        return !serverTaskIdSet.has(record.taskId)
      })
      .map(record => {
        const isBatchInference = record.taskId.startsWith('binfer_')
        const title = record.taskName || record.taskId

        return {
          id: `${isBatchInference ? 'batchinf_' : 'training_'}${record.taskId}`,
          type: isBatchInference ? 'batch_inference' : 'training',
          title,
          items: [{
            id: record.taskId,
            name: isBatchInference
              ? t('backgroundTask.taskTitles.batchInference', { name: title })
              : t('backgroundTask.taskTitles.training', { name: title }),
            status: 'pending',
            progress: 0,
          }],
          status: 'pending',
          createdAt: new Date(record.createdAt),
          totalProgress: 0,
          successCount: 0,
          failedCount: 0,
          isServerTask: true,
          serverTaskStatus: 'creating',
          taskName: record.taskName,
        }
      })

    return [
      ...localTasks,
      ...syntheticSubmissionTasks,
      ...mergedTrainingTasks,
      ...internalAnalysisTasks,
      ...filteredStorageTasks
    ]
  }, [localTasks, trainingTasks, analysisTasks, storageTasks, dismissedServerTasks, t])

  const isProcessing = tasks.some(t => t.status === 'running' || t.status === 'pending')

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
            title: t('backgroundTask.relocatingToPath', { name: destName }),
            items: [{
              id: 'migration_main',
              name: t('backgroundTask.taskTitles.movingData', { path: status.destination }),
              status: 'running',
              progress: Math.round(status.progress)
            }],
            status: 'running',
            createdAt: new Date(),
            totalProgress: Math.round(status.progress),
            successCount: 0,
            failedCount: 0
          }

          setLocalTasks(prev => {
            // Avoid duplicate if already exists
            if (prev.some(t => t.type === 'migration')) return prev
            return [task, ...prev]
          })
          setIsPanelExpanded(true)

          // Resume polling
          const pollInterval = setInterval(async () => {
            try {
              const currentStatus = await getMigrationStatus()

              setLocalTasks(prev => {
                return prev.map(task => {
                  if (task.id !== taskId) return task

                  if (currentStatus.status === 'completed') {
                    clearInterval(pollInterval)
                    refreshDiskSpace()
                    return {
                      ...task,
                      status: 'success',
                      completedAt: new Date(),
                      totalProgress: 100,
                      successCount: 1,
                      items: task.items.map(i => ({ ...i, status: 'success', progress: 100 }))
                    }
                  } else if (currentStatus.status === 'failed') {
                    clearInterval(pollInterval)
                    return {
                      ...task,
                      status: 'error',
                      completedAt: new Date(),
                      failedCount: 1,
                      items: task.items.map(i => ({
                        ...i,
                        status: 'error',
                        error: currentStatus.error || t('backgroundTask.errors.migrationFailed')
                      }))
                    }
                  } else {
                    // Still running
                    const progress = Math.round(currentStatus.progress)
                    return {
                      ...task,
                      totalProgress: progress,
                      items: task.items.map(i => ({ ...i, progress }))
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
  }, [refreshDiskSpace, isAdmin, t])

  // Task action callbacks
  const {
    addUploadTask, addDeleteWSITask, addMigrationTask, addDeleteTrainingTask,
    addExtractionTask, addPaperGenerationTask,
    cancelTask, clearCompletedTasks, removeTask, togglePanel,
    cancelServerTask, hasUploadingTasks, addMetadataUploadTask, getMetadataUploadResult
  } = useTaskActions({
    setLocalTasks, setIsPanelExpanded, setDismissedServerTasks, setMetadataUploadResults,
    cancelledTasksRef, abortControllersRef,
    trainingTasks, analysisTasks, storageTasks, tasks,
    refreshDiskSpace, metadataUploadResults
  })

  const value: BackgroundTaskContextType = {
    tasks,
    analysisTasks,
    rawTrainingTasks,
    isProcessing,
    isPanelExpanded,
    diskSpace,
    metadataUploadResults,
    addUploadTask,
    addDeleteWSITask,
    addDeleteTrainingTask,

    addExtractionTask,
    addPaperGenerationTask,
    addMigrationTask,
    addMetadataUploadTask,
    cancelTask,
    cancelServerTask,
    clearCompletedTasks,
    removeTask,
    togglePanel,
    openPanel,
    refreshDiskSpace,
    getMetadataUploadResult,
    subscribeTrainingSSE,
    subscribeAnalysisSSE,
    subscribeStorageSSE,
    hasUploadingTasks,
    deletingDatasetNames,
    addDeletingDatasetName,
    removeDeletingDatasetByTaskId,
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
