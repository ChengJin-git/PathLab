import { describe, it, expect } from 'vitest'
import {
  isSurvivalTask,
  isSegmentationTask,
  EXTRACTOR_EMBED_DIM,
  getDatasetCompatibilityError,
  filterCompatibleDatasets,
  isDatasetCompatible,
} from '@renderer/lib/externalValidationUtils'
import type { TrainedModel } from '@renderer/api/training'
import type { ValidationDataset } from '@renderer/api/analysis'
import type { TrainingTaskMetadata } from '@renderer/lib/externalValidationUtils'

// ---------------------------------------------------------------------------
// isSurvivalTask
// ---------------------------------------------------------------------------

describe('isSurvivalTask', () => {
  it('returns false for "survival"', () => expect(isSurvivalTask('survival')).toBe(false))
  it('returns true for "wsi_survival"', () => expect(isSurvivalTask('wsi_survival')).toBe(true))
  it('returns false for "patch_survival"', () => expect(isSurvivalTask('patch_survival')).toBe(false))
  it('returns false for classification', () => expect(isSurvivalTask('classification')).toBe(false))
  it('returns false for undefined', () => expect(isSurvivalTask(undefined)).toBe(false))
  it('returns false for empty string', () => expect(isSurvivalTask('')).toBe(false))
})

// ---------------------------------------------------------------------------
// isSegmentationTask
// ---------------------------------------------------------------------------

describe('isSegmentationTask', () => {
  it('returns false for "segmentation"', () => expect(isSegmentationTask('segmentation')).toBe(false))
  it('returns true for "patch_segmentation"', () => expect(isSegmentationTask('patch_segmentation')).toBe(true))
  it('returns false for classification', () => expect(isSegmentationTask('classification')).toBe(false))
  it('returns false for undefined', () => expect(isSegmentationTask(undefined)).toBe(false))
})

// ---------------------------------------------------------------------------
// EXTRACTOR_EMBED_DIM
// ---------------------------------------------------------------------------

describe('EXTRACTOR_EMBED_DIM', () => {
  it('contains known extractors with correct dimensions', () => {
    expect(EXTRACTOR_EMBED_DIM['uni']).toBe(1024)
    expect(EXTRACTOR_EMBED_DIM['conch']).toBe(512)
    expect(EXTRACTOR_EMBED_DIM['virchow']).toBe(1280)
    expect(EXTRACTOR_EMBED_DIM['resnet50']).toBe(2048)
  })

  it('returns undefined for unknown extractors', () => {
    expect(EXTRACTOR_EMBED_DIM['unknown_extractor']).toBeUndefined()
  })

  it('has at least 10 entries', () => {
    expect(Object.keys(EXTRACTOR_EMBED_DIM).length).toBeGreaterThanOrEqual(10)
  })
})

// ---------------------------------------------------------------------------
// Helpers for getDatasetCompatibilityError tests
// ---------------------------------------------------------------------------

