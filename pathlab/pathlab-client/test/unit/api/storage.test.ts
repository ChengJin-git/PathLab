import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  getStorageConfig,
  updateStorageConfig,
  getMigrationStatus,
  startMigration,
  getDiskSpace,
  checkUploadSpace,
  getStorageStats,
  getWSIStorageInfo,
  getTrainingTaskStorageInfo,
  detectOrphanedFiles,
  cleanupOrphanedFiles,
  detectOrphanedRecords,
  cleanupOrphanedRecords,
  resetDerivedData,
  scanDirectory,
  startBatchImportTask,
  startDeleteExternalTask,
  getStorageTaskStatus,
  cancelStorageTask,
  startBatchUpdateMetadataTask,
  getExternalDatasets,
  invalidateExternalDatasetsCache,
  getExternalDatasetsCachedSync,
  type StorageConfig,
  type StorageTaskStatus,
} from '@renderer/api/storage'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_STORAGE_CONFIG: StorageConfig = {
  uploads_dir: '/data/uploads',
  source: 'config',
}

const MOCK_DISK_SPACE = {
  uploads_dir: '/data/uploads',
  total: 1099511627776,
  used: 549755813888,
  free: 549755813888,
  total_gb: 1024,
  used_gb: 512,
  free_gb: 512,
  usage_percent: 50,
  warning: false,
  critical: false,
}

const MOCK_STORAGE_TASK: StorageTaskStatus = {
  task_id: 'storage_task_001',
  user_id: 'user_1',
  task_type: 'batch_import',
  status: 'completed',
  progress: 100,
  error_message: null,
  total_items: 10,
  processed_items: 10,
  success_count: 10,
  failed_count: 0,
  params: null,
  results: null,
  created_at: '2024-01-01T00:00:00Z',
  started_at: '2024-01-01T00:00:01Z',
  completed_at: '2024-01-01T00:00:10Z',
}

beforeEach(() => {
  setAuthToken('test_token')
  invalidateExternalDatasetsCache()
})

describe('getStorageConfig', () => {
  it('fetches from GET /storage/config', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_STORAGE_CONFIG))
    const result = await getStorageConfig()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/config')
    expect(result.uploads_dir).toBe('/data/uploads')
  })
})

describe('updateStorageConfig', () => {
  it('sends POST to /storage/config with new uploads_dir', async () => {
    mockFetch.mockResolvedValueOnce(ok({ uploads_dir: '/new/path', restart_required: true }))
    const result = await updateStorageConfig('/new/path')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/config')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.uploads_dir).toBe('/new/path')
    expect(result.restart_required).toBe(true)
  })
})

describe('startMigration', () => {
  it('sends POST to /storage/migrate with target path', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Migration started' }))
    await startMigration('/new/storage')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/migrate')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.target_path).toBe('/new/storage')
    expect(body.delete_source).toBe(false)
  })

  it('passes delete_source flag', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Migration started' }))
    await startMigration('/new/storage', true)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.delete_source).toBe(true)
  })
})

describe('getMigrationStatus', () => {
  it('fetches from GET /storage/migration/status', async () => {
    mockFetch.mockResolvedValueOnce(ok({ status: 'idle', source: null, destination: null, progress: 0, error: null, delete_source: false }))
    const result = await getMigrationStatus()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/migration/status')
    expect(result.status).toBe('idle')
  })
})

describe('getDiskSpace', () => {
  it('fetches from GET /storage/disk-space', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_DISK_SPACE))
    const result = await getDiskSpace()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/disk-space')
    expect(result.free_gb).toBe(512)
    expect(result.warning).toBe(false)
  })
})

describe('checkUploadSpace', () => {
  it('sends required_bytes as query param to GET /storage/check-upload-space', async () => {
    mockFetch.mockResolvedValueOnce(ok({ can_upload: true, required_bytes: 1024, required_gb: 0.000001, free_bytes: 1073741824, free_gb: 1, remaining_after_upload_gb: 0.999999, message: 'OK' }))
    const result = await checkUploadSpace(1024)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/check-upload-space?required_bytes=1024')
    expect(result.can_upload).toBe(true)
  })
})

