import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  PREPROCESSING_BASE: 'http://localhost:6101',
  AI_BASE: 'http://localhost:6102/api/ai',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

vi.mock('@renderer/api/heatmap', () => ({
  invalidateHeatmapAvailabilityCache: vi.fn(),
}))

import {
  checkDuplicateFilenames,
  fetchWSIList,
  fetchWSIIds,
  invalidateWSIListCache,
  fetchDatasets,
  fetchDatasetSummary,
  renameDataset,
  updateDatasetType,
  updateDatasetDataLevel,
  fetchWSIDetail,
  uploadWSIByPath,
  deleteWSI,
  updateWSIMetadata,
  uploadWSIByCSV,
  downloadCSVTemplate,
} from '@renderer/api/wsi'
import { invalidateHeatmapAvailabilityCache } from '@renderer/api/heatmap'
import * as clientApi from '@renderer/api/client'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_WSI_SUMMARY = {
  wsi_id: 'wsi_001',
  original_filename: 'slide.svs',
  dataset_id: 'ds_1',
  dataset_name: 'TCGA-BRCA',
  case_id: 'case_001',
  label: 'LUAD',
  file_extension: '.svs',
  age: 65,
  gender: 'F',
  source: null,
  event_time: null,
  event_status: null,
  split: 'train',
  file_size: 1024 * 1024 * 500,
  data_type: 'wsi' as const,
  created_at: '2024-01-01T00:00:00Z',
}

const MOCK_DATASET = {
  dataset_id: 'ds_1',
  dataset_name: 'TCGA-BRCA',
  user_id: 'user_1',
  file_count: 50,
  total_size: 1024 * 1024 * 1024 * 10,
  data_type: 'wsi' as const,
  task_type: 'wsi_classification' as const,
  aggregation_level: 'case' as const,
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateWSIListCache()
})

describe('checkDuplicateFilenames', () => {
  it('returns empty arrays without calling API when given an empty list', async () => {
    const result = await checkDuplicateFilenames([])
    expect(result).toEqual({ duplicates: [], new: [] })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('sends filename list to /wsi/check-duplicates', async () => {
    mockFetch.mockResolvedValueOnce(ok({ duplicates: ['slide1.svs'], new: ['slide2.svs'] }))
    const result = await checkDuplicateFilenames(['slide1.svs', 'slide2.svs'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/check-duplicates')
    expect(opts?.method).toBe('POST')
    expect(JSON.parse(opts?.body as string)).toEqual(['slide1.svs', 'slide2.svs'])
    expect(result.duplicates).toContain('slide1.svs')
    expect(result.new).toContain('slide2.svs')
  })
})

describe('fetchWSIList', () => {
  it('fetches all items when called without options (page_size=0)', async () => {
    const mockResponse = { items: [MOCK_WSI_SUMMARY], total: 1, total_cases: 1, page: 1, page_size: 0, has_multi_slide_cases: false }
    mockFetch.mockResolvedValueOnce(ok(mockResponse))
    const result = await fetchWSIList()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('page_size=0')
    expect(result.items).toHaveLength(1)
  })

  it('filters by dataset_id when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('dataset_id=ds_1')
  })

  it('sends pagination params when options provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, total_cases: 0, page: 2, page_size: 20, has_multi_slide_cases: false }))
    await fetchWSIList(undefined, undefined, { page: 2, page_size: 20 })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('page=2')
    expect(url).toContain('page_size=20')
  })

  it('includes search param when provided in options', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 20, has_multi_slide_cases: false }))
    await fetchWSIList(undefined, undefined, { page: 1, page_size: 20, search: 'brca' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('search=brca')
  })

  it('caches results and does not call fetch twice for the same params', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList()
    await fetchWSIList()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh bypasses cache', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList(undefined, undefined, { page: 1, page_size: 0, forceRefresh: true })
    await fetchWSIList(undefined, undefined, { page: 1, page_size: 0, forceRefresh: true })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('filters by data_type (patch)', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList(undefined, 'patch')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('data_type=patch')
  })
})

describe('fetchWSIIds', () => {
  it('fetches WSI IDs with correct params', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: ['wsi_001', 'wsi_002'], total: 2 }))
    const result = await fetchWSIIds('ds_1', 'wsi', 'brca')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/ids')
    expect(url).toContain('dataset_id=ds_1')
    expect(url).toContain('data_type=wsi')
    expect(url).toContain('search=brca')
    expect(result.items).toHaveLength(2)
  })
})

