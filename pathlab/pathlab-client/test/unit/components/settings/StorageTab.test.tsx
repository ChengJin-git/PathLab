import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StorageTab } from '@renderer/components/settings/StorageTab'
import { cancelStorageTask, getStorageTaskStatus, scanDirectory, startBatchImportTask, startScanDirectoryTask } from '@renderer/api/storage'
import type { ScanDirectoryResponse, ScanDirectoryTaskResult, StorageTaskStatus } from '@renderer/api/storage'

const mockOpenPanel = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({ addMigrationTask: vi.fn(), openPanel: mockOpenPanel }),
}))

vi.mock('@renderer/api/wsi', () => ({
  fetchDatasets: vi.fn().mockResolvedValue({ items: [] }),
}))

vi.mock('@renderer/api/storage', async () => {
  const actual = await vi.importActual<typeof import('@renderer/api/storage')>('@renderer/api/storage')
  return {
    ...actual,
    getStorageStats: vi.fn().mockResolvedValue(null),
    getStorageConfig: vi.fn().mockResolvedValue({ uploads_dir: '/uploads', source: 'config' }),
    getExternalDatasetsCachedSync: vi.fn(() => null),
    scanDirectory: vi.fn(),
    startScanDirectoryTask: vi.fn(),
    getStorageTaskStatus: vi.fn(),
    cancelStorageTask: vi.fn(),
    startBatchImportTask: vi.fn(),
  }
})

vi.mock('@renderer/components/settings/storage', () => ({
  StorageStatsDisplay: () => null,
  OrphanedFilesCard: () => null,
  OrphanedRecordsCard: () => null,
  ExternalFilesHealthCheckCard: () => null,
  BatchRegisterCard: ({
    batchScanPath,
    setBatchScanPath,
    batchScanResult,
    handleBatchScan,
    handleBatchRegister,
    handleCancelBatchScan,
    batchNewDatasetNameRef,
    batchScanning,
    batchScanStage,
    canCancelBatchScan,
  }: any) => (
    <div>
      <input aria-label="scan-path" value={batchScanPath} onChange={(event) => setBatchScanPath(event.target.value)} />
      <input aria-label="dataset-name" ref={batchNewDatasetNameRef} defaultValue="Patch Dataset" />
      <button type="button" onClick={handleBatchScan}>scan</button>
      {batchScanResult && <button type="button" onClick={handleBatchRegister}>register</button>}
      {batchScanning && batchScanStage === 'initial' && (
        <button type="button" onClick={handleCancelBatchScan} disabled={!canCancelBatchScan}>cancel-scan</button>
      )}
    </div>
  ),
}))

vi.mock('@renderer/components/settings/MigrationModal', () => ({
  MigrationModal: () => null,
}))

const mockScanDirectory = vi.mocked(scanDirectory)
const mockStartScanDirectoryTask = vi.mocked(startScanDirectoryTask)
const mockGetStorageTaskStatus = vi.mocked(getStorageTaskStatus)
const mockCancelStorageTask = vi.mocked(cancelStorageTask)
const mockStartBatchImportTask = vi.mocked(startBatchImportTask)

const toScanTaskResult = (result: ScanDirectoryResponse): ScanDirectoryTaskResult => ({
  scan_id: result.scan_id,
  directory: result.directory,
  total_count: result.total_count,
  valid_count: result.valid_count,
  wsi_count: result.wsi_count,
  patch_count: result.patch_count,
  page_size: result.page_size,
  annotation_scan_enabled: result.annotation_scan_enabled ?? false,
})

const createStorageTaskStatus = (
  taskId: string,
  status: StorageTaskStatus['status'],
  results: StorageTaskStatus['results'] = null,
): StorageTaskStatus => ({
  task_id: taskId,
  user_id: 'user_1',
  task_type: 'scan_directory',
  status,
  progress: status === 'completed' ? 100 : 0,
  error_message: null,
  total_items: 0,
  processed_items: 0,
  success_count: 0,
  failed_count: 0,
  params: null,
  results,
  created_at: '2026-01-01T00:00:00Z',
  started_at: '2026-01-01T00:00:00Z',
  completed_at: status === 'completed' ? '2026-01-01T00:00:01Z' : null,
})

