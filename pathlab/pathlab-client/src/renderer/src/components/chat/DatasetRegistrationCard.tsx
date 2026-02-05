import React, { useState, useEffect, useRef } from 'react'
import { 
  UploadCloud, FolderPlus, File as FileIcon, AlertCircle, CheckCircle, 
  Loader2, Database, AlertTriangle, FileSpreadsheet, Plus, X, Download
} from 'lucide-react'
import { fetchDatasets, DatasetSummary, downloadCSVTemplate } from '../../api'
import { useBackgroundTask, UploadTaskFile } from '../../contexts/BackgroundTaskContext'

// --- File Logic Constants ---
const WSI_EXTENSIONS = [
  '.svs', '.svslide', '.dyj', '.dyqx', '.tif', '.tiff', '.ndpi',
  '.vms', '.vmu', '.isyntax', '.ibl', '.kfb', '.scn', '.mrxs',
  '.mds', '.mdsx', '.vsi', '.qptiff', '.sdpc', '.tmap', '.tron',
  '.bif', '.zyp'
]
const PATCH_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.bmp']
const ALL_EXTENSIONS = [...WSI_EXTENSIONS, ...PATCH_EXTENSIONS]

// --- Parsing Logic ---
export function parseDatasetRegistrationConfig(content: string): DatasetRegistrationConfig | null {
  const match = content.match(/\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch {
    return null
  }
}

export function removeDatasetRegistrationBlock(content: string): string {
  return content.replace(/\[DATASET_REGISTRATION\][\s\S]*?\[\/DATASET_REGISTRATION\]/g, '').trim()
}

// --- Helper Functions (Ported from UploadPage) ---
const isSupportedName = (name: string) => {
  const normalized = name.toLowerCase()
  return ALL_EXTENSIONS.some(ext => normalized.endsWith(ext))
}
const isTmapDataFile = (name: string) => /\.dt\d+$/i.test(name.toLowerCase())
const getBaseName = (name: string) => {
  const lastDot = name.lastIndexOf('.')
  return lastDot > 0 ? name.substring(0, lastDot) : name
}
const getFilePath = (file: File) => (file as any).path as string | undefined

interface LocalItem {
  key: string
  name: string
  file?: File
  path?: string
  type: 'mrxs' | 'tmap' | 'standard'
  associatedFiles?: File[]
  associatedPaths?: string[]
  missingAssociated?: boolean
}

interface DatasetRegistrationConfig {
  dataset_id?: string
  dataset_name?: string
  upload_mode?: 'classification' | 'survival'
  data_level?: 'file' | 'case'
  initial_view?: 'new' | 'existing'
}

export interface DatasetRegistrationCardProps {
  config?: DatasetRegistrationConfig
  onUploadStarted?: (taskId: string) => void
  onError?: (error: string) => void
}

export function DatasetRegistrationCard({ config, onUploadStarted, onError }: DatasetRegistrationCardProps) {
  const { addUploadTask } = useBackgroundTask()
  
  // State
  const [mode, setMode] = useState<'existing' | 'new'>(
    config?.initial_view ? config.initial_view : (config?.dataset_id ? 'existing' : 'new')
  )
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(config?.dataset_id || '')
  const [newDatasetName, setNewDatasetName] = useState(config?.dataset_name || '')
  
  // Files
  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'success' | 'error'>('idle')
  
  // Validation Errors
  const [validationErrors, setValidationErrors] = useState<string[]>([])

  useEffect(() => {
    loadDatasets()
  }, [])

  const loadDatasets = async () => {
    try {
      setLoadingDatasets(true)
      const data = await fetchDatasets()
      setDatasets(data.items)
    } catch (err) {
      console.error('Failed to load datasets', err)
    } finally {
      setLoadingDatasets(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      // Determine mode based on selection
      let uploadMode: 'classification' | 'survival' = 'classification'
      
      if (mode === 'existing' && selectedDatasetId) {
        const dataset = datasets.find(d => d.dataset_id === selectedDatasetId)
        if (dataset && dataset.dataset_type) {
          uploadMode = dataset.dataset_type as 'classification' | 'survival'
        }
      } else {
        // New dataset mode - use config or default
        uploadMode = config?.upload_mode || 'classification'
      }

      await downloadCSVTemplate(uploadMode)
    } catch (err) {
      console.error('Failed to download template', err)
      if (onError) onError('Failed to download the template file.')
    }
  }

  // --- Collection Logic ---
  const readAllEntries = async (directoryEntry: any): Promise<any[]> => {
    const reader = directoryEntry.createReader()
    const entries: any[] = []
    while (true) {
      const batch: any[] = await new Promise(resolve => reader.readEntries(resolve, () => resolve([])))
      if (!batch.length) break
      entries.push(...batch)
    }
    return entries
  }

  const collectAllFilesFromDirectory = async (directoryEntry: any): Promise<File[]> => {
    const entries = await readAllEntries(directoryEntry)
    const files: File[] = []
    for (const entry of entries) {
      if (entry.isFile) {
        const file = await new Promise<File | null>(resolve => {
          entry.file((f: File) => resolve(f), () => resolve(null))
        })
        if (file) files.push(file)
      } else if (entry.isDirectory) {
        const subFiles = await collectAllFilesFromDirectory(entry)
        files.push(...subFiles)
      }
    }
    return files
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    setValidationErrors([])

    try {
      const items = Array.from(e.dataTransfer.items)
      const hasEntries = items.some(item => (item as any).webkitGetAsEntry)
      
      if (!hasEntries) {
        setValidationErrors(['Your browser does not support folder registration. Please use Chrome or Edge.'])
        return
      }

      const entries = items.map(item => (item as any).webkitGetAsEntry?.()).filter(Boolean)
      const collectedItems: LocalItem[] = []
      
      // Validation Logic: Reject if NO folder is dropped and user is trying to register a dataset
      // The user wants "Folder inside pictures" enforcement.
      const hasDirectory = entries.some(e => e.isDirectory)
      
      // We process recursively
      const allFiles: File[] = []
      
      for (const entry of entries) {
        if (entry.isFile) {
             const file = await new Promise<File | null>(resolve => {
                entry.file((f: File) => resolve(f), () => resolve(null))
             })
             if (file) allFiles.push(file)
        } else if (entry.isDirectory) {
             const files = await collectAllFilesFromDirectory(entry)
             allFiles.push(...files)
        }
      }

      // Convert to LocalItems (simplified logic for chat context)
      // We are just grabbing supported files for now.
      // Ideally we reuse the FULL UploadPage logic for MRXS/TMAP association, 
      // but for this snippet I will do a simplified supported check.
      const validFiles = allFiles.filter(f => isSupportedName(f.name))
      
      if (validFiles.length === 0) {
        setValidationErrors(['No valid pathology images found in the dropped files. Please ensure the folder contains supported formats (.svs, .tif, .mrxs, etc.).'])
        return
      }

      const newItems = validFiles.map(f => ({
        key: `${f.name}-${f.size}`,
        name: f.name,
        file: f,
        type: 'standard' as const 
      }))
      
      setLocalItems(prev => [...prev, ...newItems])

    } catch (error) {
      console.error('File processing error:', error)
      setValidationErrors(['Failed to process files.'])
    }
  }

  const handleStartUpload = async () => {
    if (localItems.length === 0) return
    setIsUploading(true)
    setValidationErrors([])

    try {
      // Validate Dataset Name/ID
      if (mode === 'new' && !newDatasetName.trim()) {
        throw new Error('Please enter a name for the new dataset.')
      }
      if (mode === 'existing' && !selectedDatasetId) {
        throw new Error('Please select an existing dataset.')
      }

      const uploadTasks: UploadTaskFile[] = localItems.map(item => ({
        key: item.key,
        name: item.name,
        file: item.file,
        path: item.path,
        type: item.type,
        metadata: {
          dataset_id: mode === 'existing' ? selectedDatasetId : undefined,
          dataset_name: mode === 'new' ? newDatasetName : undefined,
          data_level: config?.data_level || 'file',
          label: '',
          case_id: '',
          age: undefined,
          gender: '',
          source: '',
          event_time: undefined,
          event_status: undefined
        }
      }))

      const taskId = await addUploadTask(uploadTasks)
      setUploadStatus('success')
      if (onUploadStarted) onUploadStarted(taskId)
      
    } catch (error) {
      console.error('Upload failed', error)
      setValidationErrors([error instanceof Error ? error.message : 'Dataset registration failed'])
      setUploadStatus('error')
      if (onError) onError(error instanceof Error ? error.message : 'Dataset registration failed')
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden w-full mb-4">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100 flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-primary-600" />
          <h3 className="font-semibold text-gray-900">Register Dataset</h3>
        </div>
      </div>

      {/* Content */}
      <div className="p-5 space-y-5">
        {uploadStatus === 'success' ? (
          <div className="text-center py-6">
            <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-3">
              <CheckCircle className="w-6 h-6 text-green-600" />
            </div>
            <h4 className="font-medium text-gray-900 mb-1">Registration Started</h4>
            <p className="text-sm text-gray-500 mb-4">
              Your files are being registered in the background. You can track progress in the task panel or continue chatting.
            </p>
            <div className="text-xs bg-gray-50 p-2 rounded text-gray-600">
              Files: {localItems.length} | Target: {mode === 'new' ? newDatasetName : 'Existing Dataset'}
            </div>
          </div>
        ) : (
          <>
            {/* 1. Dataset Selection */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Registration Mode</label>
                <div className="grid grid-cols-2 gap-2 p-1 bg-gray-100 rounded-lg">
                  <button
                     onClick={() => setMode('new')}
                     className={`text-xs font-medium py-2 px-3 rounded-md transition-all ${
                       mode === 'new' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                     }`}
                  >
                    New Dataset
                  </button>
                  <button
                     onClick={() => setMode('existing')}
                     className={`text-xs font-medium py-2 px-3 rounded-md transition-all ${
                       mode === 'existing' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                     }`}
                  >
                    Update Existing
                  </button>
                </div>
              </div>

              <div>
                {mode === 'new' ? (
                  <>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Dataset Name</label>
                    <input
                      type="text"
                      value={newDatasetName}
                      onChange={(e) => setNewDatasetName(e.target.value)}
                      placeholder="e.g., Breast Cancer Cohort 2024"
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
                    />
                  </>
                ) : (
                  <>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Select Dataset</label>
                    {loadingDatasets ? (
                      <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                         <Loader2 className="w-4 h-4 animate-spin" /> Loading...
                      </div>
                    ) : (
                      <select
                        value={selectedDatasetId}
                        onChange={(e) => setSelectedDatasetId(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
                      >
                        <option value="">-- Choose Dataset --</option>
                        {datasets.map(d => (
                           <option key={d.dataset_id || 'uncoded'} value={d.dataset_id || ''}>{d.dataset_name}</option>
                        ))}
                      </select>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* 2. Drop Zone */}
            <div
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
                 isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'
              } ${localItems.length > 0 ? 'bg-gray-50' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
            >
              {localItems.length > 0 ? (
                <div className="space-y-3">
                  <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mx-auto">
                    <CheckCircle className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{localItems.length} files selected</p>
                    <p className="text-xs text-gray-500">Ready to register</p>
                  </div>
                  <button 
                    onClick={() => setLocalItems([])}
                    className="text-xs text-red-600 hover:text-red-700 underline"
                  >
                    Clear selection
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <UploadCloud className="w-8 h-8 text-gray-400 mx-auto" />
                  <div>
                    <p className="text-sm font-medium text-gray-900">Drag & Drop Folder Here</p>
                    <p className="text-xs text-gray-500 mt-1">
                      Please drop a <strong>folder</strong> containing images to be analyzed. <br/>
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Template Download Link */}
            <div className="flex justify-end pr-1">
              <button 
                onClick={handleDownloadTemplate}
                className="flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-700 hover:underline"
              >
                <Download className="w-3 h-3" />
                {(() => {
                  let modeLabel = 'Classification'
                  if (mode === 'existing' && selectedDatasetId) {
                    const dataset = datasets.find(d => d.dataset_id === selectedDatasetId)
                    if (dataset && dataset.dataset_type === 'survival') modeLabel = 'Survival'
                  } else if (config?.upload_mode === 'survival') {
                    modeLabel = 'Survival'
                  }
                  return `Download ${modeLabel} Metadata Template File`
                })()}
              </button>
            </div>

            {/* Validation Errors */}
            {validationErrors.length > 0 && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                   <AlertTriangle className="w-4 h-4 text-red-600" />
                   <span className="text-xs font-bold text-red-800">Format Issue</span>
                </div>
                {validationErrors.map((err, i) => (
                  <p key={i} className="text-xs text-red-700 ml-6 list-disc">• {err}</p>
                ))}
              </div>
            )}

            {/* Actions */}
            <button
               onClick={handleStartUpload}
               disabled={isUploading || localItems.length === 0}
               className="w-full py-2 bg-primary-600 text-white rounded-lg text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
              Start Registration
            </button>
          </>
        )}
      </div>
    </div>
  )
}