describe('invalidateWSIListCache', () => {
  it('clears cache so next fetch calls the API again', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList()
    invalidateWSIListCache()
    await fetchWSIList()
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('fetchDatasets', () => {
  it('fetches all datasets', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_DATASET], total: 1 }))
    const result = await fetchDatasets()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/datasets')
    expect(result.items).toHaveLength(1)
  })

  it('filters by task_type', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { task_type: 'wsi_survival' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=wsi_survival')
  })

  it('accepts canonical task_type filters', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { task_type: 'wsi_survival' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=wsi_survival')
  })

  it('filters by aggregation_level', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { aggregation_level: 'file' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('aggregation_level=file')
  })

  it('supports search filter', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { search: 'tcga' })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('search=tcga')
  })

  it('includes is_public=false filter for private datasets', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { is_public: false })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('is_public=false')
  })

  it('includes is_public=true filter for public datasets', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { is_public: true })
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('is_public=true')
  })

  it('does not include is_public when omitted', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, {})
    const [url] = mockFetch.mock.calls[0]
    expect(url).not.toContain('is_public=')
  })

  it('uses separate cache entries for private and public filters', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0 }))
    await fetchDatasets(undefined, { is_public: false })
    await fetchDatasets(undefined, { is_public: false })
    await fetchDatasets(undefined, { is_public: true })
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('caches results', async () => {
    mockFetch.mockResolvedValue(ok({ items: [], total: 0 }))
    await fetchDatasets()
    await fetchDatasets()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('fetches fresh dataset cards after list cache invalidation', async () => {
    const staleDataset = { ...MOCK_DATASET, dataset_id: 'ds_old', dataset_name: 'Old Dataset' }
    const freshDataset = { ...MOCK_DATASET, dataset_id: 'ds_new', dataset_name: 'New Dataset' }

    mockFetch
      .mockResolvedValueOnce(ok({ items: [staleDataset], total: 1 }))
      .mockResolvedValueOnce(ok({ items: [freshDataset], total: 1 }))

    const firstResult = await fetchDatasets(undefined, { page: 1, page_size: 8 })
    invalidateWSIListCache()
    const secondResult = await fetchDatasets(undefined, { page: 1, page_size: 8 })

    expect(firstResult.items[0].dataset_name).toBe('Old Dataset')
    expect(secondResult.items[0].dataset_name).toBe('New Dataset')
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })
})

describe('fetchDatasetSummary', () => {
  it('fetches a single dataset by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_DATASET))
    const result = await fetchDatasetSummary('ds_1')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/datasets/ds_1')
    expect(result.dataset_name).toBe('TCGA-BRCA')
  })
})

describe('renameDataset', () => {
  it('sends PUT request with new name', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'ok', dataset: { dataset_id: 'ds_1', name: 'New Name' } }))
    const result = await renameDataset('ds_1', 'New Name')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/datasets')
    expect(opts?.method).toBe('PUT')
    const body = JSON.parse(opts?.body as string)
    expect(body.dataset_id).toBe('ds_1')
    expect(body.new_name).toBe('New Name')
    expect(result.dataset.name).toBe('New Name')
  })

  it('invalidates WSI list cache after rename', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'ok', dataset: { dataset_id: 'ds_1', name: 'New Name' } }))
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList()
    await renameDataset('ds_1', 'New Name')
    await fetchWSIList()
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })
})

describe('updateDatasetType', () => {
  it('sends PUT request to correct endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'ok', dataset_id: 'ds_1', new_type: 'wsi_survival', updated_count: 50 }))
    const result = await updateDatasetType('ds_1', 'wsi_survival')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/datasets/ds_1/type')
    expect(opts?.method).toBe('PUT')
    const body = JSON.parse(opts?.body as string)
    expect(body.task_type).toBe('wsi_survival')
    expect(result.new_type).toBe('wsi_survival')
  })

  it('accepts canonical task_type values', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'ok', dataset_id: 'ds_1', new_type: 'wsi_survival', updated_count: 50 }))
    const result = await updateDatasetType('ds_1', 'wsi_survival')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.task_type).toBe('wsi_survival')
    expect(result.new_type).toBe('wsi_survival')
  })
})

describe('updateDatasetDataLevel', () => {
  it('sends PUT request to data-level endpoint', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'ok', dataset_id: 'ds_1', new_aggregation_level: 'file' }))
    const result = await updateDatasetDataLevel('ds_1', 'file')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/datasets/ds_1/data-level')
    expect(opts?.method).toBe('PUT')
    const body = JSON.parse(opts?.body as string)
    expect(body.aggregation_level).toBe('file')
    expect(result.new_aggregation_level).toBe('file')
  })
})

describe('fetchWSIDetail', () => {
  it('fetches WSI detail by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok({ wsi_id: 'wsi_001', meta: MOCK_WSI_SUMMARY, last_run: null }))
    const result = await fetchWSIDetail('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/wsi_001')
    expect(result.wsi_id).toBe('wsi_001')
    expect(result.last_run).toBeNull()
  })

  it('throws ApiError with NOT_FOUND code for missing WSI', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'WSI not found' }, 404))
    await expect(fetchWSIDetail('missing_id')).rejects.toMatchObject({
      status: 404,
      code: 'NOT_FOUND',
    })
  })
})

describe('uploadWSIByPath', () => {
  it('sends JSON body with WSI path and metadata', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'ok',
      wsi_id: 'wsi_new',
      wsi_path: '/data/slides/slide.svs',
      file_size: 1024 * 1024 * 100,
    }))
    const result = await uploadWSIByPath('/data/slides/slide.svs', {
      dataset_name: 'TCGA-BRCA',
      label: 'LUAD',
      case_id: 'case_001',
      task_type: 'wsi_classification',
    })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/upload/path')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.wsi_path).toBe('/data/slides/slide.svs')
    expect(body.dataset_name).toBe('TCGA-BRCA')
    expect(body.label).toBe('LUAD')
    expect(result.wsi_id).toBe('wsi_new')
  })
})

