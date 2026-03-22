import { describe, it, expect } from 'vitest'
import { cn, formatBytes, formatFileSize, formatDateTime, formatDateCompact, formatUtcDate } from '@renderer/lib/utils'

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

describe('formatFileSize', () => {
  it('returns "0 B" for falsy values', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(null)).toBe('0 B')
    expect(formatFileSize(undefined)).toBe('0 B')
  })

  it('formats bytes without decimals', () => {
    expect(formatFileSize(512)).toBe('512 B')
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

describe('formatBytes (deprecated alias for formatFileSize)', () => {
  it('is identical to formatFileSize', () => {
    expect(formatBytes).toBe(formatFileSize)
  })

  it('handles null/undefined/0', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(null)).toBe('0 B')
    expect(formatBytes(undefined)).toBe('0 B')
  })

  it('formats sizes with adaptive precision', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB')
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.00 GB')
  })
})

describe('formatDateTime', () => {
  it('returns fallback "-" for null', () => {
    expect(formatDateTime(null)).toBe('-')
  })

  it('returns fallback "-" for undefined', () => {
    expect(formatDateTime(undefined)).toBe('-')
  })

  it('returns fallback "-" for empty string', () => {
    expect(formatDateTime('')).toBe('-')
  })

  it('accepts custom fallback', () => {
    expect(formatDateTime(null, '')).toBe('')
  })

  it('returns original string for unparseable input (passthrough)', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('handles +00:00Z mixed timezone string without throwing', () => {
    const result = formatDateTime('2026-01-15T10:30:00+00:00Z')
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
    expect(result).not.toBe('-')
    expect(result).not.toBe('2026-01-15T10:30:00+00:00Z')
  })

  it('returns a non-empty string for a valid ISO date', () => {
    const result = formatDateTime('2026-01-15T10:30:00Z')
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
    expect(result).not.toBe('-')
  })
})

describe('formatDateCompact', () => {
  it('returns "-" for null', () => {
    expect(formatDateCompact(null)).toBe('-')
  })

  it('returns "-" for undefined', () => {
    expect(formatDateCompact(undefined)).toBe('-')
  })

  it('returns original string for unparseable input', () => {
    expect(formatDateCompact('not-a-date')).toBe('not-a-date')
  })

  it('returns a YYYY-MM-DD HH:mm:ss formatted string for a valid ISO date', () => {
    const result = formatDateCompact('2026-01-15T10:30:00Z')
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
  })
})

describe('formatUtcDate', () => {
  it('returns fallback for null', () => {
    expect(formatUtcDate(null)).toBe('-')
  })

  it('accepts custom locale', () => {
    const result = formatUtcDate('2026-01-15T10:30:00Z', 'zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
    })
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })
})
