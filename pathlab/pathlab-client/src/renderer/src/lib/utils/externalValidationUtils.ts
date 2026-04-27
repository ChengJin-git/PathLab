/**
 * External Validation Utilities
 * 
 * Shared logic for filtering compatible models and datasets for external validation.
 * Used by both ResultsViewerPage and AnalysisConfigCard to ensure consistent validation rules.
 */

import type { TrainedModel } from '../../api/training'
import type { ValidationDataset } from '../../api/analysis'
import { isSegmentationTask as isCanonicalSegmentationTask, isSurvivalTask as isCanonicalSurvivalTask } from '../../constants/training'

/**
 * Feature extractor name → embedding dimension mapping.
 * Used for WSI-level external validation compatibility check.
 */
export const EXTRACTOR_EMBED_DIM: Record<string, number> = {
  resnet50: 2048,
  vit_l_16: 1024,
  conch: 512,
  uni: 1024,
  uni2: 1536,
  virchow: 1280,
  virchow2: 1280,
  plip: 512,
  phikon: 1024,
  phikon2: 1024,
  patho_clip: 512,
  openmidnight: 1536,
  conch15: 512,
  'H-Optimus-1': 1536,
  'H-Optimus-0': 1536,
  mSTAR: 1024,
  GPFM: 1024,
  SmartCCS: 1024,
  SmartCyto: 768,
  CytoFM: 1024,
  KRONOS: 384,
}

/**
 * Helper to determine if a task type is survival
 */
export function isSurvivalTask(taskType: string | undefined): boolean {
  return isCanonicalSurvivalTask(taskType)
}

export function isSegmentationTask(taskType: string | undefined): boolean {
  return isCanonicalSegmentationTask(taskType)
}

/**
 * Interface for training task metadata (minimal fields needed for validation)
 */
export interface TrainingTaskMetadata {
  task_id: string
  task_type: string
  data_type: string  // "wsi" or "patch"
  wsi_ids?: string[]
  classes?: string[] | null
  source_dataset_id?: string | null
  model_config?: Record<string, unknown> | null
}

function normalizeLabels(labels: string[] | null | undefined): string[] {
  const normalized = (labels || [])
    .map(label => label?.trim().toLowerCase())
    .filter((label): label is string => Boolean(label))
  return [...new Set(normalized)].sort()
}

function getSegmentationModelSpec(model: TrainedModel, modelTask: TrainingTaskMetadata) {
  const taskArchitectureValue = modelTask.model_config?.['architecture']
  const taskBackboneValue = modelTask.model_config?.['backbone']
  const taskArchitecture = typeof taskArchitectureValue === 'string'
    ? taskArchitectureValue.trim()
    : ''
  const taskBackbone = typeof taskBackboneValue === 'string'
    ? taskBackboneValue.trim()
    : ''
  const savedArchitecture = (model.aggregator || '').trim()
  const savedBackbone = (model.feature_extractor || '').trim()

  return {
    taskArchitecture,
    taskBackbone,
    savedArchitecture,
    savedBackbone,
    isComplete: !!taskArchitecture && !!taskBackbone && !!savedArchitecture && !!savedBackbone,
    isConsistent: !!taskArchitecture && !!taskBackbone && !!savedArchitecture && !!savedBackbone
      && taskArchitecture === savedArchitecture
      && taskBackbone === savedBackbone
  }
}

