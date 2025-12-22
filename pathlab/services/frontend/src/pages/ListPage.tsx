import React, { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, uploadWSIByCSV, downloadCSVTemplate, deleteWSI, updateWSIMetadata, getWSIStorageInfo, WSIStorageInfo, StorageCleanupResult } from '../api'
import { Upload, FileSpreadsheet, Microscope, Edit, Trash2, CheckCircle, X, Loader2, AlertCircle } from 'lucide-react'

export default function ListPage() {
  // Upload functionality added
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>()
  const [inferenceResults, setInferenceResults] = useState<Map<string, any>>(new Map())

  // Upload functionality
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string>('')
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>>(new Map())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const csvInputRef = useRef<HTMLInputElement>(null)

  // CSV upload modal
  const [showCSVUploadModal, setShowCSVUploadModal] = useState(false)
  const [showCSVResultsModal, setShowCSVResultsModal] = useState(false)
  const [csvResults, setCSVResults] = useState<any>(null)

  // File upload with metadata modal
  const [showFileMetadataModal, setShowFileMetadataModal] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileMetadata, setFileMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())

  // Delete confirmation modal
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [wsiToDelete, setWsiToDelete] = useState<{ wsi_id: string; label: string } | null>(null)
  const [wsiStorageInfo, setWsiStorageInfo] = useState<WSIStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteResult, setDeleteResult] = useState<StorageCleanupResult | null>(null)
  const [showDeleteResultModal, setShowDeleteResultModal] = useState(false)
  const [deleteMode, setDeleteMode] = useState<'standard' | 'complete'>('standard')

  // Batch selection for deletion
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBatchDeleteModal, setShowBatchDeleteModal] = useState(false)

  // Edit metadata modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingWSI, setEditingWSI] = useState<{ wsi_id: string; label: string; case_id: string; age?: number; gender?: string; source?: string } | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editCaseId, setEditCaseId] = useState('')
  const [editAge, setEditAge] = useState('')
  const [editGender, setEditGender] = useState('')
  const [editSource, setEditSource] = useState('')
  const [updating, setUpdating] = useState(false)

  // Batch edit metadata
  const [showBatchEditModal, setShowBatchEditModal] = useState(false)
  const [batchEditLabel, setBatchEditLabel] = useState('')
  const [batchEditCaseId, setBatchEditCaseId] = useState('')
  const [batchEditAge, setBatchEditAge] = useState('')
  const [batchEditGender, setBatchEditGender] = useState('')
  const [batchEditSource, setBatchEditSource] = useState('')
  const [batchUpdating, setBatchUpdating] = useState(false)

  const taskDescription = sessionStorage.getItem('taskDescription') || ''
  const trainingCompleted = sessionStorage.getItem('trainingCompleted')
  const hasInferenceData = taskDescription && trainingCompleted

  useEffect(() => {
    loadWSIList()
  }, [hasInferenceData])

  const loadWSIList = async () => {
    setLoading(true)
    try {
      const d = await fetchWSIList()
      setItems(d.items || [])
      // Simulate inference results if training is completed
      if (hasInferenceData) {
        simulateInference(d.items || [])
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const simulateInference = (wsiList: any[]) => {
    const results = new Map()
    const labels = ['LUAD', 'LUSC', 'Normal']

    wsiList.forEach((wsi) => {
      // Simulate prediction
      const trueLabel = wsi.label || labels[Math.floor(Math.random() * labels.length)]
      const predLabel = Math.random() > 0.2 ? trueLabel : labels[Math.floor(Math.random() * labels.length)]

      // Generate probability distribution
      const probs: any = {}
      let remaining = 1.0
      labels.forEach((label, idx) => {
        if (idx === labels.length - 1) {
          probs[label] = remaining
        } else {
          const p = label === predLabel
            ? 0.5 + Math.random() * 0.4  // 50-90% for predicted class
            : Math.random() * remaining * 0.3
          probs[label] = p
          remaining -= p
        }
      })

      // Normalize probabilities
      const sum = Object.values(probs).reduce((a: any, b: any) => a + b, 0)
      Object.keys(probs).forEach(k => probs[k] /= sum)

      results.set(wsi.wsi_id, {
        pred: predLabel,
        confidence: probs[predLabel],
        probs: probs
      })
    })

    setInferenceResults(results)
  }

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    // Convert FileList to Array
    const filesArray = Array.from(files)
    setSelectedFiles(filesArray)

    // Initialize metadata for each file
    const metadata = new Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>()
    filesArray.forEach(file => {
      metadata.set(file.name, { label: '', case_id: '', age: '', gender: '', source: '' })
    })
    setFileMetadata(metadata)

    // Show metadata modal
    setShowFileMetadataModal(true)
  }

  const handleConfirmUpload = async () => {
    if (selectedFiles.length === 0) return

    setShowFileMetadataModal(false)
    setUploading(true)

    // Initialize upload tracking for all files
    const newUploadingFiles = new Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>()
    selectedFiles.forEach(file => {
      newUploadingFiles.set(file.name, { progress: 0, status: 'uploading' })
    })
    setUploadingFiles(newUploadingFiles)

    try {
      let successCount = 0
      let failedCount = 0

      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i]
        const metadata = fileMetadata.get(file.name)

        try {
          const age = metadata?.age ? parseInt(metadata.age) : undefined
          await uploadWSIFile(file, {
            label: metadata?.label || undefined,
            case_id: metadata?.case_id || undefined,
            age: age,
            gender: metadata?.gender || undefined,
            source: metadata?.source || undefined,
            onProgress: (progress) => {
              setUploadingFiles(prev => {
                const updated = new Map(prev)
                updated.set(file.name, { progress, status: 'uploading' })
                return updated
              })
            }
          })

          // Mark as success
          setUploadingFiles(prev => {
            const updated = new Map(prev)
            updated.set(file.name, { progress: 100, status: 'success' })
            return updated
          })
          successCount++
        } catch (err) {
          console.error(`Failed to upload ${file.name}:`, err)

          // Mark as error
          setUploadingFiles(prev => {
            const updated = new Map(prev)
            updated.set(file.name, { progress: 100, status: 'error', error: String(err) })
            return updated
          })
          failedCount++
        }
      }

      await loadWSIList()

      // Clear upload tracking after 3 seconds
      setTimeout(() => {
        setUploadingFiles(new Map())
      }, 3000)
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
      setSelectedFiles([])
      setFileMetadata(new Map())
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const updateFileMetadata = (fileName: string, field: 'label' | 'case_id' | 'age' | 'gender' | 'source', value: string) => {
    const newMetadata = new Map(fileMetadata)
    const current = newMetadata.get(fileName) || { label: '', case_id: '', age: '', gender: '', source: '' }
    newMetadata.set(fileName, { ...current, [field]: value })
    setFileMetadata(newMetadata)
  }

  const handleDeleteClick = async (wsi_id: string, label: string) => {
    setWsiToDelete({ wsi_id, label })
    setWsiStorageInfo(null)
    setShowDeleteModal(true)

    // Load storage info
    setLoadingStorageInfo(true)
    try {
      const info = await getWSIStorageInfo(wsi_id)
      setWsiStorageInfo(info)
    } catch (err) {
      console.error('Failed to load storage info:', err)
    } finally {
      setLoadingStorageInfo(false)
    }
  }

  const handleConfirmDelete = async () => {
    if (!wsiToDelete) return

    setDeleting(true)
    try {
      const result = await deleteWSI(wsiToDelete.wsi_id, deleteMode)
      setDeleteResult(result.storage_cleanup)
      setShowDeleteModal(false)
      setShowDeleteResultModal(true)
      setWsiToDelete(null)
      setWsiStorageInfo(null)
      setDeleteMode('standard') // Reset to default
      await loadWSIList()
    } catch (err) {
      console.error('Failed to delete WSI:', err)
      alert(`Failed to delete WSI: ${err}`)
    } finally {
      setDeleting(false)
    }
  }

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const toggleSelection = (wsi_id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(wsi_id)) {
      newSelected.delete(wsi_id)
    } else {
      newSelected.add(wsi_id)
    }
    setSelectedIds(newSelected)
  }

  const handleBatchDeleteClick = () => {
    if (selectedIds.size === 0) {
      alert('Please select at least one slide to delete')
      return
    }
    setShowBatchDeleteModal(true)
  }

  const handleConfirmBatchDelete = async () => {
    setDeleting(true)
    const idsToDelete = Array.from(selectedIds)
    let successCount = 0
    let failCount = 0

    try {
      for (const wsi_id of idsToDelete) {
        try {
          await deleteWSI(wsi_id)
          successCount++
        } catch (err) {
          console.error(`Failed to delete ${wsi_id}:`, err)
          failCount++
        }
      }

      setShowBatchDeleteModal(false)
      setSelectedIds(new Set())
      await loadWSIList()

      if (failCount > 0) {
        alert(`Deleted ${successCount} slides. Failed to delete ${failCount} slides.`)
      }
    } catch (err) {
      console.error('Batch delete error:', err)
      alert(`Failed to delete slides: ${err}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleEditClick = (wsi: any) => {
    setEditingWSI({
      wsi_id: wsi.wsi_id,
      label: wsi.label,
      case_id: wsi.case_id,
      age: wsi.age,
      gender: wsi.gender,
      source: wsi.source
    })
    setEditLabel(wsi.label || '')
    setEditCaseId(wsi.case_id || '')
    setEditAge(wsi.age?.toString() || '')
    setEditGender(wsi.gender || '')
    setEditSource(wsi.source || '')
    setShowEditModal(true)
  }

  const handleConfirmEdit = async () => {
    if (!editingWSI) return

    setUpdating(true)
    try {
      const age = editAge ? parseInt(editAge) : undefined
      await updateWSIMetadata(editingWSI.wsi_id, {
        label: editLabel,
        case_id: editCaseId,
        age: age,
        gender: editGender,
        source: editSource
      })
      setShowEditModal(false)
      setEditingWSI(null)
      await loadWSIList()
    } catch (err) {
      console.error('Failed to update WSI metadata:', err)
      alert(`Failed to update metadata: ${err}`)
    } finally {
      setUpdating(false)
    }
  }

  const handleBatchEditClick = () => {
    if (selectedIds.size === 0) {
      alert('Please select at least one slide to edit')
      return
    }
    setBatchEditLabel('')
    setBatchEditCaseId('')
    setBatchEditAge('')
    setBatchEditGender('')
    setBatchEditSource('')
    setShowBatchEditModal(true)
  }

  const handleConfirmBatchEdit = async () => {
    if (selectedIds.size === 0) return

    setBatchUpdating(true)
    try {
      let successCount = 0
      let failedCount = 0

      for (const wsi_id of Array.from(selectedIds)) {
        try {
          const age = batchEditAge ? parseInt(batchEditAge) : undefined
          await updateWSIMetadata(wsi_id, {
            label: batchEditLabel || undefined,
            case_id: batchEditCaseId || undefined,
            age: age,
            gender: batchEditGender || undefined,
            source: batchEditSource || undefined
          })
          successCount++
        } catch (err) {
          console.error(`Failed to update ${wsi_id}:`, err)
          failedCount++
        }
      }

      setShowBatchEditModal(false)
      setSelectedIds(new Set())
      await loadWSIList()

      if (failedCount > 0) {
        alert(`Batch edit complete!\nSuccess: ${successCount}\nFailed: ${failedCount}`)
      }
    } catch (err) {
      console.error('Failed to batch edit:', err)
      alert(`Failed to batch edit: ${err}`)
    } finally {
      setBatchUpdating(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadCSVTemplate()
      setUploadProgress('Template downloaded successfully')
      setTimeout(() => setUploadProgress(''), 3000)
    } catch (err) {
      console.error(err)
      setUploadProgress(`Failed to download template: ${err}`)
      setTimeout(() => setUploadProgress(''), 5000)
    }
  }

  const handleCSVUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    const file = files[0]
    if (!file.name.endsWith('.csv')) {
      setUploadProgress('Please select a CSV file')
      setTimeout(() => setUploadProgress(''), 3000)
      return
    }

    setUploading(true)
    setUploadProgress('Processing CSV file...')

    try {
      const result = await uploadWSIByCSV(file)
      setCSVResults(result)
      setShowCSVUploadModal(false) // Close upload modal
      setShowCSVResultsModal(true) // Open results modal
      await loadWSIList()
      setUploadProgress(`CSV processed: ${result.success} success, ${result.failed} failed`)
      setTimeout(() => setUploadProgress(''), 5000)
    } catch (err) {
      console.error(err)
      setUploadProgress(`Failed to process CSV: ${err}`)
      setTimeout(() => setUploadProgress(''), 5000)
    } finally {
      setUploading(false)
      if (csvInputRef.current) {
        csvInputRef.current.value = ''
      }
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Slide Browser</h1>
          <p className="text-gray-600 mt-1">
            {loading ? 'Loading...' :
             error ? 'Error loading slides' :
             `Total ${items.length} slides available`}
            {hasInferenceData && !loading && !error && <span className="ml-2 text-primary-600">• Analysis results available</span>}
          </p>
        </div>
        <div className="flex space-x-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            <Upload className="w-4 h-4" />
            Upload Files
          </button>
          <button
            onClick={() => setShowCSVUploadModal(true)}
            disabled={uploading}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            <FileSpreadsheet className="w-4 h-4" />
            Upload CSV
          </button>
        </div>
      </div>

      {/* Upload Progress */}
      {uploadingFiles.size > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Uploading Files ({Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}/{uploadingFiles.size})
          </h3>
          <div className="space-y-3">
            {Array.from(uploadingFiles.entries()).map(([fileName, fileStatus]) => (
              <div key={fileName} className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {fileStatus.status === 'uploading' && (
                      <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
                    )}
                    {fileStatus.status === 'success' && (
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    )}
                    {fileStatus.status === 'error' && (
                      <X className="w-4 h-4 text-red-600" />
                    )}
                    <span className="text-sm font-medium text-gray-900 truncate">{fileName}</span>
                  </div>
                  <span className="text-xs text-gray-500 ml-2">
                    {fileStatus.status === 'uploading' && 'Uploading...'}
                    {fileStatus.status === 'success' && 'Complete'}
                    {fileStatus.status === 'error' && 'Failed'}
                  </span>
                </div>
                {/* Progress Bar */}
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${
                      fileStatus.status === 'success' ? 'bg-green-600' :
                      fileStatus.status === 'error' ? 'bg-red-600' :
                      'bg-blue-600'
                    }`}
                    style={{ width: `${fileStatus.progress}%` }}
                  />
                </div>
                {fileStatus.error && (
                  <p className="text-xs text-red-600 mt-1">{fileStatus.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hidden File Inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".svs,.svslide,.ndpi,.scn,.mrxs,.bif,.tif,.tiff,.vsi,.vms,.vmu,.kfb,.sdpc,.TMAP,.mds,.mdsx,.qptiff,.tron,.isyntax"
        multiple
        style={{ display: 'none' }}
        onChange={(e) => handleFileUpload(e.target.files)}
      />
      <input
        ref={csvInputRef}
        type="file"
        accept=".csv"
        style={{ display: 'none' }}
        onChange={(e) => handleCSVUpload(e.target.files)}
      />

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          <p className="font-medium">Error loading WSI list</p>
          <p className="text-sm">{error}</p>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && items.length === 0 && (
        <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 px-6 py-8 rounded-lg text-center">
          <p className="text-lg font-medium mb-2">No slides found</p>
          <p className="text-sm">Please upload slides using the buttons above.</p>
        </div>
      )}

      {/* Batch Delete Button */}
      {!loading && !error && items.length > 0 && selectedIds.size > 0 && (
        <div className="mb-4 flex items-center justify-between bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
          <span className="text-sm text-blue-800 font-medium">
            {selectedIds.size} slide{selectedIds.size > 1 ? 's' : ''} selected
          </span>
          <div className="flex gap-2">
            <button
              onClick={handleBatchEditClick}
              className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium text-sm gap-2"
            >
              <Edit className="w-4 h-4" />
              Edit Selected
            </button>
            <button
              onClick={handleBatchDeleteClick}
              className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-medium text-sm gap-2"
            >
              <Trash2 className="w-4 h-4" />
              Delete Selected
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      {!loading && !error && items.length > 0 && (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="overflow-hidden">
          <table className="w-full table-fixed divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="w-12 px-3 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === items.length && items.length > 0}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedIds(new Set(items.map(it => it.wsi_id)))
                      } else {
                        setSelectedIds(new Set())
                      }
                    }}
                    className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                  />
                </th>
                <th className="w-40 px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Slide ID
                </th>
                <th className="w-32 px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Label
                </th>
                <th className="w-56 px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Patient Info
                </th>
                {hasInferenceData && (
                  <>
                    <th className="w-24 px-2 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      AI Result
                    </th>
                    <th className="w-48 px-2 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Score Distribution
                    </th>
                  </>
                )}
                <th className="w-32 px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {items.map((it) => {
                const result = inferenceResults.get(it.wsi_id)
                const isCorrect = result && it.label === result.pred

                return (
                  <tr key={it.wsi_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-3 py-4">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(it.wsi_id)}
                        onChange={() => toggleSelection(it.wsi_id)}
                        className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                      />
                    </td>
                    <td className="px-3 py-4 text-sm font-medium text-gray-900">
                      <div className="truncate" title={it.wsi_id}>
                        {it.wsi_id}
                      </div>
                    </td>
                    <td className="px-3 py-4 text-sm text-gray-600">
                      {it.label ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 truncate max-w-full">
                          {it.label}
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-3 py-4 text-sm text-gray-600">
                      <div className="space-y-0.5">
                        {it.age && <div className="text-xs truncate">Age: {it.age}</div>}
                        {it.gender && <div className="text-xs truncate">Gender: {it.gender}</div>}
                        {it.source && <div className="text-xs truncate">Source: {it.source}</div>}
                        {!it.age && !it.gender && !it.source && <span className="text-gray-400">-</span>}
                      </div>
                    </td>
                    {hasInferenceData && result && (
                      <>
                        <td className="px-2 py-4 text-sm">
                          <div className="space-y-0.5">
                            <div className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${
                              isCorrect
                                ? 'bg-green-100 text-green-800'
                                : 'bg-red-100 text-red-800'
                            }`}>
                              {result.pred}
                            </div>
                            <div className="text-xs text-gray-600">
                              {(result.confidence * 100).toFixed(0)}%
                            </div>
                          </div>
                        </td>
                        <td className="px-2 py-4 text-sm">
                          <div className="space-y-1">
                            {Object.entries(result.probs)
                              .sort((a: any, b: any) => b[1] - a[1])
                              .slice(0, 3)
                              .map(([cls, prob]: any) => (
                                <div key={cls} className="flex items-center space-x-1.5">
                                  <span className="text-xs text-gray-600 w-12 truncate flex-shrink-0" title={cls}>{cls}:</span>
                                  <div className="flex-1 bg-gray-200 rounded-full h-1.5 min-w-0">
                                    <div
                                      className="bg-primary-600 h-1.5 rounded-full transition-all"
                                      style={{ width: `${prob * 100}%` }}
                                    />
                                  </div>
                                  <span className="text-xs text-gray-900 w-10 text-right flex-shrink-0">
                                    {(prob * 100).toFixed(0)}%
                                  </span>
                                </div>
                              ))}
                          </div>
                        </td>
                      </>
                    )}
                    <td className="px-3 py-4 text-sm text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Link to={`/wsi/${encodeURIComponent(it.wsi_id)}`}>
                          <div className="group relative">
                            <button
                              className="inline-flex items-center justify-center px-2.5 py-1.5 text-xs font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 transition-colors"
                            >
                              <Microscope className="w-4 h-4" />
                            </button>
                            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                              View Slide
                            </div>
                          </div>
                        </Link>
                        <div className="group relative">
                          <button
                            onClick={() => handleEditClick(it)}
                            className="inline-flex items-center justify-center px-2.5 py-1.5 text-xs font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 transition-colors"
                          >
                            <Edit className="w-4 h-4" />
                          </button>
                          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                            Edit Metadata
                          </div>
                        </div>
                        <div className="group relative">
                          <button
                            onClick={() => handleDeleteClick(it.wsi_id, it.label)}
                            className="inline-flex items-center justify-center px-2.5 py-1.5 text-xs font-medium rounded-md text-white bg-red-600 hover:bg-red-700 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                            Delete Slide
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* File Metadata Modal */}
      {showFileMetadataModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            {/* Header */}
            <div className="p-6 border-b border-gray-200">
              <h3 className="text-2xl font-bold text-gray-900">Set Metadata for Files</h3>
              <p className="text-gray-600 mt-1">Add metadata for each file (all fields are optional)</p>
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto p-6">
              <div className="space-y-4">
                {selectedFiles.map((file, index) => (
                  <div key={index} className="bg-gray-50 rounded-xl p-4 border border-gray-200">
                    <div className="flex items-start gap-4">
                      {/* File Icon and Name */}
                      <div className="flex-shrink-0 w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                        <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                      </div>

                      {/* File Info and Inputs */}
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-gray-900 truncate mb-3">{file.name}</p>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Label (Disease Classification)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g., Benign, Malignant, Grade 1"
                              value={fileMetadata.get(file.name)?.label || ''}
                              onChange={(e) => updateFileMetadata(file.name, 'label', e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Case ID
                            </label>
                            <input
                              type="text"
                              placeholder="e.g., case_001"
                              value={fileMetadata.get(file.name)?.case_id || ''}
                              onChange={(e) => updateFileMetadata(file.name, 'case_id', e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Age (years)
                            </label>
                            <input
                              type="number"
                              placeholder="e.g., 45"
                              value={fileMetadata.get(file.name)?.age || ''}
                              onChange={(e) => updateFileMetadata(file.name, 'age', e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Gender
                            </label>
                            <select
                              value={fileMetadata.get(file.name)?.gender || ''}
                              onChange={(e) => updateFileMetadata(file.name, 'gender', e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            >
                              <option value="">Select Gender</option>
                              <option value="Male">Male</option>
                              <option value="Female">Female</option>
                              <option value="Unspecified">Unspecified</option>
                            </select>
                          </div>
                          <div className="col-span-2">
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Source (Organ/Tissue)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g., Cervix, Lung, Breast"
                              value={fileMetadata.get(file.name)?.source || ''}
                              onChange={(e) => updateFileMetadata(file.name, 'source', e.target.value)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-gray-200 bg-gray-50">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-600">
                  {selectedFiles.length} file(s) selected
                </p>
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setShowFileMetadataModal(false)
                      setSelectedFiles([])
                      setFileMetadata(new Map())
                      if (fileInputRef.current) {
                        fileInputRef.current.value = ''
                      }
                    }}
                    className="px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmUpload}
                    disabled={uploading}
                    className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all font-semibold shadow-lg shadow-blue-200 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Upload All Files
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CSV Upload Modal */}
      {showCSVUploadModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-purple-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Batch Import</h3>
              <p className="text-gray-600">Import multiple slides at once using a file list</p>
            </div>

            {/* Example */}
            <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-xl p-4 mb-6 border border-gray-200">
              <p className="text-sm font-semibold text-gray-700 mb-3">Example format:</p>
              <div className="bg-white rounded-lg p-3 shadow-sm overflow-x-auto">
                <code className="text-xs text-gray-600 block whitespace-nowrap">
                  <div className="text-purple-600 font-semibold">wsi_path,label,case_id,age,gender,source,wsi_id</div>
                  <div className="mt-1">/path/slide1.svs,Benign,case_001,45,Female,Cervix,slide_001</div>
                  <div>/path/slide2.svs,Malignant,case_002,52,Male,Lung,slide_002</div>
                </code>
              </div>
              <p className="text-xs text-gray-500 mt-3 flex items-start gap-2">
                <span>💡</span>
                <span>Only the file path is required. Labels and IDs are optional.</span>
              </p>
            </div>

            {/* Action Buttons */}
            <div className="space-y-3 mb-6">
              <button
                onClick={handleDownloadTemplate}
                className="w-full px-6 py-3.5 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-xl hover:from-green-700 hover:to-green-800 transition-all font-semibold flex items-center justify-center gap-3 shadow-lg shadow-green-200"
              >
                <span className="text-xl">📥</span>
                <span>Download Template</span>
              </button>
              <button
                onClick={() => csvInputRef.current?.click()}
                disabled={uploading}
                className="w-full px-6 py-3.5 bg-gradient-to-r from-purple-600 to-purple-700 text-white rounded-xl hover:from-purple-700 hover:to-purple-800 transition-all font-semibold flex items-center justify-center gap-3 shadow-lg shadow-purple-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Upload className="w-5 h-5" />
                <span>Upload File</span>
              </button>
            </div>

            {/* Upload Progress */}
            {uploading && (
              <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
                {uploadProgress}
              </div>
            )}

            {/* Close Button */}
            <button
              onClick={() => setShowCSVUploadModal(false)}
              className="w-full py-2 text-gray-500 hover:text-gray-700 transition-colors font-medium"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* CSV Upload Results Modal */}
      {showCSVResultsModal && csvResults && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full mx-4 p-6 max-h-[80vh] overflow-y-auto">
            <h3 className="text-xl font-semibold text-gray-900 mb-4">CSV Upload Results</h3>

            {/* Summary */}
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="text-sm text-blue-600 font-medium">Total</div>
                <div className="text-2xl font-bold text-blue-900">{csvResults.total}</div>
              </div>
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <div className="text-sm text-green-600 font-medium">Success</div>
                <div className="text-2xl font-bold text-green-900">{csvResults.success}</div>
              </div>
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <div className="text-sm text-red-600 font-medium">Failed</div>
                <div className="text-2xl font-bold text-red-900">{csvResults.failed}</div>
              </div>
            </div>

            {/* Detailed Results */}
            <div className="space-y-2 mb-6">
              <h4 className="font-medium text-gray-900">Detailed Results:</h4>
              <div className="max-h-96 overflow-y-auto border border-gray-200 rounded-lg">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">WSI ID</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Path</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Message</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {csvResults.results.map((result: any, idx: number) => (
                      <tr key={idx} className={result.status === 'success' ? 'bg-green-50' : 'bg-red-50'}>
                        <td className="px-4 py-2 text-sm text-gray-900">{result.wsi_id || 'N/A'}</td>
                        <td className="px-4 py-2 text-sm text-gray-600 truncate max-w-xs" title={result.wsi_path}>
                          {result.wsi_path}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                            result.status === 'success'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}>
                            {result.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-600">{result.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => {
                  setShowCSVResultsModal(false)
                  setCSVResults(null)
                }}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && wsiToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <AlertCircle className="w-10 h-10 text-red-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Delete Slide?</h3>
              <p className="text-gray-600">This action cannot be undone</p>
            </div>

            {/* WSI Info */}
            <div className="bg-gray-50 rounded-lg p-4 mb-4">
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-sm font-medium text-gray-700">Slide ID:</span>
                  <span className="text-sm text-gray-900 font-semibold">{wsiToDelete.wsi_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm font-medium text-gray-700">Label:</span>
                  <span className="text-sm text-gray-900">{wsiToDelete.label || 'Unknown'}</span>
                </div>
              </div>
            </div>

            {/* Storage Info */}
            {loadingStorageInfo && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
                  <span className="text-sm text-blue-800">Loading storage information...</span>
                </div>
              </div>
            )}

            {wsiStorageInfo && !loadingStorageInfo && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-semibold text-blue-900">Storage to be freed:</span>
                  <span className="text-lg font-bold text-blue-900">
                    {formatBytes(wsiStorageInfo.total_size)}
                  </span>
                </div>
                <details className="text-sm">
                  <summary className="cursor-pointer text-blue-800 hover:text-blue-900 font-medium">
                    Files to be deleted ({wsiStorageInfo.total_files})
                  </summary>
                  <ul className="mt-2 space-y-1 text-blue-700 ml-4">
                    {wsiStorageInfo.wsi_file.exists && (
                      <li>• WSI file ({formatBytes(wsiStorageInfo.wsi_file.size)})</li>
                    )}
                    {wsiStorageInfo.coordinates.exists && (
                      <li>• Coordinates cache ({formatBytes(wsiStorageInfo.coordinates.size)})</li>
                    )}
                    {wsiStorageInfo.thumbnail.exists && (
                      <li>• Thumbnail ({formatBytes(wsiStorageInfo.thumbnail.size)})</li>
                    )}
                    {wsiStorageInfo.mask.exists && (
                      <li>• Tissue mask ({formatBytes(wsiStorageInfo.mask.size)})</li>
                    )}
                    {wsiStorageInfo.ai_results.file_count > 0 && (
                      <li>• AI results ({wsiStorageInfo.ai_results.file_count} files, {formatBytes(wsiStorageInfo.ai_results.size)})</li>
                    )}
                    {wsiStorageInfo.features.length > 0 && (
                      <li>• Features ({wsiStorageInfo.features.length} files, {formatBytes(wsiStorageInfo.features.reduce((sum, f) => sum + f.size, 0))})</li>
                    )}
                  </ul>
                </details>
              </div>
            )}

            {/* Delete Mode Selection */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Deletion Mode
              </label>
              <div className="space-y-2">
                <label className="flex items-start gap-3 p-3 border-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
                  style={{ borderColor: deleteMode === 'standard' ? '#3b82f6' : '#e5e7eb' }}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="standard"
                    checked={deleteMode === 'standard'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-blue-600"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">Standard Delete (Recommended)</div>
                    <div className="text-sm text-gray-600 mt-1">
                      Deletes WSI file, coordinates, thumbnails, masks, and AI results.
                      <strong className="text-blue-600"> Keeps training features</strong> for future research.
                    </div>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 border-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
                  style={{ borderColor: deleteMode === 'complete' ? '#3b82f6' : '#e5e7eb' }}>
                  <input
                    type="radio"
                    name="deleteMode"
                    value="complete"
                    checked={deleteMode === 'complete'}
                    onChange={(e) => setDeleteMode(e.target.value as 'standard' | 'complete')}
                    className="mt-1 w-4 h-4 text-blue-600"
                  />
                  <div className="flex-1">
                    <div className="font-medium text-gray-900">Complete Delete</div>
                    <div className="text-sm text-gray-600 mt-1">
                      Deletes all files including training features from all training tasks.
                      <strong className="text-red-600"> Cannot be recovered.</strong>
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {/* Warning */}
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-6">
              <p className="text-sm text-red-800">
                <strong>Warning:</strong> This action cannot be undone. All selected files will be permanently deleted.
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setWsiToDelete(null)
                }}
                disabled={deleting}
                className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={deleting}
                className="flex-1 px-6 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Result Modal */}
      {showDeleteResultModal && deleteResult && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-10 h-10 text-green-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Slide Deleted Successfully</h3>
              <p className="text-gray-600">Storage has been cleaned up</p>
            </div>

            {/* Summary */}
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
              <p className="text-sm text-green-800 font-medium text-center">
                {deleteResult.summary}
              </p>
            </div>

            {/* Details */}
            <div className="space-y-3 mb-6">
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                <span className="text-sm font-medium text-gray-700">Files Deleted:</span>
                <span className="text-sm font-semibold text-gray-900">{deleteResult.deleted_files.length}</span>
              </div>
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                <span className="text-sm font-medium text-gray-700">Directories Deleted:</span>
                <span className="text-sm font-semibold text-gray-900">{deleteResult.deleted_dirs.length}</span>
              </div>
              <div className="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                <span className="text-sm font-medium text-gray-700">Space Freed:</span>
                <span className="text-sm font-semibold text-gray-900">{formatBytes(deleteResult.total_size)}</span>
              </div>
              {deleteResult.failed.length > 0 && (
                <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <span className="text-sm font-medium text-yellow-800">
                    Failed to delete {deleteResult.failed.length} item(s)
                  </span>
                </div>
              )}
            </div>

            {/* Close Button */}
            <button
              onClick={() => {
                setShowDeleteResultModal(false)
                setDeleteResult(null)
              }}
              className="w-full px-6 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-semibold"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Batch Delete Confirmation Modal */}
      {showBatchDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <AlertCircle className="w-10 h-10 text-red-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Delete Multiple Slides?</h3>
              <p className="text-gray-600">This action cannot be undone</p>
            </div>

            {/* Selection Info */}
            <div className="bg-gray-50 rounded-lg p-4 mb-6">
              <div className="text-center">
                <p className="text-sm text-gray-700">
                  You are about to delete <span className="font-bold text-red-600">{selectedIds.size}</span> slide{selectedIds.size > 1 ? 's' : ''}
                </p>
              </div>
            </div>

            {/* Warning */}
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-6">
              <p className="text-sm text-red-800">
                <strong>Warning:</strong> This will permanently delete all selected slide files, analysis results, and associated data.
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowBatchDeleteModal(false)
                }}
                disabled={deleting}
                className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmBatchDelete}
                disabled={deleting}
                className="flex-1 px-6 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deleting ? 'Deleting...' : `Delete ${selectedIds.size}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Metadata Modal */}
      {showEditModal && editingWSI && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Edit className="w-10 h-10 text-blue-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Edit Metadata</h3>
              <p className="text-gray-600">Update slide information</p>
            </div>

            {/* WSI ID (read-only) */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Slide ID
              </label>
              <input
                type="text"
                value={editingWSI.wsi_id}
                disabled
                className="w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed"
              />
            </div>

            {/* Label Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Label (Disease Classification)
              </label>
              <input
                type="text"
                value={editLabel}
                onChange={(e) => setEditLabel(e.target.value)}
                placeholder="e.g., Benign, Malignant, Grade 1"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Case ID Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Case ID
              </label>
              <input
                type="text"
                value={editCaseId}
                onChange={(e) => setEditCaseId(e.target.value)}
                placeholder="e.g., case_001"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Age Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Age (years)
              </label>
              <input
                type="number"
                value={editAge}
                onChange={(e) => setEditAge(e.target.value)}
                placeholder="e.g., 45"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Gender Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Gender
              </label>
              <select
                value={editGender}
                onChange={(e) => setEditGender(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Select Gender</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Unspecified">Unspecified</option>
              </select>
            </div>

            {/* Source Input */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Source (Organ/Tissue)
              </label>
              <input
                type="text"
                value={editSource}
                onChange={(e) => setEditSource(e.target.value)}
                placeholder="e.g., Cervix, Lung, Breast"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowEditModal(false)
                  setEditingWSI(null)
                }}
                disabled={updating}
                className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmEdit}
                disabled={updating}
                className="flex-1 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {updating ? 'Updating...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Batch Edit Metadata Modal */}
      {showBatchEditModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
            {/* Header */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Edit className="w-10 h-10 text-blue-600" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Batch Edit Metadata</h3>
              <p className="text-gray-600">Update {selectedIds.size} slide(s)</p>
            </div>

            {/* Info Message */}
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-800">
                💡 Leave fields empty to keep existing values unchanged
              </p>
            </div>

            {/* Label Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Label (Disease Classification)
              </label>
              <input
                type="text"
                value={batchEditLabel}
                onChange={(e) => setBatchEditLabel(e.target.value)}
                placeholder="Leave empty to keep existing"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Case ID Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Case ID
              </label>
              <input
                type="text"
                value={batchEditCaseId}
                onChange={(e) => setBatchEditCaseId(e.target.value)}
                placeholder="Leave empty to keep existing"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Age Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Age (years)
              </label>
              <input
                type="number"
                value={batchEditAge}
                onChange={(e) => setBatchEditAge(e.target.value)}
                placeholder="Leave empty to keep existing"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Gender Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Gender
              </label>
              <select
                value={batchEditGender}
                onChange={(e) => setBatchEditGender(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">Leave empty to keep existing</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Unspecified">Unspecified</option>
              </select>
            </div>

            {/* Source Input */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Source (Organ/Tissue)
              </label>
              <input
                type="text"
                value={batchEditSource}
                onChange={(e) => setBatchEditSource(e.target.value)}
                placeholder="Leave empty to keep existing"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowBatchEditModal(false)
                }}
                disabled={batchUpdating}
                className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmBatchEdit}
                disabled={batchUpdating}
                className="flex-1 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {batchUpdating ? 'Updating...' : `Update ${selectedIds.size}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

