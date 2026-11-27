import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import UploadPage, { DUPLICATE_CHECK_BATCH_SIZE } from '../../../src/renderer/src/pages/UploadPage'
import * as apiModule from '../../../src/renderer/src/api'
import * as catalogApi from '../../../src/renderer/src/api/datasetCatalog'
import * as wsiApi from '../../../src/renderer/src/api/wsi'
import * as uploadModule from '../../../src/renderer/src/components/upload'
import * as authModule from '../../../src/renderer/src/contexts/AuthContext'
import * as backgroundTaskModule from '../../../src/renderer/src/contexts/BackgroundTaskContext'
import * as toastModule from '../../../src/renderer/src/contexts/ToastContext'
import { TooltipProvider } from '../../../src/renderer/src/components/ui/tooltip'

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      i18n: { language: 'en-US' },
      t: (key: string, values?: Record<string, unknown>) => {
        if (!values) return key
        return `${key} ${Object.values(values).join(' / ')}`
      }
    })
  }
})

describe('UploadPage', () => {
  const addUploadTaskMock = vi.fn()
  const toastErrorMock = vi.fn()
  const toastWarningMock = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    addUploadTaskMock.mockReset()
    toastErrorMock.mockReset()
    toastWarningMock.mockReset()

    vi.spyOn(backgroundTaskModule, 'useBackgroundTask').mockReturnValue({
      addUploadTask: addUploadTaskMock
    } as unknown as ReturnType<typeof backgroundTaskModule.useBackgroundTask>)

    vi.spyOn(authModule, 'useAuth').mockReturnValue({
      user: { id: 'user-1' }
    } as unknown as ReturnType<typeof authModule.useAuth>)

    vi.spyOn(toastModule, 'useToast').mockReturnValue({
      error: toastErrorMock,
      warning: toastWarningMock
    } as unknown as ReturnType<typeof toastModule.useToast>)

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [],
      total: 0
    })
    vi.spyOn(catalogApi, 'createDataset').mockImplementation(async (draft) => ({
      ...draft,
      dataset_id: 'created',
      source_organ: draft.source_organ || null,
      revision: 1
    }))
    vi.spyOn(catalogApi, 'importDatasetLabels').mockResolvedValue({
      dataset: {} as any,
      updated_images: 1
    })
    vi.spyOn(apiModule, 'fetchDatasetSummary').mockImplementation(async (id) => {
      const data = await apiModule.fetchDatasets()
      return (
        data.items.find((item) => item.dataset_id === id) || {
          dataset_id: id,
          dataset_name: 'Existing dataset',
          data_type: 'patch',
          task_types: ['patch_classification'],
          aggregation_level: 'file',
          user_id: 'user-1',
          file_count: 0,
          total_size: 0,
          metadata: {},
          revision: 1,
          tasks: []
        }
      )
    })
    vi.spyOn(apiModule, 'checkDuplicateFilenames').mockResolvedValue({
      duplicates: [],
      new: []
    })
    vi.spyOn(apiModule, 'downloadCSVTemplate').mockResolvedValue(undefined)
    vi.spyOn(apiModule, 'uploadDatasetSplits').mockResolvedValue({
      message: '',
      updated_count: 0,
      auto_val_count: 0,
      not_found_count: 0,
      not_found_files: []
    } as unknown as Awaited<ReturnType<typeof apiModule.uploadDatasetSplits>>)
    vi.spyOn(wsiApi, 'updateDatasetProperties').mockResolvedValue({
      dataset: {}
    } as Awaited<ReturnType<typeof apiModule.updateDatasetProperties>>)
  })

  it('shows collection progress while gathering files for both initial and follow-up folder drops', async () => {
    let resolveFirstCollection: ((result: uploadModule.CollectionResult) => void) | undefined
    let resolveSecondCollection: ((result: uploadModule.CollectionResult) => void) | undefined

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer')
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, options?: uploadModule.CollectItemsOptions) => {
        options?.onProgress?.({
          phase: 'collecting',
          totalTopLevelEntries: 1,
          processedItems: 0,
          discoveredFiles: 12,
          discoveredDirectories: 2,
          currentDirectoryName: 'case-folder',
          completed: false
        })

        return await new Promise<uploadModule.CollectionResult>((resolve) => {
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
          completed: false
        })

        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveSecondCollection = resolve
        })
      })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Progress Dataset',
                uploadMode: 'patch_classification'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    const emptyDropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const emptyDropZone = emptyDropZoneLabel.closest('div')
    expect(emptyDropZone).not.toBeNull()

    fireEvent.drop(emptyDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [
          {
            webkitGetAsEntry: () => ({
              isDirectory: true,
              name: 'case-folder'
            })
          }
        ]
      }
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
            type: 'standard'
          }
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })
    })

    await waitFor(() => {
      expect(screen.queryByText('uploadPage.collectionProgressTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('row-case-a.svs')).toBeInTheDocument()

    const table = screen.getByRole('table')
    const tableDropZone = table.parentElement
    expect(tableDropZone).not.toBeNull()

    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [
          {
            webkitGetAsEntry: () => ({
              isDirectory: true,
              name: 'follow-up-folder'
            })
          }
        ]
      }
    })

    expect(await screen.findByText('uploadPage.collectionProgressTitle')).toBeInTheDocument()

    await act(async () => {
      resolveSecondCollection?.({
        items: [
          {
            key: 'case-b',
            name: 'case-b.svs',
            file: new File(['data'], 'case-b.svs'),
            type: 'standard'
          }
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })
    })

    await waitFor(() => {
      expect(screen.queryByText('uploadPage.collectionProgressTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('row-case-b.svs')).toBeInTheDocument()
    expect(container).toBeTruthy()
  })

  it('keeps a newly created dataset in the new-upload flow', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    await userEvent.type(
      screen.getByPlaceholderText('uploadComponents.datasetConfig.datasetNamePlaceholder'),
      'New cohort'
    )
    await userEvent.click(screen.getByRole('checkbox', { name: 'Detection' }))
    const next = screen.getByRole('button', {
      name: 'uploadComponents.datasetConfig.nextChooseFiles'
    })
    await waitFor(() => expect(next).toBeEnabled())
    await userEvent.click(next)
    expect(await screen.findByText('uploadPage.dropFilesHere')).toBeVisible()
    expect(catalogApi.createDataset).toHaveBeenCalledWith(
      expect.objectContaining({
        task_types: ['patch_classification', 'patch_detection']
      })
    )
    expect(screen.getByRole('heading', { name: 'Upload data' })).toBeVisible()
    expect(screen.queryByText('uploadPage.appendingData')).not.toBeInTheDocument()
  })

  it('preserves label files when switching append modes and imports the added task', async () => {
    const dataset: apiModule.DatasetSummary = {
      dataset_id: 'append',
      dataset_name: 'Append cohort',
      data_type: 'patch',
      aggregation_level: 'file',
      user_id: 'user-1',
      file_count: 12,
      total_size: 1000,
      metadata: {},
      revision: 4,
      task_types: ['patch_classification'],
      tasks: [
        {
          task_type: 'patch_classification',
          description: '',
          labelled_count: 8,
          sample_count: 12,
          classes: ['A', 'B'],
          status: 'partial'
        }
      ]
    }
    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [dataset],
      total: 1
    })
    vi.spyOn(wsiApi, 'fetchDatasetSummary').mockResolvedValue(dataset)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetId: 'append',
                datasetName: 'Append cohort',
                initialTab: 'labels'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    const editor = await screen.findByRole('region', {
      name: 'Tasks & labels'
    })
    expect(await within(editor).findByText('8 / 12 · Partly labelled')).toBeVisible()
    await userEvent.click(within(editor).getByRole('checkbox', { name: 'Detection' }))
    const coco = {
      images: [{ id: 1, file_name: 'one.png', width: 10, height: 10 }],
      categories: [{ id: 1, name: 'cell' }],
      annotations: []
    }
    await userEvent.upload(
      within(editor).getByLabelText('Detection · Annotation file (COCO JSON)'),
      new File([JSON.stringify(coco)], 'boxes.json', {
        type: 'application/json'
      })
    )
    await userEvent.click(screen.getByRole('button', { name: /New images\s*Add files/ }))
    expect(screen.getByText('uploadPage.dropFilesHere')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /Tasks & labels\s*Label existing/ }))
    expect(within(editor).getByText('boxes.json')).toBeVisible()
    await userEvent.click(within(editor).getByRole('button', { name: 'Import labels' }))
    await waitFor(() =>
      expect(catalogApi.importDatasetLabels).toHaveBeenCalledWith(
        'append',
        expect.objectContaining({
          revision: 4,
          task_types: ['patch_classification', 'patch_detection'],
          annotations: { patch_detection: coco }
        })
      )
    )
    expect(addUploadTaskMock).not.toHaveBeenCalled()
  })

  it('keeps detection canonical and rejects WSI files dropped into the upload page', async () => {
    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValue({
      items: [
        {
          key: 'slide',
          name: 'slide.svs',
          type: 'standard',
          file: new File(['data'], 'slide.svs')
        }
      ],
      jsonFiles: [],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: []
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Detection data',
                uploadMode: 'patch_detection',
                dataLevel: 'file'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    expect(await screen.findByText(/Image patches · Detection/)).toBeVisible()
    const drop = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')!
    fireEvent.drop(drop, {
      preventDefault: vi.fn(),
      dataTransfer: { items: [] }
    })
    expect(await screen.findByText('detection.patchOnly')).toBeVisible()
    expect(screen.queryByText('slide.svs')).not.toBeInTheDocument()
    expect(addUploadTaskMock).not.toHaveBeenCalled()
  })

  it('waits for upload task creation before warning and leaving the page', async () => {
    let resolveAddUploadTask: ((taskId: string) => void) | undefined
    addUploadTaskMock.mockReturnValueOnce(
      new Promise<string>((resolve) => {
        resolveAddUploadTask = resolve
      })
    )

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Upload Dataset',
                uploadMode: 'patch_classification'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
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
          type: 'standard'
        }
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: []
    })

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'case-a.png' }) }]
      }
    })

    await screen.findAllByText('case-a.png')
    await userEvent.type(screen.getByPlaceholderText('uploadPage.enterLabel'), 'tumor')
    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

    await waitFor(() => expect(addUploadTaskMock).toHaveBeenCalledTimes(1))
    expect(toastWarningMock).not.toHaveBeenCalled()

    await act(async () => {
      resolveAddUploadTask?.('upload_task_1')
    })

    await waitFor(() => expect(toastWarningMock).toHaveBeenCalledWith('uploadPage.uploadingWarning', 8000))
  })

  it('resolves new patch classification uploads to the patch canonical task type', async () => {
    addUploadTaskMock.mockResolvedValueOnce('upload_task_patch')

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Patch Classification Dataset',
                uploadMode: 'patch_classification'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items: [
        {
          key: 'patch-a',
          name: 'patch-a.png',
          file: new File(['data'], 'patch-a.png', { type: 'image/png' }),
          type: 'standard'
        }
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: []
    })

    const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const dropZone = dropZoneLabel.closest('div')
    expect(dropZone).not.toBeNull()

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'patch-a.png' }) }]
      }
    })

    await screen.findAllByText('patch-a.png')
    await userEvent.type(screen.getByPlaceholderText('uploadPage.enterLabel'), 'tumor')
    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

    await waitFor(() => expect(addUploadTaskMock).toHaveBeenCalledTimes(1))
    const [files] = addUploadTaskMock.mock.calls[0]
    expect(files[0].metadata.task_type).toBe('patch_classification')
  })

  it('resolves new WSI classification uploads to the WSI canonical task type', async () => {
    addUploadTaskMock.mockResolvedValueOnce('upload_task_wsi')

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'WSI Classification Dataset',
                uploadMode: 'classification'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items: [
        {
          key: 'slide-a',
          name: 'slide-a.svs',
          file: new File(['data'], 'slide-a.svs', { type: 'image/tiff' }),
          type: 'standard'
        }
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: []
    })

    const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
    const dropZone = dropZoneLabel.closest('div')
    expect(dropZone).not.toBeNull()

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'slide-a.svs' }) }]
      }
    })

    await screen.findAllByText('slide-a.svs')
    await userEvent.type(screen.getByPlaceholderText('uploadPage.enterLabel'), 'tumor')
    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

    await waitFor(() => expect(addUploadTaskMock).toHaveBeenCalledTimes(1))
    const [files] = addUploadTaskMock.mock.calls[0]
    expect(files[0].metadata.task_type).toBe('wsi_classification')
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
        type: 'standard'
      })
    }

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items,
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: []
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Batch Dataset',
                datasetId: 'batch-dataset',
                uploadMode: 'classification'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    const dropZone = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')!
    fireEvent.drop(dropZone, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'dummy.png' }) }]
      }
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

  it('locks dataset source to the original source when appending to an existing dataset', async () => {
    const updatePropertiesSpy = vi.spyOn(apiModule, 'updateDatasetProperties')
    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-1',
          dataset_name: 'PanCancer-TIL',
          user_id: 'user-1',
          source_organ: 'Pancreas',
          file_count: 3,
          total_size: 1024,
          data_type: 'patch',
          task_types: ['patch_classification'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[{ pathname: '/upload' }]}>
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await userEvent.type(
      screen.getByPlaceholderText('uploadComponents.datasetConfig.datasetNamePlaceholder'),
      'PanCancer-TIL'
    )
    await userEvent.click(await screen.findByRole('button', { name: /PanCancer-TIL/ }))
    await waitFor(() => expect(screen.getByText('organSources.pancreas')).toBeInTheDocument())

    await waitFor(() =>
      expect(
        screen.getByRole('button', {
          name: /uploadComponents\.datasetConfig\.nextChooseFiles/
        })
      ).toBeEnabled()
    )
    await userEvent.click(
      screen.getByRole('button', {
        name: /uploadComponents\.datasetConfig\.nextChooseFiles/
      })
    )

    await waitFor(() => {
      expect(screen.getByText('uploadPage.appendingData')).toBeInTheDocument()
    })
    expect(updatePropertiesSpy).toHaveBeenCalledWith('dataset-1', expect.objectContaining({ source: 'Pancreas' }))
  })

  it('accepts JSON-only drops when appending to an existing canonical segmentation dataset', async () => {
    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-jiangxi',
          dataset_name: 'jiangxi',
          user_id: 'user-1',
          source_organ: 'Liver',
          file_count: 4,
          total_size: 2048,
          data_type: 'patch',
          task_types: ['patch_segmentation'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
      items: [],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: [
        new File(['{"annotations":[]}'], 'tile-a.json', {
          type: 'application/json'
        })
      ]
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'jiangxi',
                datasetId: 'dataset-jiangxi',
                uploadMode: 'patch_segmentation',
                dataLevel: 'file'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findByText('uploadPage.appendingData')
    const tableDropZone = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')
    expect(tableDropZone).not.toBeNull()

    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'labels' }) }]
      }
    })

    expect(await screen.findByText('uploadPage.jsonOnlyAppendTitle')).toBeInTheDocument()
    expect(screen.getByText(/uploadPage\.jsonOnlyAppendDesc 1/)).toBeInTheDocument()
  })

  it('allows additional drops after a JSON-only drop on segmentation append', async () => {
    let resolveFirstCollection: ((result: uploadModule.CollectionResult) => void) | undefined
    let resolveSecondCollection: ((result: uploadModule.CollectionResult) => void) | undefined

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-jiangxi',
          dataset_name: 'jiangxi',
          user_id: 'user-1',
          source_organ: 'Liver',
          file_count: 4,
          total_size: 2048,
          data_type: 'patch',
          task_types: ['patch_segmentation'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer')
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, _options?: uploadModule.CollectItemsOptions) => {
        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveFirstCollection = resolve
        })
      })
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, _options?: uploadModule.CollectItemsOptions) => {
        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveSecondCollection = resolve
        })
      })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'jiangxi',
                datasetId: 'dataset-jiangxi',
                uploadMode: 'patch_segmentation',
                dataLevel: 'file'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findByText('uploadPage.appendingData')
    const tableDropZone = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')
    expect(tableDropZone).not.toBeNull()

    // First drop: JSON-only
    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'labels' }) }]
      }
    })

    await act(async () => {
      resolveFirstCollection?.({
        items: [],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: [
          new File(['{"annotations":[]}'], 'tile-a.json', {
            type: 'application/json'
          })
        ]
      })
    })

    expect(await screen.findByText('uploadPage.jsonOnlyAppendTitle')).toBeInTheDocument()

    // The JSON-only card should still be a drop zone
    const jsonOnlyCard = screen.getByText('uploadPage.jsonOnlyAppendTitle').closest('div')?.parentElement?.parentElement
    expect(jsonOnlyCard).not.toBeNull()

    fireEvent.drop(jsonOnlyCard as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'images' }) }]
      }
    })

    await act(async () => {
      resolveSecondCollection?.({
        items: [
          {
            key: 'tile-a',
            name: 'tile-a.png',
            file: new File(['data'], 'tile-a.png', { type: 'image/png' }),
            type: 'standard'
          }
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })
    })

    // After dropping images, the table should reappear with the matched item
    await waitFor(() => {
      expect(screen.queryByText('uploadPage.jsonOnlyAppendTitle')).not.toBeInTheDocument()
    })
    expect(screen.getByText('tile-a.png')).toBeInTheDocument()
  })

  it('allows image-only drops followed by JSON drops on segmentation append', async () => {
    let resolveFirstCollection: ((result: uploadModule.CollectionResult) => void) | undefined
    let resolveSecondCollection: ((result: uploadModule.CollectionResult) => void) | undefined

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-jiangxi',
          dataset_name: 'jiangxi',
          user_id: 'user-1',
          source_organ: 'Liver',
          file_count: 4,
          total_size: 2048,
          data_type: 'patch',
          task_types: ['patch_segmentation'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer')
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, _options?: uploadModule.CollectItemsOptions) => {
        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveFirstCollection = resolve
        })
      })
      .mockImplementationOnce(async (_dataTransfer: DataTransfer, _options?: uploadModule.CollectItemsOptions) => {
        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveSecondCollection = resolve
        })
      })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'jiangxi',
                datasetId: 'dataset-jiangxi',
                uploadMode: 'patch_segmentation',
                dataLevel: 'file'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findByText('uploadPage.appendingData')
    const tableDropZone = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')
    expect(tableDropZone).not.toBeNull()

    // First drop: image-only
    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'images' }) }]
      }
    })

    await act(async () => {
      resolveFirstCollection?.({
        items: [
          {
            key: 'tile-a',
            name: 'tile-a.png',
            file: new File(['data'], 'tile-a.png', { type: 'image/png' }),
            type: 'standard'
          }
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })
    })

    expect(await screen.findByText('tile-a.png')).toBeInTheDocument()

    // Second drop: JSON-only onto the table
    fireEvent.drop(screen.getByRole('table').parentElement as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'labels' }) }]
      }
    })

    await act(async () => {
      resolveSecondCollection?.({
        items: [],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: [
          new File(['{"annotations":[]}'], 'tile-a.json', {
            type: 'application/json'
          })
        ]
      })
    })

    // Mask should now be found for the image
    await waitFor(() => {
      expect(screen.getByText('uploadPage.maskFound')).toBeInTheDocument()
    })
  })

  it('allows mixed image+JSON drops on segmentation append', async () => {
    let resolveCollection: ((result: uploadModule.CollectionResult) => void) | undefined

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-jiangxi',
          dataset_name: 'jiangxi',
          user_id: 'user-1',
          source_organ: 'Liver',
          file_count: 4,
          total_size: 2048,
          data_type: 'patch',
          task_types: ['patch_segmentation'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockImplementationOnce(
      async (_dataTransfer: DataTransfer, _options?: uploadModule.CollectItemsOptions) => {
        return await new Promise<uploadModule.CollectionResult>((resolve) => {
          resolveCollection = resolve
        })
      }
    )

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'jiangxi',
                datasetId: 'dataset-jiangxi',
                uploadMode: 'patch_segmentation',
                dataLevel: 'file'
              }
            }
          ]}
        >
          <UploadPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findByText('uploadPage.appendingData')
    const tableDropZone = (await screen.findByText('uploadPage.dropFilesHere')).closest('div')
    expect(tableDropZone).not.toBeNull()

    // Mixed drop
    fireEvent.drop(tableDropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true, name: 'mixed' }) }]
      }
    })

    await act(async () => {
      resolveCollection?.({
        items: [
          {
            key: 'tile-a',
            name: 'tile-a.png',
            file: new File(['data'], 'tile-a.png', { type: 'image/png' }),
            type: 'standard'
          }
        ],
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: [
          new File(['{"annotations":[]}'], 'tile-a.json', {
            type: 'application/json'
          })
        ]
      })
    })

    expect(await screen.findByText('tile-a.png')).toBeInTheDocument()
    expect(screen.getByText('uploadPage.maskFound')).toBeInTheDocument()
  })

  describe('missing-label navigation UX', () => {
    const renderUploadPage = async (items: uploadModule.LocalItem[], uploadMode = 'patch_classification') => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } }
      })

      vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
        items,
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })

      const renderResult = render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[
              {
                pathname: '/upload',
                state: {
                  datasetName: 'Missing Label Dataset',
                  uploadMode
                }
              }
            ]}
          >
            <TooltipProvider>
              <UploadPage />
            </TooltipProvider>
          </MemoryRouter>
        </QueryClientProvider>
      )

      const dropZoneLabel = await screen.findByText('uploadPage.dropFilesHere')
      const dropZone = dropZoneLabel.closest('div')
      expect(dropZone).not.toBeNull()

      fireEvent.drop(dropZone as HTMLElement, {
        preventDefault: vi.fn(),
        dataTransfer: {
          items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'dummy.png' }) }]
        }
      })

      await waitFor(() => expect(screen.queryByText('uploadPage.dropFilesHere')).not.toBeInTheDocument())

      return renderResult
    }

    const uploadCsvMetadata = async (container: HTMLElement, file: File) => {
      await userEvent.click(screen.getByText('uploadPage.datasetMetadataConfig'))
      const csvInput = container.querySelector('input[type="file"][accept=".csv,.xlsx,.xls"]')
      expect(csvInput).not.toBeNull()

      await userEvent.upload(csvInput as HTMLInputElement, file)

      await waitFor(() => {
        expect(screen.getByText(file.name)).toBeInTheDocument()
      })
    }

    it('shows clickable filename chips when a small number of files are missing labels', async () => {
      const items: uploadModule.LocalItem[] = [
        {
          key: 'a',
          name: 'file-a.png',
          file: new File(['a'], 'file-a.png'),
          type: 'standard'
        },
        {
          key: 'b',
          name: 'file-b.png',
          file: new File(['b'], 'file-b.png'),
          type: 'standard'
        },
        {
          key: 'c',
          name: 'file-c.png',
          file: new File(['c'], 'file-c.png'),
          type: 'standard'
        }
      ]

      await renderUploadPage(items)

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
        type: 'standard'
      }))

      await renderUploadPage(items)

      for (const input of screen.getAllByPlaceholderText('uploadPage.enterLabel')) {
        await userEvent.type(input, 'tumor')
      }

      await userEvent.click(screen.getByRole('button', { name: 'uploadPage.nextPage' }))
      const secondPageInputs = screen.getAllByPlaceholderText('uploadPage.enterLabel')
      await userEvent.type(secondPageInputs[1], 'tumor')

      await userEvent.click(screen.getByRole('button', { name: 'uploadPage.previousPage' }))

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
        type: 'standard'
      }))

      await renderUploadPage(items)

      for (const input of screen.getAllByPlaceholderText('uploadPage.enterLabel')) {
        await userEvent.type(input, 'tumor')
      }

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      expect(screen.queryByRole('button', { name: 'file-0.png' })).not.toBeInTheDocument()
      expect(screen.getByText(/uploadPage\.missingLabelSummary/)).toBeInTheDocument()

      const toggleBtn = screen.getByRole('button', {
        name: /uploadPage\.showOnlyMissingLabels/
      })
      await userEvent.click(toggleBtn)

      await waitFor(() => {
        expect(screen.getAllByRole('row')).toHaveLength(8 + 1)
      })
      expect(screen.queryByText('file-0.png')).not.toBeInTheDocument()
      expect(screen.getByText('file-10.png')).toBeInTheDocument()

      const showAllBtn = screen.getByRole('button', {
        name: /uploadPage\.showAllFiles/
      })
      await userEvent.click(showAllBtn)

      await waitFor(() => {
        expect(screen.getAllByRole('row')).toHaveLength(10 + 1)
      })
    })

    it('uses CSV metadata to report only the files that are actually missing labels', async () => {
      const items: uploadModule.LocalItem[] = [
        'matched-a.png',
        'matched-b.png',
        'matched-c.png',
        'missing-a.png',
        'missing-b.png'
      ].map((name) => ({
        key: name,
        name,
        file: new File([name], name),
        type: 'standard'
      }))

      const { container } = await renderUploadPage(items)
      await uploadCsvMetadata(
        container,
        new File(
          ['filename,label\n', 'matched-a.png,tumor\n', 'matched-b.png,normal\n', 'matched-c.png,tumor\n'],
          'labels.csv',
          { type: 'text/csv' }
        )
      )

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: 'missing-a.png' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'missing-b.png' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'matched-a.png' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'matched-b.png' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'matched-c.png' })).not.toBeInTheDocument()
    })

    it('binds CSV labels only to newly appended files for existing datasets', async () => {
      const uploadDatasetSplitsSpy = vi.spyOn(apiModule, 'uploadDatasetSplits')
      vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
        items: [
          {
            dataset_id: 'dataset-append',
            dataset_name: 'Append Dataset',
            user_id: 'user-1',
            source_organ: 'Liver',
            file_count: 20,
            total_size: 4096,
            data_type: 'patch',
            task_types: ['patch_classification'],
            tasks: [],
            metadata: {},
            revision: 1,
            aggregation_level: 'file'
          }
        ],
        total: 1
      } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

      const items: uploadModule.LocalItem[] = [
        {
          key: 'append-a',
          name: 'append-a.png',
          file: new File(['a'], 'append-a.png'),
          type: 'standard'
        },
        {
          key: 'append-b',
          name: 'append-b.png',
          file: new File(['b'], 'append-b.png'),
          type: 'standard'
        }
      ]

      vi.spyOn(uploadModule, 'collectItemsFromDataTransfer').mockResolvedValueOnce({
        items,
        orphanFolders: [],
        orphanDtFiles: new Map(),
        unsupportedFileNames: [],
        jsonFiles: []
      })

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } }
      })

      const { container } = render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={[
              {
                pathname: '/upload',
                state: {
                  datasetName: 'Append Dataset',
                  datasetId: 'dataset-append',
                  uploadMode: 'classification'
                }
              }
            ]}
          >
            <TooltipProvider>
              <UploadPage />
            </TooltipProvider>
          </MemoryRouter>
        </QueryClientProvider>
      )

      await screen.findByText('uploadPage.appendingData')
      const dropZone = screen.getByText('uploadPage.dropFilesHere').closest('div')
      expect(dropZone).not.toBeNull()

      fireEvent.drop(dropZone as HTMLElement, {
        preventDefault: vi.fn(),
        dataTransfer: {
          items: [
            {
              webkitGetAsEntry: () => ({ isFile: true, name: 'append-a.png' })
            }
          ]
        }
      })

      await screen.findAllByText('append-a.png')

      await uploadCsvMetadata(
        container,
        new File(['filename,label\n', 'append-a.png,tumor\n', 'append-b.png,normal\n'], 'append-labels.csv', {
          type: 'text/csv'
        })
      )

      await userEvent.click(screen.getByRole('button', { name: /uploadPage\.addToDataset/ }))

      await waitFor(() => {
        expect(addUploadTaskMock).toHaveBeenCalledTimes(1)
      })

      expect(uploadDatasetSplitsSpy).not.toHaveBeenCalled()
      const [files] = addUploadTaskMock.mock.calls[0]
      expect(files).toHaveLength(2)
      expect(files[0].metadata).toMatchObject({
        dataset_id: 'dataset-append',
        label: 'tumor'
      })
      expect(files[1].metadata).toMatchObject({
        dataset_id: 'dataset-append',
        label: 'normal'
      })
    })

    it('parses CSV filenames containing commas when quoted', async () => {
      const items: uploadModule.LocalItem[] = [
        {
          key: 'slide-copy',
          name: 'slide, copy.svs',
          file: new File(['a'], 'slide, copy.svs'),
          type: 'standard'
        },
        {
          key: 'plain',
          name: 'plain.svs',
          file: new File(['b'], 'plain.svs'),
          type: 'standard'
        }
      ]

      const { container } = await renderUploadPage(items, 'wsi_classification')
      await uploadCsvMetadata(
        container,
        new File(['filename,label\n', '"slide, copy.svs",tumor\n', 'plain.svs,normal\n'], 'labels.csv', {
          type: 'text/csv'
        })
      )

      await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

      await waitFor(() => {
        expect(addUploadTaskMock).toHaveBeenCalledTimes(1)
      })

      const [files] = addUploadTaskMock.mock.calls[0]
      const labeledCopy = files.find((f: any) => f.name === 'slide, copy.svs')
      const labeledPlain = files.find((f: any) => f.name === 'plain.svs')
      expect(labeledCopy?.metadata.label).toBe('tumor')
      expect(labeledPlain?.metadata.label).toBe('normal')
    })

    it('shows metadata validation progress while a large CSV is being checked', async () => {
      const items: uploadModule.LocalItem[] = [
        {
          key: 'a',
          name: 'file-a.png',
          file: new File(['a'], 'file-a.png'),
          type: 'standard'
        },
        {
          key: 'b',
          name: 'file-b.png',
          file: new File(['b'], 'file-b.png'),
          type: 'standard'
        }
      ]
      let resolveCsvRead: ((value: string) => void) | undefined
      const csvReadPromise = new Promise<string>((resolve) => {
        resolveCsvRead = resolve
      })
      const csvFile = new File(['filename,label\nfile-a.png,tumor\n'], 'large-labels.csv', { type: 'text/csv' })
      Object.defineProperty(csvFile, 'text', {
        value: vi.fn().mockReturnValueOnce(csvReadPromise)
      })

      const { container } = await renderUploadPage(items)
      await userEvent.click(screen.getByText('uploadPage.datasetMetadataConfig'))
      await userEvent.upload(container.querySelector('input[accept=".csv,.xlsx,.xls"]') as HTMLInputElement, csvFile)

      expect(await screen.findByText('uploadPage.validatingMetadata')).toBeInTheDocument()

      await act(async () => {
        resolveCsvRead?.('filename,label\nfile-a.png,tumor\n')
      })

      await waitFor(() => {
        expect(screen.queryByText('uploadPage.validatingMetadata')).not.toBeInTheDocument()
      })
    })
  })

  it('disables the submit button and shows importing state while addUploadTask is pending', async () => {
    let resolveAddUploadTask: ((taskId: string) => void) | undefined
    addUploadTaskMock.mockReturnValueOnce(
      new Promise<string>((resolve) => {
        resolveAddUploadTask = resolve
      })
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Importing Dataset',
                uploadMode: 'patch_classification'
              }
            }
          ]}
        >
          <TooltipProvider>
            <UploadPage />
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>
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
          type: 'standard'
        }
      ],
      orphanFolders: [],
      orphanDtFiles: new Map(),
      unsupportedFileNames: [],
      jsonFiles: []
    })

    fireEvent.drop(dropZone as HTMLElement, {
      preventDefault: vi.fn(),
      dataTransfer: {
        items: [{ webkitGetAsEntry: () => ({ isFile: true, name: 'case-a.png' }) }]
      }
    })

    await screen.findAllByText('case-a.png')
    await userEvent.type(screen.getByPlaceholderText('uploadPage.enterLabel'), 'tumor')
    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.registerAll/ }))

    await waitFor(() => expect(addUploadTaskMock).toHaveBeenCalledTimes(1))

    const submitButton = screen.getByRole('button', {
      name: /uploadPage\.importing/
    })
    expect(submitButton).toBeDisabled()
    expect(screen.getByText('uploadPage.importing')).toBeInTheDocument()

    await act(async () => {
      resolveAddUploadTask?.('upload_task_1')
    })

    await waitFor(() => {
      expect(screen.queryByText('uploadPage.importing')).not.toBeInTheDocument()
    })
  })

  it('disables the submit button while split upload is pending', async () => {
    let resolveUploadSplit: ((value: Awaited<ReturnType<typeof catalogApi.importDatasetLabels>>) => void) | undefined
    vi.spyOn(catalogApi, 'importDatasetLabels').mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUploadSplit = resolve
      })
    )

    vi.spyOn(apiModule, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-split',
          dataset_name: 'Split Dataset',
          user_id: 'user-1',
          source_organ: 'Liver',
          file_count: 20,
          total_size: 4096,
          data_type: 'patch',
          task_types: ['patch_classification'],
          tasks: [],
          metadata: {},
          revision: 1,
          aggregation_level: 'file'
        }
      ],
      total: 1
    } as unknown as Awaited<ReturnType<typeof apiModule.fetchAllDatasets>>)

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: '/upload',
              state: {
                datasetName: 'Split Dataset',
                datasetId: 'dataset-split',
                uploadMode: 'classification'
              }
            }
          ]}
        >
          <TooltipProvider>
            <UploadPage />
          </TooltipProvider>
        </MemoryRouter>
      </QueryClientProvider>
    )

    await screen.findByText('uploadPage.appendingData')

    await userEvent.click(screen.getByText('uploadPage.datasetMetadataConfig'))
    const csvInput = container.querySelector('input[type="file"][accept=".csv,.xlsx,.xls"]')
    expect(csvInput).not.toBeNull()

    await userEvent.upload(
      csvInput as HTMLInputElement,
      new File(['filename,label\nfile-a.png,tumor\n'], 'splits.csv', {
        type: 'text/csv'
      })
    )

    await waitFor(() => {
      expect(screen.getByText('splits.csv')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /uploadPage\.uploadCsv/ }))

    await waitFor(() => expect(catalogApi.importDatasetLabels).toHaveBeenCalledTimes(1))

    const submitButton = screen.getByRole('button', {
      name: /uploadPage\.importing/
    })
    expect(submitButton).toBeDisabled()
    expect(screen.getByText('uploadPage.importing')).toBeInTheDocument()

    await act(async () => {
      resolveUploadSplit?.({
        dataset: {} as any,
        updated_images: 1
      })
    })

    await waitFor(() => {
      expect(screen.queryByText('uploadPage.importing')).not.toBeInTheDocument()
    })
  })
})
