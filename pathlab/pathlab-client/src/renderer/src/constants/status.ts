/**
 * Task Status Constants
 *
 * Centralized status labels, colors, and badge configurations for tasks.
 * Used across BackgroundTaskPanel, TaskListPage, TaskDetailPage, etc.
 */

// ============================================================================
// Training Task Status Labels
// ============================================================================

/**
 * Training task status labels for display.
 */
export const TRAINING_STATUS_LABELS: Record<string, string> = {
  creating: 'Creating Task',
  pending: 'Pending',
  queued: 'Queued',
  patching: 'Patching Images',
  extracting: 'Extracting Features',
  training: 'Training',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  resuming: 'Resuming'
}

/**
 * External validation (inference) status labels.
 */
export const VALIDATION_STATUS_LABELS: Record<string, string> = {
  creating: 'Creating Task',
  pending: 'Pending',
  queued: 'Queued',
  patching: 'Patching Images',
  extracting: 'Extracting Features',
  training: 'Running Inference',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  resuming: 'Resuming'
}

/**
 * Analysis task status labels.
 */
export const ANALYSIS_STATUS_LABELS: Record<string, string> = {
  creating: 'Creating Task',
  pending: 'Pending',
  queued: 'Queued',
  patching: 'Analyzing',
  extracting: 'Processing',
  training: 'Analyzing',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  resuming: 'Resuming'
}

// ============================================================================
// Task Status Badge Configurations
// ============================================================================

export interface StatusBadgeConfig {
  bg: string
  text: string
  label: string
}

/**
 * Status badge configurations for TaskDetailPage.
 * Includes background color, text color, and label.
 */
export const TASK_DETAIL_STATUS_BADGES: Record<string, StatusBadgeConfig> = {
  creating: { bg: 'bg-blue-50', text: 'text-blue-700', label: 'Creating Task' },
  pending: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Pending' },
  queued: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Queued' },

  resuming: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Resuming' },
  patching: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Patching' },
  extracting: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Extracting Features' },
  training: { bg: 'bg-purple-100', text: 'text-purple-800', label: 'Training Model' },
  completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Success' },
  failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' },
  cancelled: { bg: 'bg-gray-100', text: 'text-gray-600', label: 'Cancelled' }
}

/**
 * Status badge configurations for TaskListPage.
 * Uses combined color class for simpler styling.
 */
export const TASK_LIST_STATUS_BADGES: Record<string, { color: string; label: string }> = {
  creating: { color: 'bg-blue-50 text-blue-700', label: 'Creating Task' },
  pending: { color: 'bg-gray-100 text-gray-800', label: 'Pending' },
  queued: { color: 'bg-yellow-100 text-yellow-800', label: 'Queued' },

  resuming: { color: 'bg-yellow-100 text-yellow-800', label: 'Resuming' },
  patching: { color: 'bg-blue-100 text-blue-800', label: 'Patching' },
  extracting: { color: 'bg-purple-100 text-purple-800', label: 'Extracting' },
  training: { color: 'bg-orange-100 text-orange-800', label: 'Training' },
  completed: { color: 'bg-green-100 text-green-800', label: 'Success' },
  failed: { color: 'bg-red-100 text-red-800', label: 'Failed' },
  cancelled: { color: 'bg-gray-100 text-gray-600', label: 'Cancelled' }
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get training status label for display.
 */
export function getTrainingStatusLabel(status: string): string {
  return TRAINING_STATUS_LABELS[status] || status
}

/**
 * Get validation status label for display.
 */
export function getValidationStatusLabel(status: string): string {
  return VALIDATION_STATUS_LABELS[status] || status
}

/**
 * Get analysis status label for display.
 */
export function getAnalysisStatusLabel(status: string): string {
  return ANALYSIS_STATUS_LABELS[status] || status
}

/**
 * Check if a task status represents an active/running state.
 */
export function isActiveStatus(status: string): boolean {
  return status === 'creating' || status === 'patching' || status === 'extracting' || status === 'training' || status === 'resuming'
}

// ============================================================================
// Cancellable Status Constants (for UI validation)
// ============================================================================

/**
 * Statuses that can be cancelled for training tasks.
 */
export const TRAINING_CANCELLABLE_STATUSES = [
  'creating',
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',
  'resuming'
] as const

/**
 * Statuses that can be cancelled for validation/inference tasks.
 * Note: Uses 'training' status from backend but displays as 'Running Inference'.
 */
export const VALIDATION_CANCELLABLE_STATUSES = [
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',  // Backend returns 'training' but UI shows 'Running Inference'
  'resuming'
] as const

/**
 * Statuses that can be cancelled for analysis tasks.
 */
export const ANALYSIS_CANCELLABLE_STATUSES = [
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',
  'resuming'
] as const

/**
 * Type for cancellable status arrays.
 */
export type CancellableStatus = typeof TRAINING_CANCELLABLE_STATUSES[number]

/**
 * Check if a status is cancellable based on task type.
 */
export function isCancellableStatus(status: string, taskType: 'training' | 'validation' | 'analysis'): boolean {
  switch (taskType) {
    case 'training':
      return TRAINING_CANCELLABLE_STATUSES.includes(status as CancellableStatus)
    case 'validation':
      return (VALIDATION_CANCELLABLE_STATUSES as readonly string[]).includes(status)
    case 'analysis':
      return (ANALYSIS_CANCELLABLE_STATUSES as readonly string[]).includes(status)
    default:
      return false
  }
}
