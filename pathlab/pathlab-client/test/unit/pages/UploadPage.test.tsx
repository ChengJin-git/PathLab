import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UploadPage from '../../../src/renderer/src/pages/UploadPage'
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
      t: (key: string) => key,
    }),
  }
})

describe('UploadPage', () => {
  const addUploadTaskMock = vi.fn()
  const toastErrorMock = vi.fn()
  const toastWarningMock = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()

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

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({ items: [] } as Awaited<ReturnType<typeof apiModule.fetchDatasets>>)
    vi.spyOn(apiModule, 'checkDuplicateFilenames').mockResolvedValue({ duplicates: [], new: [] })
    vi.spyOn(apiModule, 'downloadCSVTemplate').mockResolvedValue(undefined)
    vi.spyOn(apiModule, 'uploadDatasetSplits').mockResolvedValue({ updated_count: 0, auto_val_count: 0, not_found_count: 0 })
    vi.spyOn(apiModule, 'updateDatasetSource').mockResolvedValue(undefined)
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
})
