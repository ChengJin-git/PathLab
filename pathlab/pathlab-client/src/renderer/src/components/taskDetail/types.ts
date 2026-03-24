import type { TrainingTaskStatus } from '../../contexts/backgroundTask/types'

export interface LogEntry {
  id: number
  task_id: string
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
  message: string
  sequence: number
  metadata?: Record<string, any>
  created_at: string
}

export interface TaskDetail {
  task_id: string
  task_name: string
  task_type: 'classification' | 'survival' | 'segmentation' | 'external_validation'
  data_type: 'wsi' | 'patch'
  task_description: string
  status: TrainingTaskStatus
  progress: number
  created_at: string
  updated_at: string
  wsi_count: number
  wsi_ids?: string[]
  username?: string | null  // Username of task creator (only for admin users)
  preprocessing_config: {
    // Note: tile_size and stride removed - auto-determined by PrePATH-style tiling
    feature_extractor?: string
    feature_batch_size?: number
    use_gpu?: boolean
    // Tissue segmentation parameters
    level?: number
    sthresh?: number
    mthresh?: number
    close?: number
    use_otsu?: boolean
    contour_fn?: string
    use_padding?: boolean
    // Filter parameters
    a_t?: number
    a_h?: number
    max_n_holes?: number
    split_config?: {
      strategy: 'random' | 'k_fold' | 'manual'
      n_splits?: number
      ratios?: { train: number; val: number; test: number }
      manual_splits?: Record<string, string>
      seed?: number
    }
  }
  model_config: {
    aggregator?: string
    classifier?: string  // Classifier head for patch-level: linear, mlp, attention
    backbone?: string  // For patch-level tasks
    learning_rate?: number
    epochs?: number
    optimizer?: string
    batch_size?: number
    auto_balance?: boolean  // Auto-balance class weights for imbalanced datasets
    early_stopping_patience?: number  // Number of epochs to wait before early stopping
    // Segmentation-specific fields
    architecture?: string      // Segmentation architecture (unet, deeplabv3, etc.)
    loss_names?: string[]      // Segmentation loss function names
    loss_weights?: number[]    // Segmentation loss function weights
    // External validation specific fields
    model_id?: string
    model_name?: string  // Model name for display
    model_task_id?: string
    model_task_name?: string  // Training task name for display
    dataset_id?: string
    dataset_name?: string  // Dataset name for display
    total_wsi?: number
  }
  classes?: string[]
  error_message?: string
  patch_count?: number
  processed_patches?: number
  current_epoch?: number
}