describe('getStorageStats', () => {
  it('fetches from GET /storage/stats without refresh', async () => {
    mockFetch.mockResolvedValueOnce(ok({ uploads_dir: '/data', total_size: 0, total_size_mb: 0, total_size_gb: 0, breakdown: {}, timestamp: '2024-01-01T00:00:00Z' }))
    await getStorageStats()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).not.toContain('refresh=true')
  })

  it('appends refresh=true when forced', async () => {
    mockFetch.mockResolvedValueOnce(ok({ uploads_dir: '/data', total_size: 0, total_size_mb: 0, total_size_gb: 0, breakdown: {}, timestamp: '2024-01-01T00:00:00Z' }))
    await getStorageStats(true)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('refresh=true')
  })
})

describe('getWSIStorageInfo', () => {
  it('fetches from GET /storage/wsi/:wsiId with URL encoding', async () => {
    mockFetch.mockResolvedValueOnce(ok({ wsi_id: 'wsi_001', wsi_file: { path: '/data/wsi_001.svs', size: 1024, exists: true }, coordinates: { path: '', size: 0, exists: false }, mask: { path: '', size: 0, exists: false }, ai_results: { path: '', size: 0, exists: false, file_count: 0 }, features: [], total_size: 1024, total_size_mb: 0.001, total_size_gb: 0.000001, total_files: 1 }))
    await getWSIStorageInfo('wsi_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/wsi/wsi_001')
  })
})

describe('getTrainingTaskStorageInfo', () => {
  it('fetches from GET /storage/training/:taskId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'task_001', ai_results: { path: '', size: 0, exists: false, file_count: 0, wsi_dir_count: 0 }, training_dir: { path: '', size: 0, exists: false, file_count: 0 }, training_logs: { path: '', size: 0, exists: false, file_count: 0 }, analysis_logs: { path: '', size: 0, exists: false, file_count: 0 }, models: [], total_size: 0, total_size_mb: 0, total_size_gb: 0, total_files: 0 }))
    await getTrainingTaskStorageInfo('task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/training/task_001')
  })
})

describe('detectOrphanedFiles', () => {
  it('fetches from GET /storage/orphaned', async () => {
    mockFetch.mockResolvedValueOnce(ok({ orphaned_wsi_files: [], orphaned_coordinates: [], orphaned_masks: [], orphaned_features_cache: [], orphaned_ai_results: [], orphaned_training_dirs: [], orphaned_logs: [], total_orphaned_size: 0, total_orphaned_count: 0, total_orphaned_file_count: 0, total_orphaned_dir_count: 0, total_orphaned_size_mb: 0, total_orphaned_size_gb: 0 }))
    const result = await detectOrphanedFiles()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/orphaned')
    expect(result.total_orphaned_count).toBe(0)
  })
})

describe('cleanupOrphanedFiles', () => {
  it('sends POST to /storage/orphaned/cleanup', async () => {
    mockFetch.mockResolvedValueOnce(ok({ deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: 'Nothing deleted' }))
    await cleanupOrphanedFiles()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/orphaned/cleanup')
    expect(opts?.method).toBe('POST')
  })

  it('includes categories in body when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ deleted_files: [], deleted_dirs: [], failed: [], total_size: 0, summary: 'Done' }))
    await cleanupOrphanedFiles(['orphaned_wsi_files', 'orphaned_coordinates'])
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.categories).toEqual(['orphaned_wsi_files', 'orphaned_coordinates'])
  })
})

describe('detectOrphanedRecords', () => {
  it('fetches from GET /storage/orphaned-records', async () => {
    mockFetch.mockResolvedValueOnce(ok({ orphaned_ai_tasks: [], orphaned_ai_results: [], orphaned_training_task_wsi: [], orphaned_training_logs: [], orphaned_trained_models: [], orphaned_message_feedbacks: [], orphaned_dataset_grants: [], total_orphaned_count: 0, summary: {} }))
    const result = await detectOrphanedRecords()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/orphaned-records')
    expect(result.total_orphaned_count).toBe(0)
  })
})

describe('cleanupOrphanedRecords', () => {
  it('sends POST to /storage/orphaned-records/cleanup', async () => {
    mockFetch.mockResolvedValueOnce(ok({ deleted_counts: {}, total_deleted: 0, summary: 'Nothing deleted' }))
    await cleanupOrphanedRecords()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/orphaned-records/cleanup')
    expect(opts?.method).toBe('POST')
  })
})

describe('resetDerivedData', () => {
  it('sends POST to /storage/reset-derived-data', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'reset_001', message: 'Reset started', total_items: 50 }))
    const result = await resetDerivedData()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/reset-derived-data')
    expect(opts?.method).toBe('POST')
    expect(result.task_id).toBe('reset_001')
  })
})

