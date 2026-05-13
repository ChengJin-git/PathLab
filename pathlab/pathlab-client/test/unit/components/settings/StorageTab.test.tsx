import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StorageTab } from '@renderer/components/settings/StorageTab'
import { scanDirectory, startBatchImportTask } from '@renderer/api/storage'

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({ addMigrationTask: vi.fn() }),
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
    batchNewDatasetNameRef,
  }: any) => (
    <div>
      <input aria-label="scan-path" value={batchScanPath} onChange={(event) => setBatchScanPath(event.target.value)} />
      <input aria-label="dataset-name" ref={batchNewDatasetNameRef} defaultValue="Patch Dataset" />
      <button type="button" onClick={handleBatchScan}>scan</button>
      {batchScanResult && <button type="button" onClick={handleBatchRegister}>register</button>}
    </div>
  ),
}))

vi.mock('@renderer/components/settings/MigrationModal', () => ({
  MigrationModal: () => null,
}))

const mockScanDirectory = vi.mocked(scanDirectory)
const mockStartBatchImportTask = vi.mocked(startBatchImportTask)

describe('StorageTab batch registration', () => {
  beforeEach(() => {
    mockScanDirectory.mockReset()
    mockStartBatchImportTask.mockReset()
  })

  it('submits patch-only classification scans as patch_classification without expanding all paths', async () => {
    mockScanDirectory.mockResolvedValueOnce({
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
      page: 1,
      page_size: 100,
      total_pages: 2500,
    })
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
})
