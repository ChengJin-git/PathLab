import Papa from 'papaparse'

export async function readFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') {
    return file.text()
  }

  if (typeof file.arrayBuffer === 'function') {
    const buffer = await file.arrayBuffer()
    return new TextDecoder().decode(buffer)
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file'))
    reader.readAsText(file)
  })
}

export async function xlsxToCSV(arrayBuffer: ArrayBuffer): Promise<{ sheetNames: string[]; csv: string }> {
  const {default:ExcelJS}=await import('exceljs')
  const workbook = new ExcelJS.Workbook()
  await workbook.xlsx.load(arrayBuffer)
  const sheetNames = workbook.worksheets.map((ws) => ws.name)
  const worksheet = workbook.worksheets[0]
  if (!worksheet) throw new Error('Workbook has no worksheets')
  const rowStrings: string[] = []
  const columns=worksheet.getRow(1).cellCount
  for(let index=1;index<=worksheet.rowCount;index++) {
    const row=worksheet.getRow(index)
    const cells: string[] = []
    for(let column=1;column<=columns;column++) {
      const cell=row.getCell(column)
      const v = cell.text
      cells.push(v.includes(',') || v.includes('"') || v.includes('\n') ? `"${v.replace(/"/g, '""')}"` : v)
    }
    rowStrings.push(cells.join(','))
    if(index%1000===0) await new Promise(resolve=>setTimeout(resolve,0))
  }
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
    const text = await readFileText(file)
    const result = Papa.parse<any>(text, { header: true, skipEmptyLines: true })
    jsonData = result.data
  } else {
    const {default:ExcelJS}=await import('exceljs')
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
