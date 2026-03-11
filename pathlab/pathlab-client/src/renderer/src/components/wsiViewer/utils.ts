import { HeatmapPoint, buildAuthRequestInit, downloadBlobFile, getPatchImageUrl } from '../../api'

/**
 * Export patches as a ZIP file containing images
 */
export async function exportPatchesAsZip(
  wsi_id: string,
  patches: HeatmapPoint[],
  prefix: string,
  fileName: string
) {
  // Dynamically import JSZip
  const JSZip = (await import('jszip')).default
  const zip = new JSZip()

  // Download all patch images
  const authRequestInit = buildAuthRequestInit()
  const downloadPromises = patches.map(async (patch, idx) => {
    const url = getPatchImageUrl(wsi_id, patch.x, patch.y, 256)
    try {
      const response = await fetch(url, authRequestInit)
      if (response.ok) {
        const blob = await response.blob()
        const paddedIdx = String(idx + 1).padStart(2, '0')
        const attention = (patch.weight * 100).toFixed(1)
        zip.file(`${prefix}_${paddedIdx}_attn${attention}_x${patch.x}_y${patch.y}.png`, blob)
      }
    } catch (err) {
      console.error(`Failed to download patch ${idx}:`, err)
    }
  })

  await Promise.all(downloadPromises)

  // Generate and download the ZIP file
  const content = await zip.generateAsync({ type: 'blob' })
  downloadBlobFile(content, fileName)
}

/**
 * Format classes for display
 * - 2 classes: "A vs B"
 * - 3 classes: "A, B, C"
 * - >3 classes: "A, B, C +N more"
 */
export function formatClasses(classes: string[] | null | undefined, maxShow: number = 3): string | null {
  if (!classes || classes.length === 0) return null
  if (classes.length === 2) {
    return classes.join(' vs ')
  }
  if (classes.length <= maxShow) {
    return classes.join(', ')
  }
  const shown = classes.slice(0, maxShow)
  const remaining = classes.length - maxShow
  return `${shown.join(', ')} +${remaining} more`
}

