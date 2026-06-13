import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

vi.mock('@renderer/api/training', () => ({
  invalidateTrainingTasksCache: vi.fn(),
}))

import {
  getQueueStatus,
  getQueueConfig,
  updateQueueConfig,
  cancelQueueTask,
  type QueueStatus,
  type QueueConfig,
} from '@renderer/api/queue'
import { invalidateTrainingTasksCache } from '@renderer/api/training'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_QUEUE_STATUS: QueueStatus = {
  max_concurrent: 2,
  gpu_count: 2,
  running_count: 1,
  pending_count: 3,
  queue_size: 3,
  running_task_ids: ['task_001'],
  running_tasks: [{ task_id: 'task_001', gpu: 0 }],
  pending_task_ids: ['task_002', 'task_003', 'task_004'],
  is_running: true,
  gpus: [
    { index: 0, name: 'NVIDIA A100', allocated_mb: 8192, free_mb: 32768, total_mb: 40960 },
    { index: 1, name: 'NVIDIA A100', allocated_mb: 0, free_mb: 40960, total_mb: 40960 },
  ],
  vram_available: true,
  vram_free_mb: 32768,
  vram_status: 'ok',
}

const MOCK_QUEUE_CONFIG: QueueConfig = {
  max_concurrent: 2,
  task_timeout: 86400,
}

beforeEach(() => {
  setAuthToken('test_token')
  vi.mocked(invalidateTrainingTasksCache).mockReset()
})

describe('getQueueStatus', () => {
  it('fetches from GET /queue', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUEUE_STATUS))
    const result = await getQueueStatus()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/queue')
    expect(result.running_count).toBe(1)
    expect(result.pending_count).toBe(3)
    expect(result.gpus).toHaveLength(2)
  })

  it('throws on API error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Internal error' }, 500))
    await expect(getQueueStatus()).rejects.toMatchObject({ status: 500 })
  })
})

describe('getQueueConfig', () => {
  it('fetches from GET /queue/config', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUEUE_CONFIG))
    const result = await getQueueConfig()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/queue/config')
    expect(result.max_concurrent).toBe(2)
    expect(result.task_timeout).toBe(86400)
  })
})

describe('updateQueueConfig', () => {
  it('sends POST to /queue/config with partial config', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Updated', config: { ...MOCK_QUEUE_CONFIG, max_concurrent: 4 } }))
    await updateQueueConfig({ max_concurrent: 4 })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/queue/config')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.max_concurrent).toBe(4)
  })

  it('updates task_timeout', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Updated', config: { ...MOCK_QUEUE_CONFIG, task_timeout: 3600 } }))
    const result = await updateQueueConfig({ task_timeout: 3600 })
    expect(result.config.task_timeout).toBe(3600)
  })
})

describe('cancelQueueTask', () => {
  it('sends DELETE to /queue/:taskId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ cancelled: true, message: 'Task cancelled' }))
    await cancelQueueTask('task_002')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/queue/task_002')
    expect(opts?.method).toBe('DELETE')
  })

  it('invalidates training tasks cache when cancellation succeeds', async () => {
    mockFetch.mockResolvedValueOnce(ok({ cancelled: true, message: 'Task cancelled' }))
    await cancelQueueTask('task_002')
    expect(invalidateTrainingTasksCache).toHaveBeenCalledOnce()
  })

  it('does NOT invalidate cache when cancellation fails', async () => {
    mockFetch.mockResolvedValueOnce(ok({ cancelled: false, message: 'Task not found in queue' }))
    await cancelQueueTask('task_999')
    expect(invalidateTrainingTasksCache).not.toHaveBeenCalled()
  })

  it('throws NOT_FOUND for unknown task', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(cancelQueueTask('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})
