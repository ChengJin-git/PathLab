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
  pending: 'Waiting',
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
  pending: 'Waiting',
  queued: 'Queued',
  patching: 'Running Inference',
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
  pending: 'Waiting',
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
  pending: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Waiting' },
  queued: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Queued' },

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
  pending: { color: 'bg-gray-100 text-gray-800', label: 'Waiting' },
  queued: { color: 'bg-gray-100 text-gray-800', label: 'Queued' },

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
  return status === 'patching' || status === 'extracting' || status === 'training' || status === 'resuming'
}

