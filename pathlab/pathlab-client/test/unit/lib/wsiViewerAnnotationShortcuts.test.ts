import { describe, expect, it } from 'vitest'
import { getLabelFromDigitShortcut, isEditableTarget } from '@renderer/lib/wsiViewerAnnotationShortcuts'

describe('wsiViewerAnnotationShortcuts', () => {
  it('maps Digit1..Digit9 codes to visible labels', () => {
    const labels = ['A', 'B', 'C']
    expect(getLabelFromDigitShortcut('Digit1', labels)).toBe('A')
    expect(getLabelFromDigitShortcut('Digit3', labels)).toBe('C')
    expect(getLabelFromDigitShortcut('Digit9', labels)).toBeNull()
  })

  it('accepts key values 1..9 as fallback', () => {
    const labels = ['A', 'B']
    expect(getLabelFromDigitShortcut('', labels, '2')).toBe('B')
    expect(getLabelFromDigitShortcut('', labels, '9')).toBeNull()
  })

  it('returns true for input, textarea, and contenteditable targets', () => {
    const input = document.createElement('input')
    const textarea = document.createElement('textarea')
    const div = document.createElement('div')
    div.setAttribute('contenteditable', 'true')

    expect(isEditableTarget(input)).toBe(true)
    expect(isEditableTarget(textarea)).toBe(true)
    expect(isEditableTarget(div)).toBe(true)
  })

  it('returns false for non-editable elements and null target', () => {
    expect(isEditableTarget(document.createElement('button'))).toBe(false)
    expect(isEditableTarget(null)).toBe(false)
  })
})
