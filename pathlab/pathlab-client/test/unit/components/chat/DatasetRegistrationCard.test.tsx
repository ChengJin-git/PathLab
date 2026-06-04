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

  it.each([
    ['wsi_classification'],
    ['patch_classification'],
    ['wsi_survival'],
    ['patch_segmentation'],
  ] as const)('downloads exact canonical %s template from canonical chat config', async (taskType) => {
    render(
      <DatasetRegistrationCard
        config={{ upload_mode: taskType }}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith(taskType)
    })
  })

  it('downloads exact canonical task_type for existing dataset without backward compat mapping', async () => {
    fetchDatasetsMock.mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-1',
          dataset_name: 'LegacyDS',
          task_type: 'wsi_classification',
          data_type: 'wsi',
          aggregation_level: 'file',
          file_count: 1,
          total_size: 1,
        },
      ],
    })

    render(
      <DatasetRegistrationCard
        config={{ upload_mode: 'classification', dataset_id: 'dataset-1' }}
      />,
    )

    await waitFor(() => {
      expect(fetchDatasetsMock).toHaveBeenCalled()
    })

    const selectButton = screen.getByRole('button', { name: /chatComponents\.datasetRegistration\.chooseDataset/ })
    fireEvent.click(selectButton)
    const option = await screen.findByText('chatComponents.datasetRegistration.datasetWithSource')
    fireEvent.click(option)

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith('wsi_classification')
    })
  })

  it('surfaces error when existing dataset has non-canonical task_type instead of mapping', async () => {
    const onErrorMock = vi.fn()
    fetchDatasetsMock.mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-legacy',
          dataset_name: 'LegacyDS',
          task_type: 'classification',
          data_type: 'wsi',
          aggregation_level: 'file',
          file_count: 1,
          total_size: 1,
        },
      ],
    })

    render(
      <DatasetRegistrationCard
        config={{ dataset_id: 'dataset-legacy' }}
        onError={onErrorMock}
      />,
    )

    await waitFor(() => {
      expect(fetchDatasetsMock).toHaveBeenCalled()
    })

    const selectButton = screen.getByRole('button', { name: /chatComponents\.datasetRegistration\.chooseDataset/ })
    fireEvent.click(selectButton)
    const option = await screen.findByText('chatComponents.datasetRegistration.datasetWithSource')
    fireEvent.click(option)

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(onErrorMock).toHaveBeenCalledWith('chatComponents.datasetRegistration.downloadTemplateFailed')
    })
    expect(downloadCSVTemplateMock).not.toHaveBeenCalled()
  })

  it.each([
    ['classification'],
    ['survival'],
    ['segmentation'],
  ] as const)('rejects explicit legacy upload_mode "%s" for template download and calls onError', async (legacyMode) => {
    const onErrorMock = vi.fn()
    render(
      <DatasetRegistrationCard
        config={{ upload_mode: legacyMode }}
        onError={onErrorMock}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(onErrorMock).toHaveBeenCalledWith('chatComponents.datasetRegistration.downloadTemplateFailed')
    })
    expect(downloadCSVTemplateMock).not.toHaveBeenCalled()
  })

  it('defaults missing upload_mode to wsi_classification for template download', async () => {
    render(
      <DatasetRegistrationCard
        config={{}}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.datasetRegistration.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith('wsi_classification')
    })
  })

  it('adds upload tasks with canonical task_type metadata from canonical chat config', async () => {
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
        config={{ upload_mode: 'patch_segmentation', dataset_name: 'Masks' }}
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
