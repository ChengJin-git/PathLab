import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { DatasetRegistrationCard } from '@renderer/components/chat/DatasetRegistrationCard'

const {
  fetchDatasetsMock,
  downloadCSVTemplateMock,
  addUploadTaskMock,
  collectItemsFromDataTransferMock,
} = vi.hoisted(() => ({
  fetchDatasetsMock: vi.fn(),
  downloadCSVTemplateMock: vi.fn(),
  addUploadTaskMock: vi.fn(),
  collectItemsFromDataTransferMock: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/api', () => ({
  fetchDatasets: fetchDatasetsMock,
  downloadCSVTemplate: downloadCSVTemplateMock,
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({ addUploadTask: addUploadTaskMock }),
}))

vi.mock('@renderer/components/upload', () => ({
  collectItemsFromDataTransfer: collectItemsFromDataTransferMock,
}))

describe('DatasetRegistrationCard', () => {
  beforeEach(() => {
    fetchDatasetsMock.mockResolvedValue({ items: [] })
    downloadCSVTemplateMock.mockReset()
    addUploadTaskMock.mockReset()
    collectItemsFromDataTransferMock.mockReset()
  })

  it('shows collection progress while the shared collector is still traversing dropped files', async () => {
    let resolveCollection: ((result: {
      items: Array<{ key: string; name: string; file: File; type: 'standard' }>
      orphanFolders: []
      orphanDtFiles: Map<string, File[]>
      unsupportedFileNames: string[]
      jsonFiles: File[]
    }) => void) | undefined

    collectItemsFromDataTransferMock.mockImplementation((_dataTransfer: DataTransfer, options?: { onProgress?: (snapshot: unknown) => void }) => {
      options?.onProgress?.({
        phase: 'collecting',
        totalTopLevelEntries: 1,
        processedItems: 0,
        discoveredFiles: 12,
        discoveredDirectories: 2,
        currentDirectoryName: 'case-folder',
        completed: false,
      })

      return new Promise(resolve => {
        resolveCollection = resolve
      })
    })

    render(
      <DatasetRegistrationCard
        config={{ upload_mode: 'classification' }}
      />,
    )

    const dropTarget = screen.getByText('chatComponents.datasetRegistration.dragDropFolder').closest('div')
    expect(dropTarget).not.toBeNull()

    fireEvent.drop(dropTarget as HTMLElement, {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'case-folder' }) }] },
    })

    expect(await screen.findByText('chatComponents.datasetRegistration.collectionProgressTitle')).toBeInTheDocument()
    expect(screen.getByText('chatComponents.datasetRegistration.collectionProgressDescription')).toBeInTheDocument()

    await act(async () => {
      resolveCollection?.({
        items: [
          {
            key: 'case-a',
            name: 'case-a.svs',
            file: new File(['data'], 'case-a.svs'),
            type: 'standard',
          },
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: [],
      })
    })

    await waitFor(() => {
      expect(screen.queryByText('chatComponents.datasetRegistration.collectionProgressTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByText('chatComponents.datasetRegistration.filesSelected')).toBeInTheDocument()
  })

  it('downloads canonical segmentation templates from legacy chat config', async () => {
    render(
      <DatasetRegistrationCard
        config={{ upload_mode: 'segmentation' }}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith('patch_segmentation')
    })
  })

  it('adds upload tasks with canonical task_type metadata from legacy chat config', async () => {
    collectItemsFromDataTransferMock.mockResolvedValue({
      items: [
        {
          key: 'patch-a',
          name: 'patch-a.png',
          file: new File(['data'], 'patch-a.png'),
          type: 'standard',
        },
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: [new File(['{}'], 'patch-a.json')],
    })
    addUploadTaskMock.mockResolvedValue('upload_task_1')

    render(
      <DatasetRegistrationCard
        config={{ upload_mode: 'segmentation', dataset_name: 'Masks' }}
      />,
    )

    const dropTarget = screen.getByText('chatComponents.datasetRegistration.dragDropFolder').closest('div')
    expect(dropTarget).not.toBeNull()

    fireEvent.drop(dropTarget as HTMLElement, {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'patch-a.png' }) }], files: [new File(['data'], 'patch-a.png')] },
    })

    await screen.findByText('chatComponents.datasetRegistration.filesSelected')
    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.startRegistration'))

    await waitFor(() => {
      const files = addUploadTaskMock.mock.calls[0][0]
      expect(files[0].metadata.task_type).toBe('patch_segmentation')
    })
  })
})
