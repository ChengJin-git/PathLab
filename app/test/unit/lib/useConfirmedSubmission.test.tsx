import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useConfirmedSubmission } from '@renderer/lib/hooks/useConfirmedSubmission'

describe('configuration confirmation lifecycle', () => {
  it('does not replay confirmation when an older card becomes the active target', () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const { rerender } = renderHook(({ trigger }: { trigger: number | undefined }) =>
      useConfirmedSubmission(trigger, true, false, submit), { initialProps: { trigger: undefined } as { trigger: number | undefined } })
    rerender({ trigger: 4 })
    expect(submit).not.toHaveBeenCalled()
    rerender({ trigger: 5 })
    expect(submit).toHaveBeenCalledTimes(1)
    rerender({ trigger: 5 })
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('drops a pending confirmation when a different card takes over', () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const { rerender } = renderHook(({ trigger, ready }: { trigger: number | undefined; ready: boolean }) =>
      useConfirmedSubmission(trigger, ready, false, submit), { initialProps: { trigger: 0, ready: false } as { trigger: number | undefined; ready: boolean } })
    rerender({ trigger: 1, ready: false })
    rerender({ trigger: undefined, ready: false })
    rerender({ trigger: undefined, ready: true })
    expect(submit).not.toHaveBeenCalled()
  })
})