describe('StorageTab batch registration', () => {
  beforeEach(() => {
    mockScanDirectory.mockReset()
    mockStartScanDirectoryTask.mockReset()
    mockStartScanDirectoryTask.mockResolvedValue({ task_id: 'scan_default_1', message: 'started' })
    mockGetStorageTaskStatus.mockReset()
    mockGetStorageTaskStatus.mockResolvedValue(createStorageTaskStatus('scan_default_1', 'completed', {
      scan_id: 'scan_default_1',
      directory: '/patches',
      total_count: 0,
      valid_count: 0,
      wsi_count: 0,
      patch_count: 0,
      page_size: 100,
      annotation_scan_enabled: false,
    }))
    mockCancelStorageTask.mockReset()
    mockStartBatchImportTask.mockReset()
    mockOpenPanel.mockReset()
  })

  it('submits patch-only classification scans as patch_classification without expanding all paths', async () => {
    const scanResult: ScanDirectoryResponse = {
      scan_id: 'scan_patch_1',
      directory: '/patches',
      files: [
        {
          path: '/patches/a.png',
          filename: 'a.png',
          size: 100,
          extension: '.png',
          format_type: 'standard',
          data_type: 'patch',
          valid: true,
          validation_message: null,
        },
      ],
      total_count: 250000,
      valid_count: 250000,
      total_size: 1000000,
      wsi_count: 0,
      patch_count: 250000,
      annotation_scan_enabled: false,
      page: 1,
      page_size: 100,
      total_pages: 2500,
    }
    mockScanDirectory.mockResolvedValueOnce(scanResult)
    mockGetStorageTaskStatus.mockResolvedValueOnce(createStorageTaskStatus('scan_default_1', 'completed', toScanTaskResult(scanResult)))
    mockStartBatchImportTask.mockResolvedValueOnce({ task_id: 'import_1', message: 'started', total_files: 250000 })

    render(<StorageTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)

    await userEvent.type(screen.getByLabelText('scan-path'), '/patches')
    await userEvent.click(screen.getByRole('button', { name: 'scan' }))
    await screen.findByRole('button', { name: 'register' })
    await userEvent.click(screen.getByRole('button', { name: 'register' }))

    await waitFor(() => expect(mockStartBatchImportTask).toHaveBeenCalled())
    expect(mockStartBatchImportTask).toHaveBeenCalledWith(expect.objectContaining({
      scan_id: 'scan_patch_1',
      select_all_valid: true,
      task_type: 'patch_classification',
      aggregation_level: 'file',
      selected_paths: [],
      excluded_paths: [],
    }))
  })

  it('opens the notification center after submitting a batch import task', async () => {
    const scanResult: ScanDirectoryResponse = {
      scan_id: 'scan_patch_2',
      directory: '/patches',
      files: [
        {
          path: '/patches/a.png',
          filename: 'a.png',
          size: 100,
          extension: '.png',
          format_type: 'standard',
          data_type: 'patch',
          valid: true,
          validation_message: null,
        },
      ],
      total_count: 1,
      valid_count: 1,
      total_size: 100,
      wsi_count: 0,
      patch_count: 1,
      annotation_scan_enabled: false,
      page: 1,
      page_size: 100,
      total_pages: 1,
    }
    mockScanDirectory.mockResolvedValueOnce(scanResult)
    mockGetStorageTaskStatus.mockResolvedValueOnce(createStorageTaskStatus('scan_default_1', 'completed', toScanTaskResult(scanResult)))
    mockStartBatchImportTask.mockResolvedValueOnce({ task_id: 'import_2', message: 'started', total_files: 1 })

    render(<StorageTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)

    await userEvent.type(screen.getByLabelText('scan-path'), '/patches')
    await userEvent.click(screen.getByRole('button', { name: 'scan' }))
    await screen.findByRole('button', { name: 'register' })
    await userEvent.click(screen.getByRole('button', { name: 'register' }))

    await waitFor(() => expect(mockOpenPanel).toHaveBeenCalledTimes(1))
  })

  it('cancels an active directory scan when the settings tab unmounts', async () => {
    mockStartScanDirectoryTask.mockResolvedValueOnce({ task_id: 'scan_active_1', message: 'started' })
    mockGetStorageTaskStatus.mockResolvedValue(createStorageTaskStatus('scan_active_1', 'processing'))
    mockCancelStorageTask.mockResolvedValueOnce({ cancelled: true, message: 'cancelled' })

    const { unmount } = render(<StorageTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)

    await userEvent.type(screen.getByLabelText('scan-path'), '/patches')
    await userEvent.click(screen.getByRole('button', { name: 'scan' }))

    await waitFor(() => expect(mockStartScanDirectoryTask).toHaveBeenCalledWith('/patches', expect.any(Object)))
    unmount()

    await waitFor(() => expect(mockCancelStorageTask).toHaveBeenCalledWith('scan_active_1'))
  })

  it('cancels an active directory scan when the cancel button is clicked', async () => {
    mockStartScanDirectoryTask.mockResolvedValueOnce({ task_id: 'scan_active_2', message: 'started' })
    mockGetStorageTaskStatus.mockResolvedValue(createStorageTaskStatus('scan_active_2', 'processing'))
    mockCancelStorageTask.mockResolvedValueOnce({ cancelled: true, message: 'cancelled' })

    render(<StorageTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />)

    await userEvent.type(screen.getByLabelText('scan-path'), '/patches')
    await userEvent.click(screen.getByRole('button', { name: 'scan' }))

    await waitFor(() => expect(mockStartScanDirectoryTask).toHaveBeenCalledWith('/patches', expect.any(Object)))

    await userEvent.click(screen.getByRole('button', { name: 'cancel-scan' }))

    await waitFor(() => expect(mockCancelStorageTask).toHaveBeenCalledWith('scan_active_2'))
  })
})