function makeModel(overrides: Partial<TrainedModel> = {}): TrainedModel {
  return {
    model_id: 'model_1',
    task_id: 'task_1',
    model_name: 'Test Model',
    model_path: '/path/to/model',
    classes: ['tumor', 'normal'],
    feature_extractor: 'uni',
    aggregator: 'abmil',
    is_default: false,
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeTask(overrides: Partial<TrainingTaskMetadata> = {}): TrainingTaskMetadata {
  return {
    task_id: 'task_1',
    task_type: 'wsi_classification',
    data_type: 'wsi',
    wsi_ids: ['wsi_a', 'wsi_b'],
    classes: ['tumor', 'normal'],
    source_dataset_id: 'ds_source',
    ...overrides,
  }
}

function makeDataset(overrides: Partial<ValidationDataset> = {}): ValidationDataset {
  return {
    dataset_id: 'ds_target',
    name: 'Target Dataset',
    data_type: 'wsi',
    aggregation_level: 'slide',
    task_type: 'wsi_classification',
    total_wsi_count: 50,
    total_case_count: 50,
    display_count: 50,
    distinct_label_count: 2,
    distinct_labels: ['tumor', 'normal'],
    segmentation_labels: [],
    available_feature_extractors: ['uni'],
    wsi_ids: ['wsi_c', 'wsi_d'],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// getDatasetCompatibilityError
// ---------------------------------------------------------------------------

describe('getDatasetCompatibilityError', () => {
  it('returns null for a fully compatible model and dataset', () => {
    const err = getDatasetCompatibilityError(makeModel(), makeTask(), makeDataset())
    expect(err).toBeNull()
  })

  it('returns error when data_type mismatches (wsi vs patch)', () => {
    const err = getDatasetCompatibilityError(
      makeModel(),
      makeTask({ data_type: 'wsi' }),
      makeDataset({ data_type: 'patch' })
    )
    expect(err).toContain('Data type mismatch')
  })

  it('returns error when task_type mismatches (classification vs survival)', () => {
    const err = getDatasetCompatibilityError(
      makeModel(),
      makeTask({ task_type: 'wsi_classification' }),
      makeDataset({ task_type: 'wsi_survival' })
    )
    expect(err).toContain('Task type mismatch')
  })

  it('returns error when classification label sets differ in size', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ classes: ['a', 'b', 'c'] }),
      makeTask({ classes: ['a', 'b', 'c'] }),
      makeDataset({ distinct_labels: ['a', 'b'] })
    )
    expect(err).toContain('Label sets must exactly match')
  })

  it('returns error when classification labels match in size but differ in content', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ classes: ['tumor', 'normal'] }),
      makeTask(),
      makeDataset({ distinct_labels: ['tumor', 'stroma'] })
    )
    expect(err).toContain('Label sets must exactly match')
  })

  it('returns null when label sets match with extra whitespace (trim-normalized)', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ classes: [' tumor ', ' normal '] }),
      makeTask({ classes: [' tumor ', ' normal '] }),
      makeDataset({ distinct_labels: ['tumor', 'normal'] })
    )
    expect(err).toBeNull()
  })

  it('returns error when WSI extractor embed dims do not match', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ feature_extractor: 'uni' }),
      makeTask(),
      makeDataset({ available_feature_extractors: ['conch'] })
    )
    expect(err).toContain('embedding dimensions do not match')
  })

  it('skips extractor check when dataset has no extractors listed', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ feature_extractor: 'uni' }),
      makeTask(),
      makeDataset({ available_feature_extractors: [] })
    )
    expect(err).toBeNull()
  })

  it('returns error when dataset WSIs overlap with training data', () => {
    const err = getDatasetCompatibilityError(
      makeModel(),
      makeTask({ wsi_ids: ['wsi_overlap'] }),
      makeDataset({ wsi_ids: ['wsi_overlap', 'wsi_new'] })
    )
    expect(err).toContain('overlaps with the source model training data')
  })

  it('returns null for survival tasks (no label check needed)', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ classes: [] }),
      makeTask({ task_type: 'wsi_survival', classes: [] }),
      makeDataset({ task_type: 'wsi_survival', distinct_labels: [], wsi_ids: [] })
    )
    expect(err).toBeNull()
  })

  it('returns error for segmentation with non-patch dataset', () => {
    const err = getDatasetCompatibilityError(
      makeModel({ aggregator: 'unet', feature_extractor: 'resnet' }),
      makeTask({
        task_type: 'patch_segmentation', data_type: 'patch',
        model_config: { architecture: 'unet', backbone: 'resnet' },
        classes: ['tumor'],
      }),
      makeDataset({
        data_type: 'patch', task_type: 'patch_segmentation',
        aggregation_level: 'slide',
        segmentation_labels: ['tumor'],
      })
    )
    expect(err).toContain('file-level datasets')
  })
})

// ---------------------------------------------------------------------------
// filterCompatibleDatasets / isDatasetCompatible
// ---------------------------------------------------------------------------

describe('filterCompatibleDatasets', () => {
  it('returns only datasets with no compatibility error', () => {
    const compatible = makeDataset({ dataset_id: 'good' })
    const incompatible = makeDataset({ dataset_id: 'bad', data_type: 'patch' })
    const result = filterCompatibleDatasets(makeModel(), makeTask(), [compatible, incompatible])
    expect(result).toHaveLength(1)
    expect(result[0].dataset_id).toBe('good')
  })

  it('returns empty array when all datasets are incompatible', () => {
    const result = filterCompatibleDatasets(
      makeModel(),
      makeTask(),
      [makeDataset({ data_type: 'patch' })]
    )
    expect(result).toHaveLength(0)
  })

  it('returns all datasets when all are compatible', () => {
    const datasets = [
      makeDataset({ dataset_id: 'ds1', wsi_ids: ['c'] }),
      makeDataset({ dataset_id: 'ds2', wsi_ids: ['d'] }),
    ]
    const result = filterCompatibleDatasets(makeModel(), makeTask(), datasets)
    expect(result).toHaveLength(2)
  })
})

describe('isDatasetCompatible', () => {
  it('returns true for compatible model/dataset pair', () => {
    expect(isDatasetCompatible(makeModel(), makeTask(), makeDataset())).toBe(true)
  })

  it('returns false for incompatible pair', () => {
    expect(
      isDatasetCompatible(makeModel(), makeTask(), makeDataset({ data_type: 'patch' }))
    ).toBe(false)
  })
})
