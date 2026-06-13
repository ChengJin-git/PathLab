import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  getTrainingTasks,
  getTrainingTask,
  createTrainingTask,
  deleteTrainingTask,
  updateTrainingTaskName,
  invalidateTrainingTasksCache,
  getTrainedModels,
  getTrainedModel,
  updateTrainedModel,
  deleteTrainedModel,
  fetchExtractors,
  type TrainingTaskConfig,
} from '@renderer/api/training'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_TASK = {
  task_id: 'task_001',
  task_name: 'BRCA Classification',
  task_type: 'classification',
  data_type: 'wsi',
  task_description: 'BRCA subtype classification',
  status: 'completed',
  progress: 100,
  error_message: null,
  preprocessing_config: null,
  model_config: null,
  classes: ['LUAD', 'LUSC'],
  source_dataset_id: 'ds_1',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-02T00:00:00Z',
  started_at: '2024-01-01T01:00:00Z',
  finished_at: '2024-01-02T00:00:00Z',
}

const MOCK_MODEL = {
  model_id: 'model_001',
  task_id: 'task_001',
  model_name: 'abmil_uni_classification',
  model_path: '/models/task_001/best.pth',
  classes: ['LUAD', 'LUSC'],
  feature_extractor: 'uni',
  aggregator: 'abmil',
  is_default: true,
  is_active: true,
  created_at: '2024-01-02T00:00:00Z',
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateTrainingTasksCache()
})

describe('getTrainingTasks', () => {
  it('fetches training tasks list', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      items: [MOCK_TASK],
      total: 1,
      page: 1,
      page_size: 20,
      stats: { total: 1, running: 0, completed: 1, failed: 0, cancelled: 0 },
    }))
    const result = await getTrainingTasks()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/training')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].task_id).toBe('task_001')
  })

  it('passes status_filter param', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks({ status_filter: 'completed' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('status_filter=completed')
  })

  it('passes search param', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks({ search: 'BRCA' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('search=BRCA')
  })

  it('passes sort_by param', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks({ sort_by: 'name' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('sort_by=name')
  })

  it('caches results and does not fetch twice for same params', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks()
    await getTrainingTasks()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh bypasses cache', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks({ forceRefresh: true })
    await getTrainingTasks({ forceRefresh: true })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('getTrainingTask', () => {
  it('fetches a single training task by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50, wsi_ids: [] }))
    const result = await getTrainingTask('task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/training/task_001')
    expect(result.task_id).toBe('task_001')
    expect(result.wsi_count).toBe(50)
  })

  it('throws ApiError with NOT_FOUND for unknown task', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Task not found' }, 404))
    await expect(getTrainingTask('bad_id')).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' })
  })
})

describe('createTrainingTask', () => {
  const baseConfig: TrainingTaskConfig = {
    task_name: 'Test Task',
    task_type: 'classification',
    data_type: 'wsi',
    task_description: 'Test',
    dataset_id: 'ds_1',
    preprocessing: {
      feature_extractor: 'uni',
      feature_batch_size: 64,
      use_gpu: true,
    },
    model: {
      aggregator: 'abmil',
      learning_rate: 1e-4,
      epochs: 50,
      optimizer: 'adam',
      batch_size: 32,
    },
  }

  it('sends POST request to /tasks/training', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50 }))
    await createTrainingTask(baseConfig)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/training')
    expect(opts?.method).toBe('POST')
  })

  it('includes HuggingFace token from localStorage in request body', async () => {
    localStorage.setItem('huggingface_token', 'hf_my_token')
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50 }))
    await createTrainingTask(baseConfig)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.huggingface_token).toBe('hf_my_token')
  })

  it('sends empty string for HuggingFace token when not set', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50 }))
    await createTrainingTask(baseConfig)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.huggingface_token).toBe('')
  })

  it('sends the full task configuration', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50 }))
    await createTrainingTask(baseConfig)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.task_name).toBe('Test Task')
    expect(body.preprocessing.feature_extractor).toBe('uni')
    expect(body.model.aggregator).toBe('abmil')
  })

  it('invalidates training tasks cache after creation', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks()
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_TASK, wsi_count: 50 }))
    await createTrainingTask(baseConfig)
    await getTrainingTasks()
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })
})

describe('deleteTrainingTask', () => {
  it('sends DELETE request to correct endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'deleted', task_id: 'task_001' }))
    await deleteTrainingTask('task_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/training/task_001')
    expect(opts?.method).toBe('DELETE')
  })

  it('includes mode param in DELETE request', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'deleted', task_id: 'task_001' }))
    await deleteTrainingTask('task_001', 'complete')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('mode=complete')
  })

  it('uses "standard" mode by default', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'deleted', task_id: 'task_001' }))
    await deleteTrainingTask('task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('mode=standard')
  })

  it('invalidates cache after deletion', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, page: 1, page_size: 20, stats: { total: 0, running: 0, completed: 0, failed: 0, cancelled: 0 } }))
    await getTrainingTasks()
    mockFetch.mockResolvedValueOnce(ok({ message: 'deleted', task_id: 'task_001' }))
    await deleteTrainingTask('task_001')
    await getTrainingTasks()
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })
})

describe('updateTrainingTaskName', () => {
  it('sends PATCH request with new task name', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_TASK))
    const result = await updateTrainingTaskName('task_001', 'New Task Name')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/training/task_001')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.task_name).toBe('New Task Name')
    expect(result.task_id).toBe('task_001')
  })
})

describe('getTrainedModels', () => {
  it('fetches trained models with pagination', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_MODEL], total: 1 }))
    const result = await getTrainedModels(0, 50)
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/models')
    expect(url).toContain('skip=0')
    expect(url).toContain('limit=50')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].model_id).toBe('model_001')
  })
})

describe('getTrainedModel', () => {
  it('fetches a single model by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_MODEL))
    const result = await getTrainedModel('model_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/models/model_001')
    expect(result.model_id).toBe('model_001')
  })
})

describe('updateTrainedModel', () => {
  it('sends PATCH request with model updates', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_MODEL, is_default: false, is_active: false }))
    const result = await updateTrainedModel('model_001', { is_default: false, is_active: false })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/models/model_001')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.is_default).toBe(false)
    expect(body.is_active).toBe(false)
    expect(result.is_default).toBe(false)
  })
})

describe('deleteTrainedModel', () => {
  it('sends DELETE request for model', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'deleted', model_id: 'model_001' }))
    const result = await deleteTrainedModel('model_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/models/model_001')
    expect(opts?.method).toBe('DELETE')
    expect(result.model_id).toBe('model_001')
  })
})

describe('fetchExtractors', () => {
  it('fetches available feature extractors', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      items: [
        { id: 'uni', name: 'UNI', description: 'Universal pathology foundation model', supports_spatial: true },
        { id: 'conch', name: 'CONCH', description: 'CONCH pathology model', supports_spatial: false },
      ],
    }))
    const result = await fetchExtractors()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/tasks/extractors')
    expect(result).toHaveLength(2)
    expect(result[0].id).toBe('uni')
    expect(result[1].id).toBe('conch')
  })
})
