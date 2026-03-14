/**
 * Training Task Types
 *
 * Shared type definitions for the NewTaskPage and related components.
 */

import { DatasetSummary, TrainingTaskDetail } from '../api'
import { TaskType, DataLevel, SplitStrategy, TrainingStatus, ExtractorOption } from '../constants/training'

// ============================================================================
// WSI Item Types
// ============================================================================

export interface WSIItem {
  wsi_id: string
  original_filename?: string
  label?: string | null
  case_id?: string | null
  age?: number | null
  gender?: string | null
  source?: string | null
  split?: string | null
  file_extension?: string | null  // e.g. ".svs", ".png" - for file type determination (wsi_path no longer exposed)
  file_size?: number | null
  data_type?: 'wsi' | 'patch' | null
  event_time?: number | null
  event_status?: number | null
}

export interface FileMetadata {
  label: string
  case_id: string
  age: string
  gender: string
}

export interface UploadingFileStatus {
  progress: number
  status: 'uploading' | 'success' | 'error'
  error?: string
}

// ============================================================================
// Validation Types
// ============================================================================

export interface KFoldValidation {
  isValid: boolean
  maxK: number
  minSamplesPerClass: number
  numClasses: number
  unlabeledCount: number
  totalLabeled: number
  eventCount?: number
  censoredCount?: number
  message?: string
}

export interface RandomSplitValidation {
  isValid: boolean
  minRequired: number
  minSamplesPerClass?: number
  numClasses: number
  unlabeledCount: number
  totalLabeled: number
  eventCount?: number
  censoredCount?: number
  message?: string
}

export interface ConfigurationValidation {
  warnings: string[]
  errors: string[]
  isValid: boolean
}

// ============================================================================
// Step Props Types
// ============================================================================

export interface TaskSetupStepProps {
  taskName: string
  setTaskName: (name: string) => void
  taskType: TaskType
  setTaskType: (type: TaskType) => void
  dataLevel: DataLevel
  setDataLevel: (level: DataLevel) => void
  taskDescription: string
  setTaskDescription: (desc: string) => void
  canProceed: boolean
  onNext: () => void
}

export interface DataSelectionStepProps {
  dataLevel: DataLevel
  taskType: TaskType
  datasets: DatasetSummary[]
  datasetsLoading: boolean
  selectedDatasetId: string | null
  selectedDatasetName: string
  onSelectDataset: (id: string | null, name: string) => void
  items: WSIItem[]
  loading: boolean
  selectedIds: Set<string>
  onToggleSelection: (wsiId: string) => void
  onSelectPage: () => void
  onSelectAllFiltered: () => void
  // Split configuration
  splitStrategy: SplitStrategy
  setSplitStrategy: (strategy: SplitStrategy) => void
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  randomSeed: number
  setRandomSeed: (seed: number) => void
  hasPreDefinedSplits: boolean
  predefinedSplitCounts: { train: number; val: number; test: number }
  // Validation
  kFoldValidation: KFoldValidation
  randomSplitValidation: RandomSplitValidation
  classDistribution: Record<string, number>
  // File operations
  onFileUpload: (files: FileList | null) => void
  onDeleteClick: (wsiId: string, label: string, filename?: string) => void
  onEditClick: (wsi: WSIItem) => void
  onBatchEditClick: () => void
  onBatchDeleteClick: () => void
  // Navigation
  canProceed: boolean
  onNext: () => void
  onBack: () => void
}

export interface PreprocessingStepProps {
  // tileSize and stride removed - auto-determined by PrePATH-style tiling
  pyramidLevel: number
  setPyramidLevel: (level: number) => void
  featureExtractor: string
  setFeatureExtractor: (extractor: string) => void
  featureBatchSize: number
  setFeatureBatchSize: (size: number) => void
  availableExtractors: ExtractorOption[]
  loadingExtractors: boolean
  extractorSearch: string
  setExtractorSearch: (search: string) => void
  // Segmentation params
  segSthresh: number
  setSegSthresh: (val: number) => void
  segMthresh: number
  setSegMthresh: (val: number) => void
  segClose: number
  setSegClose: (val: number) => void
  segUseOtsu: boolean
  setSegUseOtsu: (val: boolean) => void
  // Filter params
  filterAreaThresh: number
  setFilterAreaThresh: (val: number) => void
  filterHoleArea: number
  setFilterHoleArea: (val: number) => void
  filterMaxHoles: number
  setFilterMaxHoles: (val: number) => void
  // Navigation
  onNext: () => void
  onBack: () => void
}

export interface ModelConfigStepProps {
  dataLevel: DataLevel
  taskType: TaskType
  // WSI-level aggregator
  aggregator: string
  setAggregator: (agg: string) => void
  // Patch-level backbone (uses featureExtractor)
  featureExtractor: string
  setFeatureExtractor: (extractor: string) => void
  availableExtractors: ExtractorOption[]
  loadingExtractors: boolean
  extractorSearch: string
  setExtractorSearch: (search: string) => void
  // Training params
  learningRate: number
  setLearningRate: (lr: number) => void
  epochs: number
  setEpochs: (epochs: number) => void
  trainBatchSize: number
  setTrainBatchSize: (size: number) => void
  optimizer: string
  setOptimizer: (opt: string) => void
  earlyStoppingPatience: number
  setEarlyStoppingPatience: (patience: number) => void
  autoBalance: boolean
  setAutoBalance: (balance: boolean) => void
  // Navigation
  onNext: () => void
  onBack: () => void
}

export interface ReviewSubmitStepProps {
  // Task config
  taskName: string
  taskType: TaskType
  dataLevel: DataLevel
  taskDescription: string
  // Data selection
  selectedIds: Set<string>
  splitStrategy: SplitStrategy
  kFoldSplits: number
  // Preprocessing (WSI only) - tileSize and stride removed, auto-determined by PrePATH-style
  pyramidLevel: number
  featureExtractor: string
  // Model config
  aggregator: string
  learningRate: number
  epochs: number
  trainBatchSize: number
  optimizer: string
  earlyStoppingPatience: number
  autoBalance: boolean
  // Validation
  validateConfiguration: ConfigurationValidation
  // Training status
  trainingStatus: TrainingStatus
  submitError: string
  // Actions
  onStartTraining: () => void
  onBack: () => void
}

export interface TaskResultStepProps {
  submittedTaskId: string
  polledTask: TrainingTaskDetail | null
  onViewDetails: () => void
  onCreateNew: () => void
}

