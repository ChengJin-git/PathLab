import React, { useState } from 'react'
import { FileSpreadsheet, Upload, AlertTriangle, CheckCircle, Loader2, X } from 'lucide-react'
import { uploadWSIByCSV, uploadDatasetSplits } from '../../api'

// Types for CSV action
export interface CSVCorrection {
  type: 'rename_column' | 'map_values'
  from?: string
  to?: string
  column?: string
  mapping?: Record<string, string>
}

export interface CSVValidation {
  status: 'valid' | 'correctable' | 'invalid'
  row_count?: number
  columns?: string[]
  issues?: string[]
}

export interface CSVActionConfig {
  action: 'upload' | 'correct_and_upload' | 'reject'
  csv_type?: 'wsi_registration' | 'split_config'
  dataset_name?: string
  dataset_id?: string
  corrections?: CSVCorrection[]
  validation?: CSVValidation
  reason?: string
  suggestions?: string[]
}

interface CSVActionCardProps {
  config: CSVActionConfig
  csvContent: string // The original CSV content from user upload
  fileName: string
  onSuccess?: (result: unknown) => void
  onError?: (error: string) => void
}

/**
 * Parse [CSV_ACTION] block from message content
 */
export function parseCSVAction(content: string): CSVActionConfig | null {
  const match = content.match(/\[CSV_ACTION\]([\s\S]*?)\[\/CSV_ACTION\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    console.error('Failed to parse CSV_ACTION JSON')
    return null
  }
}

/**
 * Remove [CSV_ACTION] block from content for display
 */
export function removeCSVActionBlock(content: string): string {
  return content.replace(/\[CSV_ACTION\][\s\S]*?\[\/CSV_ACTION\]/g, '').trim()
}

/**
 * Apply corrections to CSV content
 */
function applyCorrections(csvContent: string, corrections: CSVCorrection[]): string {
  const lines = csvContent.split('\n')
  if (lines.length === 0) return csvContent

  // Parse header
  const headerLine = lines[0]
  let headers = headerLine.split(',').map(h => h.trim())

  // Apply column renames
  for (const correction of corrections) {
    if (correction.type === 'rename_column' && correction.from && correction.to) {
      headers = headers.map(h => h.toLowerCase() === correction.from!.toLowerCase() ? correction.to! : h)
    }
  }

  // Rebuild CSV with corrected headers
  const correctedLines = [headers.join(',')]

  // Process data rows
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue

    const values = line.split(',')

    // Apply value mappings
    for (const correction of corrections) {
      if (correction.type === 'map_values' && correction.column && correction.mapping) {
        const colIndex = headers.findIndex(h => h.toLowerCase() === correction.column!.toLowerCase())
        if (colIndex >= 0 && values[colIndex]) {
          const originalValue = values[colIndex].trim().toLowerCase()
          const mappedValue = correction.mapping[originalValue]
          if (mappedValue) {
            values[colIndex] = mappedValue
          }
        }
      }
    }

    correctedLines.push(values.join(','))
  }

  return correctedLines.join('\n')
}

/**
 * CSV Action Card component - handles CSV upload with optional corrections
 */
