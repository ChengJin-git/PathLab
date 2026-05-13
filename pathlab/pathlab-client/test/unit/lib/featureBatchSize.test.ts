import { describe, expect, it } from 'vitest'

import {
  getFeatureBatchSizeForAvailableVram,
  resolveFeatureBatchSizeForSubmission,
} from '@renderer/lib/featureBatchSize'

describe('feature batch size submission defaults', () => {
  it('chooses a safe CONCH default for the observed 15.5GB free GPU window', () => {
    expect(getFeatureBatchSizeForAvailableVram('conch', 15524)).toBe(8)
  })

  it('keeps explicit non-default batch sizes unchanged', () => {
    const batchSize = resolveFeatureBatchSizeForSubmission({
      configuredBatchSize: 32,
      featureExtractor: 'conch',
      queueStatus: {
        max_concurrent: 1,
        gpu_count: 1,
        running_count: 0,
        pending_count: 0,
        queue_size: 0,
        running_task_ids: [],
        running_tasks: [],
        pending_task_ids: [],
        is_running: true,
        gpus: [{ index: 0, name: 'GPU', allocated_mb: 8600, free_mb: 15524, total_mb: 24124 }],
      },
    })

    expect(batchSize).toBe(32)
  })

  it('keeps an explicit default-sized batch unless the caller marks it as an unset UI default', () => {
    const queueStatus = {
      max_concurrent: 1,
      gpu_count: 1,
      running_count: 0,
      pending_count: 0,
      queue_size: 0,
      running_task_ids: [],
      running_tasks: [],
      pending_task_ids: [],
      is_running: true,
      gpus: [{ index: 0, name: 'GPU', allocated_mb: 8600, free_mb: 15524, total_mb: 24124 }],
    }

    expect(resolveFeatureBatchSizeForSubmission({
      configuredBatchSize: 64,
      featureExtractor: 'conch',
      queueStatus,
    })).toBe(64)

    expect(resolveFeatureBatchSizeForSubmission({
      configuredBatchSize: 64,
      featureExtractor: 'conch',
      queueStatus,
      treatDefaultAsUnset: true,
    })).toBe(8)
  })
})
