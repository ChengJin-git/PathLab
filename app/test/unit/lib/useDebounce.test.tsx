import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useDebounce } from '@renderer/lib/hooks/useDebounce'

describe('useDebounce', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('returns the initial value immediately without waiting for delay', () => {
    const { result } = renderHook(() => useDebounce('hello', 300))
    expect(result.current).toBe('hello')
  })

  it('does not update before the delay has elapsed', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'initial' } }
    )
    rerender({ value: 'updated' })
    act(() => { vi.advanceTimersByTime(299) })
    expect(result.current).toBe('initial')
  })

  it('updates to the new value once the delay has elapsed', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'initial' } }
    )
    rerender({ value: 'updated' })
    act(() => { vi.advanceTimersByTime(300) })
    expect(result.current).toBe('updated')
  })

  it('debounces rapid changes — only the last value is emitted after the delay', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'initial' } }
    )

    rerender({ value: 'first' })
    act(() => { vi.advanceTimersByTime(200) })
    expect(result.current).toBe('initial')

    rerender({ value: 'second' })
    act(() => { vi.advanceTimersByTime(200) })
    expect(result.current).toBe('initial')

    act(() => { vi.advanceTimersByTime(100) })
    expect(result.current).toBe('second')
  })

  it('works with numeric values', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: number }) => useDebounce(value, 200),
      { initialProps: { value: 0 } }
    )
    rerender({ value: 42 })
    act(() => { vi.advanceTimersByTime(200) })
    expect(result.current).toBe(42)
  })
})
