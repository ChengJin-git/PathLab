import { API_BASE } from '../config'
import { PERSISTENT_CACHE_TTL, createPersistentCache } from '../lib/cache'
import { apiFetch } from './client'

export interface TrainingExtractorOption {
  id: string
  name: string
  description: string
  supports_spatial?: boolean
}

export interface TrainingAggregatorOption {
  id: string
  name: string
  description: string
  detail: string
}

export interface TrainingSegmentationBackboneOption {
  id: string
  name: string
  description: string
  group: string
}

export interface TrainingSegmentationLossOption {
  id: string
  name: string
  description: string
}

export interface TrainingOptimizerOption {
  value: string
  label: string
}

export interface TrainingPreprocessingDefaults {
  a_t: number
  a_h: number
  max_n_holes: number
  sthresh: number
  mthresh: number
  close: number
  use_otsu: boolean
}

export interface TrainingOptionsResponse {
  feature_extractors: TrainingExtractorOption[]
  aggregators: TrainingAggregatorOption[]
  segmentation_architectures: TrainingExtractorOption[]
  segmentation_backbones: TrainingSegmentationBackboneOption[]
  segmentation_losses: TrainingSegmentationLossOption[]
  optimizers: TrainingOptimizerOption[]
  preprocessing_defaults?: TrainingPreprocessingDefaults
}

const trainingOptionsCache = createPersistentCache<TrainingOptionsResponse>(
  'training-options-cache',
  PERSISTENT_CACHE_TTL
)

export async function fetchTrainingOptions(forceRefresh = false): Promise<TrainingOptionsResponse> {
  return trainingOptionsCache.get(
    () => apiFetch<TrainingOptionsResponse>(
      `${API_BASE}/training/options`,
      undefined,
      'Failed to fetch training options'
    ),
    forceRefresh
  )
}
