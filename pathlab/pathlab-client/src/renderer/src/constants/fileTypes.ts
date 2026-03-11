/**
 * File Type Constants
 *
 * Centralized file extension definitions for WSI and patch image files.
 * Keep extension lists and TIFF fallback threshold in sync with the backend.
 * Note: authoritative TIFF classification happens in the backend, where ASlide
 * can inspect pyramid levels and metadata. The frontend only keeps a lightweight
 * size-based fallback heuristic for local UI decisions.
 */

// WSI file extensions (excluding .tif/.tiff which need size check)
// These are always treated as WSI files regardless of size
export const WSI_EXTENSIONS: readonly string[] = [
  '.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif',
  '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap',
  '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax',
  '.dyj', '.dyqx', '.ibl', '.zyp',
] as const

// Patch/image file extensions (excluding .tif/.tiff which need size check)
// These are always treated as patch files regardless of size
export const PATCH_EXTENSIONS: readonly string[] = [
  '.jpg', '.jpeg', '.png', '.bmp',
] as const

// TIFF extensions that use a lightweight frontend size-based fallback
export const TIF_EXTENSIONS: readonly string[] = [
  '.tif', '.tiff',
] as const

// File size threshold for determining WSI vs Patch for .tif/.tiff files (32 MB)
export const SIZE_THRESHOLD = 32 * 1024 * 1024

// All supported extensions (WSI + TIF + Patch)
export const ALL_EXTENSIONS: readonly string[] = [
  ...WSI_EXTENSIONS,
  ...TIF_EXTENSIONS,
  ...PATCH_EXTENSIONS,
] as const

/**
 * Generate an HTML accept string for file inputs.
 * Includes all WSI + TIF extensions (no patch extensions for WSI-only inputs).
 */
export const WSI_ACCEPT_STRING = [...WSI_EXTENSIONS, ...TIF_EXTENSIONS].join(',')

/**
 * Generate an HTML accept string for file inputs.
 * Includes all supported extensions (WSI + TIF + Patch).
 */
export const ALL_ACCEPT_STRING = ALL_EXTENSIONS.join(',')

// ============================================================================
// File Name Utilities
// ============================================================================

/** Check if a filename has a supported extension */
export function isSupportedName(name: string): boolean {
  const normalized = name.toLowerCase()
  return ALL_EXTENSIONS.some(ext => normalized.endsWith(ext))
}

/** Determine whether a file should be treated as a WSI or Patch */
export function getFileType(
  fileExtension: string | null,
  fileSize: number | null,
  authoritativeDataType?: 'wsi' | 'patch' | null,
): 'WSI' | 'Patch' {
  if (authoritativeDataType === 'wsi') return 'WSI'
  if (authoritativeDataType === 'patch') return 'Patch'
  if (!fileExtension) return 'WSI'
  const ext = fileExtension.toLowerCase()

  if (PATCH_EXTENSIONS.includes(ext)) return 'Patch'

  if (TIF_EXTENSIONS.includes(ext)) {
    return (fileSize || 0) >= SIZE_THRESHOLD ? 'WSI' : 'Patch'
  }

  return 'WSI'
}

/** Check if a filename is a TMAP data file (.dt0, .dt1, etc.) */
export function isTmapDataFile(name: string): boolean {
  return /\.dt\d+$/i.test(name.toLowerCase())
}

/** Get filename without extension */
export function getBaseName(name: string): string {
  const lastDot = name.lastIndexOf('.')
  return lastDot > 0 ? name.substring(0, lastDot) : name
}

/** Get Electron file path from File object */
export function getFilePath(file: File): string | undefined {
  return (file as any).path as string | undefined
}

