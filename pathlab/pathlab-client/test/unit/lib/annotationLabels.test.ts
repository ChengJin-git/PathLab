import { describe, expect, it } from 'vitest'
import { deriveAnnotationLabels, isMissingCurrentLabel } from '@renderer/lib/annotationLabels'
import type { AnnotationsMap } from '@renderer/api/annotation'

const annotations: AnnotationsMap = {
  slide_a: [
    { id: 'r1', type: 'rect', x: 0, y: 0, width: 10, height: 10, label: 'A', color: '#ef4444' },
    { id: 'r2', type: 'polygon', x: 0, y: 0, width: 10, height: 10, label: 'B', color: '#22c55e', points: [[0, 0], [10, 0], [10, 10]] },
  ],
}

describe('annotation label helpers', () => {
  it('derives labels from annotations and remembered labels without duplicates', () => {
    expect(deriveAnnotationLabels(annotations, ['B', 'C'])).toEqual(['A', 'B', 'C'])
  })

  it('detects when the current label is absent from the visible label set', () => {
    expect(isMissingCurrentLabel('A', ['A', 'B'])).toBe(false)
    expect(isMissingCurrentLabel('C', ['A', 'B'])).toBe(true)
    expect(isMissingCurrentLabel('', ['A', 'B'])).toBe(false)
  })

  it('returns empty array for empty annotations and empty remembered labels', () => {
    expect(deriveAnnotationLabels({}, [])).toEqual([])
  })

  it('ignores whitespace-only annotation labels and remembered labels', () => {
    const whitespaceAnnotations: AnnotationsMap = {
      slide_a: [
        { id: 'r1', type: 'rect', x: 0, y: 0, width: 10, height: 10, label: '  ', color: '#ef4444' },
        { id: 'r2', type: 'rect', x: 0, y: 0, width: 10, height: 10, label: 'Valid', color: '#22c55e' },
      ],
    }
    expect(deriveAnnotationLabels(whitespaceAnnotations, ['  ', 'AlsoValid'])).toEqual(['Valid', 'AlsoValid'])
  })

  it('deduplicates duplicate labels across annotations and remembered labels', () => {
    const dupAnnotations: AnnotationsMap = {
      slide_a: [
        { id: 'r1', type: 'rect', x: 0, y: 0, width: 10, height: 10, label: 'A', color: '#ef4444' },
        { id: 'r2', type: 'rect', x: 0, y: 0, width: 10, height: 10, label: 'A', color: '#ef4444' },
      ],
    }
    expect(deriveAnnotationLabels(dupAnnotations, ['A', 'B', 'B'])).toEqual(['A', 'B'])
  })

  it('returns false for isMissingCurrentLabel with whitespace-only current label', () => {
    expect(isMissingCurrentLabel('  ', ['A'])).toBe(false)
  })

  it('returns true for isMissingCurrentLabel when visible labels is empty', () => {
    expect(isMissingCurrentLabel('A', [])).toBe(true)
  })

  it('trims current label before checking isMissingCurrentLabel', () => {
    expect(isMissingCurrentLabel('  A  ', ['A'])).toBe(false)
  })

  it('supports mode-scoped remembered labels without cross-mode leakage', () => {
    const personalVisible = deriveAnnotationLabels(annotations, ['PersonalOnly'])
    const sharedVisible = deriveAnnotationLabels(annotations, ['SharedOnly'])

    expect(personalVisible).toContain('PersonalOnly')
    expect(personalVisible).not.toContain('SharedOnly')
    expect(sharedVisible).toContain('SharedOnly')
    expect(sharedVisible).not.toContain('PersonalOnly')
  })
})
