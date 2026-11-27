import React, { useState } from 'react'
import { useAsyncAction } from '../../lib/hooks/useAsyncAction'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FileSpreadsheet, Upload, AlertTriangle, CheckCircle, Loader2, X, ArrowRight } from 'lucide-react'
import { uploadWSIByCSV, uploadDatasetSplits } from '../../api'

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
  labels_found?: string[]
}

export interface CSVActionConfig {
  action: 'upload' | 'correct_and_upload' | 'reject' | 'navigate_with_csv'
  csv_type?: 'wsi_registration' | 'split_config'
  dataset_name?: string
  dataset_id?: string
  upload_mode?: 'classification' | 'survival' | 'segmentation'
  aggregation_level?: 'case' | 'file'
  generate_split?: boolean
  corrections?: CSVCorrection[]
  validation?: CSVValidation
  reason?: string
  suggestions?: string[]
}

interface CSVActionCardProps {
  config: CSVActionConfig
  csvContent: string
  fileName: string
  onSuccess?: (result: unknown) => void
  onError?: (error: string) => void
}

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

export function removeCSVActionBlock(content: string): string {
  return content.replace(/\[CSV_ACTION\][\s\S]*?\[\/CSV_ACTION\]/g, '').trim()
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

function toCSVLine(values: string[]): string {
  return values.map(v => {
    if (v.includes(',') || v.includes('"') || v.includes('\n')) {
      return `"${v.replace(/"/g, '""')}"`
    }
    return v
  }).join(',')
}

function applyCorrections(csvContent: string, corrections: CSVCorrection[]): string {
  const lines = csvContent.split('\n')
  if (lines.length === 0) return csvContent

  const headerLine = lines[0]
  let headers = parseCSVLine(headerLine)

  for (const correction of corrections) {
    if (correction.type === 'rename_column' && correction.from && correction.to) {
      headers = headers.map(h => h.toLowerCase() === correction.from!.toLowerCase() ? correction.to! : h)
    }
  }

  const correctedLines = [toCSVLine(headers)]

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line) continue

    const values = parseCSVLine(line)

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

    correctedLines.push(toCSVLine(values))
  }

  return correctedLines.join('\n')
}

function generateSplit(csvContent: string): string {
  const lines = csvContent.split('\n')
  if (lines.length < 2) return csvContent

  const headerLine = lines[0]
  const headers = parseCSVLine(headerLine).map(h => h.toLowerCase())

  const splitIndex = headers.findIndex(h => h === 'split')

  const dataRows = lines.slice(1).filter(line => line.trim())

  const shuffled = [...dataRows]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }

  const total = shuffled.length
  const trainEnd = Math.floor(total * 0.7)
  const valEnd = Math.floor(total * 0.8)

  const rowsWithSplit = shuffled.map((row, idx) => {
    let split: string
    if (idx < trainEnd) split = 'train'
    else if (idx < valEnd) split = 'val'
    else split = 'test'

    const values = parseCSVLine(row)

    if (splitIndex >= 0) {
      values[splitIndex] = split
    } else {
      values.push(split)
    }

    return toCSVLine(values)
  })

  const headerValues = parseCSVLine(headerLine)
  if (splitIndex < 0) {
    headerValues.push('split')
  }
  const newHeader = toCSVLine(headerValues)

  return [newHeader, ...rowsWithSplit].join('\n')
}

