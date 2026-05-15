import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTaskActions } from '@renderer/contexts/backgroundTask/useTaskActions'
import * as storageApi from '@renderer/api/storage'
import * as wsiApi from '@renderer/api/wsi'
import * as queueApi from '@renderer/api/queue'

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual('react-i18next')
  return {
    ...actual,
    useTranslation: () => ({ t: (key: string) => key }),
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
    vi.restoreAllMocks()
    mockSetLocalTasks.mockClear()
    mockSetIsPanelExpanded.mockClear()
    mockRefreshDiskSpace.mockClear()
  })

  it('calls startDeleteWSIsTask once with all WSI IDs and does not call deleteWSI per item', async () => {
    const startDeleteWSIsTaskSpy = vi
      .spyOn(storageApi, 'startDeleteWSIsTask')
      .mockResolvedValue({ task_id: 'server_delete_001', message: 'Started', total_items: 3 })

    const deleteWSISpy = vi.spyOn(wsiApi, 'deleteWSI')

    const { result } = renderHook(() => useTaskActions(defaultParams))

    let taskId: string
    await act(async () => {
      taskId = await result.current.addDeleteWSITask(['wsi_a', 'wsi_b', 'wsi_c'], 'complete')
    })

    expect(taskId!).toBe('server_delete_001')
    expect(startDeleteWSIsTaskSpy).toHaveBeenCalledTimes(1)
    expect(startDeleteWSIsTaskSpy).toHaveBeenCalledWith({
      wsi_ids: ['wsi_a', 'wsi_b', 'wsi_c'],
      mode: 'complete',
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
})
