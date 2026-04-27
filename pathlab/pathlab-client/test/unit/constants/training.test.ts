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

  it('accepts canonical task ids without normalizing legacy families', () => {
    expect(toCanonicalTaskType('patch_segmentation', 'wsi')).toBe('patch_segmentation')
    expect(toCanonicalTaskType('classification', 'wsi')).toBeNull()
    expect(toCanonicalTaskType('survival', 'patch')).toBeNull()
    expect(toCanonicalTaskType('segmentation', 'wsi')).toBeNull()
    expect(toCanonicalTaskType('unknown', 'wsi')).toBeNull()
  })
})
