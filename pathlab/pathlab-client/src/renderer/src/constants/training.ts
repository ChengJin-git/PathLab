/**
 * Training Task Configuration Constants
 *
 * Centralized configuration for training task creation.
 * Extracted from NewTaskPage.tsx for better maintainability.
 */

// ============================================================================
// Common Option Interface
// ============================================================================

export interface SelectOption<T = string> {
  value: T
  label: string
  description?: string
}

// ============================================================================
// Task Types
// ============================================================================

/**
 * Available task types for training.
 */
export const TASK_TYPES: readonly SelectOption[] = [
  { value: 'classification', label: 'Classification' },
  { value: 'survival', label: 'Survival Prediction' },
  { value: 'segmentation', label: 'Segmentation' }
] as const

export type TaskType = 'classification' | 'survival' | 'segmentation'

// ============================================================================
// Data Levels
// ============================================================================

/**
 * Available data levels for training.
 */
export const DATA_LEVELS: readonly SelectOption[] = [
  { value: 'wsi', label: 'WSI (Whole Slide)' },
  { value: 'patch', label: 'Patch' }
] as const

export type DataLevel = 'wsi' | 'patch'

// ============================================================================
// Split Strategy & Training Status Types
// ============================================================================

export type SplitStrategy = 'random' | 'k_fold' | 'manual'
export type TrainingStatus = 'idle' | 'validating' | 'submitting' | 'submitted' | 'failed'

// ============================================================================
// Feature Extractors
// ============================================================================

export interface ExtractorOption {
  id: string
  name: string
  description: string
}

/**
 * Available feature extractors for patch-level feature extraction.
 * Order matches backend registry.py to avoid UI jump.
 */
export const FEATURE_EXTRACTORS: readonly ExtractorOption[] = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained CNN, 2048-dim, general-purpose baseline' },
  { id: 'vit_l_16', name: 'ViT-Large', description: 'ImageNet pretrained ViT-L/16, 1024-dim, general-purpose baseline' },
  { id: 'conch', name: 'CONCH', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)' },
  { id: 'uni', name: 'UNI', description: 'DINOv2 ViT-L/16, 1024-dim (Mahmood Lab)' },
  { id: 'uni2', name: 'UNI2', description: 'ViT-G/14, 1536-dim (Mahmood Lab)' },
  { id: 'virchow', name: 'Virchow', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)' },
  { id: 'virchow2', name: 'Virchow2', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)' },
  { id: 'plip', name: 'PLIP', description: 'CLIP ViT-B/32, 512-dim (Stanford)' },
  { id: 'phikon', name: 'Phikon', description: 'DINOv2 ViT-B/16, 768-dim (Owkin)' },
  { id: 'phikon2', name: 'Phikon2', description: 'DINOv2 ViT-L/16, 1024-dim (Owkin)' },
  { id: 'patho_clip', name: 'PathoCLIP', description: 'CLIP ViT-L/14, 768-dim' },
  { id: 'openmidnight', name: 'OpenMidnight', description: 'DINOv2 ViT-G/14, 1536-dim' },
  { id: 'conch15', name: 'CONCH 1.5', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)' },
  { id: 'H-Optimus-1', name: 'H-Optimus-1', description: 'ViT-G/14, 1536-dim (Bioptimus)' },
  { id: 'H-Optimus-0', name: 'H-Optimus-0', description: 'ViT-G/14, 1536-dim (Bioptimus)' },
  { id: 'mSTAR', name: 'mSTAR', description: 'DINOv2 ViT-L/16, 1024-dim' },
  { id: 'GPFM', name: 'GPFM', description: 'DINOv2 ViT-G/14, 1536-dim' }
] as const

/** Default feature extractor ID */
export const DEFAULT_EXTRACTOR = 'resnet50'

/**
 * Feature extractors as SelectOption format for dropdowns.
 */
export const ENCODER_OPTIONS: readonly SelectOption[] = FEATURE_EXTRACTORS.map(e => ({
  value: e.id,
  label: e.name,
  description: e.description
}))

