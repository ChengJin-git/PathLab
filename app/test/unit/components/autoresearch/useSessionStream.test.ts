import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useSessionStream } from '@renderer/components/autoresearch/useSessionStream'
import { getAutoResearchEventsUrl } from '@renderer/api/autoresearch'

vi.mock('@renderer/api/autoresearch', () => ({ getAutoResearchEventsUrl: vi.fn() }))

class Stream {
  static instances: Stream[] = []
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor() { Stream.instances.push(this) }
}

const originalEventSource = globalThis.EventSource
afterEach(() => { cleanup(); globalThis.EventSource = originalEventSource; vi.clearAllMocks(); Stream.instances = [] })

it('drops events from a closed session after switching to another conversation', async () => {
  vi.stubGlobal('EventSource', Stream)
  vi.mocked(getAutoResearchEventsUrl).mockImplementation(async id => `/events/${id}`)
  const { result, rerender } = renderHook(({ id }) => useSessionStream(id), { initialProps: { id: 'alice-session' } })
  await waitFor(() => expect(Stream.instances).toHaveLength(1))
  const previous = Stream.instances[0]
  act(() => previous.onmessage?.({ data: JSON.stringify({ kind: 'message', seq: 1, message: {id: 'alice', type: 'assistant', text: 'Private Alice message'} }) } as MessageEvent))
  expect(result.current.events).toHaveLength(1)
  rerender({ id: 'bob-session' })
  await waitFor(() => expect(Stream.instances).toHaveLength(2))
  expect(previous.close).toHaveBeenCalled()
  act(() => previous.onmessage?.({ data: JSON.stringify({ kind: 'message', seq: 2, message: 'Late private Alice message' }) } as MessageEvent))
  expect(result.current.events).toEqual([])
})

it('retains prose through pause, resume and repeated snapshots with a stable cursor', async () => {
  vi.stubGlobal('EventSource', Stream)
  vi.mocked(getAutoResearchEventsUrl).mockImplementation(async id => `/events/${id}`)
  const { result, rerender } = renderHook(({ enabled }) => useSessionStream('research', enabled, 10), { initialProps: { enabled: true } })
  await waitFor(() => expect(Stream.instances).toHaveLength(1))
  const event = (seq: number, id: string, text: string) => ({data: JSON.stringify({kind: 'message', seq, message: {id, type: 'assistant', text}})} as MessageEvent)
  act(() => Stream.instances[0].onmessage?.(event(11, 'prose', 'Scientific question')))
  rerender({enabled: false})
  expect(result.current.events).toHaveLength(1)
  rerender({enabled: true})
  await waitFor(() => expect(Stream.instances).toHaveLength(2))
  expect(getAutoResearchEventsUrl).toHaveBeenLastCalledWith('research', 11)
  act(() => {
    for (let seq = 12; seq <= 700; seq++) Stream.instances[1].onmessage?.(event(seq, 'updated', `Progress ${seq}`))
  })
  expect(result.current.events).toHaveLength(2)
  expect(result.current.events[0].message).toMatchObject({text: 'Scientific question'})
  expect(result.current.events[1].message).toMatchObject({text: 'Progress 700'})
})
