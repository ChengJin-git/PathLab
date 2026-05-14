import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UploadPage, { DUPLICATE_CHECK_BATCH_SIZE } from '../../../src/renderer/src/pages/UploadPage'
import * as apiModule from '../../../src/renderer/src/api'
import * as uploadModule from '../../../src/renderer/src/components/upload'
import * as authModule from '../../../src/renderer/src/contexts/AuthContext'
import * as backgroundTaskModule from '../../../src/renderer/src/contexts/BackgroundTaskContext'
import * as toastModule from '../../../src/renderer/src/contexts/ToastContext'

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, values?: Record<string, unknown>) => {
        if (!values) return key
        return `${key} ${Object.values(values).join(' / ')}`
      },
    }),
  }
})

describe('UploadPage', () => {
  const addUploadTaskMock = vi.fn()
  const toastErrorMock = vi.fn()
  const toastWarningMock = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    addUploadTaskMock.mockReset()
    toastErrorMock.mockReset()
    toastWarningMock.mockReset()

    vi.spyOn(backgroundTaskModule, 'useBackgroundTask').mockReturnValue({
      addUploadTask: addUploadTaskMock,
    } as unknown as ReturnType<typeof backgroundTaskModule.useBackgroundTask>)

    vi.spyOn(authModule, 'useAuth').mockReturnValue({
      user: { id: 'user-1' },
    } as unknown as ReturnType<typeof authModule.useAuth>)

    vi.spyOn(toastModule, 'useToast').mockReturnValue({
      error: toastErrorMock,
      warning: toastWarningMock,
    } as unknown as ReturnType<typeof toastModule.useToast>)

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({ items: [], total: 0 } as unknown as Awaited<ReturnType<typeof apiModule.fetchDatasets>>)
    vi.spyOn(apiModule, 'checkDuplicateFilenames').mockResolvedValue({ duplicates: [], new: [] })
    vi.spyOn(apiModule, 'downloadCSVTemplate').mockResolvedValue(undefined)
    vi.spyOn(apiModule, 'uploadDatasetSplits').mockResolvedValue({ message: '', updated_count: 0, auto_val_count: 0, not_found_count: 0, not_found_files: [] } as unknown as Awaited<ReturnType<typeof apiModule.uploadDatasetSplits>>)
    vi.spyOn(apiModule, 'updateDatasetSource').mockResolvedValue({ message: '', dataset_id: '', source: null, updated_count: 0 } as unknown as Awaited<ReturnType<typeof apiModule.updateDatasetSource>>)
  })

  it('shows collection progress while gathering files for both initial and follow-up folder drops', async () => {
    let resolveFirstCollection:
      | ((result: uploadModule.CollectionResult) => void)
      | undefined
    let resolveSecondCollection:
      | ((result: uploadModule.CollectionResult) => void)
      | undefined

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer')
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, options?: uploadModule.CollectItemsOptions) => {
        options?.onProgress?.({
          phase: 'collecting',
          totalTopLevelEntries: 1,
          processedItems: 0,
          discoveredFiles: 12,
          discoveredDirectories: 2,
          currentDirectoryName: 'case-folder',
          completed: false,
        })

        return await new Promise<uploadModule.CollectionResult>(resolve => {
          resolveFirstCollection = resolve
        })
      })
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, options?: uploadModule.CollectItemsOptions) => {
        options?.onProgress?.({
          phase: 'collecting',
          totalTopLevelEntries: 1,
          processedItems: 0,
          discoveredFiles: 4,
          discoveredDirectories: 1,
          currentDirectoryName: 'follow-up-folder',
          completed: false,
        })

        return await new Promise<uploadModule.CollectionResult>(resolve => {
          resolveSecondCollection = resolve
        })
      })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/register',
              state: {
                datasetName: 'Progress Dataset',
                uploadMode: 'classification',
              },
            },
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const emptyDropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const emptyDropZone = emptyDropZoneLabel.closest('div')
    expect(emptyDropZone).not.toBeNull()

    fireEvent.drop(emptyDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'case-folder' }) }] },
    })

    expect(await screen.findByText('uploadPage.collectionProgressTitle')).toBeInTheDocument()
    expect(screen.getByText('uploadPage.collectionProgressDescription')).toBeInTheDocument()

    await act(async () => {
      resolveFirstCollection?.({
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
      expect(screen.queryByText('uploadPage.collectionProgressTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByText('case-a.svs')).toBeInTheDocument()

    const table = screen.getByRole('table')
    const tableDropZone = table.parentElement
    expect(tableDropZone).not.toBeNull()

    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'follow-up-folder' }) }] },
    })

    expect(await screen.findByText('uploadPage.collectionProgressTitle')).toBeInTheDocument()

    await act(async () => {
      resolveSecondCollection?.({
        items: [
          {
            key: 'case-b',
            name: 'case-b.svs',
            file: new File(['data'], 'case-b.svs'),
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
      expect(screen.queryByText('uploadPage.collectionProgressTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByText('case-b.svs')).toBeInTheDocument()
    expect(container).toBeTruthy()
  })

  it('waits for upload task creation before warning and leaving the page', async () => {
    let resolveAddUploadTask: ((taskId: string) => void) | undefined
    addUploadTaskMock.mockReturnValueOnce(new Promise<string>(resolve => {
      resolveAddUploadTask = resolve
    }))

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/register',
              state: {
                datasetName: 'Upload Dataset',
                uploadMode: 'classification',
              },
            },
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const dropZone = dropZoneLabel.closest('div')
    expect(dropZone).not.toBeNull()

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items: [
        {
          key: 'case-a',
          name: 'case-a.png',
          file: new File(['data'], 'case-a.png', { type: 'image/png' }),
          type: 'standard',
        },
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: [],
    })

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'case-a.png' }) }] },
    })

    await screen.findByText('case-a.png')
    await userEvent.type(screen.getByPlaceholderText('uploadPage.enterLabel'), 'tumor')
    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

    await waitFor(() => expect(addUploadTaskMock).toHaveBeenCalledTimes(1))
    expect(toastWarningMock).not.toHaveBeenCalled()

    await act(async () => {
      resolveAddUploadTask?.('upload_task_1')
    })

    await waitFor(() => expect(toastWarningMock).toHaveBeenCalledWith('uploadPage.uploadingWarning', 8000))
  })

  it('batches duplicate filename checks into chunks no larger than the batch size', async () => {
    const checkDuplicateFilenamesSpy = vi.spyOn(apiModule, 'checkDuplicateFilenames')
    checkDuplicateFilenamesSpy.mockResolvedValue({ duplicates: [], new: [] })

    const batchSize = DUPLICATE_CHECK_BATCH_SIZE
    const totalFiles = batchSize * 2 + 2
    const items: uploadModule.LocalItem[] = []
    for (let i = 0; i < totalFiles; i++) {
      items.push({
        key: `key-${i}`,
        name: `file-${i}.png`,
        file: new File(['data'], `file-${i}.png`, { type: 'image/png' }),
        type: 'standard',
      })
    }

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items,
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: [],
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/register',
              state: {
                datasetName: 'Batch Dataset',
                uploadMode: 'classification',
              },
            },
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const dropZone = dropZoneLabel.closest('div')
    expect(dropZone).not.toBeNull()

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'dummy.png' }) }] },
    })

    await waitFor(() => expect(checkDuplicateFilenamesSpy).toHaveBeenCalled())

    const calls = checkDuplicateFilenamesSpy.mock.calls
    expect(calls.length).toBeGreaterThan(1)

    for (const [filenames] of calls) {
      expect((filenames as string[]).length).toBeLessThanOrEqual(batchSize)
    }

    const totalChecked = calls.reduce((sum, [filenames]) => sum + (filenames as string[]).length, 0)
    expect(totalChecked).toBe(totalFiles)
  })

  describe('missing-label navigation UX', () => {
    const renderUploadPage = async (items: uploadModule.LocalItem[]) => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      })

      vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
        items,
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: [],
      })

      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[
              {
                pathname: '/register',
                state: {
                  datasetName: 'Missing Label Dataset',
                  uploadMode: 'classification',
                },
              },
            ]}
          >
            <UploadPage />
          </MemoryRouter>
        </QueryClientProvider>,
      )

      const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
      const dropZone = dropZoneLabel.closest('div')
      expect(dropZone).not.toBeNull()

      fireEvent.drop(dropZone as HTMLElement, {
        preventDefault: vi.fn(),
        dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'dummy.png' }) }] },
      })

      await waitFor(() => expect(screen.queryByText('uploadPage.dropFilesHere')).not.toBeInTheDocument())
    }

    it('shows clickable filename chips when a small number of files are missing labels', async () => {
      const items: uploadModule.LocalItem[] = [
        { key: 'a', name: 'file-a.png', file: new File(['a'], 'file-a.png'), type: 'standard' },
        { key: 'b', name: 'file-b.png', file: new File(['b'], 'file-b.png'), type: 'standard' },
        { key: 'c', name: 'file-c.png', file: new File(['c'], 'file-c.png'), type: 'standard' },
      ]

      await renderUploadPage(items)

      await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: 'file-a.png' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'file-b.png' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'file-c.png' })).toBeInTheDocument()
    })

    it('clicking a missing-label chip jumps to the correct page, highlights the row, and focuses the label input', async () => {
      const items: uploadModule.LocalItem[] = Array.from({ length: 12 }, (_, i) => ({
        key: `key-${i}`,
        name: `file-${String(i).padStart(2, '0')}.png`,
        file: new File([String(i)], `file-${String(i).padStart(2, '0')}.png`),
        type: 'standard',
      }))

      await renderUploadPage(items)

      for (const input of screen.getAllByPlaceholderText('uploadPage.enterLabel')) {
        await userEvent.type(input, 'tumor')
      }

      await userEvent.click(screen.getByRole('button', { name: 'uploadPage.nextPage' }))
      const secondPageInputs = screen.getAllByPlaceholderText('uploadPage.enterLabel')
      await userEvent.type(secondPageInputs[1], 'tumor')

      await userEvent.click(screen.getByRole('button', { name: 'uploadPage.previousPage' }))

      await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      const targetChip = screen.getByRole('button', { name: 'file-10.png' })
      await userEvent.click(targetChip)

      await waitFor(() => {
        expect(screen.getByText(/uploadPage\.pageIndicator/)).toHaveTextContent('2 / 2')
      })

      const highlightedRow = screen.getByTestId('row-file-10.png')
      expect(highlightedRow).toHaveClass('bg-red-50')

      const labelInput = within(highlightedRow).getByPlaceholderText('uploadPage.enterLabel')
      expect(labelInput).toHaveFocus()
    })

    it('shows summary with filter toggle when many files are missing labels', async () => {
      const items: uploadModule.LocalItem[] = Array.from({ length: 18 }, (_, i) => ({
        key: `key-${i}`,
        name: `file-${i}.png`,
        file: new File([String(i)], `file-${i}.png`),
        type: 'standard',
      }))

      await renderUploadPage(items)

      for (const input of screen.getAllByPlaceholderText('uploadPage.enterLabel')) {
        await userEvent.type(input, 'tumor')
      }

      await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      expect(screen.queryByRole('button', { name: 'file-0.png' })).not.toBeInTheDocument()
      expect(screen.getByText(/uploadPage\.missingLabelSummary/)).toBeInTheDocument()

      const toggleBtn = screen.getByRole('button', { name: /uploadPage\.showOnlyMissingLabels/ })
      await userEvent.click(toggleBtn)

      await waitFor(() => {
        expect(screen.getAllByRole('row')).toHaveLength(8 + 1)
      })
      expect(screen.queryByText('file-0.png')).not.toBeInTheDocument()
      expect(screen.getByText('file-10.png')).toBeInTheDocument()

      const showAllBtn = screen.getByRole('button', { name: /uploadPage\.showAllFiles/ })
      await userEvent.click(showAllBtn)

      await waitFor(() => {
        expect(screen.getAllByRole('row')).toHaveLength(10 + 1)
      })
    })
  })
})
