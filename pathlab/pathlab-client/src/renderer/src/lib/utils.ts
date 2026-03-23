import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format a byte count into a human-readable string with adaptive decimal precision.
 *
 * - null / undefined / 0 → "0 B"
 * - B:    no decimals  (e.g. "512 B")
 * - KB / MB: 1 decimal (e.g. "1.5 KB", "3.2 MB")
 * - GB+:  2 decimals   (e.g. "1.25 GB")
 */
export function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes === 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}



// ────────────────────────────────────────────────────────────────────────────
// Date formatting utilities
// ────────────────────────────────────────────────────────────────────────────

/**
 * Normalize a backend UTC date string before parsing.
 *
 * The backend occasionally emits strings like "2026-01-15T10:30:00+00:00Z"
 * (both +00:00 and Z present), which `new Date()` may refuse to parse.
 * This function strips the redundant suffix and ensures a bare UTC string
 * gets a trailing Z so browsers parse it as UTC.
 */
function _normalizeUtcString(dateStr: string): string {
  // Remove +00:00Z hybrid (keep the Z only)
  const sanitized = dateStr.replace(/\+00:00Z$/, 'Z')
  // If there is no timezone info at all, treat as UTC
  if (!sanitized.endsWith('Z') && !sanitized.includes('+') && !sanitized.includes('-', 10)) {
    return `${sanitized}Z`
  }
  return sanitized
}

/**
 * Format a backend UTC date string for display.
 *
 * - null/undefined/empty → returns `fallback` (default `'-'`)
 * - Unparseable string   → returns the original string as-is (passthrough)
 * - Valid date           → returns `new Date(...).toLocaleString(locale, options)`
 *
 * @param dateStr  ISO 8601 string from the backend (may contain +00:00Z hybrid).
 * @param locale   BCP 47 locale tag (e.g. 'en-US', 'zh-CN'). Defaults to 'en-US'.
 * @param options  Intl.DateTimeFormatOptions passed to toLocaleString.
 * @param fallback Returned for null/undefined/empty input. Defaults to '-'.
 *
 * NOTE: `locale` is a separate param because Intl.DateTimeFormatOptions cannot
 * carry locale — it is a distinct argument to toLocaleString().
 */
export function formatUtcDate(
  dateStr: string | null | undefined,
  locale: string = 'en-US',
  options?: Intl.DateTimeFormatOptions,
  fallback: string = '-'
): string {
  if (!dateStr) return fallback
  const normalized = _normalizeUtcString(dateStr)
  const date = new Date(normalized)
  if (isNaN(date.getTime())) return dateStr
  return date.toLocaleString(locale, options)
}

/**
 * Format as a locale timestamp, e.g. "Jan 15, 2026, 10:30 AM" (en-US).
 * Suitable for most UI timestamps.
 *
 * - null/undefined/empty → returns `fallback` (default `'-'`)
 * - Unparseable string   → passthrough
 */
export function formatDateTime(
  dateStr: string | null | undefined,
  fallback: string = '-'
): string {
  if (!dateStr) return fallback
  const normalized = _normalizeUtcString(dateStr)
  const date = new Date(normalized)
  if (isNaN(date.getTime())) return dateStr
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Compact local-time format: "YYYY-MM-DD HH:mm:ss".
 * Outputs LOCAL time (matches AnnotationAuditCard's existing getHours() behavior).
 *
 * - null/undefined → returns '-'
 * - Unparseable string → passthrough
 */
export function formatDateCompact(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  const normalized = _normalizeUtcString(dateStr)
  const d = new Date(normalized)
  if (isNaN(d.getTime())) return dateStr
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
