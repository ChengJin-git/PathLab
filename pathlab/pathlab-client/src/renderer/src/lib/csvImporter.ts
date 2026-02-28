import * as XLSX from 'xlsx'

/**
 * Parse a CSV/XLSX file and return a Map of filename -> metadata row.
 * Keys are lowercased for case-insensitive matching.
 * For each filename, both the full name and name-without-extension are stored.
 */
export async function parseCsvMetadata(file: File): Promise<Map<string, any>> {
  const csvMetadataMap = new Map<string, any>()

  const arrayBuffer = await file.arrayBuffer()
  const workbook = XLSX.read(arrayBuffer, { type: 'array' })
  const sheet = workbook.Sheets[workbook.SheetNames[0]]
  const jsonData = XLSX.utils.sheet_to_json(sheet) // Array of objects

  jsonData.forEach((row: any) => {
    // Normalize keys
    const normRow: any = {}
    Object.keys(row).forEach(k => normRow[k.toLowerCase().trim()] = row[k])

    if (normRow.filename) {
      const name = String(normRow.filename).trim()
      // Map full name (e.g. "slide1.svs")
      csvMetadataMap.set(name.toLowerCase(), normRow)
      // Map name without extension (e.g. "slide1" -> match "slide1.svs")
      // This handles cases where CSV lists "slide1" but file is "slide1.svs"
      const nameNoExt = name.replace(/\.[^/.]+$/, "")
      if (nameNoExt !== name) {
        csvMetadataMap.set(nameNoExt.toLowerCase(), normRow)
      }
    }
  })

  return csvMetadataMap
}

