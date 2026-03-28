import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp, blobResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  fetchDatasetsForInference,
  startBatchInference,
  listBatchInferenceTasks,
  getBatchInferenceResults,
  getBatchInferenceSummary,
  exportBatchInferenceCsv,
  type InferenceDataset,
  type BatchInferenceTask,
  type BatchInferenceSummary,
} from '@renderer/api/batchInference'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_DATASET: InferenceDataset = {
  dataset_id: 'ds_unlabeled_1',
  name: 'TCGA Unlabeled',
  data_type: 'wsi',
  task_type: 'classification',
  aggregation_level: 'file',
  slide_count: 80,
}

const MOCK_TASK: BatchInferenceTask = {
  task_id: 'binfer_abc123',
  task_name: 'Lung Model → TCGA Unlabeled',
  status: 'completed',
  progress: 100,
  model_task_id: 'task_src_1',
  model_id: 'model_1',
  dataset_id: 'ds_unlabeled_1',
  model_task_type: 'classification',
  model_data_type: 'wsi',
  data_type: 'wsi',
  task_type: 'batch_inference',
  total_wsi: 80,
  results_count: 80,
  error: null,
  created_at: '2026-03-28T10:00:00Z',
  finished_at: '2026-03-28T10:05:00Z',
}

const MOCK_SUMMARY: BatchInferenceSummary = {
  task_id: 'binfer_abc123',
  task_name: 'Lung Model → TCGA Unlabeled',
  status: 'completed',
  task_type: 'classification',
  data_type: 'wsi',
  model_task_id: 'task_src_1',
  model_id: 'model_1',
  dataset_id: 'ds_unlabeled_1',
  total_slides: 80,
  processed_slides: 80,
  created_at: '2026-03-28T10:00:00Z',
  completed_at: '2026-03-28T10:05:00Z',
  class_distribution: { Tumor: 50, Normal: 30 },
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('fetchDatasetsForInference', () => {
  it('fetches from GET /results/datasets-for-inference', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_DATASET], total: 1 }))
    const result = await fetchDatasetsForInference()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/datasets-for-inference')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].dataset_id).toBe('ds_unlabeled_1')
  })

  it('appends unlabeled_only and task_type query params', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasetsForInference(true, 'classification')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('unlabeled_only=true')
    expect(String(url)).toContain('task_type=classification')
  })

  it('throws on API error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Unauthorized' }, 401))
    await expect(fetchDatasetsForInference()).rejects.toMatchObject({ status: 401 })
  })
})

describe('startBatchInference', () => {
  it('sends POST to /results/batch-inference', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'binfer_abc123', status: 'pending', message: 'ok' }))
    await startBatchInference({ model_task_id: 'task_1', model_id: 'model_1', dataset_id: 'ds_1' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/batch-inference')
    expect(opts?.method).toBe('POST')
  })

  it('includes model_task_id, model_id, dataset_id in body', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'binfer_abc123', status: 'pending', message: 'ok' }))
    await startBatchInference({ model_task_id: 'task_1', model_id: 'model_1', dataset_id: 'ds_1' })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.model_task_id).toBe('task_1')
    expect(body.model_id).toBe('model_1')
    expect(body.dataset_id).toBe('ds_1')
  })

  it('returns task_id and status', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'binfer_abc123', status: 'pending', message: 'submitted' }))
    const result = await startBatchInference({ model_task_id: 't', model_id: 'm', dataset_id: 'd' })
    expect(result.task_id).toBe('binfer_abc123')
    expect(result.status).toBe('pending')
  })

  it('throws 400 on incompatible model/dataset', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Task type mismatch' }, 400))
    await expect(
      startBatchInference({ model_task_id: 't', model_id: 'm', dataset_id: 'd' })
    ).rejects.toMatchObject({ status: 400 })
  })
})

describe('listBatchInferenceTasks', () => {
  it('fetches from GET /results/batch-inference/tasks', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_TASK], total: 1 }))
    const result = await listBatchInferenceTasks()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/batch-inference/tasks')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].task_id).toBe('binfer_abc123')
  })

  it('appends skip and limit query params', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await listBatchInferenceTasks(20, 10)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('skip=20')
    expect(String(url)).toContain('limit=10')
  })
})

describe('getBatchInferenceResults', () => {
  it('fetches from GET /results/batch-inference/:taskId/results', async () => {
    mockFetch.mockResolvedValueOnce(
      ok({ task_type: 'classification', data_type: 'wsi', items: [], total: 0, skip: 0, limit: 100 })
    )
    const result = await getBatchInferenceResults('binfer_abc123')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/batch-inference/binfer_abc123/results')
    expect(result.task_type).toBe('classification')
  })

  it('includes skip and limit in URL', async () => {
    mockFetch.mockResolvedValueOnce(
      ok({ task_type: 'classification', data_type: 'wsi', items: [], total: 0, skip: 10, limit: 50 })
    )
    await getBatchInferenceResults('binfer_abc123', 10, 50)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('skip=10')
    expect(String(url)).toContain('limit=50')
  })

  it('throws 404 for unknown task', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(getBatchInferenceResults('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})

describe('getBatchInferenceSummary', () => {
  it('fetches from GET /results/batch-inference/:taskId/summary', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_SUMMARY))
    const result = await getBatchInferenceSummary('binfer_abc123')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/batch-inference/binfer_abc123/summary')
    expect(result.task_id).toBe('binfer_abc123')
    expect(result.total_slides).toBe(80)
    expect(result.class_distribution).toEqual({ Tumor: 50, Normal: 30 })
  })

  it('throws 404 for unknown task', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(getBatchInferenceSummary('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})

describe('exportBatchInferenceCsv', () => {
  it('fetches from GET /results/batch-inference/:taskId/export-csv and triggers download', async () => {
    const origCreateObjectURL = URL.createObjectURL
    const origRevokeObjectURL = URL.revokeObjectURL
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()

    mockFetch.mockResolvedValueOnce(blobResp('wsi_id,pred\nwsi_1,Tumor', 'text/csv'))
    await exportBatchInferenceCsv('binfer_abc123')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/batch-inference/binfer_abc123/export-csv')

    URL.createObjectURL = origCreateObjectURL
    URL.revokeObjectURL = origRevokeObjectURL
  })
})
