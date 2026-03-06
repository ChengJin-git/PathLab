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
  supports_spatial?: boolean
}

/**
 * Available feature extractors for patch-level feature extraction.
 * Order matches backend registry.py to avoid UI jump.
 */
export const FEATURE_EXTRACTORS: readonly ExtractorOption[] = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained CNN, 2048-dim, general-purpose baseline', supports_spatial: false },
  { id: 'vit_l_16', name: 'ViT-Large', description: 'ImageNet pretrained ViT-L/16, 1024-dim, general-purpose baseline', supports_spatial: false },
  { id: 'conch', name: 'CONCH', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)', supports_spatial: true },
  { id: 'uni', name: 'UNI', description: 'DINOv2 ViT-L/16, 1024-dim (Mahmood Lab)', supports_spatial: true },
  { id: 'uni2', name: 'UNI2', description: 'ViT-G/14, 1536-dim (Mahmood Lab)', supports_spatial: true },
  { id: 'virchow', name: 'Virchow', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)', supports_spatial: true },
  { id: 'virchow2', name: 'Virchow2', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)', supports_spatial: true },
  { id: 'plip', name: 'PLIP', description: 'CLIP ViT-B/32, 512-dim (Stanford)', supports_spatial: true },
  { id: 'phikon', name: 'Phikon', description: 'DINOv2 ViT-B/16, 768-dim (Owkin)', supports_spatial: true },
  { id: 'phikon2', name: 'Phikon2', description: 'DINOv2 ViT-L/16, 1024-dim (Owkin)', supports_spatial: true },
  { id: 'patho_clip', name: 'PathoCLIP', description: 'CLIP ViT-L/14, 768-dim', supports_spatial: true },
  { id: 'openmidnight', name: 'OpenMidnight', description: 'DINOv2 ViT-G/14, 1536-dim', supports_spatial: true },
  { id: 'conch15', name: 'CONCH 1.5', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)', supports_spatial: true },
  { id: 'H-Optimus-1', name: 'H-Optimus-1', description: 'ViT-G/14, 1536-dim (Bioptimus)', supports_spatial: true },
  { id: 'H-Optimus-0', name: 'H-Optimus-0', description: 'ViT-G/14, 1536-dim (Bioptimus)', supports_spatial: true },
  { id: 'mSTAR', name: 'mSTAR', description: 'DINOv2 ViT-L/16, 1024-dim', supports_spatial: true },
  { id: 'GPFM', name: 'GPFM', description: 'DINOv2 ViT-G/14, 1536-dim', supports_spatial: true },
  { id: 'SmartCCS', name: 'Smart-CCS', description: 'DINOv2 ViT-L/14, 1024-dim (Smartlab)', supports_spatial: true },
  { id: 'SmartCyto', name: 'SmartCyto', description: 'DINOv3 ViT-B/16, 768-dim (Smartlab)', supports_spatial: true }
] as const

/** Default feature extractor ID */
export const DEFAULT_EXTRACTOR = 'resnet50'
export const FM_SEGMENTATION_ARCHITECTURE = 'conv_decoder'

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
// Patch Classifiers (for patch-level classification heads)
// ============================================================================

/**
 * Available classifier heads for patch-level classification.
 * These are trained on top of frozen FM features.
 */
export const PATCH_CLASSIFIERS: readonly SelectOption[] = [
  { value: 'linear', label: 'Linear Probe', description: 'Single linear layer' },
  { value: 'mlp', label: 'MLP', description: 'Multi-layer perceptron with hidden layers' },
  { value: 'attention', label: 'Attention', description: 'Attention-pooling classifier' },
] as const

/** Default patch classifier */
export const DEFAULT_PATCH_CLASSIFIER = 'linear'

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
 * All segmentation backbones matching backend SUPPORT_FEATURE_EXTRACTORS.
 * Grouped by family for UI filtering.
 */
