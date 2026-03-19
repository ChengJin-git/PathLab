import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  fetchDatasetsForValidation,
  startExternalValidation,
  runTaskAnalysis,
  getTaskQuickAnalysis,
  getAnalysisStatus,
  type InferenceTaskResponse,
  type AnalysisResponse,
  type QuickAnalysisResponse,
  type AnalysisStatusResponse,
} from '@renderer/api/analysis'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_VALIDATION_DATASET = {
  dataset_id: 'ds_ext',
  name: 'External TCGA',
  data_type: 'wsi',
  aggregation_level: 'file',
  task_type: 'classification',
  total_wsi_count: 120,
  total_case_count: 100,
  display_count: 120,
  distinct_label_count: 2,
  distinct_labels: ['LUAD', 'LUSC'],
  segmentation_labels: [],
  available_feature_extractors: ['uni', 'conch'],
  wsi_ids: ['wsi_001', 'wsi_002'],
}

const MOCK_INFERENCE_TASK: InferenceTaskResponse = {
  task_id: 'inf_001',
  status: 'queued',
  total_wsi: 120,
  message: 'Validation queued',
}

const MOCK_ANALYSIS_RESPONSE: AnalysisResponse = {
  task_id: 'task_001',
  analysis_id: 'analysis_001',
  summary: { accuracy: 0.88 },
  chart_paths: ['/charts/roc.png', '/charts/cm.png'],
}

const MOCK_QUICK_ANALYSIS: QuickAnalysisResponse = {
  task_id: 'task_001',
  analysis_id: 'analysis_001',
  has_analysis: true,
  task_type: 'classification',
  num_samples: 100,
  classes: ['LUAD', 'LUSC'],
  is_binary: true,
  metrics: { accuracy: 0.88, auc: 0.92, f1: 0.87 },
}

const MOCK_ANALYSIS_STATUS: AnalysisStatusResponse = {
  analysis_id: 'analysis_001',
  task_id: 'task_001',
  status: 'completed',
  progress: 100,
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('fetchDatasetsForValidation', () => {
  it('fetches from GET /results/datasets-for-validation', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_VALIDATION_DATASET], total: 1 }))
    const result = await fetchDatasetsForValidation()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/datasets-for-validation')
    expect(result.items).toHaveLength(1)
    expect(result.items[0].dataset_id).toBe('ds_ext')
  })

  it('throws on API error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(fetchDatasetsForValidation()).rejects.toMatchObject({ status: 404 })
  })
})

describe('startExternalValidation', () => {
  it('sends POST to /results/external-validation', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_INFERENCE_TASK))
    await startExternalValidation('model_001', 'ds_ext')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/external-validation')
    expect(opts?.method).toBe('POST')
  })

  it('includes model_id and dataset_id in body', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_INFERENCE_TASK))
    await startExternalValidation('model_001', 'ds_ext')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.model_id).toBe('model_001')
    expect(body.dataset_id).toBe('ds_ext')
  })

  it('includes optional metrics and charts params', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_INFERENCE_TASK))
    await startExternalValidation('model_001', 'ds_ext', ['accuracy', 'auc'], ['roc_curve'], true)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.metrics).toEqual(['accuracy', 'auc'])
    expect(body.charts).toEqual(['roc_curve'])
    expect(body.compute_bootstrap_ci).toBe(true)
  })

  it('includes rerun_from_task_id when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_INFERENCE_TASK))
    await startExternalValidation('model_001', 'ds_ext', undefined, undefined, undefined, 'task_old')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.rerun_from_task_id).toBe('task_old')
  })

  it('returns task_id and status', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_INFERENCE_TASK))
    const result = await startExternalValidation('model_001', 'ds_ext')
    expect(result.task_id).toBe('inf_001')
    expect(result.status).toBe('queued')
    expect(result.total_wsi).toBe(120)
  })
})

describe('runTaskAnalysis', () => {
  it('sends POST to /results/tasks/:taskId/analysis', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANALYSIS_RESPONSE))
    await runTaskAnalysis('task_001', ['accuracy', 'auc'], ['roc_curve', 'confusion_matrix'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/tasks/task_001/analysis')
    expect(opts?.method).toBe('POST')
  })

  it('includes metrics and charts in body', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANALYSIS_RESPONSE))
    await runTaskAnalysis('task_001', ['accuracy'], ['roc_curve'], 'Test run')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.metrics).toEqual(['accuracy'])
    expect(body.charts).toEqual(['roc_curve'])
    expect(body.description).toBe('Test run')
  })

  it('includes bootstrap_ci_metrics when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANALYSIS_RESPONSE))
    await runTaskAnalysis('task_001', ['accuracy', 'auc'], [], undefined, ['accuracy', 'auc'])
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.bootstrap_ci_metrics).toEqual(['accuracy', 'auc'])
  })

  it('returns analysis_id and chart_paths', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANALYSIS_RESPONSE))
    const result = await runTaskAnalysis('task_001', ['accuracy'], [])
    expect(result.analysis_id).toBe('analysis_001')
    expect(result.chart_paths).toHaveLength(2)
  })
})

describe('getTaskQuickAnalysis', () => {
  it('fetches from GET /results/tasks/:taskId/quick-analysis', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUICK_ANALYSIS))
    await getTaskQuickAnalysis('task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/tasks/task_001/quick-analysis')
  })

  it('appends metrics filter as query param', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUICK_ANALYSIS))
    await getTaskQuickAnalysis('task_001', { metrics: ['accuracy', 'auc'] })
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('metrics=accuracy%2Cauc')
  })

  it('appends charts filter as query param', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUICK_ANALYSIS))
    await getTaskQuickAnalysis('task_001', { charts: ['roc_curve'] })
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('charts=roc_curve')
  })

  it('appends bootstrap_ci_metrics when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUICK_ANALYSIS))
    await getTaskQuickAnalysis('task_001', { bootstrapCIMetrics: ['accuracy'] })
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('bootstrap_ci_metrics=accuracy')
  })

  it('returns metrics and class info', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_QUICK_ANALYSIS))
    const result = await getTaskQuickAnalysis('task_001')
    expect(result.has_analysis).toBe(true)
    expect(result.metrics?.accuracy).toBe(0.88)
    expect(result.classes).toEqual(['LUAD', 'LUSC'])
  })
})

describe('getAnalysisStatus', () => {
  it('fetches from GET /results/analysis/:analysisId/status', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_ANALYSIS_STATUS))
    const result = await getAnalysisStatus('analysis_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/results/analysis/analysis_001/status')
    expect(result.status).toBe('completed')
    expect(result.progress).toBe(100)
  })

  it('throws NOT_FOUND for unknown analysis', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(getAnalysisStatus('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})