// ============================================================================
// Optimizers
// ============================================================================

/**
 * Available optimizers for training.
 */
export const OPTIMIZERS: readonly SelectOption[] = [
  { value: 'adam', label: 'Adam' },
  { value: 'sgd', label: 'SGD' },
  { value: 'adamw', label: 'AdamW' }
] as const

/** Default optimizer */
export const DEFAULT_OPTIMIZER = 'adam'

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

/**
 * Aggregators as SelectOption format for dropdowns.
 */
export const AGGREGATOR_OPTIONS: readonly SelectOption[] = AGGREGATORS.map(a => ({
  value: a.id,
  label: a.name,
  description: a.description
}))

// ============================================================================
// Segmentation Architectures (for patch-level segmentation)
// ============================================================================

/**
 * Available segmentation model architectures.
 * Matches backend SUPPORT_ARCHTECTURES in segmentors/__init__.py.
 */
export const SEGMENTATION_ARCHITECTURES: readonly ExtractorOption[] = [
  { id: 'unet', name: 'U-Net', description: 'Classic encoder-decoder with skip connections' },
  { id: 'unetplusplus', name: 'UNet++', description: 'Nested U-Net with dense skip connections' },
  { id: 'manet', name: 'MANet', description: 'Multi-scale Attention Network' },
  { id: 'linknet', name: 'LinkNet', description: 'Lightweight encoder-decoder with residual connections' },
  { id: 'fpn', name: 'FPN', description: 'Feature Pyramid Network for multi-scale features' },
  { id: 'pspnet', name: 'PSPNet', description: 'Pyramid Scene Parsing Network' },
  { id: 'deeplabv3', name: 'DeepLabV3', description: 'Atrous Spatial Pyramid Pooling' },
  { id: 'deeplabv3plus', name: 'DeepLabV3+', description: 'DeepLabV3 with decoder module' },
  { id: 'pan', name: 'PAN', description: 'Pyramid Attention Network' },
  { id: 'upernet', name: 'UPerNet', description: 'Unified Perceptual Parsing Network' },
  { id: 'segformer', name: 'SegFormer', description: 'Transformer-based segmentation' },
  { id: 'dpt', name: 'DPT', description: 'Dense Prediction Transformer' },
] as const

/** Default segmentation architecture */
export const DEFAULT_SEG_ARCHITECTURE = 'unet'

// ============================================================================
// Segmentation Backbones (Encoders for segmentation models)
// ============================================================================

export interface BackboneOption {
  id: string
  name: string
  description: string
  group: string
}

/**
 * Common segmentation backbones grouped by family.
 * Full list available in backend SUPPORT_FEATURE_EXTRACTORS.
 * UI shows a curated subset for usability.
 */
export const SEGMENTATION_BACKBONES: readonly BackboneOption[] = [
  // ResNet family
  { id: 'resnet18', name: 'ResNet-18', description: 'Lightweight, fast training', group: 'ResNet' },
  { id: 'resnet34', name: 'ResNet-34', description: 'Good balance of speed and accuracy', group: 'ResNet' },
  { id: 'resnet50', name: 'ResNet-50', description: 'Standard baseline (recommended)', group: 'ResNet' },
  { id: 'resnet101', name: 'ResNet-101', description: 'Higher capacity, slower training', group: 'ResNet' },
  // EfficientNet family
  { id: 'efficientnet-b0', name: 'EfficientNet-B0', description: 'Efficient, lightweight', group: 'EfficientNet' },
  { id: 'efficientnet-b3', name: 'EfficientNet-B3', description: 'Good accuracy-efficiency tradeoff', group: 'EfficientNet' },
  { id: 'efficientnet-b5', name: 'EfficientNet-B5', description: 'High accuracy, more compute', group: 'EfficientNet' },
  // DenseNet family
  { id: 'densenet121', name: 'DenseNet-121', description: 'Dense connections, feature reuse', group: 'DenseNet' },
  { id: 'densenet169', name: 'DenseNet-169', description: 'More layers, richer features', group: 'DenseNet' },
  // SE-ResNet family
  { id: 'se_resnet50', name: 'SE-ResNet-50', description: 'ResNet-50 with channel attention', group: 'SE-Net' },
  // MobileNet
  { id: 'mobilenet_v2', name: 'MobileNet-V2', description: 'Mobile-optimized, very fast', group: 'MobileNet' },
  // Mix Transformer (for SegFormer)
  { id: 'mit_b0', name: 'MiT-B0', description: 'SegFormer backbone, lightweight', group: 'MiT' },
  { id: 'mit_b2', name: 'MiT-B2', description: 'SegFormer backbone, balanced', group: 'MiT' },
  { id: 'mit_b4', name: 'MiT-B4', description: 'SegFormer backbone, high capacity', group: 'MiT' },
  // VGG
  { id: 'vgg16_bn', name: 'VGG-16 BN', description: 'Classic CNN with batch normalization', group: 'VGG' },
] as const