export function getDatasetCompatibilityError(
  model: TrainedModel,
  modelTask: TrainingTaskMetadata,
  dataset: ValidationDataset
): string | null {
  const modelDataType = modelTask.data_type || 'wsi'
  const modelIsSurvival = isSurvivalTask(modelTask.task_type)
  const modelIsSegmentation = isSegmentationTask(modelTask.task_type)
  const modelClasses = new Set(normalizeLabels(model.classes || []))
  const modelWsiIds = new Set(modelTask.wsi_ids || [])
  const modelExtractor = model.feature_extractor || ''
  const modelEmbedDim = EXTRACTOR_EMBED_DIM[modelExtractor] ?? 0

  if (dataset.data_type !== modelDataType) {
    return 'Data type mismatch between source model and target dataset.'
  }

  const datasetIsSurvival = isSurvivalTask(dataset.task_type)
  const datasetIsSegmentation = isSegmentationTask(dataset.task_type)
  if (modelIsSurvival !== datasetIsSurvival) {
    return 'Task type mismatch between source model and target dataset.'
  }
  if (modelIsSegmentation !== datasetIsSegmentation) {
    return 'Task type mismatch between source model and target dataset.'
  }

  if (modelIsSegmentation) {
    if (dataset.data_type !== 'patch') return 'Segmentation external validation only supports patch datasets.'
    if (dataset.aggregation_level !== 'file') return 'Segmentation external validation requires file-level datasets.'

    const segmentationSpec = getSegmentationModelSpec(model, modelTask)
    if (!segmentationSpec.isComplete) {
      return 'Segmentation source model is missing architecture/backbone metadata.'
    }
    if (!segmentationSpec.isConsistent) {
      return 'Segmentation source model architecture/backbone metadata is inconsistent.'
    }

    if (!modelTask.source_dataset_id) {
      return 'Cannot determine the source training dataset for this segmentation model.'
    }
    if (dataset.dataset_id === modelTask.source_dataset_id) {
      return 'Target dataset must be different from the source training dataset.'
    }

    const modelSegmentationLabels = normalizeLabels(modelTask.classes || model.classes || [])
    const datasetSegmentationLabels = normalizeLabels(dataset.segmentation_labels || [])
    if (modelSegmentationLabels.length === 0 || datasetSegmentationLabels.length === 0) {
      return 'Segmentation labels are missing on the source model or target dataset.'
    }
    if (modelSegmentationLabels.length !== datasetSegmentationLabels.length) {
      return 'Segmentation labels must exactly match between source model and target dataset.'
    }
    for (const label of modelSegmentationLabels) {
      if (!datasetSegmentationLabels.includes(label)) {
        return 'Segmentation labels must exactly match between source model and target dataset.'
      }
    }

    if (modelWsiIds.size > 0 && dataset.wsi_ids?.some(id => modelWsiIds.has(id))) {
      return 'Target dataset overlaps with the source model training data.'
    }

    return null
  }

  if (!modelIsSurvival) {
    const dsLabels = new Set(normalizeLabels(dataset.distinct_labels || []))
    if (modelClasses.size !== dsLabels.size) {
      return 'Label sets must exactly match between source model and target dataset.'
    }
    for (const cls of modelClasses) {
      if (!dsLabels.has(cls)) {
        return 'Label sets must exactly match between source model and target dataset.'
      }
    }
  }

  if (modelDataType === 'wsi' && modelExtractor && modelEmbedDim > 0) {
    const dsExtractors = dataset.available_feature_extractors || []
    if (dsExtractors.length > 0) {
      const hasSameDim = dsExtractors.some(e => (EXTRACTOR_EMBED_DIM[e] ?? 0) === modelEmbedDim)
      if (!hasSameDim) {
        return 'Feature extractor embedding dimensions do not match.'
      }
    }
  }

  if (modelWsiIds.size > 0 && dataset.wsi_ids?.some(id => modelWsiIds.has(id))) {
    return 'Target dataset overlaps with the source model training data.'
  }

  return null
}

/**
 * Filter datasets compatible with a given model for external validation.
 * 
 * Compatibility rules:
 * 1. data_type must match (WSI vs patch)
 * 2. task_type must match (survival vs classification)
 * 3. For classification: label sets must match exactly
 * 4. For segmentation: source/target datasets must differ, architecture metadata must be consistent,
 *    segmentation labels must match exactly, and WSIs must not overlap
 * 5. For WSI: feature extractor embedding dimensions must match
 * 6. No WSI overlap with training data (data leakage prevention)
 * 
 * @param model - The trained model to validate against
 * @param modelTask - The training task metadata for the model
 * @param datasets - List of all available validation datasets
 * @returns Filtered list of compatible datasets
 */
export function filterCompatibleDatasets(
  model: TrainedModel,
  modelTask: TrainingTaskMetadata,
  datasets: ValidationDataset[]
): ValidationDataset[] {
  return datasets.filter(dataset => getDatasetCompatibilityError(model, modelTask, dataset) === null)
}

/**
 * Check if a specific dataset is compatible with a model.
 * 
 * @param model - The trained model
 * @param modelTask - The training task metadata for the model
 * @param dataset - The dataset to check
 * @returns true if compatible, false otherwise
 */
export function isDatasetCompatible(
  model: TrainedModel,
  modelTask: TrainingTaskMetadata,
  dataset: ValidationDataset
): boolean {
  return getDatasetCompatibilityError(model, modelTask, dataset) === null
}