export const SEGMENTATION_BACKBONES: readonly BackboneOption[] = [
  // ── ResNet ──
  { id: 'resnet18', name: 'ResNet-18', description: '11M params, lightweight baseline', group: 'ResNet' },
  { id: 'resnet34', name: 'ResNet-34', description: '21M params, good speed/accuracy balance', group: 'ResNet' },
  { id: 'resnet50', name: 'ResNet-50', description: '23M params, standard baseline (recommended)', group: 'ResNet' },
  { id: 'resnet101', name: 'ResNet-101', description: '42M params, higher capacity', group: 'ResNet' },
  { id: 'resnet152', name: 'ResNet-152', description: '58M params, deep model', group: 'ResNet' },
  // ── ResNeXt ──
  { id: 'resnext50_32x4d', name: 'ResNeXt-50', description: '22M params, grouped convolutions', group: 'ResNeXt' },
  { id: 'resnext101_32x4d', name: 'ResNeXt-101 (32×4d)', description: '42M params', group: 'ResNeXt' },
  { id: 'resnext101_32x8d', name: 'ResNeXt-101 (32×8d)', description: '86M params, high capacity', group: 'ResNeXt' },
  { id: 'resnext101_32x16d', name: 'ResNeXt-101 (32×16d)', description: '191M params', group: 'ResNeXt' },
  { id: 'resnext101_32x32d', name: 'ResNeXt-101 (32×32d)', description: '466M params', group: 'ResNeXt' },
  { id: 'resnext101_32x48d', name: 'ResNeXt-101 (32×48d)', description: '826M params', group: 'ResNeXt' },
  // ── DPN ──
  { id: 'dpn68', name: 'DPN-68', description: '11M params, dual path network', group: 'DPN' },
  { id: 'dpn68b', name: 'DPN-68b', description: '11M params, ImageNet+5k pretrained', group: 'DPN' },
  { id: 'dpn92', name: 'DPN-92', description: '34M params', group: 'DPN' },
  { id: 'dpn98', name: 'DPN-98', description: '58M params', group: 'DPN' },
  { id: 'dpn107', name: 'DPN-107', description: '84M params', group: 'DPN' },
  { id: 'dpn131', name: 'DPN-131', description: '76M params', group: 'DPN' },
  // ── VGG ──
  { id: 'vgg11', name: 'VGG-11', description: '9M params', group: 'VGG' },
  { id: 'vgg11_bn', name: 'VGG-11 BN', description: '9M params, with batch norm', group: 'VGG' },
  { id: 'vgg13', name: 'VGG-13', description: '9M params', group: 'VGG' },
  { id: 'vgg13_bn', name: 'VGG-13 BN', description: '9M params, with batch norm', group: 'VGG' },
  { id: 'vgg16', name: 'VGG-16', description: '14M params', group: 'VGG' },
  { id: 'vgg16_bn', name: 'VGG-16 BN', description: '14M params, with batch norm', group: 'VGG' },
  { id: 'vgg19', name: 'VGG-19', description: '20M params', group: 'VGG' },
  { id: 'vgg19_bn', name: 'VGG-19 BN', description: '20M params, with batch norm', group: 'VGG' },
  // ── SE-Net ──
  { id: 'senet154', name: 'SENet-154', description: '113M params, squeeze-and-excitation', group: 'SE-Net' },
  { id: 'se_resnet50', name: 'SE-ResNet-50', description: '26M params, channel attention', group: 'SE-Net' },
  { id: 'se_resnet101', name: 'SE-ResNet-101', description: '47M params', group: 'SE-Net' },
  { id: 'se_resnet152', name: 'SE-ResNet-152', description: '64M params', group: 'SE-Net' },
  { id: 'se_resnext50_32x4d', name: 'SE-ResNeXt-50', description: '25M params', group: 'SE-Net' },
  { id: 'se_resnext101_32x4d', name: 'SE-ResNeXt-101', description: '46M params', group: 'SE-Net' },
  // ── DenseNet ──
  { id: 'densenet121', name: 'DenseNet-121', description: '6M params, dense connections', group: 'DenseNet' },
  { id: 'densenet169', name: 'DenseNet-169', description: '12M params', group: 'DenseNet' },
  { id: 'densenet201', name: 'DenseNet-201', description: '18M params', group: 'DenseNet' },
  { id: 'densenet161', name: 'DenseNet-161', description: '26M params', group: 'DenseNet' },
  // ── Inception ──
  { id: 'inceptionresnetv2', name: 'Inception-ResNet-V2', description: '54M params', group: 'Inception' },
  { id: 'inceptionv4', name: 'Inception-V4', description: '41M params', group: 'Inception' },
  // ── EfficientNet ──
  { id: 'efficientnet-b0', name: 'EfficientNet-B0', description: '4M params, lightweight', group: 'EfficientNet' },
  { id: 'efficientnet-b1', name: 'EfficientNet-B1', description: '6M params', group: 'EfficientNet' },
  { id: 'efficientnet-b2', name: 'EfficientNet-B2', description: '7M params', group: 'EfficientNet' },
  { id: 'efficientnet-b3', name: 'EfficientNet-B3', description: '10M params, good tradeoff', group: 'EfficientNet' },
  { id: 'efficientnet-b4', name: 'EfficientNet-B4', description: '17M params', group: 'EfficientNet' },
  { id: 'efficientnet-b5', name: 'EfficientNet-B5', description: '28M params, high accuracy', group: 'EfficientNet' },
  { id: 'efficientnet-b6', name: 'EfficientNet-B6', description: '40M params', group: 'EfficientNet' },
  { id: 'efficientnet-b7', name: 'EfficientNet-B7', description: '63M params', group: 'EfficientNet' },
  // ── MobileNet ──
  { id: 'mobilenet_v2', name: 'MobileNet-V2', description: '2M params, mobile-optimized', group: 'MobileNet' },
  // ── Xception ──
  { id: 'xception', name: 'Xception', description: '20M params, depthwise separable convs', group: 'Xception' },
  // ── timm EfficientNet ──
  { id: 'timm-efficientnet-b0', name: 'timm EfficientNet-B0', description: '4M params, noisy-student available', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b1', name: 'timm EfficientNet-B1', description: '6M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b2', name: 'timm EfficientNet-B2', description: '7M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b3', name: 'timm EfficientNet-B3', description: '10M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b4', name: 'timm EfficientNet-B4', description: '17M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b5', name: 'timm EfficientNet-B5', description: '28M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b6', name: 'timm EfficientNet-B6', description: '40M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b7', name: 'timm EfficientNet-B7', description: '63M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-b8', name: 'timm EfficientNet-B8', description: '84M params', group: 'timm-EfficientNet' },
  { id: 'timm-efficientnet-l2', name: 'timm EfficientNet-L2', description: '474M params, largest', group: 'timm-EfficientNet' },
  // ── timm EfficientNet Lite ──
  { id: 'timm-tf_efficientnet_lite0', name: 'timm EfficientNet-Lite0', description: '3M params', group: 'timm-EfficientNet' },
  { id: 'timm-tf_efficientnet_lite1', name: 'timm EfficientNet-Lite1', description: '4M params', group: 'timm-EfficientNet' },
  { id: 'timm-tf_efficientnet_lite2', name: 'timm EfficientNet-Lite2', description: '4M params', group: 'timm-EfficientNet' },
  { id: 'timm-tf_efficientnet_lite3', name: 'timm EfficientNet-Lite3', description: '6M params', group: 'timm-EfficientNet' },
  { id: 'timm-tf_efficientnet_lite4', name: 'timm EfficientNet-Lite4', description: '11M params', group: 'timm-EfficientNet' },
  // ── timm SK-ResNet ──
  { id: 'timm-skresnet18', name: 'timm SK-ResNet-18', description: '11M params, selective kernel', group: 'timm-SKNet' },
  { id: 'timm-skresnet34', name: 'timm SK-ResNet-34', description: '21M params', group: 'timm-SKNet' },
  { id: 'timm-skresnext50_32x4d', name: 'timm SK-ResNeXt-50', description: '23M params', group: 'timm-SKNet' },
  // ── MiT (Mix Vision Transformer) ──
  { id: 'mit_b0', name: 'MiT-B0', description: '3M params, SegFormer backbone, lightweight', group: 'MiT' },
  { id: 'mit_b1', name: 'MiT-B1', description: '13M params', group: 'MiT' },
  { id: 'mit_b2', name: 'MiT-B2', description: '24M params, balanced', group: 'MiT' },
  { id: 'mit_b3', name: 'MiT-B3', description: '44M params', group: 'MiT' },
  { id: 'mit_b4', name: 'MiT-B4', description: '60M params, high capacity', group: 'MiT' },
  { id: 'mit_b5', name: 'MiT-B5', description: '81M params, largest MiT', group: 'MiT' },
  // ── MobileOne ──
  { id: 'mobileone_s0', name: 'MobileOne-S0', description: '4M params, ultra-fast inference', group: 'MobileOne' },
  { id: 'mobileone_s1', name: 'MobileOne-S1', description: '3M params', group: 'MobileOne' },
  { id: 'mobileone_s2', name: 'MobileOne-S2', description: '5M params', group: 'MobileOne' },
  { id: 'mobileone_s3', name: 'MobileOne-S3', description: '8M params', group: 'MobileOne' },
  { id: 'mobileone_s4', name: 'MobileOne-S4', description: '12M params', group: 'MobileOne' },
] as const

/** Unique backbone group names for UI filtering */
export const BACKBONE_GROUPS: readonly string[] = [
  ...new Set(SEGMENTATION_BACKBONES.map(b => b.group))
] as unknown as readonly string[]

/** Default segmentation backbone */
export const DEFAULT_SEG_BACKBONE = 'resnet50'

/**
 * Check whether a segmentation backbone/encoder name refers to a Foundation Model.
 * Mirrors backend `is_fm_encoder()` logic in segmentors/__init__.py:
 * FM if it's a known FM extractor but NOT a traditional SMP encoder.
 */
export function isSegFmEncoder(encoderName: string | undefined): boolean {
  if (!encoderName) return false
  return (
    FEATURE_EXTRACTORS.some((e) => e.id === encoderName) &&
    !SEGMENTATION_BACKBONES.some((b) => b.id === encoderName)
  )
}

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
  { id: 'MCCLoss', name: 'MCC Loss', description: 'Matthews Correlation Coefficient loss' },
] as const

