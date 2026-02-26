/**
 * External Validation Utilities
 * 
 * Shared logic for filtering compatible models and datasets for external validation.
 * Used by both ResultsViewerPage and AnalysisConfigCard to ensure consistent validation rules.
 */

import { TrainedModel, ValidationDataset } from '../api'

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
}

/**
 * Helper to determine if a task type is survival
 */
export function isSurvivalTask(taskType: string | undefined): boolean {
  return taskType === 'survival' || taskType === 'wsi_survival' || taskType === 'patch_survival'
}

export function isSegmentationTask(taskType: string | undefined): boolean {
  return taskType === 'segmentation' || taskType === 'patch_segmentation'
}

/**
 * Interface for training task metadata (minimal fields needed for validation)
 */
export interface TrainingTaskMetadata {
  task_id: string
  task_type: string
  data_type: string  // "wsi" or "patch"
  wsi_ids?: string[]
}

/**
 * Filter datasets compatible with a given model for external validation.
 * 
 * Compatibility rules:
 * 1. data_type must match (WSI vs patch)
 * 2. task_type must match (survival vs classification)
 * 3. For classification: label sets must match exactly
 * 4. For WSI: feature extractor embedding dimensions must match
 * 5. No WSI overlap with training data (data leakage prevention)
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
  const modelDataType = modelTask.data_type || 'wsi'
  const modelIsSurvival = isSurvivalTask(modelTask.task_type)
  const modelClasses = new Set(model.classes || [])
  const modelWsiIds = new Set(modelTask.wsi_ids || [])
  const modelExtractor = model.feature_extractor || ''
  const modelEmbedDim = EXTRACTOR_EMBED_DIM[modelExtractor] ?? 0

  return datasets.filter(ds => {
    // Rule 1: data_type must match
    if (ds.data_type !== modelDataType) return false

    // Rule 2: task_type must match (survival vs classification)
    const datasetIsSurvival = ds.task_type === 'survival'
    if (modelIsSurvival !== datasetIsSurvival) return false

    // Rule 3: For classification, require exact label name set match
    if (!modelIsSurvival) {
      const dsLabels = new Set(ds.distinct_labels || [])
      if (modelClasses.size !== dsLabels.size) return false
      for (const cls of modelClasses) {
        if (!dsLabels.has(cls)) return false
      }
    }

    // Rule 4: For WSI, require matching embed_dim (feature extractor compatibility)
    if (modelDataType === 'wsi' && modelExtractor && modelEmbedDim > 0) {
      const dsExtractors = ds.available_feature_extractors || []
      const hasSameDim = dsExtractors.some(e => (EXTRACTOR_EMBED_DIM[e] ?? 0) === modelEmbedDim)
      if (!hasSameDim) return false
    }

    // Rule 5: No WSI overlap with training data (data leakage prevention)
    if (modelWsiIds.size > 0 && ds.wsi_ids?.some(id => modelWsiIds.has(id))) return false

    return true
  })
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
  const compatible = filterCompatibleDatasets(model, modelTask, [dataset])
  return compatible.length > 0
}

