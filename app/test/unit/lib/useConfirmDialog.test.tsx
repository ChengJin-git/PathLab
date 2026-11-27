import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useConfirmDialog } from '@renderer/lib/hooks/useConfirmDialog'

describe('useConfirmDialog', () => {
  it('starts with dialog closed and empty title and message', () => {
    const { result } = renderHook(() => useConfirmDialog())
    expect(result.current.dialogState.isOpen).toBe(false)
    expect(result.current.dialogState.title).toBe('')
    expect(result.current.dialogState.message).toBe('')
  })

  it('showConfirmDialog opens the dialog with title, message and onConfirm', () => {
    const { result } = renderHook(() => useConfirmDialog())
    const onConfirm = vi.fn()

    act(() => {
      result.current.showConfirmDialog({ title: 'Delete?', message: 'Sure?', onConfirm })
    })

    expect(result.current.dialogState.isOpen).toBe(true)
    expect(result.current.dialogState.title).toBe('Delete?')
    expect(result.current.dialogState.message).toBe('Sure?')
    expect(result.current.dialogState.onConfirm).toBe(onConfirm)
  })

  it('showConfirmDialog includes optional confirmText and confirmVariant when provided', () => {
    const { result } = renderHook(() => useConfirmDialog())

    act(() => {
      result.current.showConfirmDialog({
        title: 'Warning',
        message: 'Proceed?',
        onConfirm: vi.fn(),
        confirmText: 'Yes, delete',
        confirmVariant: 'danger',
      })
    })

    expect(result.current.dialogState.confirmText).toBe('Yes, delete')
    expect(result.current.dialogState.confirmVariant).toBe('danger')
  })

  it('closeConfirmDialog resets the dialog back to closed state', () => {
    const { result } = renderHook(() => useConfirmDialog())

    act(() => {
      result.current.showConfirmDialog({ title: 'T', message: 'M', onConfirm: vi.fn() })
    })
    expect(result.current.dialogState.isOpen).toBe(true)

    act(() => { result.current.closeConfirmDialog() })

    expect(result.current.dialogState.isOpen).toBe(false)
    expect(result.current.dialogState.title).toBe('')
    expect(result.current.dialogState.message).toBe('')
  })

  it('allows re-opening after closing with different config', () => {
    const { result } = renderHook(() => useConfirmDialog())

    act(() => {
      result.current.showConfirmDialog({ title: 'First', message: 'Msg1', onConfirm: vi.fn() })
    })
    act(() => { result.current.closeConfirmDialog() })
    act(() => {
      result.current.showConfirmDialog({ title: 'Second', message: 'Msg2', onConfirm: vi.fn() })
    })

    expect(result.current.dialogState.isOpen).toBe(true)
    expect(result.current.dialogState.title).toBe('Second')
  })
})