describe('deleteWSI', () => {
  it('sends DELETE request with mode param', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSI('wsi_001', 'standard')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/wsi_001')
    expect(url).toContain('mode=standard')
    expect(opts?.method).toBe('DELETE')
  })

  it('uses "standard" mode by default', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    await deleteWSI('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('mode=standard')
  })

  it('invalidates WSI list cache and heatmap cache after deletion', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'deleted',
      wsi_id: 'wsi_001',
      storage_cleanup: { deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: '' },
    }))
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList()
    await deleteWSI('wsi_001')
    await fetchWSIList()
    expect(invalidateHeatmapAvailabilityCache).toHaveBeenCalledWith('wsi_001')
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })
})

describe('updateWSIMetadata', () => {
  it('sends PATCH request with partial metadata', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'updated', wsi: MOCK_WSI_SUMMARY }))
    const result = await updateWSIMetadata('wsi_001', { label: 'LUSC', age: 70 })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/wsi_001')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.label).toBe('LUSC')
    expect(body.age).toBe(70)
    expect(result.wsi.wsi_id).toBe('wsi_001')
  })

  it('invalidates cache after metadata update', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'updated', wsi: MOCK_WSI_SUMMARY }))
    mockFetch.mockResolvedValue(ok({ items: [], total: 0, total_cases: 0, page: 1, page_size: 0, has_multi_slide_cases: false }))
    await fetchWSIList()
    await updateWSIMetadata('wsi_001', { label: 'LUSC' })
    await fetchWSIList()
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })

  it('supports survival analysis fields (event_time, event_status)', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'updated', wsi: MOCK_WSI_SUMMARY }))
    await updateWSIMetadata('wsi_001', { event_time: 36.5, event_status: 1 })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.event_time).toBe(36.5)
    expect(body.event_status).toBe(1)
  })
})

describe('uploadWSIByCSV', () => {
  it('sends FormData with CSV file to /wsi/upload/csv', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      message: 'done',
      total: 2,
      successful: 2,
      failed: 0,
      results: [],
    }))
    const file = new File(['wsi_path,label\n/data/s1.svs,LUAD'], 'batch.csv', { type: 'text/csv' })
    const result = await uploadWSIByCSV(file)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/wsi/upload/csv')
    expect(opts?.method).toBe('POST')
    expect(opts?.body).toBeInstanceOf(FormData)
    expect(result.successful).toBe(2)
  })
})

describe('downloadCSVTemplate', () => {
  it('fetches classification template by default', async () => {
    const origURL = globalThis.URL
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:url'), revokeObjectURL: vi.fn() })
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/csv' }),
      blob: () => Promise.resolve(new Blob(['wsi_path,label'])),
    } as unknown as Response)
    await downloadCSVTemplate()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=wsi_classification')
    vi.stubGlobal('URL', origURL)
    appendSpy.mockRestore()
    removeSpy.mockRestore()
  })

  it('fetches survival template when task_type is canonical wsi_survival', async () => {
    const origURL = globalThis.URL
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:url'), revokeObjectURL: vi.fn() })
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/csv' }),
      blob: () => Promise.resolve(new Blob(['wsi_path,event_time,event_status'])),
    } as unknown as Response)
    await downloadCSVTemplate('wsi_survival')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=wsi_survival')
    vi.stubGlobal('URL', origURL)
    appendSpy.mockRestore()
    removeSpy.mockRestore()
  })

  it('fetches segmentation template when task_type is canonical patch_segmentation', async () => {
    const origURL = globalThis.URL
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:url'), revokeObjectURL: vi.fn() })
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/csv' }),
      blob: () => Promise.resolve(new Blob(['wsi_path,label'])),
    } as unknown as Response)
    await downloadCSVTemplate('patch_segmentation')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=patch_segmentation')
    vi.stubGlobal('URL', origURL)
    appendSpy.mockRestore()
    removeSpy.mockRestore()
  })

  it('maps canonical survival task_type to survival template filename', async () => {
    const origURL = globalThis.URL
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:url'), revokeObjectURL: vi.fn() })
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n)
    const downloadSpy = vi.spyOn(clientApi, 'downloadBlobFile')
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/csv' }),
      blob: () => Promise.resolve(new Blob(['wsi_path,event_time,event_status'])),
    } as unknown as Response)

    await downloadCSVTemplate('wsi_survival')

    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('task_type=wsi_survival')
    expect(downloadSpy).toHaveBeenCalled()
    expect(downloadSpy.mock.calls[0][1]).toBe('wsi_survival_metadata_template.csv')
    vi.stubGlobal('URL', origURL)
    appendSpy.mockRestore()
    removeSpy.mockRestore()
    downloadSpy.mockRestore()
  })
})
