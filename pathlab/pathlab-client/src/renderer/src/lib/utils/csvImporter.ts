import ExcelJS from 'exceljs'
import Papa from 'papaparse'

export async function xlsxToCSV(arrayBuffer: ArrayBuffer): Promise<{ sheetNames: string[]; csv: string }> {
  const workbook = new ExcelJS.Workbook()
  await workbook.xlsx.load(arrayBuffer)
  const sheetNames = workbook.worksheets.map((ws) => ws.name)
  const worksheet = workbook.worksheets[0]
  const rowStrings: string[] = []
  worksheet.eachRow((row) => {
    const cells: string[] = []
    row.eachCell({ includeEmpty: true }, (cell) => {
      const v = String(cell.value ?? '')
      cells.push(v.includes(',') || v.includes('"') || v.includes('\n') ? `"${v.replace(/"/g, '""')}"` : v)
    })
    rowStrings.push(cells.join(','))
  })
  return { sheetNames, csv: rowStrings.join('\n') }
}

/**
 * Parse a CSV/XLSX file and return a Map of filename -> metadata row.
 * Keys are lowercased for case-insensitive matching.
 * For each filename, both the full name and name-without-extension are stored.
 */
export async function parseCsvMetadata(file: File): Promise<Map<string, any>> {
  const csvMetadataMap = new Map<string, any>()
  let jsonData: any[] = []

  if (file.name.toLowerCase().endsWith('.csv')) {
    // PapaParse: actively maintained, no known vulnerabilities, zero dependencies
    const text = await file.text()
    const result = Papa.parse<any>(text, { header: true, skipEmptyLines: true })
    jsonData = result.data
  } else {
    // ExcelJS: handles .xlsx / .xls from ArrayBuffer, works in browser/Electron renderer
    const arrayBuffer = await file.arrayBuffer()
    const workbook = new ExcelJS.Workbook()
    await workbook.xlsx.load(arrayBuffer)
    const worksheet = workbook.worksheets[0]

    // Read header row
    const headers: string[] = []
    worksheet.getRow(1).eachCell((cell) => {
      headers.push(String(cell.value ?? ''))
    })

    // Read data rows
    worksheet.eachRow((row, rowNumber) => {
      if (rowNumber === 1) return // skip header
      const obj: any = {}
      row.eachCell((cell, colNumber) => {
        obj[headers[colNumber - 1]] = cell.value
      })
      jsonData.push(obj)
    })
  }

  jsonData.forEach((row: any) => {
    // Normalize keys
    const normRow: any = {}
    Object.keys(row).forEach((k) => (normRow[k.toLowerCase().trim()] = row[k]))

    if (normRow.filename) {
      const name = String(normRow.filename).trim()
      // Map full name (e.g. "slide1.svs")
      csvMetadataMap.set(name.toLowerCase(), normRow)
      // Map name without extension (e.g. "slide1" -> match "slide1.svs")
      // This handles cases where CSV lists "slide1" but file is "slide1.svs"
      const nameNoExt = name.replace(/\.[^/.]+$/, '')
      if (nameNoExt !== name) {
        csvMetadataMap.set(nameNoExt.toLowerCase(), normRow)
      }
    }
  })

  return csvMetadataMap
}
