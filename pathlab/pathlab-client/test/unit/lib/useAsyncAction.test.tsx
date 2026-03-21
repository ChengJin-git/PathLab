import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAsyncAction } from '@renderer/lib/useAsyncAction'

describe('useAsyncAction', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('starts with isPending = false', () => {
    const { result } = renderHook(() => useAsyncAction())
    const [isPending] = result.current
    expect(isPending).toBe(false)
  })

  it('sets isPending = true while running, then false on success', async () => {
    let resolveFn!: () => void
    const promise = new Promise<void>((res) => { resolveFn = res })

    const { result } = renderHook(() => useAsyncAction())

    // Start the action — do NOT await yet
    let runPromise: Promise<unknown>
    act(() => {
      const [, run] = result.current
      runPromise = run(() => promise)
    })

    // While the promise is unresolved, isPending should be true
    expect(result.current[0]).toBe(true)

    // Resolve and wait
    await act(async () => {
      resolveFn()
      await runPromise
    })

    expect(result.current[0]).toBe(false)
  })

  it('returns the resolved value from run()', async () => {
    const { result } = renderHook(() => useAsyncAction<string>())
    let returnValue: string | undefined
    await act(async () => {
      const [, run] = result.current
      returnValue = await run(async () => 'hello')
    })
    expect(returnValue).toBe('hello')
  })

  it('sets isPending = false after fn throws', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useAsyncAction({ onError }))

    await act(async () => {
      const [, run] = result.current
      await run(async () => { throw new Error('boom') })
    })

    expect(result.current[0]).toBe(false)
  })

  it('calls onError with the thrown error', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useAsyncAction({ onError }))
    const err = new Error('test error')

    await act(async () => {
      const [, run] = result.current
      await run(async () => { throw err })
    })

    expect(onError).toHaveBeenCalledWith(err)
  })

  it('returns undefined when fn throws', async () => {
    const { result } = renderHook(() => useAsyncAction({ onError: vi.fn() }))
    let returnValue: string | undefined = 'initial'

    await act(async () => {
      const [, run] = result.current
      returnValue = await run(async (): Promise<string> => { throw new Error() })
    })

    expect(returnValue).toBeUndefined()
  })

  it('defaults to console.error when no onError provided', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { result } = renderHook(() => useAsyncAction())

    await act(async () => {
      const [, run] = result.current
      await run(async () => { throw new Error('default handler') })
    })

    expect(consoleSpy).toHaveBeenCalled()
  })

  it('two concurrent run() calls both complete independently', async () => {
    let resolve1!: () => void
    let resolve2!: () => void
    const p1 = new Promise<void>((r) => { resolve1 = r })
    const p2 = new Promise<void>((r) => { resolve2 = r })

    const { result } = renderHook(() => useAsyncAction())

    let run1Promise: Promise<unknown>
    let run2Promise: Promise<unknown>
    act(() => {
      const [, run] = result.current
      run1Promise = run(() => p1)
      run2Promise = run(() => p2)
    })

    // While both are pending, isPending is true
    expect(result.current[0]).toBe(true)

    // Resolve first
    await act(async () => {
      resolve1()
      await run1Promise
    })
    // Still pending (second in flight)
    expect(result.current[0]).toBe(true)

    // Resolve second
    await act(async () => {
      resolve2()
      await run2Promise
    })
    expect(result.current[0]).toBe(false)
  })
})
