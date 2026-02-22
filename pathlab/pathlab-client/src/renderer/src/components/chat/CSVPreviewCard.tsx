import React from 'react'
import { useTranslation } from 'react-i18next'
import { FileSpreadsheet } from 'lucide-react'

interface CSVPreviewCardProps {
  fileName: string
  fileType: 'csv' | 'xlsx'
  preview: string[]
  totalRows: number
}

function parseCSVLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i++) {
    const char = line[i]

    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"'
        i++
      } else {
        inQuotes = !inQuotes
      }
    } else if (char === ',' && !inQuotes) {
      result.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }

  result.push(current.trim())

  return result
}

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

export function removeCSVPreviewBlock(content: string): string {
  return content.replace(/\[CSV_PREVIEW\][\s\S]*?\[\/CSV_PREVIEW\]/g, '').trim()
}

export function CSVPreviewCard({ fileName, fileType, preview, totalRows }: CSVPreviewCardProps) {
  const { t } = useTranslation()

  const lines = preview.filter(line => line.trim())
  if (lines.length === 0) return null

  const headers = parseCSVLine(lines[0])
  const dataRows = lines.slice(1).map(line => {
    const values = parseCSVLine(line)
    while (values.length < headers.length) values.push('')
    return values
  })

  const displayType = fileType === 'xlsx' ? 'Excel' : 'CSV'
  const dataRowCount = totalRows - 1

  return (
    <div className="my-3 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-4 py-3 bg-gradient-to-r from-slate-50 to-slate-100 border-b border-slate-200 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
          <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-800 truncate">{fileName}</p>
          <p className="text-xs text-slate-500">{displayType} • {t('chatComponents.csvPreview.rowCount', { count: dataRowCount })}</p>
        </div>
      </div>

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

      {dataRows.length < dataRowCount && (
        <div className="px-4 py-2 bg-slate-50 border-t border-slate-200 text-center">
          <p className="text-xs text-slate-500">
            {t('chatComponents.csvPreview.showingRows', { showing: dataRows.length, total: dataRowCount })}
          </p>
        </div>
      )}
    </div>
  )
}
