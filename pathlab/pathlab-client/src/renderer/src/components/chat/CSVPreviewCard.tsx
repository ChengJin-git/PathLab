import React from 'react'
import { FileSpreadsheet } from 'lucide-react'

interface CSVPreviewCardProps {
  fileName: string
  fileType: 'csv' | 'xlsx'
  preview: string[] // First few lines of CSV
  totalRows: number
}

/**
 * Parse CSV preview block from user message content
 * Format: [CSV_PREVIEW]{"fileName":"...", "fileType":"...", "preview":[...], "totalRows":...}[/CSV_PREVIEW]
 */
export function parseCSVPreview(content: string): CSVPreviewCardProps | null {
  const match = content.match(/\[CSV_PREVIEW\]([\s\S]*?)\[\/CSV_PREVIEW\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    console.error('Failed to parse CSV_PREVIEW JSON')
    return null
  }
}

/**
 * Remove [CSV_PREVIEW] block from content for display
 */
export function removeCSVPreviewBlock(content: string): string {
  return content.replace(/\[CSV_PREVIEW\][\s\S]*?\[\/CSV_PREVIEW\]/g, '').trim()
}

/**
 * CSVPreviewCard - Beautiful table display for uploaded CSV files
 */
export function CSVPreviewCard({ fileName, fileType, preview, totalRows }: CSVPreviewCardProps) {
  // Parse CSV lines into table data
  const lines = preview.filter(line => line.trim())
  if (lines.length === 0) return null

  const headers = lines[0].split(',').map(h => h.trim())
  const dataRows = lines.slice(1).map(line => {
    const values = line.split(',').map(v => v.trim())
    // Pad with empty strings if fewer values than headers
    while (values.length < headers.length) values.push('')
    return values
  })

  const displayType = fileType === 'xlsx' ? 'Excel' : 'CSV'
  const dataRowCount = totalRows - 1 // Exclude header

  return (
    <div className="my-3 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gradient-to-r from-slate-50 to-slate-100 border-b border-slate-200 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
          <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-800 truncate">{fileName}</p>
          <p className="text-xs text-slate-500">{displayType} • {dataRowCount} rows</p>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50">
              {headers.map((header, i) => (
                <th
                  key={i}
                  className="px-4 py-2 text-left text-xs font-semibold text-slate-600 uppercase tracking-wider border-b border-slate-200"
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataRows.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}
              >
                {row.map((cell, cellIdx) => (
                  <td
                    key={cellIdx}
                    className="px-4 py-2 text-slate-700 border-b border-slate-100 whitespace-nowrap"
                  >
                    {cell || <span className="text-slate-300">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {dataRows.length < dataRowCount && (
        <div className="px-4 py-2 bg-slate-50 border-t border-slate-200 text-center">
          <p className="text-xs text-slate-500">
            Showing {dataRows.length} of {dataRowCount} rows
          </p>
        </div>
      )}
    </div>
  )
}