describe('scanDirectory', () => {
  it('sends POST to /storage/scan-directory', async () => {
    mockFetch.mockResolvedValueOnce(ok({ scan_id: 'scan_001', directory: '/data', files: [], total_count: 0, valid_count: 0, total_size: 0, wsi_count: 0, patch_count: 0, page: 1, page_size: 100, total_pages: 0 }))
    await scanDirectory('/data/slides')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/scan-directory')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.directory_path).toBe('/data/slides')
  })

  it('passes optional scan options', async () => {
    mockFetch.mockResolvedValueOnce(ok({ scan_id: 'scan_001', directory: '/data', files: [], total_count: 0, valid_count: 0, total_size: 0, wsi_count: 0, patch_count: 0, page: 2, page_size: 50, total_pages: 0 }))
    await scanDirectory('/data', { scanId: 'scan_001', taskType: 'classification', page: 2, pageSize: 50 })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.scan_id).toBe('scan_001')
    expect(body.task_type).toBe('classification')
    expect(body.page).toBe(2)
    expect(body.page_size).toBe(50)
  })
})

describe('startBatchImportTask', () => {
  it('sends POST to /storage/tasks/batch-import', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'import_001', message: 'Import started', total_files: 5 }))
    const result = await startBatchImportTask({ files: [], dataset_name: 'Test Dataset' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/tasks/batch-import')
    expect(opts?.method).toBe('POST')
    expect(result.task_id).toBe('import_001')
    expect(result.total_files).toBe(5)
  })
})

describe('startDeleteExternalTask', () => {
  it('sends POST to /storage/tasks/delete-external with wsi_ids', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'delete_001', message: 'Delete started', total_files: 3 }))
    await startDeleteExternalTask(['wsi_001', 'wsi_002', 'wsi_003'])
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/tasks/delete-external')
    const body = JSON.parse(opts?.body as string)
    expect(body.wsi_ids).toEqual(['wsi_001', 'wsi_002', 'wsi_003'])
  })
})

describe('getStorageTaskStatus', () => {
  it('fetches from GET /storage/tasks/:taskId', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_STORAGE_TASK))
    const result = await getStorageTaskStatus('storage_task_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/tasks/storage_task_001')
    expect(result.status).toBe('completed')
    expect(result.success_count).toBe(10)
  })
})

describe('cancelStorageTask', () => {
  it('sends DELETE to /storage/tasks/:taskId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ cancelled: true, message: 'Cancelled' }))
    const result = await cancelStorageTask('storage_task_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/tasks/storage_task_001')
    expect(opts?.method).toBe('DELETE')
    expect(result.cancelled).toBe(true)
  })
})

describe('startBatchUpdateMetadataTask', () => {
  it('sends POST to /storage/tasks/batch-update-metadata', async () => {
    mockFetch.mockResolvedValueOnce(ok({ task_id: 'meta_001', message: 'Update started', total_items: 3 }))
    const result = await startBatchUpdateMetadataTask({ wsi_ids: ['wsi_001', 'wsi_002', 'wsi_003'], label: 'LUAD' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/tasks/batch-update-metadata')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.wsi_ids).toHaveLength(3)
    expect(body.label).toBe('LUAD')
    expect(result.task_id).toBe('meta_001')
  })
})

describe('getExternalDatasets (persistent cache)', () => {
  it('fetches from GET /storage/external-datasets-summary', async () => {
    mockFetch.mockResolvedValueOnce(ok({ datasets: [{ dataset_id: 'ds_ext', dataset_name: 'External TCGA', total_files: 50 }], total: 1 }))
    const result = await getExternalDatasets()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/storage/external-datasets-summary')
    expect(result.datasets).toHaveLength(1)
    expect(result.datasets[0].dataset_name).toBe('External TCGA')
  })

  it('caches result and does not re-fetch within TTL', async () => {
    mockFetch.mockResolvedValue(ok({ datasets: [], total: 0 }))
    await getExternalDatasets()
    await getExternalDatasets()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh bypasses cache', async () => {
    mockFetch.mockResolvedValue(ok({ datasets: [], total: 0 }))
    await getExternalDatasets()
    await getExternalDatasets(true)
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('getExternalDatasetsCachedSync returns null before first fetch', () => {
    expect(getExternalDatasetsCachedSync()).toBeNull()
  })
})
