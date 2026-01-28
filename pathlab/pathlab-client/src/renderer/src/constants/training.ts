/**
 * Training Task Configuration Constants
 *
 * Centralized configuration for training task creation.
 * Extracted from NewTaskPage.tsx for better maintainability.
 */

// ============================================================================
// MIL Aggregators (for WSI-level classification)
// ============================================================================

export interface AggregatorOption {
  id: string
  name: string
  description: string
  detail: string
}

/**
 * Available MIL aggregators for WSI-level classification.
 * These aggregate patch-level features into slide-level predictions.
 */
export const AGGREGATORS: readonly AggregatorOption[] = [
  { id: 'abmil', name: 'ABMIL', description: 'Attention-based MIL (recommended)', detail: 'Learns importance weights for each patch' },
  { id: 'meanmil', name: 'MeanMIL', description: 'Simple average pooling', detail: 'Average of all patch features' },
  { id: 'maxmil', name: 'MaxMIL', description: 'Maximum activation pooling', detail: 'Takes maximum across patches' },
  { id: 'clam_sb', name: 'CLAM-SB', description: 'Single Branch CLAM', detail: 'Single-branch Instance-level clustering with attention' },
  { id: 'clam_mb', name: 'CLAM-MB', description: 'Multi Branch CLAM', detail: 'Multi-branch Instance-level clustering with attention' },
  { id: 'dsmil', name: 'DSMIL', description: 'Dual-stream MIL', detail: 'Combines instance and bag-level features' },
  { id: 'dtfdmil', name: 'DTFD-MIL', description: 'Double-Tier Feature Distillation', detail: 'Two-tier pseudo-bag distillation' },
  { id: 'transmil', name: 'TransMIL', description: 'Transformer-based MIL', detail: 'Correlation modeling with Transformer' },
] as const

/** Default aggregator ID */
export const DEFAULT_AGGREGATOR = 'abmil'

// ============================================================================
// Preprocessing Configuration
// ============================================================================

/**
 * Available tile sizes for patch extraction.
 * Larger tiles provide more context but require more GPU memory.
 */
export const TILE_SIZES = [256, 512, 1024] as const
export type TileSize = typeof TILE_SIZES[number]

/** Default tile size in pixels */
export const DEFAULT_TILE_SIZE: TileSize = 512

/** Default stride (0 = non-overlapping) */
export const DEFAULT_STRIDE = 0

/** Default pyramid level (0 = highest resolution) */
export const DEFAULT_PYRAMID_LEVEL = 0

/** Default feature extraction batch size */
export const DEFAULT_FEATURE_BATCH_SIZE = 64

// ============================================================================
// Tissue Segmentation Parameters
// ============================================================================

export interface SegmentationDefaults {
  sthresh: number
  mthresh: number
  close: number
  useOtsu: boolean
}

/**
 * Default tissue segmentation parameters.
 * These control how tissue regions are detected in WSI.
 */
export const SEGMENTATION_DEFAULTS: SegmentationDefaults = {
  sthresh: 8,   // Saturation threshold
  mthresh: 7,   // Median filter threshold
  close: 4,     // Morphological closing kernel size
  useOtsu: false,
}

// ============================================================================
// Filter Parameters
// ============================================================================

export interface FilterDefaults {
  areaThresh: number
  holeArea: number
  maxHoles: number
}

/**
 * Default filter parameters for patch filtering.
 */
export const FILTER_DEFAULTS: FilterDefaults = {
  areaThresh: 1,     // Minimum tissue area threshold
  holeArea: 256,     // Minimum hole area to filter
  maxHoles: 100,     // Maximum number of holes per contour
}

// ============================================================================
// Training Hyperparameters
// ============================================================================

export interface TrainingDefaults {
  learningRate: number
  epochs: number
  batchSize: number
  optimizer: string
  earlyStoppingPatience: number
  autoBalance: boolean
}

/**
 * Default training hyperparameters.
 */
export const TRAINING_DEFAULTS: TrainingDefaults = {
  learningRate: 0.0001,
  epochs: 50,
  batchSize: 64,
  optimizer: 'adam',
  earlyStoppingPatience: 10,
  autoBalance: true,
}

// ============================================================================
// Split Configuration
// ============================================================================

export interface SplitDefaults {
  strategy: 'random' | 'k_fold' | 'manual'
  kFoldSplits: number
  randomSeed: number
  splitRatio: number  // Train percentage for random split
}

/**
 * Default data split configuration.
 */
export const SPLIT_DEFAULTS: SplitDefaults = {
  strategy: 'random',
  kFoldSplits: 5,
  randomSeed: 42,
  splitRatio: 70,
}