export function CSVActionCard({ config, csvContent, fileName, onSuccess, onError }: CSVActionCardProps) {
  const [isUploading, setIsUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<'success' | 'error' | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Handle reject action - just show the message
  if (config.action === 'reject') {
    return (
      <div className="mt-3 p-4 bg-red-50 border border-red-200 rounded-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-medium text-red-800">Cannot Process This File</h4>
            <p className="text-sm text-red-600 mt-1">{config.reason}</p>
            {config.suggestions && config.suggestions.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-medium text-red-700">Suggestions:</p>
                <ul className="text-xs text-red-600 list-disc list-inside mt-1">
                  {config.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  const handleUpload = async () => {
    setIsUploading(true)
    setErrorMessage(null)

    try {
      // Apply corrections if needed
      let finalCSV = csvContent
      if (config.action === 'correct_and_upload' && config.corrections) {
        finalCSV = applyCorrections(csvContent, config.corrections)
      }

      // Create a File object from the corrected CSV
      const blob = new Blob([finalCSV], { type: 'text/csv' })
      const file = new File([blob], fileName.replace(/\.xlsx?$/i, '.csv'), { type: 'text/csv' })

      let result: unknown
      if (config.csv_type === 'wsi_registration') {
        result = await uploadWSIByCSV(file)
      } else if (config.csv_type === 'split_config' && config.dataset_id) {
        result = await uploadDatasetSplits(config.dataset_id, file)
      } else {
        throw new Error('Invalid CSV type or missing dataset_id')
      }

      setUploadResult('success')
      onSuccess?.(result)
    } catch (error) {
      setUploadResult('error')
      const msg = error instanceof Error ? error.message : 'Upload failed'
      setErrorMessage(msg)
      onError?.(msg)
    } finally {
      setIsUploading(false)
    }
  }

  // Success state
  if (uploadResult === 'success') {
    return (
      <div className="mt-3 p-4 bg-green-50 border border-green-200 rounded-xl">
        <div className="flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-green-500" />
          <div>
            <h4 className="font-medium text-green-800">Upload Successful</h4>
            <p className="text-sm text-green-600">
              {config.csv_type === 'wsi_registration'
                ? 'WSI files have been registered.'
                : 'Split configuration has been applied.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  // Error state
  if (uploadResult === 'error') {
    return (
      <div className="mt-3 p-4 bg-red-50 border border-red-200 rounded-xl">
        <div className="flex items-start gap-3">
          <X className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="font-medium text-red-800">Upload Failed</h4>
            <p className="text-sm text-red-600">{errorMessage}</p>
          </div>
        </div>
      </div>
    )
  }

  // Ready to upload state
  const isCorrection = config.action === 'correct_and_upload'

  return (
    <div className={`mt-3 p-4 rounded-xl border ${isCorrection ? 'bg-yellow-50 border-yellow-200' : 'bg-blue-50 border-blue-200'}`}>
      <div className="flex items-start gap-3">
        <FileSpreadsheet className={`w-5 h-5 flex-shrink-0 mt-0.5 ${isCorrection ? 'text-yellow-600' : 'text-blue-500'}`} />
        <div className="flex-1">
          <h4 className={`font-medium ${isCorrection ? 'text-yellow-800' : 'text-blue-800'}`}>
            {config.csv_type === 'wsi_registration' ? 'WSI Batch Registration' : 'Split Configuration'}
            {isCorrection && ' (with corrections)'}
          </h4>

          <div className="mt-2 text-sm space-y-1">
            <p className={isCorrection ? 'text-yellow-700' : 'text-blue-600'}>
              📄 <strong>{fileName}</strong> • {config.validation?.row_count || 0} rows
            </p>
            {config.dataset_name && (
              <p className={isCorrection ? 'text-yellow-700' : 'text-blue-600'}>
                📁 Dataset: <strong>{config.dataset_name}</strong>
              </p>
            )}
          </div>

          {/* Show corrections if any */}
          {isCorrection && config.validation?.issues && (
            <div className="mt-2 p-2 bg-yellow-100 rounded-lg">
              <p className="text-xs font-medium text-yellow-800">Corrections to apply:</p>
              <ul className="text-xs text-yellow-700 list-disc list-inside mt-1">
                {config.validation.issues.map((issue, i) => <li key={i}>{issue}</li>)}
              </ul>
            </div>
          )}

          {/* Upload button */}
          <button
            onClick={handleUpload}
            disabled={isUploading}
            className={`mt-3 px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-all
              ${isUploading ? 'bg-gray-300 text-gray-500 cursor-not-allowed' :
                isCorrection ? 'bg-yellow-500 text-white hover:bg-yellow-600' :
                'bg-blue-500 text-white hover:bg-blue-600'}`}
          >
            {isUploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="w-4 h-4" />
                {isCorrection ? 'Apply Corrections & Upload' : 'Upload to PathLab'}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

