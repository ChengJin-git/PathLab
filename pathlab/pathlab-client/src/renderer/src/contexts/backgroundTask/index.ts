/**
 * Background Task Context — barrel export
 *
 * Re-exports all public types, hooks, and the Provider so that consumers
 * can keep using:
 *   import { useBackgroundTask, BackgroundTask, ... } from '../contexts/BackgroundTaskContext'
 *
 * After the directory rename, the import path becomes:
 *   import { ... } from '../contexts/backgroundTask'
 * But we also keep the old path working via the original file re-export.
 */

// Types
export type {
  TaskType, TaskStatus, StorageTaskType, TrainingTaskStatus, ServerTaskType,
  TaskItem, BackgroundTask, DiskSpaceInfo,
  MetadataUploadTaskConfig, MetadataUploadResult,
  UploadTaskFile, UploadTaskOptions,
  BackgroundTaskContextType
} from './types'

// Provider and hook
export { BackgroundTaskProvider, useBackgroundTask } from './BackgroundTaskProvider'