const SUPPORTED_SEGMENTATION_LOSS_NAMES = new Set(SEGMENTATION_LOSSES.map((loss) => loss.id))

const normalizeSegmentationLossToken = (name: string): string => (
  name.trim().replace(/[\s_-]+/g, '').toLowerCase()
)

const SEGMENTATION_LOSS_NAME_BY_KEY: Readonly<Record<string, string>> = Object.freeze({
  ...Object.fromEntries(SEGMENTATION_LOSSES.map((loss) => [normalizeSegmentationLossToken(loss.id), loss.id])),
  softbcewithlogitsloss: 'BCE',
  binarycrossentropy: 'BCE',
  binarycrossentropyloss: 'BCE',
  bcewithlogitsloss: 'BCE',
})

export function normalizeSegmentationLossName(name: string): string {
  return SEGMENTATION_LOSS_NAME_BY_KEY[normalizeSegmentationLossToken(name)] ?? name
}

export function normalizeSegmentationLossConfig(
  lossNames?: string[],
  lossWeights?: number[]
): { lossNames: string[], lossWeights: number[] } {
  const names = Array.isArray(lossNames) ? lossNames : []
  if (names.length === 0) {
    return {
      lossNames: [...DEFAULT_SEG_LOSS_NAMES],
      lossWeights: [...DEFAULT_SEG_LOSS_WEIGHTS],
    }
  }

  const hasAlignedWeights = Array.isArray(lossWeights) && lossWeights.length === names.length
  const mergedWeights = new Map<string, number>()
  const normalizedNames: string[] = []

  names.forEach((rawName, index) => {
    const normalizedName = normalizeSegmentationLossName(rawName)
    if (!SUPPORTED_SEGMENTATION_LOSS_NAMES.has(normalizedName)) {
      return
    }

    if (!mergedWeights.has(normalizedName)) {
      normalizedNames.push(normalizedName)
      mergedWeights.set(normalizedName, 0)
    }

    if (hasAlignedWeights) {
      const rawWeight = Number(lossWeights?.[index])
      const safeWeight = Number.isFinite(rawWeight) && rawWeight > 0 ? rawWeight : 0
      mergedWeights.set(normalizedName, (mergedWeights.get(normalizedName) ?? 0) + safeWeight)
    }
  })

  if (normalizedNames.length === 0) {
    return {
      lossNames: [...DEFAULT_SEG_LOSS_NAMES],
      lossWeights: [...DEFAULT_SEG_LOSS_WEIGHTS],
    }
  }

  let normalizedWeights = hasAlignedWeights
    ? normalizedNames.map((name) => mergedWeights.get(name) ?? 0)
    : normalizedNames.map(() => 1 / normalizedNames.length)

  const totalWeight = normalizedWeights.reduce((sum, weight) => sum + weight, 0)
  normalizedWeights = totalWeight > 0
    ? normalizedWeights.map((weight) => weight / totalWeight)
    : normalizedNames.map(() => 1 / normalizedNames.length)

  return { lossNames: normalizedNames, lossWeights: normalizedWeights }
}

/** Default segmentation loss configuration */
export const DEFAULT_SEG_LOSS_NAMES = ['DiceLoss']
export const DEFAULT_SEG_LOSS_WEIGHTS = [1.0]

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
 * Batch size is kept conservative for common single-GPU RTX 3090 (24GB) training.
 */
export const SEG_TRAINING_DEFAULTS: SegTrainingDefaults = {
  learningRate: 0.0001,
  epochs: 50,
  batchSize: 8,
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

