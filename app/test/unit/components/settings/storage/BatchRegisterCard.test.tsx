import React, { createRef } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BatchRegisterCard } from '@renderer/components/settings/storage/BatchRegisterCard'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/components/settings/storage/BatchScanResults', () => ({
  BatchScanResults: () => <div data-testid="batch-scan-results">results</div>,
}))

vi.mock('@renderer/components/settings/storage/ExternalDatasetsTable', () => ({
  ExternalDatasetsTable: () => <div data-testid="external-datasets-table">external</div>,
}))

const baseProps = {
  batchScanPath: '/data/imports',
  setBatchScanPath: vi.fn(),
  batchScanResult: null,
  batchScanning: false,
  batchScanStage: 'idle' as const,
  batchScanError: null,
  batchSelectedCount: 0,
  batchDatasetMode: 'new' as const,
  setBatchDatasetMode: vi.fn(),
  batchSelectedDatasetId: '',
  setBatchSelectedDatasetId: vi.fn(),
  batchNewDatasetNameRef: createRef<HTMLInputElement>(),
  batchRegistering: false,
  batchImportTaskId: null,
  batchDatasets: [],
  batchTaskType: 'wsi_classification' as const,
  setBatchTaskType: vi.fn(),
  batchDataLevel: 'file' as const,
  setBatchDataLevel: vi.fn(),
  batchIsPublic: false,
  setBatchIsPublic: vi.fn(),
  handleSelectBatchScanDir: vi.fn(async () => {}),
  handleBatchScan: vi.fn(),
  handleBatchScanPageChange: vi.fn(),
  handleCancelBatchScan: vi.fn(),
  canCancelBatchScan: true,
  isBatchFileSelected: vi.fn(() => false),
  handleBatchFileToggle: vi.fn(),
  handleBatchSelectAll: vi.fn(),
  handleBatchDeselectAll: vi.fn(),
  handleBatchRegister: vi.fn(),
  formatFileSize: vi.fn(() => '1 KB'),
  hasSelectDirectoryApi: true,
  externalDatasets: [],
  loadingExternalDatasets: false,
  externalDatasetsLoaded: true,
  loadExternalDatasets: vi.fn(async () => {}),
  selectedExternalDatasets: new Set<string>(),
  unbindingDatasets: false,
  refreshExternalDatasets: vi.fn(),
  handleExternalDatasetToggle: vi.fn(),
  handleExternalDatasetSelectAll: vi.fn(),
  handleUnbindDataset: vi.fn(),
  handleUnbindSelectedDatasets: vi.fn(),
  navigate: vi.fn(),
}

describe('BatchRegisterCard', () => {
  it('shows an explicit scan progress banner while the initial directory scan is running', () => {
    render(
      <BatchRegisterCard
        {...baseProps}
        batchScanning={true}
        batchScanStage="initial"
      />,
    )

    expect(screen.getByText('settings.storage.scanInProgressTitle')).toBeInTheDocument()
    expect(screen.getByText('settings.storage.scanInProgressDescription')).toBeInTheDocument()
  })

  it('shows a refresh progress banner while scan results are being updated', () => {
    render(
      <BatchRegisterCard
        {...baseProps}
        batchScanning={true}
        batchScanStage="refresh"
        batchScanResult={{
          scan_id: 'scan_1',
          directory: '/data/imports',
          files: [],
          total_count: 25,
          valid_count: 20,
          total_size: 1024,
          wsi_count: 10,
          patch_count: 15,
          page: 1,
          page_size: 100,
          total_pages: 1,
        }}
      />,
    )

    expect(screen.getByText('settings.storage.refreshingScanResults')).toBeInTheDocument()
    expect(screen.getByTestId('batch-scan-results')).toBeInTheDocument()
  })

  it('shows a cancel scan button while the initial directory scan is running', () => {
    render(
      <BatchRegisterCard
        {...baseProps}
        batchScanning={true}
        batchScanStage="initial"
      />,
    )

    expect(screen.getByRole('button', { name: 'common.cancel' })).toBeInTheDocument()
  })

  it('disables the cancel scan button until the scan task can be cancelled', () => {
    render(
      <BatchRegisterCard
        {...baseProps}
        batchScanning={true}
        batchScanStage="initial"
        canCancelBatchScan={false}
      />,
    )

    expect(screen.getByRole('button', { name: 'common.cancel' })).toBeDisabled()
  })

  it('does not show a cancel scan button when not scanning', () => {
    render(<BatchRegisterCard {...baseProps} batchScanning={false} batchScanStage="idle" />)

    expect(screen.queryByRole('button', { name: 'common.cancel' })).not.toBeInTheDocument()
  })

  it('calls handleCancelBatchScan when the cancel button is clicked', async () => {
    const handleCancelBatchScan = vi.fn()
    render(
      <BatchRegisterCard
        {...baseProps}
        batchScanning={true}
        batchScanStage="initial"
        handleCancelBatchScan={handleCancelBatchScan}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
    expect(handleCancelBatchScan).toHaveBeenCalledTimes(1)
  })
})