/** Default segmentation backbone */
export const DEFAULT_SEG_BACKBONE = 'resnet50'

// ============================================================================
// Segmentation Loss Functions
// ============================================================================

export interface LossOption {
  id: string
  name: string
  description: string
}

/**
 * Available loss functions for segmentation tasks.
 * Matches backend loss.py get_loss() factory.
 */
export const SEGMENTATION_LOSSES: readonly LossOption[] = [
  { id: 'DiceLoss', name: 'Dice Loss', description: 'Overlap-based, handles class imbalance well' },
  { id: 'JaccardLoss', name: 'Jaccard Loss (IoU)', description: 'IoU-based loss, similar to Dice' },
  { id: 'TverskyLoss', name: 'Tversky Loss', description: 'Generalized Dice with adjustable FP/FN weights' },
  { id: 'FocalLoss', name: 'Focal Loss', description: 'Down-weights easy examples, focuses on hard cases' },
  { id: 'LovaszLoss', name: 'Lovász Loss', description: 'Submodular IoU surrogate, good for imbalanced data' },
  { id: 'BCE', name: 'Binary Cross Entropy', description: 'Standard per-pixel binary classification loss' },
  { id: 'CE', name: 'Cross Entropy', description: 'Standard multi-class cross entropy loss' },
  { id: 'MCCLoss', name: 'MCC Loss', description: 'Matthews Correlation Coefficient loss' },
] as const

/** Default segmentation loss configuration */
export const DEFAULT_SEG_LOSS_NAMES = ['DiceLoss', 'JaccardLoss']
export const DEFAULT_SEG_LOSS_WEIGHTS = [0.5, 0.5]

// ============================================================================
// Segmentation Training Defaults
// ============================================================================

export interface SegTrainingDefaults {
  learningRate: number
  epochs: number
  batchSize: number
  optimizer: string
  earlyStoppingPatience: number
  scheduler: string
  useAmp: boolean
  gradientClip: number
}

/**
 * Default training hyperparameters for segmentation tasks.
 * Different from classification defaults to match backend __default_config__.
 */
export const SEG_TRAINING_DEFAULTS: SegTrainingDefaults = {
  learningRate: 0.0001,
  epochs: 100,
  batchSize: 16,
  optimizer: 'adamw',
  earlyStoppingPatience: 15,
  scheduler: 'cosine_warm_restarts',
  useAmp: true,
  gradientClip: 1.0,
}

// ============================================================================
// Preprocessing Configuration
// ============================================================================

// Note: tile_size and stride are no longer configurable.
// Patch size is auto-determined by PrePATH-style tiling based on WSI magnification
// to ensure consistent physical coverage (~128μm) across different resolution WSIs.
// - 20x (mpp≈0.5): patch_size=256
// - 40x (mpp≈0.25): patch_size=512
// - 80x (mpp≈0.125): patch_size=1024

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
  learningRate: 0.0002,
  epochs: 50,
  batchSize: 64,
  optimizer: 'adam',
  earlyStoppingPatience: 20,
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

