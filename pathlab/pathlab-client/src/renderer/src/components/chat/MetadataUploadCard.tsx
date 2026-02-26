import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  FileSpreadsheet, UploadCloud, AlertCircle, CheckCircle,
  Download, AlertTriangle
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { downloadCSVTemplate, UploadSplitsResponse } from '../../api'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'
import * as XLSX from 'xlsx'

// --- Parsing Logic ---
export interface MetadataUploadConfig {
  dataset_id?: string
  dataset_name?: string
  upload_mode?: 'classification' | 'survival' | 'segmentation'
  aggregation_level?: 'file' | 'case'
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
  const { t } = useTranslation()
  const { tasks, addMetadataUploadTask, getMetadataUploadResult } = useBackgroundTask()

  // Local UI state only
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [bgTaskId, setBgTaskId] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadMode = config.upload_mode || 'classification'
  const onSuccessCalledRef = useRef(false)

  // On mount, reconnect to an existing background task for this dataset (survives navigation)
  useEffect(() => {
    if (bgTaskId || onSuccessCalledRef.current) return
    const datasetName = config.dataset_name
    if (!datasetName) return

    const existingTask = tasks.find(task =>
      task.type === 'metadata_upload' && task.title === `Metadata: ${datasetName}`
    )
    if (existingTask) {
      setBgTaskId(existingTask.id)
    }
  }, [tasks, bgTaskId, config.dataset_name])