export function CSVActionCard({ config, csvContent, fileName, onSuccess, onError }: CSVActionCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [isUploading, runUploading] = useAsyncAction<void>({
    onError: (err) => {
      setUploadResult('error')
      const msg = err instanceof Error ? err.message : t('chatComponents.csvAction.uploadFailed')
      setErrorMessage(msg)
      onError?.(msg)
    }
  })
  const [uploadResult, setUploadResult] = useState<'success' | 'error' | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  if (config.action === 'reject') {
    return (
      <div className="mt-3 p-4 bg-red-50 border border-red-200 rounded-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-medium text-red-800">{t('chatComponents.csvAction.cannotProcess')}</h4>
            <p className="text-sm text-red-600 mt-1">{config.reason}</p>
            {config.suggestions && config.suggestions.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-medium text-red-700">{t('chatComponents.csvAction.suggestions')}:</p>
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

  if (config.action === 'navigate_with_csv') {
    const [isProcessing, setIsProcessing] = useState(false)

    const handleNavigate = () => {
      setIsProcessing(true)

      setTimeout(() => {
        try {
          let finalCSV = csvContent
          if (config.corrections && config.corrections.length > 0) {
            finalCSV = applyCorrections(csvContent, config.corrections)
          }

          if (config.generate_split) {
            finalCSV = generateSplit(finalCSV)
          }

          const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
          if (conversationId) {
            sessionStorage.setItem('ai-chat-conversation-id', conversationId)
          }

          navigate('/upload', {
            state: {
              datasetName: config.dataset_name,
              uploadMode: config.upload_mode || 'classification',
              dataLevel: config.aggregation_level || 'file',
              csvContent: finalCSV,
              csvFileName: fileName.replace(/\.xlsx?$/i, '.csv'),
              fromAIChat: true
            }
          })
        } catch (error) {
          console.error('Error processing CSV:', error)
          setIsProcessing(false)
        }
      }, 50)
    }

    const hasCorrections = config.corrections && config.corrections.length > 0

    return (
      <div className="mt-3 p-4 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-xl">
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <h4 className="font-medium text-green-800">{t('chatComponents.csvAction.fileReadyForRegistration')}</h4>

            <div className="mt-2 text-sm space-y-1">
              <p className="text-green-700">
                📄 <strong>{fileName}</strong> • {config.validation?.row_count || 0} {t('chatComponents.csvAction.rows')}
              </p>
              {config.dataset_name && (
                <p className="text-green-700">
                  📁 {t('chatComponents.csvAction.dataset')}: <strong>{config.dataset_name}</strong>
                </p>
              )}
              {config.upload_mode && (
                <p className="text-green-700">
                  🎯 {t('chatComponents.csvAction.type')}: <strong className="capitalize">{config.upload_mode}</strong>
                </p>
              )}
              {config.validation?.labels_found && config.validation.labels_found.length > 0 && (
                <p className="text-green-700">
                  🏷️ {t('chatComponents.csvAction.labels')}: <strong>{config.validation.labels_found.join(', ')}</strong>
                </p>
              )}
            </div>

            <div className="mt-3 p-2 bg-green-100 rounded-lg text-xs text-green-800">
              <p className="font-medium mb-1">{t('chatComponents.csvAction.processingSteps')}:</p>
              <ul className="list-disc list-inside space-y-0.5">
                {hasCorrections && <li>{t('chatComponents.csvAction.applyColumnCorrections')}</li>}
                {config.generate_split && <li>{t('chatComponents.csvAction.generateSplit')}</li>}
                <li>{t('chatComponents.csvAction.navigateToRegistration')}</li>
              </ul>
            </div>

            <button
              onClick={handleNavigate}
              disabled={isProcessing}
              className={`mt-3 px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-all ${
                isProcessing
                  ? 'bg-green-400 text-white cursor-not-allowed'
                  : 'bg-green-600 text-white hover:bg-green-700'
              }`}
            >
              {isProcessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('chatComponents.csvAction.processing')}
                </>
              ) : (
                <>
                  <ArrowRight className="w-4 h-4" />
                  {t('chatComponents.csvAction.goToRegistrationPage')}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const handleUpload = () => {
    setErrorMessage(null)
    void runUploading(async () => {
      let finalCSV = csvContent
      if (config.action === 'correct_and_upload' && config.corrections) {
        finalCSV = applyCorrections(csvContent, config.corrections)
      }

      const blob = new Blob([finalCSV], { type: 'text/csv' })
      const file = new File([blob], fileName.replace(/\.xlsx?$/i, '.csv'), { type: 'text/csv' })

      let result: unknown
      if (config.csv_type === 'wsi_registration') {
        result = await uploadWSIByCSV(file)
      } else if (config.csv_type === 'split_config' && config.dataset_id) {
        result = await uploadDatasetSplits(config.dataset_id, file)
      } else {
        throw new Error(t('chatComponents.csvAction.invalidCsvType'))
      }

      setUploadResult('success')
      onSuccess?.(result)
    })
  }

  if (uploadResult === 'success') {
    return (
      <div className="mt-3 p-4 bg-green-50 border border-green-200 rounded-xl">
        <div className="flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-green-500" />
          <div>
            <h4 className="font-medium text-green-800">{t('chatComponents.csvAction.uploadSuccessful')}</h4>
            <p className="text-sm text-green-600">
              {config.csv_type === 'wsi_registration'
                ? t('chatComponents.csvAction.wsiRegistered')
                : t('chatComponents.csvAction.splitApplied')}
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (uploadResult === 'error') {
    return (
      <div className="mt-3 p-4 bg-red-50 border border-red-200 rounded-xl">
        <div className="flex items-start gap-3">
          <X className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="font-medium text-red-800">{t('chatComponents.csvAction.uploadFailedTitle')}</h4>
            <p className="text-sm text-red-600">{errorMessage}</p>
          </div>
        </div>
      </div>
    )
  }

  const isCorrection = config.action === 'correct_and_upload'

  return (
    <div className={`mt-3 p-4 rounded-xl border ${isCorrection ? 'bg-yellow-50 border-yellow-200' : 'bg-blue-50 border-blue-200'}`}>
      <div className="flex items-start gap-3">
        <FileSpreadsheet className={`w-5 h-5 flex-shrink-0 mt-0.5 ${isCorrection ? 'text-yellow-600' : 'text-blue-500'}`} />
        <div className="flex-1">
          <h4 className={`font-medium ${isCorrection ? 'text-yellow-800' : 'text-blue-800'}`}>
            {config.csv_type === 'wsi_registration' ? t('chatComponents.csvAction.wsiBatchRegistration') : t('chatComponents.csvAction.splitConfiguration')}
            {isCorrection && ` (${t('chatComponents.csvAction.withCorrections')})`}
          </h4>

          <div className="mt-2 text-sm space-y-1">
            <p className={isCorrection ? 'text-yellow-700' : 'text-blue-600'}>
              📄 <strong>{fileName}</strong> • {config.validation?.row_count || 0} {t('chatComponents.csvAction.rows')}
            </p>
            {config.dataset_name && (
              <p className={isCorrection ? 'text-yellow-700' : 'text-blue-600'}>
                📁 {t('chatComponents.csvAction.dataset')}: <strong>{config.dataset_name}</strong>
              </p>
            )}
          </div>

          {isCorrection && config.validation?.issues && (
            <div className="mt-2 p-2 bg-yellow-100 rounded-lg">
              <p className="text-xs font-medium text-yellow-800">{t('chatComponents.csvAction.correctionsToApply')}:</p>
              <ul className="text-xs text-yellow-700 list-disc list-inside mt-1">
                {config.validation.issues.map((issue, i) => <li key={i}>{issue}</li>)}
              </ul>
            </div>
          )}

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
                {t('chatComponents.csvAction.uploading')}
              </>
            ) : (
              <>
                <Upload className="w-4 h-4" />
                {isCorrection ? t('chatComponents.csvAction.applyCorrectionsAndUpload') : t('chatComponents.csvAction.uploadToPathLab')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
