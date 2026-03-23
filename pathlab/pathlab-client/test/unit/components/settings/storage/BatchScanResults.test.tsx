import React, { createRef } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@radix-ui/react-tooltip'
import { BatchScanResults } from '@renderer/components/settings/storage/BatchScanResults'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const baseProps = {
  batchScanResult: {
    scan_id: 'scan_1',
    directory: '/data',
    files: [
      {
        path: '/data/a.svs',
        filename: 'a.svs',
        size: 1024,
        extension: '.svs',
        format_type: 'standard' as const,
        data_type: 'wsi' as const,
        valid: true,
        validation_message: null,
      },
    ],
    total_count: 1,
    valid_count: 1,
    total_size: 1024,
    wsi_count: 1,
    patch_count: 0,
    page: 1,
    page_size: 100,
    total_pages: 1,
  },
  batchSelectedCount: 1,
  batchDatasetMode: 'new' as const,
  setBatchDatasetMode: vi.fn(),
  batchSelectedDatasetId: '',
  setBatchSelectedDatasetId: vi.fn(),
  batchNewDatasetNameRef: createRef<HTMLInputElement>(),
  batchRegistering: false,
  batchImportTaskId: null,
  batchDatasets: [],
  batchTaskType: 'classification' as const,
  setBatchTaskType: vi.fn(),
  batchDataLevel: 'file' as const,
  setBatchDataLevel: vi.fn(),
  batchIsPublic: false,
  setBatchIsPublic: vi.fn(),
  handleBatchScanPageChange: vi.fn(async () => {}),
  isBatchFileSelected: vi.fn(() => true),
  handleBatchFileToggle: vi.fn(),
  handleBatchSelectAll: vi.fn(),
  handleBatchDeselectAll: vi.fn(),
  handleBatchRegister: vi.fn(async () => {}),
  formatFileSize: vi.fn(() => '1 KB'),
}

describe('BatchScanResults', () => {
  it('does not show collaboration visibility options for new dataset import', () => {
    render(<TooltipProvider><BatchScanResults {...baseProps} /></TooltipProvider>)

    expect(screen.queryByText('datasetPermission.openCollaboration')).not.toBeInTheDocument()
    expect(screen.queryByText('datasetPermission.closedCollaboration')).not.toBeInTheDocument()
  })
})
