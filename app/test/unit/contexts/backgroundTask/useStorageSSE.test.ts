import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useStorageSSE } from '@renderer/contexts/backgroundTask/useStorageSSE'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/client', () => ({
  getAuthToken: () => 'token-1',
}))

vi.mock('@renderer/api/auth', () => ({
  getCurrentUser: vi.fn(),
}))

class MockEventSource {
  static instances: MockEventSource[] = []

  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 1

  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }

  close = vi.fn(() => {
    this.readyState = 2
  })
}

describe('useStorageSSE', () => {
  const OriginalEventSource = globalThis.EventSource

  beforeEach(async () => {
    await i18n.changeLanguage('en-US')
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.stubGlobal('EventSource', OriginalEventSource)
    vi.useRealTimers()
  })

  it('hides only conversation cleanup and preserves other deletion lifecycle states', () => {
    const { result } = renderHook(() => useStorageSSE(false, true, true))
    const statuses = ['pending', 'processing', 'completed', 'failed', 'cancelled']
    const visibleTypes = ['delete_dataset', 'delete_wsis', 'delete_external', 'cleanup_empty_datasets', 'batch_import']
    const task = (task_type: string, status: string) => ({
      task_id: `${task_type}-${status}`, task_type, status,
      completed_at: new Date().toISOString(),
    })
    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({ items: [
          ...statuses.map(status => task('chat_delete', status)),
          ...visibleTypes.flatMap(type => statuses.map(status => task(type, status))),
        ] }),
      } as MessageEvent)
    })
    expect(result.current.storageTasks.map(task => task.items[0].id)).toEqual(
      visibleTypes.flatMap(type => statuses.map(status => `${type}-${status}`)),
    )
    expect(result.current.storageTasks.slice(0, 5).map(task => task.status)).toEqual(
      ['pending', 'running', 'success', 'error', 'cancelled'],
    )
  })

  it.each(['zh-CN', 'zh-HK'])('localizes storage task titles and item names in %s', async language => {
    await i18n.changeLanguage(language)
    const { result } = renderHook(() => useStorageSSE(false, true, true))
    const labels = {
      batch_update_metadata: 'metadataUpdate', cleanup_empty_datasets: 'cleanupEmptyDatasets',
      unbind_dataset: 'unbindDataset',
      scan_directory: 'scanDirectory', delete_wsis: 'deleteFiles', delete_external: 'deleteExternal',
    }
    const types = [...Object.keys(labels), 'batch_import', 'delete_dataset']
    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({ items: types.map(task_type => ({
          task_id: task_type, task_type, status: 'processing',
        })) }),
      } as MessageEvent)
    })
    for (const [index, type] of types.entries()) {
      const label = labels[type as keyof typeof labels]
      const key = label ? `backgroundTask.typeLabels.${label}` : 'listPage.dataset'
      const expected = i18n.t(key)
      expect(expected).not.toBe(key)
      expect(expected).toMatch(/[\u4e00-\u9fff]/)
      expect(result.current.storageTasks[index].title).toBe(expected)
      expect(result.current.storageTasks[index].items[0].name).toBe(expected)
    }
  })

  it('maps batch import dataset id from storage task params', async () => {
    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'task-1',
              task_type: 'batch_import',
              status: 'processing',
              progress: 30,
              total_items: 100,
              processed_items: 30,
              success_count: 30,
              failed_count: 0,
              skipped_count: 0,
              params: {
                dataset_id: 'training-dataset',
                dataset_name: 'Training Dataset',
              },
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(1))
    expect(result.current.storageTasks[0].datasetId).toBe('training-dataset')
  })

  it('does not render unknown scan totals as 0 of 0', async () => {
    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'scan-1',
              task_type: 'scan_directory',
              status: 'processing',
              progress: 0,
              total_items: 0,
              processed_items: 0,
              success_count: 0,
              failed_count: 0,
              skipped_count: 0,
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(1))
    expect(result.current.storageTasks[0].title).toBe('Scan Directory')
    expect(result.current.storageTasks[0].items[0].name).toBe('Scan Directory')
  })

  it('interpolates large delete_dataset processed_items smoothly toward backend target', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-1',
              task_type: 'delete_dataset',
              status: 'processing',
              progress: 0,
              total_items: 375806,
              processed_items: 0,
              success_count: 0,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'TestDataset' },
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(1))
    expect(result.current.storageTasks[0].title).toBe('TestDataset (0/375806)')

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-1',
              task_type: 'delete_dataset',
              status: 'processing',
              progress: 0.27,
              total_items: 375806,
              processed_items: 1000,
              success_count: 1000,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'TestDataset' },
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() =>
      expect(result.current.storageTasks[0].title).not.toBe('TestDataset (0/375806)')
    )

    const titleAfterUpdate = result.current.storageTasks[0].title
    const matchAfterUpdate = titleAfterUpdate.match(/\((\d+)\/375806\)/)
    expect(matchAfterUpdate).toBeTruthy()
    const displayedCountAfterUpdate = parseInt(matchAfterUpdate![1], 10)
    expect(displayedCountAfterUpdate).toBeGreaterThan(0)
    expect(displayedCountAfterUpdate).toBeLessThan(1000)
    expect(result.current.storageTasks[0].successCount).toBe(displayedCountAfterUpdate)

    act(() => {
      vi.advanceTimersByTime(4000)
    })

    await waitFor(() => {
      const title = result.current.storageTasks[0].title
      return title === 'TestDataset (1000/375806)'
    })

    expect(result.current.storageTasks[0].title).toBe('TestDataset (1000/375806)')
    expect(result.current.storageTasks[0].successCount).toBe(1000)
  })

  it('interpolates large delete_wsis processed_items smoothly toward backend target', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-wsi-1',
              task_type: 'delete_wsis',
              status: 'processing',
              progress: 0,
              total_items: 50000,
              processed_items: 0,
              success_count: 0,
              failed_count: 0,
              skipped_count: 0,
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(1))
    expect(result.current.storageTasks[0].title).toBe('Delete File(s) (0/50000)')

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-wsi-1',
              task_type: 'delete_wsis',
              status: 'processing',
              progress: 2,
              total_items: 50000,
              processed_items: 1000,
              success_count: 1000,
              failed_count: 0,
              skipped_count: 0,
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() =>
      expect(result.current.storageTasks[0].title).not.toBe('Delete File(s) (0/50000)')
    )

    const titleAfterUpdate = result.current.storageTasks[0].title
    const matchAfterUpdate = titleAfterUpdate.match(/\((\d+)\/50000\)/)
    expect(matchAfterUpdate).toBeTruthy()
    const displayedCountAfterUpdate = parseInt(matchAfterUpdate![1], 10)
    expect(displayedCountAfterUpdate).toBeGreaterThan(0)
    expect(displayedCountAfterUpdate).toBeLessThan(1000)
    expect(result.current.storageTasks[0].successCount).toBe(displayedCountAfterUpdate)

    act(() => {
      vi.advanceTimersByTime(4000)
    })

    await waitFor(() => {
      const title = result.current.storageTasks[0].title
      return title === 'Delete File(s) (1000/50000)'
    })

    expect(result.current.storageTasks[0].title).toBe('Delete File(s) (1000/50000)')
    expect(result.current.storageTasks[0].successCount).toBe(1000)
  })

  it('shows exact raw count for completed large delete tasks', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-1',
              task_type: 'delete_dataset',
              status: 'processing',
              progress: 50,
              total_items: 5000,
              processed_items: 2500,
              success_count: 2500,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'TestDataset' },
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(1))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-1',
              task_type: 'delete_dataset',
              status: 'completed',
              progress: 100,
              total_items: 5000,
              processed_items: 5000,
              success_count: 5000,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'TestDataset' },
              completed_at: new Date().toISOString(),
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() =>
      expect(result.current.storageTasks[0].title).toBe('TestDataset (5000/5000)')
    )

    expect(result.current.storageTasks[0].title).toBe('TestDataset (5000/5000)')
    expect(result.current.storageTasks[0].successCount).toBe(5000)
  })

  it('keeps small delete tasks and non-delete tasks with exact counts', async () => {
    const { result } = renderHook(() => useStorageSSE(false, true, true))

    act(() => {
      MockEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          items: [
            {
              task_id: 'del-small',
              task_type: 'delete_dataset',
              status: 'processing',
              progress: 50,
              total_items: 100,
              processed_items: 50,
              success_count: 50,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'SmallDataset' },
            },
            {
              task_id: 'import-1',
              task_type: 'batch_import',
              status: 'processing',
              progress: 30,
              total_items: 100,
              processed_items: 30,
              success_count: 7,
              failed_count: 0,
              skipped_count: 0,
              params: { dataset_name: 'ImportDataset' },
            },
          ],
        }),
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.storageTasks).toHaveLength(2))

    const deleteTask = result.current.storageTasks.find(t => t.id === 'delete_dataset_del-small')
    const importTask = result.current.storageTasks.find(t => t.id === 'import_import-1')

    expect(deleteTask!.title).toBe('SmallDataset (50/100)')
    expect(deleteTask!.successCount).toBe(50)
    expect(importTask!.title).toBe('ImportDataset (30/100)')
    expect(importTask!.successCount).toBe(7)
  })
})
