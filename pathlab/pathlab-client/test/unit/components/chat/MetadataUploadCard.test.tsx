import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MetadataUploadCard } from '@renderer/components/chat/MetadataUploadCard'
import { readFileText } from '@renderer/lib/csvImporter'

const {
  downloadCSVTemplateMock,
  addMetadataUploadTaskMock,
} = vi.hoisted(() => ({
  downloadCSVTemplateMock: vi.fn(),
  addMetadataUploadTaskMock: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/api', () => ({
  downloadCSVTemplate: downloadCSVTemplateMock,
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({
    tasks: [],
    addMetadataUploadTask: addMetadataUploadTaskMock,
    getMetadataUploadResult: vi.fn(),
  }),
}))

vi.mock('@renderer/lib/csvImporter', () => ({
  readFileText: vi.fn(),
  xlsxToCSV: vi.fn(),
  parseCsvMetadata: vi.fn(),
}))

describe('MetadataUploadCard', () => {
  beforeEach(() => {
    downloadCSVTemplateMock.mockClear()
    downloadCSVTemplateMock.mockResolvedValue(undefined)
    addMetadataUploadTaskMock.mockReset()
  })

  it.each([
    ['wsi_classification', 'wsi_classification'],
    ['patch_classification', 'patch_classification'],
    ['wsi_survival', 'wsi_survival'],
    ['patch_segmentation', 'patch_segmentation'],
  ] as const)('downloads exact canonical template when upload_mode is %s', async (uploadMode, expectedTaskType) => {
    render(
      <MetadataUploadCard
        config={{ upload_mode: uploadMode as any, dataset_name: 'TestDataset' }}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.metadataUpload.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith(expectedTaskType)
    })
  })

  it('does not map legacy upload_mode for template download and calls onError', async () => {
    const onErrorMock = vi.fn()
    render(
      <MetadataUploadCard
        config={{ upload_mode: 'classification' as any, dataset_name: 'TestDataset' }}
        onError={onErrorMock}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.metadataUpload.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).not.toHaveBeenCalled()
      expect(onErrorMock).toHaveBeenCalled()
    })
  })

  it('does not call addMetadataUploadTask for legacy upload_mode', async () => {
    const csvContent = 'filename,label\n"folder/slide, copy.svs",train\n'
    const file = new File([csvContent], 'labels.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: vi.fn().mockResolvedValue(new TextEncoder().encode(csvContent).buffer),
    })
    vi.mocked(readFileText).mockResolvedValue(csvContent)

    const onErrorMock = vi.fn()
    render(
      <MetadataUploadCard
        config={{ upload_mode: 'classification' as any, dataset_name: 'TestDataset' }}
        onError={onErrorMock}
      />,
    )

    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(hiddenInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(addMetadataUploadTaskMock).not.toHaveBeenCalled()
      expect(onErrorMock).toHaveBeenCalled()
    })
  })

  it('defaults missing upload_mode to wsi_classification for template download', async () => {
    render(
      <MetadataUploadCard
        config={{ dataset_name: 'TestDataset' }}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.metadataUpload.downloadTemplate'))

    await waitFor(() => {
      expect(downloadCSVTemplateMock).toHaveBeenCalledWith('wsi_classification')
    })
  })

  it('defaults missing upload_mode to wsi_classification for metadata upload', async () => {
    const csvContent = 'filename,label\n"folder/slide, copy.svs",train\n'
    const file = new File([csvContent], 'labels.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: vi.fn().mockResolvedValue(new TextEncoder().encode(csvContent).buffer),
    })
    vi.mocked(readFileText).mockResolvedValue(csvContent)

    render(
      <MetadataUploadCard
        config={{ dataset_name: 'TestDataset' }}
      />,
    )

    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(hiddenInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(addMetadataUploadTaskMock).toHaveBeenCalledWith(
        expect.objectContaining({ uploadMode: 'wsi_classification' }),
      )
    })
  })

  it('accepts CSV rows with quoted commas in filename during validation', async () => {
    const csvContent = 'filename,label\n"folder/slide, copy.svs",train\n'
    const file = new File([csvContent], 'labels.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'arrayBuffer', {
      value: vi.fn().mockResolvedValue(new TextEncoder().encode(csvContent).buffer),
    })
    vi.mocked(readFileText).mockResolvedValue(csvContent)

    render(
      <MetadataUploadCard
        config={{ upload_mode: 'wsi_classification' as any, dataset_name: 'TestDataset' }}
      />,
    )

    const hiddenInput = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(hiddenInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(addMetadataUploadTaskMock).toHaveBeenCalled()
    })
  })
})
