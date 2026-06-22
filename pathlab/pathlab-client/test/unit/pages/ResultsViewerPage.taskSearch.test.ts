import { describe, expect, it } from 'vitest'
import { filterTasksByQuery } from '../../../src/renderer/src/pages/ResultsViewerPage'

function makeTask(overrides: Partial<{
  task_id: string
  name: string
  task_type: string
  feature_extractor: string | null
  model_config: Record<string, unknown> | null
  split_config: {
    strategy?: 'random' | 'k_fold' | 'manual'
    n_splits?: number
    ratios?: { train: number; val: number; test: number }
    stratified?: boolean
  } | null
  is_kfold: boolean
}> = {}): Parameters<typeof filterTasksByQuery>[0][number] {
  return {
    task_id: 'task-1',
    name: 'Default Task',
    task_type: 'wsi_classification',
    feature_extractor: 'resnet50',
    model_config: null,
    split_config: null,
    is_kfold: false,
    ...overrides,
  } as Parameters<typeof filterTasksByQuery>[0][number]
}

describe('filterTasksByQuery', () => {
  it('returns all tasks when query is empty', () => {
    const tasks = [
      makeTask({ name: 'Alpha', task_type: 'wsi_classification' }),
      makeTask({ name: 'Beta', task_type: 'patch_classification' }),
    ]
    expect(filterTasksByQuery(tasks, '')).toEqual(tasks)
    expect(filterTasksByQuery(tasks, '   ')).toEqual(tasks)
  })

  it('filters by task name (case-insensitive)', () => {
    const tasks = [
      makeTask({ name: 'Alpha Task' }),
      makeTask({ name: 'Beta Task' }),
    ]
    expect(filterTasksByQuery(tasks, 'alpha')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'ALPHA')[0].name).toBe('Alpha Task')
  })

  it('filters by task type (case-insensitive)', () => {
    const tasks = [
      makeTask({ task_type: 'wsi_classification' }),
      makeTask({ task_type: 'patch_classification' }),
    ]
    expect(filterTasksByQuery(tasks, 'wsi')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'WSI')[0].task_type).toBe('wsi_classification')
  })

  it('filters by task id (case-insensitive)', () => {
    const tasks = [
      makeTask({ task_id: 'abc-123' }),
      makeTask({ task_id: 'def-456' }),
    ]
    expect(filterTasksByQuery(tasks, 'abc')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'ABC')[0].task_id).toBe('abc-123')
  })

  it('filters by feature_extractor (model display label)', () => {
    const tasks = [
      makeTask({ feature_extractor: 'resnet50' }),
      makeTask({ feature_extractor: 'vit_base' }),
    ]
    expect(filterTasksByQuery(tasks, 'resnet')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'RESNET')[0].feature_extractor).toBe('resnet50')
  })

  it('filters by segmentation backbone when task is segmentation', () => {
    const tasks = [
      makeTask({ task_type: 'wsi_segmentation', feature_extractor: null, model_config: { backbone: 'unet' } }),
      makeTask({ task_type: 'wsi_segmentation', feature_extractor: null, model_config: { backbone: 'deeplab' } }),
    ]
    expect(filterTasksByQuery(tasks, 'unet')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'UNET')[0].model_config).toEqual({ backbone: 'unet' })
  })

  it('filters by split label (random)', () => {
    const tasks = [
      makeTask({ split_config: { strategy: 'random' } }),
      makeTask({ split_config: { strategy: 'k_fold', n_splits: 5 } }),
    ]
    expect(filterTasksByQuery(tasks, 'random')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'RANDOM')[0].split_config?.strategy).toBe('random')
  })

  it('filters by split label (k-fold)', () => {
    const tasks = [
      makeTask({ split_config: { strategy: 'k_fold', n_splits: 5 } }),
      makeTask({ split_config: { strategy: 'random' } }),
    ]
    expect(filterTasksByQuery(tasks, '5-fold')).toHaveLength(1)
    expect(filterTasksByQuery(tasks, 'K-FOLD')).toHaveLength(1)
  })

  it('filters by split label (manual)', () => {
    const tasks = [
      makeTask({ split_config: { strategy: 'manual' } }),
      makeTask({ split_config: { strategy: 'random' } }),
    ]
    expect(filterTasksByQuery(tasks, 'manual')).toHaveLength(1)
  })

  it('returns empty array when nothing matches', () => {
    const tasks = [makeTask({ name: 'Alpha' })]
    expect(filterTasksByQuery(tasks, 'zzz')).toEqual([])
  })
})
