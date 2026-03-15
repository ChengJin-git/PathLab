import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp, blobResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  startAsyncExport,
  getExportTaskStatus,
  downloadExportFile,
  type ExportTaskStatus,
} from '@renderer/api/export'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_EXPORT_TASK: ExportTaskStatus = {
  task_id: 'export_001',
  user_id: 'user_1',
  export_type: 'feedbacks',
  status: 'completed',
  progress: 100,
  error_message: null,
  file_format: 'csv',
  total_records: 500,
  filter_params: null,
  created_at: '2024-01-01T00:00:00Z',
  started_at: '2024-01-01T00:00:01Z',
  completed_at: '2024-01-01T00:00:05Z',
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('startAsyncExport', () => {
  it('sends POST to /admin/feedbacks/export-async with format param', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    await startAsyncExport('csv')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks/export-async')
    expect(String(url)).toContain('format=csv')
    expect(opts?.method).toBe('POST')
  })

  it('defaults to json format', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    await startAsyncExport()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('format=json')
  })

  it('appends date_from and date_to filters', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    await startAsyncExport('json', '2024-01-01', '2024-01-31')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('date_from=2024-01-01')
    expect(String(url)).toContain('date_to=2024-01-31')
  })

  it('appends feedback_type filter', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    await startAsyncExport('json', null, null, 'thumbs_up')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('feedback_type=thumbs_up')
  })

  it('appends helpfulness filter', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    await startAsyncExport('json', null, null, null, 'helpful')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('helpfulness=helpful')
  })

  it('returns task_id for polling', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'export_001', status: 'pending' }))
    const result = await startAsyncExport('csv')
    expect(result.task_id).toBe('export_001')
    expect(result.status).toBe('pending')
  })
})

describe('getExportTaskStatus', () => {
  it('fetches from GET /admin/feedbacks/export-async/:taskId', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_EXPORT_TASK))
    const result = await getExportTaskStatus('export_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks/export-async/export_001')
    expect(result.status).toBe('completed')
    expect(result.progress).toBe(100)
    expect(result.total_records).toBe(500)
  })

  it('reflects in-progress status', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_EXPORT_TASK, status: 'processing', progress: 50 }))
    const result = await getExportTaskStatus('export_001')
    expect(result.status).toBe('processing')
    expect(result.progress).toBe(50)
  })

  it('throws NOT_FOUND for unknown task', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(getExportTaskStatus('bad_id')).rejects.toMatchObject({ status: 404 })
  })
})

describe('downloadExportFile', () => {
  it('fetches blob from /admin/feedbacks/export-async/:taskId/download', async () => {
    mockFetch.mockResolvedValueOnce(blobResp('id,message_id\n1,42', 'text/csv'))
    const result = await downloadExportFile('export_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks/export-async/export_001/download')
    expect(result).toBeInstanceOf(Blob)
  })

  it('throws when export not ready', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Export not ready' }, 400))
    await expect(downloadExportFile('export_001')).rejects.toMatchObject({ status: 400 })
  })
})
