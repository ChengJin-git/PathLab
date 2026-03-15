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

/**
 * @deprecated Use {@link formatFileSize} instead — identical behavior.
 */
export const formatBytes = formatFileSize
