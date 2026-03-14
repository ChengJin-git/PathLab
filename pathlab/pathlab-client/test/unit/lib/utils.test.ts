import { describe, it, expect } from 'vitest'
import { cn, formatBytes, formatFileSize } from '@renderer/lib/utils'

describe('cn (class name merger)', () => {
  it('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('deduplicates Tailwind classes (tailwind-merge)', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4')
  })

  it('handles conditional classes', () => {
    expect(cn('base', false && 'hidden', 'visible')).toBe('base visible')
  })

  it('handles undefined and null gracefully', () => {
    expect(cn('a', undefined, null as unknown as string, 'b')).toBe('a b')
  })
})

describe('formatBytes', () => {
  it('returns "0 B" for falsy values', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(null)).toBe('0 B')
    expect(formatBytes(undefined)).toBe('0 B')
  })

  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512.00 B')
  })

  it('formats kilobytes', () => {
    expect(formatBytes(1024)).toBe('1.00 KB')
    expect(formatBytes(1536)).toBe('1.50 KB')
  })

  it('formats megabytes', () => {
    expect(formatBytes(1024 * 1024)).toBe('1.00 MB')
  })

  it('formats gigabytes', () => {
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.00 GB')
  })
})

describe('formatFileSize', () => {
  it('formats bytes without decimals', () => {
    expect(formatFileSize(500)).toBe('500 B')
    expect(formatFileSize(1023)).toBe('1023 B')
  })

  it('formats kilobytes with 1 decimal', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
  })

  it('formats megabytes with 1 decimal', () => {
    expect(formatFileSize(1024 * 1024)).toBe('1.0 MB')
    expect(formatFileSize(1024 * 1024 * 1.5)).toBe('1.5 MB')
  })

  it('formats gigabytes with 2 decimals', () => {
    expect(formatFileSize(1024 * 1024 * 1024)).toBe('1.00 GB')
    expect(formatFileSize(1024 * 1024 * 1024 * 2.5)).toBe('2.50 GB')
  })
})
