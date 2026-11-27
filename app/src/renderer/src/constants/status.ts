/**
 * Task Status Constants
 *
 * Centralized status labels, colors, and badge configurations for tasks.
 * Used across BackgroundTaskPanel, TaskListPage, TaskDetailPage, etc.
 */

// ============================================================================
// Core: base labels + per-task-type overrides
// ============================================================================

const BASE_STATUS_LABELS: Record<string, string> = {
  creating: 'Creating Task',
  pending: 'Checking Dataset Integrity',
  queued: 'Queued',
  patching: 'Patching Images',
  extracting: 'Extracting Features',
  training: 'Training',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  resuming: 'Resuming',
}

const STATUS_LABEL_OVERRIDES: Record<'training' | 'validation' | 'analysis', Partial<Record<string, string>>> = {
  training: {},
  validation: {
    training: 'Running Inference',
  },
  analysis: {
    patching: 'Analyzing',
    extracting: 'Processing',
    training: 'Analyzing',
  },
}

export function getStatusLabel(
  status: string,
  taskType: 'training' | 'validation' | 'analysis' = 'training',
): string {
  return STATUS_LABEL_OVERRIDES[taskType]?.[status] ?? BASE_STATUS_LABELS[status] ?? status
}

// ============================================================================
// Backward-compatible Map exports (derived from getStatusLabel)
// ============================================================================

export const TRAINING_STATUS_LABELS: Record<string, string> = Object.fromEntries(
  Object.keys(BASE_STATUS_LABELS).map((k) => [k, getStatusLabel(k, 'training')]),
)

export const VALIDATION_STATUS_LABELS: Record<string, string> = Object.fromEntries(
  Object.keys(BASE_STATUS_LABELS).map((k) => [k, getStatusLabel(k, 'validation')]),
)

export const ANALYSIS_STATUS_LABELS: Record<string, string> = Object.fromEntries(
  Object.keys(BASE_STATUS_LABELS).map((k) => [k, getStatusLabel(k, 'analysis')]),
)

// ============================================================================
// Backward-compatible helper functions
// ============================================================================

export function getTrainingStatusLabel(status: string): string {
  return getStatusLabel(status, 'training')
}

export function getValidationStatusLabel(status: string): string {
  return getStatusLabel(status, 'validation')
}

export function getAnalysisStatusLabel(status: string): string {
  return getStatusLabel(status, 'analysis')
}

// ============================================================================
// Task Status Badge Configurations
// ============================================================================

export interface StatusBadgeConfig {
  bg: string
  text: string
  label: string
}

export const TASK_DETAIL_STATUS_BADGES: Record<string, StatusBadgeConfig> = {
  creating:   { bg: 'bg-blue-50',     text: 'text-blue-700',   label: 'Creating Task' },
  pending:    { bg: 'bg-gray-100',    text: 'text-gray-800',   label: 'Checking Dataset Integrity' },
  queued:     { bg: 'bg-yellow-100',  text: 'text-yellow-800', label: 'Queued' },
  resuming:   { bg: 'bg-yellow-100',  text: 'text-yellow-800', label: 'Resuming' },
  patching:   { bg: 'bg-blue-100',    text: 'text-blue-800',   label: 'Patching' },
  extracting: { bg: 'bg-blue-100',    text: 'text-blue-800',   label: 'Extracting Features' },
  training:   { bg: 'bg-purple-100',  text: 'text-purple-800', label: 'Training Model' },
  completed:  { bg: 'bg-green-100',   text: 'text-green-800',  label: 'Success' },
  failed:     { bg: 'bg-red-100',     text: 'text-red-800',    label: 'Failed' },
  cancelled:  { bg: 'bg-gray-100',    text: 'text-gray-600',   label: 'Cancelled' },
}

export const TASK_LIST_STATUS_BADGES: Record<string, { color: string; label: string }> = {
  creating:   { color: 'bg-blue-50 text-blue-700',      label: 'Creating Task' },
  pending:    { color: 'bg-gray-100 text-gray-800',     label: 'Checking Dataset Integrity' },
  queued:     { color: 'bg-yellow-100 text-yellow-800', label: 'Queued' },
  resuming:   { color: 'bg-yellow-100 text-yellow-800', label: 'Resuming' },
  patching:   { color: 'bg-blue-100 text-blue-800',     label: 'Patching' },
  extracting: { color: 'bg-purple-100 text-purple-800', label: 'Extracting' },
  training:   { color: 'bg-orange-100 text-orange-800', label: 'Training' },
  completed:  { color: 'bg-green-100 text-green-800',   label: 'Success' },
  failed:     { color: 'bg-red-100 text-red-800',       label: 'Failed' },
  cancelled:  { color: 'bg-gray-100 text-gray-600',     label: 'Cancelled' },
}

// ============================================================================
// Cancellable Status Constants
// ============================================================================

export const TRAINING_CANCELLABLE_STATUSES = [
  'creating',
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',
  'resuming',
] as const

export const VALIDATION_CANCELLABLE_STATUSES = [
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',
  'resuming',
] as const

export const ANALYSIS_CANCELLABLE_STATUSES = [
  'pending',
  'queued',
  'patching',
  'extracting',
  'training',
  'resuming',
] as const

export type CancellableStatus = typeof TRAINING_CANCELLABLE_STATUSES[number]

export function isActiveStatus(status: string): boolean {
  return (
    status === 'creating' ||
    status === 'patching' ||
    status === 'extracting' ||
    status === 'training' ||
    status === 'resuming'
  )
}

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