  // Find the background task for this card (if running)
  const bgTask = bgTaskId ? tasks.find(task => task.id === bgTaskId) : null
  const bgTaskRunning = bgTask?.status === 'running'
  const bgTaskError = bgTask?.status === 'error' ? bgTask.items[0]?.error : null
  const bgTaskSuccess = bgTask?.status === 'success'
  // Task was submitted (running or completed) — used to hide drop zone
  const taskSubmitted = !!bgTaskId && !!bgTask && !bgTaskError

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
          return t('chatComponents.metadataUpload.multipleSheets')
        }
        const worksheet = workbook.Sheets[workbook.SheetNames[0]]
        csvContent = XLSX.utils.sheet_to_csv(worksheet)
      } else {
        csvContent = new TextDecoder().decode(arrayBuffer)
      }

      const lines = csvContent.split('\n').filter(line => line.trim() !== '')
      if (lines.length < 2) return t('chatComponents.metadataUpload.emptyFile')

      const headers = lines[0].toLowerCase().split(',').map(h => h.trim())
      if (!headers.includes('filename')) return t('chatComponents.metadataUpload.missingFilename')

      if (uploadMode === 'classification' || uploadMode === 'segmentation') {
        if (!headers.includes('label')) return t('chatComponents.metadataUpload.missingLabel')
      } else {
        if (!headers.includes('event_time')) return t('chatComponents.metadataUpload.missingEventTime')
        if (!headers.includes('event_status')) return t('chatComponents.metadataUpload.missingEventStatus')
      }

      return null // valid
    } catch (err) {
      return t('chatComponents.metadataUpload.failedToRead', { error: err instanceof Error ? err.message : String(err) })
    }
  }, [uploadMode, t])

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
        dataLevel: config.aggregation_level || 'file'
      })
      setBgTaskId(taskId)
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('chatComponents.metadataUpload.failedToStartUpload')
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

  // Get the file name shown in "submitted" state (from local state or from background task title)
  const submittedFileName = selectedFile?.name || (bgTask ? bgTask.title.replace('Metadata: ', '') : null)

  // --- Render ---
  // Already completed (persisted result from config)
  if (uploadResult) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
        <div className="px-5 py-4 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-gray-100 flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-green-600" />
          <h3 className="font-semibold text-gray-900">{t('chatComponents.metadataUpload.title')}</h3>
        </div>
        <div className="p-5 space-y-3">
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-green-800">{t('chatComponents.metadataUpload.uploadedSuccessfully')}</h4>
              <p className="text-xs text-green-700 mt-1 leading-relaxed">
                {t('chatComponents.metadataUpload.updatedFiles', { count: uploadResult.updated_count })}
                {uploadResult.auto_val_count > 0 && (
                  <>, {t('chatComponents.metadataUpload.autoAssignedValidation', { count: uploadResult.auto_val_count })}</>
                )}
                {uploadResult.not_found_count > 0 && (
                  <>, <span className="font-medium text-amber-700">{t('chatComponents.metadataUpload.filesNotFoundCount', { count: uploadResult.not_found_count })}</span></>
                )}
              </p>
            </div>
          </div>
          {uploadResult.not_found_count > 0 && uploadResult.not_found_files && uploadResult.not_found_files.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                <span className="text-xs font-bold text-amber-800">{t('chatComponents.metadataUpload.filesNotFoundInDataset')}</span>
              </div>
              <div className="max-h-24 overflow-y-auto">
                {uploadResult.not_found_files.slice(0, 10).map((f, i) => (
                  <p key={i} className="text-xs text-amber-700 ml-6">• {f}</p>
                ))}
                {uploadResult.not_found_files.length > 10 && (
                  <p className="text-xs text-amber-600 ml-6 italic">{t('chatComponents.metadataUpload.andMore', { count: uploadResult.not_found_files.length - 10 })}</p>
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
            <h3 className="font-semibold text-gray-900">{t('chatComponents.metadataUpload.title')}</h3>
          </div>
          <div className="p-5 space-y-3">
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold text-green-800">{t('chatComponents.metadataUpload.uploadedSuccessfully')}</h4>
                <p className="text-xs text-green-700 mt-1 leading-relaxed">
                  {t('chatComponents.metadataUpload.updatedFiles', { count: result.updated_count })}
                  {result.auto_val_count > 0 && (
                    <>, {t('chatComponents.metadataUpload.autoAssignedValidation', { count: result.auto_val_count })}</>
                  )}
                  {result.not_found_count > 0 && (
                    <>, <span className="font-medium text-amber-700">{t('chatComponents.metadataUpload.filesNotFoundCount', { count: result.not_found_count })}</span></>
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      )
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full max-w-2xl mb-4">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100 flex items-center gap-2">
        <FileSpreadsheet className="w-4 h-4 text-primary-600" />
        <h3 className="font-semibold text-gray-900">{t('chatComponents.metadataUpload.uploadTitle')}</h3>
        {config.dataset_name && (
          <span className="ml-auto text-xs text-gray-500">
            {t('chatComponents.metadataUpload.dataset')}: <span className="font-medium text-gray-700">{config.dataset_name}</span>
          </span>
        )}
      </div>

      <div className="p-5 space-y-4">
        {/* Background task error — show error + drop zone for retry */}
        {bgTaskError && (
          <div className="bg-red-50 border border-red-100 rounded-lg p-3 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-red-700">{bgTaskError}</p>
          </div>
        )}

        {/* Submitted state — task is running in background, show calm confirmation */}
        {taskSubmitted && bgTaskRunning && (
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-blue-800">{t('chatComponents.metadataUpload.fileSubmitted')}</h4>
              {submittedFileName && (
                <p className="text-xs text-blue-600 mt-0.5">{submittedFileName}</p>
              )}
              <p className="text-xs text-blue-500 mt-1">
                {t('chatComponents.metadataUpload.processingInBackground')}
              </p>
            </div>
          </div>
        )}

        {/* Drop zone — show when no task submitted yet, or on error (retry) */}
        {!taskSubmitted && (
          <div
            className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer ${
              isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'
            }`}
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
            <div className="space-y-2">
              <UploadCloud className="w-8 h-8 text-gray-400 mx-auto" />
              <div>
                <p className="text-sm font-medium text-gray-900">{t('chatComponents.metadataUpload.dragAndDrop')}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {t('chatComponents.metadataUpload.orClickToBrowse')} <code className="bg-gray-100 px-1 rounded">filename</code>
                  {uploadMode === 'classification'
                    ? <>, <code className="bg-gray-100 px-1 rounded">label</code></>
                    : <>, <code className="bg-gray-100 px-1 rounded">event_time</code>, <code className="bg-gray-100 px-1 rounded">event_status</code></>
                  }
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Download template — only when drop zone is visible */}
        {!taskSubmitted && (
          <div className="flex justify-end pr-1">
            <button
              onClick={handleDownloadTemplate}
              className="flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-700 hover:underline"
            >
              <Download className="w-3 h-3" />
              {t('chatComponents.metadataUpload.downloadTemplate', { type: uploadMode === 'survival' ? t('chatComponents.metadataUpload.survival') : uploadMode === 'segmentation' ? t('chatComponents.metadataUpload.segmentation') : t('chatComponents.metadataUpload.classification') })}
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
      </div>
    </div>
  )
}
