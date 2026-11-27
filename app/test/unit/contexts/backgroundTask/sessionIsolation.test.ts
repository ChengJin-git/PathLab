import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useTrainingSSE } from '@renderer/contexts/backgroundTask/useTrainingSSE'
import { useAnalysisSSE } from '@renderer/contexts/backgroundTask/useAnalysisSSE'
import { useStorageSSE } from '@renderer/contexts/backgroundTask/useStorageSSE'

vi.mock('@renderer/api/client', () => ({ getAuthToken: () => 'token' }))
vi.mock('@renderer/api/auth', () => ({ getCurrentUser: vi.fn() }))
vi.mock('react-i18next', () => {
  const t = (key: string) => key
  return { useTranslation: () => ({ t }) }
})

class MockEventSource {
  static instances: MockEventSource[] = []
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()

  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }
}

const cases = [
  {
    name: 'training',
    useTasks: (loggedIn: boolean) => useTrainingSSE(loggedIn, true).trainingTasks,
    item: { task_id: 'task-1', task_name: 'Training', status: 'training', progress: 20 },
  },
  {
    name: 'analysis',
    useTasks: (loggedIn: boolean) => useAnalysisSSE(loggedIn, true).analysisTasks,
    item: { analysis_id: 'analysis-1', task_id: 'task-1', status: 'patching', progress: 20 },
  },
  {
    name: 'storage',
    useTasks: (loggedIn: boolean) => useStorageSSE(false, loggedIn, true).storageTasks,
    item: { task_id: 'storage-1', task_type: 'batch_import', status: 'processing', progress: 20 },
  },
]

describe.each(cases)('$name SSE session isolation', ({ useTasks, item }) => {
  const originalEventSource = globalThis.EventSource
  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })
  afterEach(() => vi.stubGlobal('EventSource', originalEventSource))

  it('does not subscribe when logged out even if a token remains', () => {
    const { result } = renderHook(() => useTasks(false))
    expect(MockEventSource.instances).toHaveLength(0)
    expect(result.current).toEqual([])
  })

  it('clears old tasks on logout and ignores late events after re-login', () => {
    const { result, rerender } = renderHook(({ loggedIn }) => useTasks(loggedIn), {
      initialProps: { loggedIn: true },
    })
    const oldSource = MockEventSource.instances[0]
    const message = { data: JSON.stringify({ items: [item] }) } as MessageEvent
    act(() => oldSource.onmessage?.(message))
    expect(result.current).toHaveLength(1)

    rerender({ loggedIn: false })
    expect(oldSource.close).toHaveBeenCalledOnce()
    expect(result.current).toEqual([])
    expect(MockEventSource.instances).toHaveLength(1)

    rerender({ loggedIn: true })
    expect(MockEventSource.instances).toHaveLength(2)
    act(() => oldSource.onmessage?.(message))
    expect(result.current).toEqual([])

    act(() => MockEventSource.instances[1].onmessage?.(message))
    expect(result.current).toHaveLength(1)
  })
})
