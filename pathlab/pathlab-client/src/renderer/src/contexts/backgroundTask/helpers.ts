/**
 * Pure helper functions for Background Task Context
 */

import type { TaskStatus } from './types'

/** localStorage key for persisted dismissed server tasks */
export const DISMISSED_TASKS_KEY = 'pathlab_dismissed_tasks'

/** Generate a unique task ID */
export const generateId = (): string =>
  `task_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`

/** Convert training task status from backend to our TaskStatus */
export const mapTrainingStatus = (status: string): TaskStatus => {
  switch (status) {
    case 'pending':
    case 'queued':  // Task is queued in GPU queue
    case 'resuming':  // Task is being resumed after system restart
      return 'pending'
    case 'patching':
    case 'extracting':
    case 'training':
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

