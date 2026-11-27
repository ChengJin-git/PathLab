import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useTaskActions } from '@renderer/contexts/backgroundTask/useTaskActions'
import * as storageApi from '@renderer/api/storage'
import * as wsiApi from '@renderer/api/wsi'
import * as queueApi from '@renderer/api/queue'
import * as exportApi from '@renderer/api/export'

const mockT = vi.hoisted(() => vi.fn((key: string) => key))

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual('react-i18next')
  return {
    ...actual,
    useTranslation: () => ({ t: mockT }),
  }
})

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
  }),
}))

describe('useTaskActions addDeleteWSITask', () => {
  const mockSetLocalTasks = vi.fn()
  const mockSetIsPanelExpanded = vi.fn()
  const mockSetDismissedServerTasks = vi.fn()
  const mockSetMetadataUploadResults = vi.fn()
  const mockRefreshDiskSpace = vi.fn()

  const defaultParams = {
    setLocalTasks: mockSetLocalTasks,
    setIsPanelExpanded: mockSetIsPanelExpanded,
    setDismissedServerTasks: mockSetDismissedServerTasks,
    setMetadataUploadResults: mockSetMetadataUploadResults,
    cancelledTasksRef: { current: new Set<string>() },
    abortControllersRef: { current: new Map<string, AbortController>() },
    trainingTasks: [],
    analysisTasks: [],
    storageTasks: [],
    tasks: [],
    refreshDiskSpace: mockRefreshDiskSpace,
    metadataUploadResults: new Map(),
  }

  beforeEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    mockSetLocalTasks.mockClear()
    mockSetIsPanelExpanded.mockClear()
    mockRefreshDiskSpace.mockClear()
    mockT.mockClear()
  })

  it('calls startDeleteWSIsTask once with all WSI IDs and does not call deleteWSI per item', async () => {
    const startDeleteWSIsTaskSpy = vi
      .spyOn(storageApi, 'startDeleteWSIsTask')
      .mockResolvedValue({ task_id: 'server_delete_001', message: 'Started', total_items: 3 })

    const deleteWSISpy = vi.spyOn(wsiApi, 'deleteWSI')

    const { result } = renderHook(() => useTaskActions(defaultParams))

    let taskId: string
    await act(async () => {
      taskId = await result.current.addDeleteWSITask(['wsi_a', 'wsi_b', 'wsi_c'])
    })

    expect(taskId!).toBe('server_delete_001')
    expect(startDeleteWSIsTaskSpy).toHaveBeenCalledTimes(1)
    expect(startDeleteWSIsTaskSpy).toHaveBeenCalledWith({
      wsi_ids: ['wsi_a', 'wsi_b', 'wsi_c'],
    })
    expect(deleteWSISpy).not.toHaveBeenCalled()
    expect(mockSetLocalTasks).not.toHaveBeenCalled()
  })

  it('cancels delete_wsis server tasks through storage task cancellation', async () => {
    const cancelStorageTaskSpy = vi
      .spyOn(storageApi, 'cancelStorageTask')
      .mockResolvedValue({ cancelled: true, message: 'Cancelled' })
    const cancelQueueTaskSpy = vi
      .spyOn(queueApi, 'cancelQueueTask')
      .mockResolvedValue({ cancelled: false, message: 'Wrong path' })

    const { result } = renderHook(() => useTaskActions(defaultParams))

    const cancelled = await result.current.cancelServerTask({
      id: 'delete_wsis_delete_wsis_abc',
      type: 'delete_wsi',
      title: 'Delete WSI',
      items: [],
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0,
      isServerTask: true,
    })

    expect(cancelled).toBe(true)
    expect(cancelStorageTaskSpy).toHaveBeenCalledWith('delete_wsis_abc')
    expect(cancelQueueTaskSpy).not.toHaveBeenCalled()
  })

  it('cancels scan_directory server tasks through storage task cancellation', async () => {
    const cancelStorageTaskSpy = vi
      .spyOn(storageApi, 'cancelStorageTask')
      .mockResolvedValue({ cancelled: true, message: 'Cancelled' })
    const cancelQueueTaskSpy = vi
      .spyOn(queueApi, 'cancelQueueTask')
      .mockResolvedValue({ cancelled: false, message: 'Wrong path' })

    const { result } = renderHook(() => useTaskActions(defaultParams))

    const cancelled = await result.current.cancelServerTask({
      id: 'scan_scan_abc',
      type: 'scan_directory',
      title: 'Scan Directory',
      items: [],
      status: 'running',
      createdAt: new Date(),
      totalProgress: 0,
      successCount: 0,
      failedCount: 0,
      isServerTask: true,
    })

    expect(cancelled).toBe(true)
    expect(cancelStorageTaskSpy).toHaveBeenCalledWith('scan_abc')
    expect(cancelQueueTaskSpy).not.toHaveBeenCalled()
  })

  it('records the existing dataset id on local upload tasks', async () => {
    vi.spyOn(wsiApi,'uploadWSIByPath').mockResolvedValue({message:'ok',wsi_id:'slide-1',wsi_path:'/fixture/slide-1.svs',file_size:1})
    const { result } = renderHook(() => useTaskActions(defaultParams))

    await act(async () => {
      await result.current.addUploadTask([
        {
          key: 'slide-1',
          name: 'slide-1.svs',
          path: '/fixture/slide-1.svs',
          metadata: { dataset_id: 'training-dataset' },
        },
      ])
    })

    const addTaskUpdater = mockSetLocalTasks.mock.calls[0][0]
    const [task] = addTaskUpdater([])
    expect(task.datasetId).toBe('training-dataset')
  })

  it('does not report uploads for an unrelated batch import when scoped to a dataset', () => {
    const { result } = renderHook(() => useTaskActions({
      ...defaultParams,
      tasks: [
        {
          id: 'import_other-dataset',
          type: 'batch_import',
          title: 'Other Dataset (10/100)',
          items: [],
          status: 'running',
          createdAt: new Date(),
          totalProgress: 10,
          successCount: 10,
          failedCount: 0,
          isServerTask: true,
          datasetId: 'other-dataset',
          datasetName: 'Other Dataset',
        },
      ],
    }))

    expect(result.current.hasUploadingTasks('training-dataset')).toBe(false)
  })

  it('reports uploads for a matching batch import when scoped to a dataset', () => {
    const { result } = renderHook(() => useTaskActions({
      ...defaultParams,
      tasks: [
        {
          id: 'import_training-dataset',
          type: 'batch_import',
          title: 'Training Dataset (10/100)',
          items: [],
          status: 'running',
          createdAt: new Date(),
          totalProgress: 10,
          successCount: 10,
          failedCount: 0,
          isServerTask: true,
          datasetId: 'training-dataset',
          datasetName: 'Training Dataset',
        },
      ],
    }))

    expect(result.current.hasUploadingTasks('training-dataset')).toBe(true)
  })

  it('creates segmentation mask export tasks with packaging copy instead of inference copy', () => {
    const { result } = renderHook(() => useTaskActions(defaultParams))

    act(() => {
      result.current.addAnalysisExportTask('export-task-1', 'analysis-abcdef123', 'Tumor segmentation run')
    })

    const addTaskUpdater = mockSetLocalTasks.mock.calls[0][0]
    const [task] = addTaskUpdater([])

    expect(task.type).toBe('segmentation_export')
    expect(task.title).toBe('backgroundTask.taskTitles.segmentationMaskExport')
    expect(task.items[0].name).toBe('backgroundTask.taskTitles.packagingSegmentationMasks')
    expect(mockT).toHaveBeenCalledWith('backgroundTask.taskTitles.segmentationMaskExport', { name: 'Tumor segmentation run' })
  })

  it('cancels segmentation mask export polling and backend export task', async () => {
    vi.useFakeTimers()
    const cancelAnalysisFullExportSpy = vi
      .spyOn(exportApi, 'cancelAnalysisFullExport')
      .mockResolvedValue({ cancelled: true, status: 'cancelled' })
    const getStatusSpy = vi
      .spyOn(exportApi, 'getAnalysisFullExportStatus')
      .mockResolvedValue({
        task_id: 'export-task-1',
        status: 'completed',
        progress: 100,
        error_message: null,
        created_at: null,
        started_at: null,
        completed_at: null,
      })
    const downloadSpy = vi.spyOn(exportApi, 'downloadAnalysisFullExportFile')
      .mockResolvedValue(new Blob(['zip']))

    const { result } = renderHook(() => useTaskActions(defaultParams))

    let taskId: string
    act(() => {
      taskId = result.current.addAnalysisExportTask('export-task-1', 'analysis-abcdef123', 'Tumor segmentation run')
    })

    act(() => {
      result.current.cancelTask(taskId!)
    })

    expect(cancelAnalysisFullExportSpy).toHaveBeenCalledWith('export-task-1')
    expect(getStatusSpy).not.toHaveBeenCalled()
    expect(downloadSpy).not.toHaveBeenCalled()

    vi.useRealTimers()
  })
})
