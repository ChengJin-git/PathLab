/**
 * Type definitions for Background Task Context
 */

import { TrainingTaskDetail, UploadSplitsResponse } from '../../api'

// Task types - includes server-side training tasks and storage tasks
export type TaskType = 'upload' | 'delete_wsi' | 'delete_task' | 'training' | 'external_validation' | 'analysis' | 'migration' | 'batch_import' | 'delete_external' | 'batch_update_metadata' | 'delete_dataset' | 'cleanup_empty_datasets' | 'unbind_dataset' | 'reset_derived_data' | 'metadata_upload' | 'extraction'
export type TaskStatus = 'pending' | 'running' | 'success' | 'error' | 'cancelled'

// Storage task type from backend
export type StorageTaskType = 'batch_import' | 'delete_external' | 'batch_update_metadata' | 'delete_dataset' | 'cleanup_empty_datasets' | 'unbind_dataset' | 'reset_derived_data'

// Training task status from backend (more granular)
export type TrainingTaskStatus = 'pending' | 'queued' | 'patching' | 'extracting' | 'training' | 'completed' | 'failed' | 'cancelled'

// Server task type from backend
export type ServerTaskType = 'classification' | 'survival' | 'segmentation' | 'external_validation'

// Individual task item (e.g., one file in a batch)
export interface TaskItem {
  id: string
  name: string
  status: TaskStatus
  progress: number  // 0-100
  error?: string
}

// A batch task containing multiple items
export interface BackgroundTask {
  id: string
  type: TaskType
  title: string
  items: TaskItem[]
  status: TaskStatus
  createdAt: Date
  completedAt?: Date
  totalProgress: number  // 0-100, calculated from items
  successCount: number
  failedCount: number
  skippedCount?: number
  // For server-side tasks (training/inference)
  isServerTask?: boolean
  serverTaskStatus?: TrainingTaskStatus  // Original status from server
  taskName?: string  // Task name for training tasks
  dataLevel?: 'wsi' | 'patch' // For progress calculation
  // For analysis tasks
  analysisType?: 'internal' | 'external'  // Type of analysis
  taskCategory?: 'classification' | 'survival' | 'segmentation'  // Task category for i18n display (internal analysis only)
  trainingTaskId?: string  // The training task ID this analysis belongs to (for merging external validation)
}

// Disk space info
export interface DiskSpaceInfo {
  free_gb: number
  warning: boolean
  critical: boolean
}

// Metadata upload task configuration (for background CSV/Excel upload)
export interface MetadataUploadTaskConfig {
  csvFile: File              // Already-converted CSV file (or raw CSV if user selected CSV)
  datasetName: string        // Dataset name to find/poll for
  datasetId?: string         // If already known
  uploadMode: 'classification' | 'survival' | 'segmentation'
  dataLevel: 'file' | 'case'
}

// Metadata upload result stored after completion
export interface MetadataUploadResult {
  result: UploadSplitsResponse
  datasetId: string
}

// Upload task file configuration
export interface UploadTaskFile {
  key: string
  name: string
  file?: File
  path?: string  // For local path upload
  metadata?: {
    dataset_id?: string  // Dataset UUID (for existing dataset)
    dataset_name?: string  // Dataset display name (for creating new dataset)
    aggregation_level?: 'case' | 'file'  // Aggregation level for new dataset
    task_type?: 'classification' | 'survival' | 'segmentation'
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
    // Survival analysis fields
    event_time?: number
    event_status?: number
  }
  associatedFiles?: File[]
}

export interface UploadTaskOptions {
  onComplete?: () => void
}

export interface BackgroundTaskContextType {
  // State
  tasks: BackgroundTask[]
  analysisTasks: BackgroundTask[]  // Expose analysis tasks for monitoring completion
  rawTrainingTasks: TrainingTaskDetail[] | null  // Raw training tasks from SSE (null = not yet loaded)
  isProcessing: boolean
  isPanelExpanded: boolean
  diskSpace: DiskSpaceInfo | null
  metadataUploadResults: Map<string, MetadataUploadResult>  // datasetName → result

  // Actions
  addUploadTask: (files: UploadTaskFile[], options?: UploadTaskOptions) => Promise<string>
  addDeleteWSITask: (wsiIds: string[], mode: 'standard' | 'complete') => Promise<string>
  addDeleteTrainingTask: (taskIds: string[], mode: 'standard' | 'complete') => Promise<string>

  addExtractionTask: (taskId: string, datasetName: string) => string
  addMigrationTask: (targetPath: string, deleteSource: boolean) => Promise<string>
  addMetadataUploadTask: (config: MetadataUploadTaskConfig) => string
  cancelTask: (taskId: string) => void
  cancelServerTask: (task: BackgroundTask) => Promise<boolean>  // Cancel training/inference task on server
  clearCompletedTasks: () => void
  removeTask: (task: BackgroundTask) => void
  togglePanel: () => void
  refreshDiskSpace: () => Promise<void>
  getMetadataUploadResult: (datasetName: string) => MetadataUploadResult | undefined

  // SSE subscriptions (on-demand connection management)
  subscribeTrainingSSE: () => () => void
  subscribeAnalysisSSE: () => () => void
  subscribeStorageSSE: () => () => void

  // Validation
  hasUploadingTasks: () => boolean  // Check if there are any uploading tasks (upload or batch_import)
}

export interface BackgroundTaskProviderProps {
  children: React.ReactNode
}

