import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useStorageSSE } from '@renderer/contexts/backgroundTask/useStorageSSE'

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

  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.stubGlobal('EventSource', OriginalEventSource)
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
})
