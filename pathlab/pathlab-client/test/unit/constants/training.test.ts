import { describe, expect, it } from 'vitest'
import {
  TASK_TYPES,
  getTaskMetadata,
  getTaskFamily,
  isClassificationTask,
  isSegmentationTask,
  isSurvivalTask,
  toCanonicalTaskType,
  type TaskType,
} from '@renderer/constants/training'

describe('canonical training task taxonomy', () => {
  it('exposes exactly four canonical training task types', () => {
    expect(TASK_TYPES.map(task => task.value)).toEqual([
      'wsi_classification',
      'patch_classification',
      'wsi_survival',
      'patch_segmentation',
    ])
  })

  it('keeps data type separate from aggregation level', () => {
    const task: TaskType = 'wsi_classification'
    expect(getTaskMetadata(task).dataType).toBe('wsi')
    expect(getTaskMetadata(task).allowedAggregationLevels).toContain('case')
  })

  it('classifies canonical task families without generic durable ids', () => {
    expect(isClassificationTask('wsi_classification')).toBe(true)
    expect(isClassificationTask('patch_classification')).toBe(true)
    expect(isSurvivalTask('wsi_survival')).toBe(true)
    expect(isSegmentationTask('patch_segmentation')).toBe(true)
    expect(isClassificationTask('classification')).toBe(false)
    expect(isSurvivalTask('survival')).toBe(false)
    expect(isSegmentationTask('segmentation')).toBe(false)
  })

  it('maps canonical dataset records to task families only', () => {
    expect(getTaskFamily('wsi_classification')).toBe('classification')
    expect(getTaskFamily('patch_classification')).toBe('classification')
    expect(getTaskFamily('wsi_survival')).toBe('survival')
    expect(getTaskFamily('patch_segmentation')).toBe('segmentation')
    expect(getTaskFamily('classification')).toBeNull()
    expect(getTaskFamily('survival')).toBeNull()
    expect(getTaskFamily('segmentation')).toBeNull()
    expect(getTaskFamily('unknown')).toBeNull()
  })

  it('accepts canonical task ids and normalizes supported legacy families', () => {
    expect(toCanonicalTaskType('patch_segmentation', 'patch')).toBe('patch_segmentation')
    expect(toCanonicalTaskType('wsi_classification', 'patch')).toBe('patch_classification')
    expect(toCanonicalTaskType('classification', 'wsi')).toBe('wsi_classification')
    expect(toCanonicalTaskType('classification', 'patch')).toBe('patch_classification')
    expect(toCanonicalTaskType('survival', 'wsi')).toBe('wsi_survival')
    expect(toCanonicalTaskType('segmentation', 'patch')).toBe('patch_segmentation')
    expect(toCanonicalTaskType('unknown', 'wsi')).toBeNull()
    expect(toCanonicalTaskType('survival', 'patch')).toBeNull()
    expect(toCanonicalTaskType('patch_segmentation', 'wsi')).toBeNull()
    expect(toCanonicalTaskType('segmentation', 'wsi')).toBeNull()
  })

  it('normalizes legacy classification family to patch_classification when data_type is patch', () => {
    expect(toCanonicalTaskType('classification', 'patch')).toBe('patch_classification')
  })

  it('normalizes legacy classification family to wsi_classification when data_type is wsi', () => {
    expect(toCanonicalTaskType('classification', 'wsi')).toBe('wsi_classification')
  })

  it('normalizes legacy survival family to wsi_survival when data_type is wsi', () => {
    expect(toCanonicalTaskType('survival', 'wsi')).toBe('wsi_survival')
  })

  it('normalizes legacy segmentation family to patch_segmentation when data_type is patch', () => {
    expect(toCanonicalTaskType('segmentation', 'patch')).toBe('patch_segmentation')
  })
})
