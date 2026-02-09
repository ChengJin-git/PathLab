import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  FileSpreadsheet, UploadCloud, AlertCircle, CheckCircle,
  Loader2, Download, AlertTriangle, FileIcon
} from 'lucide-react'
import { downloadCSVTemplate, UploadSplitsResponse } from '../../api'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'
import * as XLSX from 'xlsx'

// --- Parsing Logic ---
export interface MetadataUploadConfig {
  dataset_id?: string
  dataset_name?: string
  upload_mode?: 'classification' | 'survival'
  data_level?: 'file' | 'case'
  // Persisted after successful upload
  upload_result?: {
    updated_count: number
    not_found_count: number
    auto_val_count: number
  }
}

export function parseMetadataUploadConfig(content: string): MetadataUploadConfig | null {
  const match = content.match(/\[METADATA_UPLOAD\]([\s\S]*?)\[\/METADATA_UPLOAD\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch {
    return null
  }
}

export function removeMetadataUploadBlock(content: string): string {
  return content.replace(/\[METADATA_UPLOAD\][\s\S]*?\[\/METADATA_UPLOAD\]/g, '').trim()
}

export interface MetadataUploadCardProps {
  config: MetadataUploadConfig
  onSuccess?: (result: UploadSplitsResponse, datasetId: string) => void
  onError?: (error: string) => void
  messageId?: string
}

export function MetadataUploadCard({ config, onSuccess, onError }: MetadataUploadCardProps) {
  const { tasks, addMetadataUploadTask, getMetadataUploadResult } = useBackgroundTask()

  // Local UI state only
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [bgTaskId, setBgTaskId] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadMode = config.upload_mode || 'classification'
  const onSuccessCalledRef = useRef(false)

  // Find the background task for this card (if running)
  const bgTask = bgTaskId ? tasks.find(t => t.id === bgTaskId) : null
  const isUploading = bgTask?.status === 'running'
  const bgTaskError = bgTask?.status === 'error' ? bgTask.items[0]?.error : null
  const bgTaskSuccess = bgTask?.status === 'success'

  // Check if we already have a persisted result in config
  const uploadResult: UploadSplitsResponse | null = config.upload_result
    ? (config.upload_result as unknown as UploadSplitsResponse)
    : null

  // On mount or when background task completes, check for completed result and call onSuccess
  useEffect(() => {
    if (onSuccessCalledRef.current || uploadResult) return

    const datasetName = config.dataset_name
    if (!datasetName) return

    const completedResult = getMetadataUploadResult(datasetName)
    if (completedResult) {
      onSuccessCalledRef.current = true
      onSuccess?.(completedResult.result, completedResult.datasetId)
    }
  }, [config.dataset_name, getMetadataUploadResult, onSuccess, uploadResult])

  // When background task transitions to success, call onSuccess
  useEffect(() => {
    if (bgTaskSuccess && !onSuccessCalledRef.current && config.dataset_name) {
      const completedResult = getMetadataUploadResult(config.dataset_name)
      if (completedResult) {
        onSuccessCalledRef.current = true
        onSuccess?.(completedResult.result, completedResult.datasetId)
      }
    }
  }, [bgTaskSuccess, config.dataset_name, getMetadataUploadResult, onSuccess])

  // Validate file columns
  const validateFile = useCallback(async (file: File): Promise<string | null> => {
    try {
      const arrayBuffer = await file.arrayBuffer()
      const fileName = file.name.toLowerCase()
      let csvContent: string

      if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
        const workbook = XLSX.read(arrayBuffer, { type: 'array' })
        if (workbook.SheetNames.length > 1) {
          return 'Excel file has multiple sheets. Please use a file with only one sheet.'
        }
        const worksheet = workbook.Sheets[workbook.SheetNames[0]]
        csvContent = XLSX.utils.sheet_to_csv(worksheet)
      } else {
        csvContent = new TextDecoder().decode(arrayBuffer)
      }

      const lines = csvContent.split('\n').filter(line => line.trim() !== '')
      if (lines.length < 2) return 'File is empty or has no data rows'

      const headers = lines[0].toLowerCase().split(',').map(h => h.trim())
      if (!headers.includes('filename')) return 'File must contain a "filename" column'

      if (uploadMode === 'classification') {
        if (!headers.includes('label')) return 'File must contain a "label" column for classification'
      } else {
        if (!headers.includes('event_time')) return 'File must contain an "event_time" column for survival'
        if (!headers.includes('event_status')) return 'File must contain an "event_status" column for survival'
      }

      return null // valid
    } catch (err) {
      return `Failed to read file: ${err instanceof Error ? err.message : String(err)}`
    }
  }, [uploadMode])

  // Convert Excel to CSV File object for background task
  const convertToCSV = async (file: File): Promise<File> => {
    const fileName = file.name.toLowerCase()
    if (fileName.endsWith('.csv')) return file

    const arrayBuffer = await file.arrayBuffer()
    const workbook = XLSX.read(arrayBuffer, { type: 'array' })
    const worksheet = workbook.Sheets[workbook.SheetNames[0]]
    const csvContent = XLSX.utils.sheet_to_csv(worksheet)
    const blob = new Blob([csvContent], { type: 'text/csv' })
    return new File([blob], file.name.replace(/\.(xlsx|xls)$/i, '.csv'), { type: 'text/csv' })
  }

  // Handle file selection → validate → convert → start background task
  const handleFileSelect = async (file: File) => {
    setValidationError(null)

    const error = await validateFile(file)
    if (error) {
      setValidationError(error)
      return
    }
    setSelectedFile(file)

    // Convert to CSV and start background task immediately
    try {
      const csvFile = await convertToCSV(file)
      const taskId = addMetadataUploadTask({
        csvFile,
        datasetName: config.dataset_name!,
        datasetId: config.dataset_id,
        uploadMode: config.upload_mode || 'classification',
        dataLevel: config.data_level || 'file'
      })
      setBgTaskId(taskId)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start upload'
      onError?.(msg)
    }
  }

  // File input change
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileSelect(file)
    // Reset input so same file can be re-selected
    e.target.value = ''
  }

  // Drag & drop
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }
  const handleDragLeave = () => setIsDragging(false)
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFileSelect(file)
  }

  // Download template
  const handleDownloadTemplate = () => {
    downloadCSVTemplate(uploadMode).catch(err => {
      console.error('Failed to download template:', err)
    })
  }

  // Determine upload button state text
  const getStatusText = () => {
    if (bgTask?.status === 'running') {
      const item = bgTask.items[0]
      return item?.name || 'Processing...'
    }
    return null
  }

  // --- Render ---
  // Already completed (persisted result from config)
  if (uploadResult) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
        <div className="px-5 py-4 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-gray-100 flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-green-600" />
          <h3 className="font-semibold text-gray-900">Metadata Upload</h3>
        </div>
        <div className="p-5 space-y-3">
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-green-800">Metadata Uploaded Successfully</h4>
              <p className="text-xs text-green-700 mt-1 leading-relaxed">
                Updated <span className="font-medium">{uploadResult.updated_count}</span> files
                {uploadResult.auto_val_count > 0 && (
                  <>, auto-assigned <span className="font-medium">{uploadResult.auto_val_count}</span> to validation</>
                )}
                {uploadResult.not_found_count > 0 && (
                  <>, <span className="font-medium text-amber-700">{uploadResult.not_found_count}</span> files not found in dataset</>
                )}
              </p>
            </div>
          </div>
          {uploadResult.not_found_count > 0 && uploadResult.not_found_files && uploadResult.not_found_files.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                <span className="text-xs font-bold text-amber-800">Files Not Found in Dataset</span>
              </div>
              <div className="max-h-24 overflow-y-auto">
                {uploadResult.not_found_files.slice(0, 10).map((f, i) => (
                  <p key={i} className="text-xs text-amber-700 ml-6">• {f}</p>
                ))}
                {uploadResult.not_found_files.length > 10 && (
                  <p className="text-xs text-amber-600 ml-6 italic">...and {uploadResult.not_found_files.length - 10} more</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Background task completed successfully — show result from context
  if (bgTaskSuccess && config.dataset_name) {
    const completedResult = getMetadataUploadResult(config.dataset_name)
    if (completedResult) {
      const result = completedResult.result
      return (
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
          <div className="px-5 py-4 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-gray-100 flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-green-600" />
            <h3 className="font-semibold text-gray-900">Metadata Upload</h3>
          </div>
          <div className="p-5 space-y-3">
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold text-green-800">Metadata Uploaded Successfully</h4>
                <p className="text-xs text-green-700 mt-1 leading-relaxed">
                  Updated <span className="font-medium">{result.updated_count}</span> files
                  {result.auto_val_count > 0 && (
                    <>, auto-assigned <span className="font-medium">{result.auto_val_count}</span> to validation</>
                  )}
                  {result.not_found_count > 0 && (
                    <>, <span className="font-medium text-amber-700">{result.not_found_count}</span> files not found in dataset</>
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      )
    }
  }

  const statusText = getStatusText()

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100 flex items-center gap-2">
        <FileSpreadsheet className="w-4 h-4 text-primary-600" />
        <h3 className="font-semibold text-gray-900">Upload Metadata (CSV / Excel)</h3>
        {config.dataset_name && (
          <span className="ml-auto text-xs text-gray-500">
            Dataset: <span className="font-medium text-gray-700">{config.dataset_name}</span>
          </span>
        )}
      </div>

      <div className="p-5 space-y-4">
        {/* Background task error */}
        {bgTaskError && (
          <div className="bg-red-50 border border-red-100 rounded-lg p-3 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-red-700">{bgTaskError}</p>
          </div>
        )}

        {/* Drop zone - always show so user can select file while dataset is being created */}
        {!isUploading && (
          <div
            className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer ${
              isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'
            } ${selectedFile ? 'bg-gray-50' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={handleInputChange}
              className="hidden"
            />
            {selectedFile ? (
              <div className="space-y-2">
                <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mx-auto">
                  <FileIcon className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="font-medium text-gray-900 text-sm">{selectedFile.name}</p>
                  <p className="text-xs text-gray-500">{(selectedFile.size / 1024).toFixed(1)} KB</p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <UploadCloud className="w-8 h-8 text-gray-400 mx-auto" />
                <div>
                  <p className="text-sm font-medium text-gray-900">Drag & Drop CSV / Excel File</p>
                  <p className="text-xs text-gray-500 mt-1">
                    or click to browse. Required columns: <code className="bg-gray-100 px-1 rounded">filename</code>
                    {uploadMode === 'classification'
                      ? <>, <code className="bg-gray-100 px-1 rounded">label</code></>
                      : <>, <code className="bg-gray-100 px-1 rounded">event_time</code>, <code className="bg-gray-100 px-1 rounded">event_status</code></>
                    }
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Download template */}
        {!isUploading && (
          <div className="flex justify-end pr-1">
            <button
              onClick={handleDownloadTemplate}
              className="flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-700 hover:underline"
            >
              <Download className="w-3 h-3" />
              Download {uploadMode === 'survival' ? 'Survival' : 'Classification'} Template
            </button>
          </div>
        )}

        {/* Validation error */}
        {validationError && (
          <div className="bg-red-50 border border-red-100 rounded-lg p-3 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-red-700">{validationError}</p>
          </div>
        )}

        {/* Status indicator (background task running) */}
        {isUploading && statusText && (
          <div className="flex items-center justify-center gap-2 py-3">
            <Loader2 className="w-4 h-4 animate-spin text-primary-600" />
            <p className="text-sm text-gray-600">{statusText}</p>
          </div>
        )}

        {/* Progress hint */}
        {isUploading && (
          <p className="text-xs text-gray-400 text-center">
            正在后台处理中，你可以切换到其他页面，上传会继续进行...
          </p>
        )}
      </div>
    </div>
  )
}
