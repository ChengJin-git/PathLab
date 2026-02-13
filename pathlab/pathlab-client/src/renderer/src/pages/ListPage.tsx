import React, { useEffect, useState, useRef, useMemo } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useToast } from '../contexts/ToastContext'
import { fetchWSIList, fetchDatasets, renameDataset, updateDatasetType, updateDatasetDataLevel, uploadWSIFile, updateWSIMetadata, getWSIStorageInfo, uploadDatasetSplits, WSIStorageInfo, DatasetSummary, startBatchUpdateMetadataTask, invalidateWSIListCache, getFileType } from '../api'
import { Upload, Microscope, Edit, Trash2, CheckCircle, X, Loader2, AlertCircle, ChevronLeft, ChevronRight, ChevronDown, Search, FolderOpen, ArrowLeft, Database, LayoutGrid, Pencil, Users, FileImage } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { ALL_ACCEPT_STRING } from '../constants/fileTypes'
import { formatBytes } from '../lib/utils'
import { FileMetadataModal, DeleteConfirmModal, BatchDeleteModal, EditMetadataModal, BatchEditModal, EditDatasetModal } from '../components/list'

export default function ListPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  const initialDatasetId = (location.state as { dataset_id?: string } | null)?.dataset_id
  const { error: toastError, success: toastSuccess } = useToast()
  const { addDeleteWSITask } = useBackgroundTask()

  // Dataset view state - null means showing dataset list, otherwise showing files in that dataset
  // selectedDatasetId is used for API calls, selectedDatasetName is used for display
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(initialDatasetId || null)
  const [selectedDatasetName, setSelectedDatasetName] = useState<string>('')
  const [selectedDatasetType, setSelectedDatasetType] = useState<'classification' | 'survival'>('classification')
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(true)
  const [datasetsError, setDatasetsError] = useState<string | undefined>()

  // File list state (when viewing a dataset)
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [totalCount, setTotalCount] = useState<number>(0)

  // Server-side pagination metadata
  const [totalCases, setTotalCases] = useState<number>(0)
  const [hasMultiSlideCases, setHasMultiSlideCases] = useState(false)

  // Search and Filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  // Upload functionality
  const [uploading, setUploading] = useState(false)
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>>(new Map())
  const fileInputRef = useRef<HTMLInputElement>(null)



  // File upload with metadata modal
  const [showFileMetadataModal, setShowFileMetadataModal] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileMetadata, setFileMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())

  // Delete confirmation modal
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [wsiToDelete, setWsiToDelete] = useState<{ wsi_id: string; label: string; original_filename?: string } | null>(null)
  const [wsiStorageInfo, setWsiStorageInfo] = useState<WSIStorageInfo | null>(null)
  const [loadingStorageInfo, setLoadingStorageInfo] = useState(false)
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

  // Case grouping - tracks which case_ids are expanded
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set())

  // Edit dataset - stores dataset_id for the dataset being edited (rename + type + aggregation_level change)
  const [editingDatasetId, setEditingDatasetId] = useState<string | null>(null)
  const [editingDatasetName, setEditingDatasetName] = useState('')
  const [editingDatasetType, setEditingDatasetType] = useState<'classification' | 'survival'>('classification')
  const [editingDatasetOriginalType, setEditingDatasetOriginalType] = useState<'classification' | 'survival'>('classification')
  const [editingDatasetDataLevel, setEditingDatasetDataLevel] = useState<'case' | 'file'>('file')
  const [editingDatasetOriginalDataLevel, setEditingDatasetOriginalDataLevel] = useState<'case' | 'file'>('file')
  const [editingDatasetSaving, setEditingDatasetSaving] = useState(false)

  // Legacy inline rename (still used for inline editing display)
  const [renamingDatasetId, setRenamingDatasetId] = useState<string | null>(null)
  const [renameDatasetNewName, setRenameDatasetNewName] = useState('')

  // Delete dataset - stores dataset_id and name for the dataset to delete
  const [datasetToDeleteId, setDatasetToDeleteId] = useState<string | null>(null)
  const [datasetToDeleteName, setDatasetToDeleteName] = useState<string>('')
  const [deleting, setDeleting] = useState(false)
  // Optimistically hide datasets that are being deleted in background
  const [optimisticallyDeletedDatasetIds, setOptimisticallyDeletedDatasetIds] = useState<Set<string>>(new Set())

  const visibleDatasets = useMemo(() => {
    return datasets.filter(d => !d.dataset_id || !optimisticallyDeletedDatasetIds.has(d.dataset_id))
  }, [datasets, optimisticallyDeletedDatasetIds])

  // Load datasets on mount
  useEffect(() => {
    loadDatasets()
  }, [])

  // Set initial dataset name and type when datasets are loaded and we have an initialDatasetId
  useEffect(() => {
    if (initialDatasetId && datasets.length > 0 && !selectedDatasetName) {
      const dataset = datasets.find(d => d.dataset_id === initialDatasetId)
      if (dataset) {
        setSelectedDatasetName(dataset.dataset_name)
        setSelectedDatasetType(dataset.task_type)
      }
    }
  }, [datasets, initialDatasetId, selectedDatasetName])

  // Debounce search input → debouncedSearch (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Load files when dataset, page, or debounced search changes
  useEffect(() => {
    if (selectedDatasetId) {
      loadWSIList(selectedDatasetId, currentPage, debouncedSearch)
    }
  }, [selectedDatasetId, currentPage, debouncedSearch])

  const loadDatasets = async () => {
    setDatasetsLoading(true)
    setDatasetsError(undefined)
    try {
      const d = await fetchDatasets()
      setDatasets(d.items || [])
    } catch (e) {
      setDatasetsError(String(e))
    } finally {
      setDatasetsLoading(false)
    }
  }

  const loadWSIList = async (datasetId: string, page: number = 1, search: string = '') => {
    setLoading(true)
    setError(undefined)
    try {
      const d = await fetchWSIList(datasetId, undefined, {
        page,
        page_size: itemsPerPage,
        search: search || undefined,
      })
      setItems(d.items || [])
      setTotalCount(d.total ?? d.items?.length ?? 0)
      setTotalCases(d.total_cases ?? 0)
      setHasMultiSlideCases(d.has_multi_slide_cases ?? false)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleBackToDatasets = () => {
    // If we came from AI Chat, go back to AI Chat
    if (fromAIChat) {
      navigate('/ai-chat')
      return
    }
    // Otherwise, go back to dataset list
    setSelectedDatasetId(null)
    setSelectedDatasetName('')
    setSelectedDatasetType('classification')
    setItems([])
    setTotalCount(0)
    setTotalCases(0)
    setHasMultiSlideCases(false)
    setSearchQuery('')
    setDebouncedSearch('')
    setCurrentPage(1)
    setSelectedIds(new Set())
  }

  const handleDatasetClick = (dataset: DatasetSummary) => {
    setSelectedDatasetId(dataset.dataset_id)
    setSelectedDatasetName(dataset.dataset_name)
    setSelectedDatasetType(dataset.task_type)
    setCurrentPage(1)
    setSearchQuery('')
    setDebouncedSearch('')
  }

  // Reload current dataset files (for use after edits/deletes)
  const reloadCurrentDataset = async () => {
    if (selectedDatasetId) {
      invalidateWSIListCache()
      await loadWSIList(selectedDatasetId, currentPage, debouncedSearch)
    }
  }




  // Helper function to guess dataset content type based on average file size
  const getDatasetItemType = (totalSize: number, fileCount: number): 'slides' | 'images' => {
    if (fileCount === 0) return 'images'
    const avgSize = totalSize / fileCount
    // Threshold: 20MB. WSI files are usually much larger, patches are much smaller.
    return avgSize > 20 * 1024 * 1024 ? 'slides' : 'images'
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

      await reloadCurrentDataset()

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

  const handleDeleteClick = async (wsi_id: string, label: string, original_filename?: string) => {
    setWsiToDelete({ wsi_id, label, original_filename })
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

    try {
      await addDeleteWSITask([wsiToDelete.wsi_id], deleteMode)
      setShowDeleteModal(false)
      setWsiToDelete(null)
      setWsiStorageInfo(null)
      setDeleteMode('standard') // Reset to default
      // List will be refreshed when task completes - we can trigger a delayed refresh
      setTimeout(() => reloadCurrentDataset(), 500)
    } catch (err) {
      console.error('Failed to add delete task:', err)
      alert(`Failed to delete WSI: ${err}`)
    }
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
      alert('Please select at least one file to delete')
      return
    }
    setDeleteMode('standard')
    setShowBatchDeleteModal(true)
  }

  const handleConfirmBatchDelete = async () => {
    const idsToDelete = Array.from(selectedIds)
    setDeleting(true)

    try {
      await addDeleteWSITask(idsToDelete, deleteMode)
      setShowBatchDeleteModal(false)
      setSelectedIds(new Set())

      if (datasetToDeleteId) {
        // Optimistically hide from UI immediately
        setOptimisticallyDeletedDatasetIds(prev => new Set(prev).add(datasetToDeleteId))
        setDatasetToDeleteId(null)
        setDatasetToDeleteName('')
        await loadDatasets()
      } else {
        // List will be refreshed when task completes - we can trigger a delayed refresh
        setTimeout(() => reloadCurrentDataset(), 500)
      }
    } catch (err) {
      console.error('Batch delete error:', err)
      alert(`Failed to delete files: ${err}`)
    } finally {
      setDeleting(false)
    }
  }



  const handleDatasetDeleteClick = async (e: React.MouseEvent, datasetId: string | null, datasetName: string) => {
    e.stopPropagation()
    if (!datasetId) {
      alert("Cannot delete uncategorized dataset")
      return
    }
    setDeleting(true)
    try {
      const d = await fetchWSIList(datasetId)
      if (!d.items || d.items.length === 0) {
        alert("Dataset is empty or could not be loaded")
        return
      }
      const allIds = new Set(d.items.map((it: any) => it.wsi_id))
      setSelectedIds(allIds)
      setDatasetToDeleteId(datasetId)
      setDatasetToDeleteName(datasetName)
      setDeleteMode('standard')
      setShowBatchDeleteModal(true)
    } catch (err) {
      console.error('Failed to prepare dataset delete:', err)
      alert(`Failed to load dataset files: ${err}`)
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
      await reloadCurrentDataset()
    } catch (err) {
      console.error('Failed to update WSI metadata:', err)
      alert(`Failed to update metadata: ${err}`)
    } finally {
      setUpdating(false)
    }
  }

  const handleBatchEditClick = () => {
    if (selectedIds.size === 0) {
      alert('Please select at least one file to edit')
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

    // Check if at least one field is provided
    const hasUpdates = batchEditLabel || batchEditCaseId || batchEditAge || batchEditGender || batchEditSource
    if (!hasUpdates) {
      setShowBatchEditModal(false)
      return
    }

    setBatchUpdating(true)
    try {
      // Prepare the request
      const age = batchEditAge ? parseInt(batchEditAge) : undefined
      const request = {
        wsi_ids: Array.from(selectedIds),
        label: batchEditLabel || undefined,
        case_id: batchEditCaseId || undefined,
        age: age,
        gender: batchEditGender || undefined,
        source: batchEditSource || undefined
      }

      // Start background task
      await startBatchUpdateMetadataTask(request)

      // Close modal and clear selection immediately
      setShowBatchEditModal(false)
      setSelectedIds(new Set())
      toastSuccess(`Metadata update started for ${request.wsi_ids.length} items. Check notification center for progress.`)
    } catch (err) {
      console.error('Failed to start batch edit:', err)
      toastError(err instanceof Error ? err.message : `Failed to start batch edit: ${err}`)
    } finally {
      setBatchUpdating(false)
    }
  }

  // Open edit dataset modal
  const handleEditDatasetClick = (e: React.MouseEvent, dataset: DatasetSummary) => {
    e.stopPropagation()
    if (!dataset.dataset_id) return
    setEditingDatasetId(dataset.dataset_id)
    setEditingDatasetName(dataset.dataset_name)
    setEditingDatasetType(dataset.task_type)
    setEditingDatasetOriginalType(dataset.task_type)
    const dataLevel = dataset.aggregation_level || 'file'
    setEditingDatasetDataLevel(dataLevel)
    setEditingDatasetOriginalDataLevel(dataLevel)
  }

  const handleEditDatasetCancel = () => {
    setEditingDatasetId(null)
    setEditingDatasetName('')
    setEditingDatasetType('classification')
    setEditingDatasetOriginalType('classification')
    setEditingDatasetDataLevel('file')
    setEditingDatasetOriginalDataLevel('file')
    setEditingDatasetSaving(false)
  }

  const handleEditDatasetSave = async () => {
    if (!editingDatasetId || !editingDatasetName.trim()) {
      handleEditDatasetCancel()
      return
    }

    setEditingDatasetSaving(true)
    try {
      // Find the original name from datasets
      const originalDataset = datasets.find(d => d.dataset_id === editingDatasetId)
      const originalName = originalDataset?.dataset_name || ''

      // Rename if name changed
      if (editingDatasetName !== originalName) {
        await renameDataset(editingDatasetId, editingDatasetName)
      }

      // Update type if changed
      if (editingDatasetType !== editingDatasetOriginalType) {
        await updateDatasetType(editingDatasetId, editingDatasetType)
      }

      // Update data level if changed
      if (editingDatasetDataLevel !== editingDatasetOriginalDataLevel) {
        await updateDatasetDataLevel(editingDatasetId, editingDatasetDataLevel)
      }

      await loadDatasets() // Reload datasets list

      // If this dataset was selected, update the displayed info
      if (selectedDatasetId === editingDatasetId) {
        setSelectedDatasetName(editingDatasetName)
        setSelectedDatasetType(editingDatasetType)
      }

      toastSuccess('Dataset updated successfully')
    } catch (err) {
      console.error('Failed to update dataset:', err)
      toastError(`Failed to update dataset: ${err}`)
    } finally {
      handleEditDatasetCancel()
    }
  }

  // Legacy inline rename functions (kept for compatibility)
  const handleRenameClick = (e: React.MouseEvent, datasetId: string | null, datasetName: string) => {
    e.stopPropagation()
    setRenamingDatasetId(datasetId)
    setRenameDatasetNewName(datasetName)
  }

  const handleRenameCancel = () => {
    setRenamingDatasetId(null)
    setRenameDatasetNewName('')
  }

  const handleRenameConfirm = async () => {
    if (!renamingDatasetId || !renameDatasetNewName) {
      handleRenameCancel()
      return
    }

    try {
      await renameDataset(renamingDatasetId, renameDatasetNewName)
      await loadDatasets() // Reload datasets list

      // If the renamed dataset was selected, update the displayed name
      if (selectedDatasetId === renamingDatasetId) {
        setSelectedDatasetName(renameDatasetNewName)
      }
    } catch (err) {
      console.error('Failed to rename dataset:', err)
      alert(`Failed to rename dataset: ${err}`)
    } finally {
      handleRenameCancel()
    }
  }

  // Group items by case_id (for display within current page)
  const groupedByCaseId = React.useMemo(() => {
    const groups = new Map<string, typeof items>()
    const NO_CASE = '__no_case__'

    items.forEach(item => {
      const caseId = item.case_id || NO_CASE
      if (!groups.has(caseId)) {
        groups.set(caseId, [])
      }
      groups.get(caseId)!.push(item)
    })

    // Convert to array and sort: named cases alphabetically, __no_case__ last
    const sortedGroups = Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === NO_CASE) return 1
      if (b[0] === NO_CASE) return -1
      return a[0].localeCompare(b[0])
    })

    return sortedGroups
  }, [items])

  // Check if this is a patch dataset (majority of files are patches)
  const isPatchDataset = React.useMemo(() => {
    if (items.length === 0) return false
    const patchCount = items.filter(item => getFileType(item.file_extension, item.file_size) === 'Patch').length
    return patchCount > items.length / 2
  }, [items])

  // Server-side pagination: totalPages based on server-provided totalCases (or totalCount for non-grouped)
  const totalPages = hasMultiSlideCases
    ? Math.ceil(totalCases / itemsPerPage)
    : Math.ceil(totalCount / itemsPerPage)
  const startIndex = (currentPage - 1) * itemsPerPage

  // All current-page items are already the "paginated" items (server-side pagination)
  const paginatedCases = hasMultiSlideCases ? groupedByCaseId : null
  const paginatedItems = hasMultiSlideCases ? [] : items

  // Batch selection logic — operates on current page items
  const pageSlides = useMemo(() => {
    if (hasMultiSlideCases && paginatedCases) {
      return paginatedCases.flatMap(([, slides]) => slides)
    }
    return paginatedItems || []
  }, [hasMultiSlideCases, paginatedCases, paginatedItems])

  const allPageSelected = pageSlides.length > 0 && pageSlides.every(s => selectedIds.has(s.wsi_id))

  // Check if all items across all pages are selected (based on totalCount)
  const allFilteredSelected = selectedIds.size > 0 && selectedIds.size === totalCount

  const handleSelectPage = () => {
    if (allFilteredSelected) {
      setSelectedIds(new Set())
      return
    }

    const newSelected = new Set(selectedIds)
    if (allPageSelected) {
      pageSlides.forEach(s => newSelected.delete(s.wsi_id))
    } else {
      pageSlides.forEach(s => newSelected.add(s.wsi_id))
    }
    setSelectedIds(newSelected)
  }

  // Handle selecting all filtered items (across all pages)
  const handleSelectAllFiltered = async () => {
    try {
      // Fetch all IDs without loading full data
      const d = await fetchWSIList(selectedDatasetId!, undefined, {
        page: 1,
        page_size: totalCount, // Request all items
        search: debouncedSearch || undefined,
      })
      const allIds = new Set((d.items || []).map((item: any) => item.wsi_id))
      setSelectedIds(allIds)
    } catch (e) {
      toastError('Failed to select all items')
      console.error(e)
    }
  }

  // Toggle case expansion
  const toggleCaseExpansion = (caseId: string) => {
    setExpandedCases(prev => {
      const next = new Set(prev)
      if (next.has(caseId)) {
        next.delete(caseId)
      } else {
        next.add(caseId)
      }
      return next
    })
  }

  return (
    <div className="w-full space-y-6 h-full flex flex-col">
      <div className="flex-none">
        <PageHeader
          title={selectedDatasetId ? selectedDatasetName : "Data Repository"}
          description={
            <>
              {selectedDatasetId ? (
                loading ? 'Loading files...' :
                  error ? 'Error loading files' :
                    <span className="flex items-center gap-2">
                      <FolderOpen className="w-4 h-4" />
                      {totalCount} files stored in this dataset
                    </span>
              ) : (
                'Manage your datasets and images.'
              )}
            </>
          }
        >
          <div className="flex items-center gap-2">
            {selectedDatasetId ? (
              <>
                <Button
                  variant="outline"
                  onClick={handleBackToDatasets}
                  className="gap-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  {fromAIChat ? 'Back to Chat' : 'Back to Repository'}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  onClick={() => navigate('/dashboard')}
                  className="gap-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back to Dashboard
                </Button>
                <Button
                  onClick={() => navigate('/register')}
                  className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white"
                >
                  <Upload className="w-4 h-4" />
                  Register Files
                </Button>
              </>
            )}
          </div>
        </PageHeader>
      </div>

      {/* Registration Progress */}
      {uploadingFiles.size > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Registering Files ({Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}/{uploadingFiles.size})
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
                    {fileStatus.status === 'uploading' && 'Registering...'}
                    {fileStatus.status === 'success' && 'Complete'}
                    {fileStatus.status === 'error' && 'Failed'}
                  </span>
                </div>
                {/* Progress Bar */}
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${fileStatus.status === 'success' ? 'bg-green-600' :
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
        accept={ALL_ACCEPT_STRING}
        multiple
        style={{ display: 'none' }}
        onChange={(e) => handleFileUpload(e.target.files)}
      />

      {/* === DATASETS VIEW (when no dataset is selected) === */}
      {!selectedDatasetId && (
        <>
          {/* Datasets Loading State */}
          {datasetsLoading && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
            </div>
          )}

          {/* Datasets Error State */}
          {datasetsError && !datasetsLoading && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
              <p className="font-medium">Error loading datasets</p>
              <p className="text-sm">{datasetsError}</p>
            </div>
          )}

          {/* Datasets Empty State */}
          {!datasetsLoading && !datasetsError && visibleDatasets.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50">
              <div className="bg-white p-4 rounded-full border border-gray-200 shadow-sm mb-4">
                <Database className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">No datasets found</h3>
              <p className="text-sm text-gray-500 max-w-sm text-center">
                Register files using the button above to create your first dataset.
              </p>
            </div>
          )}

          {/* Datasets Grid */}
          {!datasetsLoading && !datasetsError && visibleDatasets.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-6 p-1">
              {visibleDatasets.map((dataset) => {
                const itemType = getDatasetItemType(dataset.total_size, dataset.file_count)

                return (
                  <Card
                    key={dataset.dataset_id ?? dataset.dataset_name}
                    className="group relative overflow-hidden transition-all duration-300 hover:shadow-xl hover:-translate-y-1 border-slate-200 bg-white"
                    onClick={() => handleDatasetClick(dataset)}
                  >
                    <div className={`absolute inset-x-0 top-0 h-1 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-r ${itemType === 'slides' ? 'from-blue-500 to-indigo-500' : 'from-emerald-500 to-teal-500'
                      }`} />
                    <div className="p-4 sm:p-6">
                      <div className="flex items-start justify-between mb-3 sm:mb-4">
                        <div className={`p-2 sm:p-3 rounded-2xl transition-colors ${itemType === 'slides' ? 'bg-blue-50 group-hover:bg-blue-100' : 'bg-emerald-50 group-hover:bg-emerald-100'
                          }`}>
                          {itemType === 'slides' ? (
                            <Microscope className="w-6 h-6 sm:w-8 sm:h-8 text-blue-600" />
                          ) : (
                            <LayoutGrid className="w-6 h-6 sm:w-8 sm:h-8 text-emerald-600" />
                          )}
                        </div>
                        <div className="sm:opacity-0 group-hover:opacity-100 transition-opacity -mr-1 sm:-mr-2 -mt-1 sm:-mt-2">
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 hover:text-blue-600">
                            <ChevronRight className="w-5 h-5" />
                          </Button>
                        </div>
                      </div>

                      <div className="flex items-center justify-between mb-0.5 sm:mb-1 min-w-0 relative z-10" onClick={e => renamingDatasetId === dataset.dataset_id && e.stopPropagation()}>
                        {renamingDatasetId === dataset.dataset_id ? (
                          <div className="flex items-center gap-2 w-full animate-in fade-in duration-200">
                            <input
                              type="text"
                              value={renameDatasetNewName}
                              onChange={(e) => setRenameDatasetNewName(e.target.value)}
                              className="flex-1 px-1 sm:px-2 py-0.5 text-base sm:text-lg font-bold text-slate-900 border-b-2 border-blue-500 bg-transparent focus:outline-none"
                              autoFocus
                              onClick={e => e.stopPropagation()}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleRenameConfirm()
                                if (e.key === 'Escape') handleRenameCancel()
                              }}
                            />
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 sm:h-7 sm:w-7 text-green-600 hover:text-green-700 hover:bg-green-50"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleRenameConfirm()
                              }}
                            >
                              <CheckCircle className="w-4 h-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 sm:h-7 sm:w-7 text-red-600 hover:text-red-700 hover:bg-red-50"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleRenameCancel()
                              }}
                            >
                              <X className="w-4 h-4" />
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 sm:gap-2 max-w-full group/title">
                            <h3 className="text-lg sm:text-xl font-bold text-slate-900 truncate" title={dataset.dataset_name}>
                              {dataset.dataset_name}
                            </h3>
                            {dataset.can_delete && (
                              <div className="flex items-center sm:opacity-0 group-hover/title:opacity-100 transition-all -ml-0.5 sm:-ml-1">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 sm:h-6 sm:w-6 text-slate-300 hover:text-blue-600"
                                  onClick={(e) => handleEditDatasetClick(e, dataset)}
                                  title="Edit dataset"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-5 w-5 sm:h-6 sm:w-6 text-slate-300 hover:text-red-600"
                                  onClick={(e) => handleDatasetDeleteClick(e, dataset.dataset_id, dataset.dataset_name)}
                                  title="Delete dataset"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </Button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mb-3 sm:mb-4 flex-wrap">
                        <p className="text-xs sm:text-sm text-slate-500 font-medium whitespace-nowrap">
                          {itemType === 'slides' ? 'Whole Slide Imaging' : 'Patch Collection'}
                        </p>
                        <div className="w-1 h-1 rounded-full bg-slate-300" />
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                          dataset.task_type === 'survival'
                            ? 'bg-amber-50 text-amber-700 border border-amber-100/50'
                            : 'bg-indigo-50 text-indigo-700 border border-indigo-100/50'
                        }`}>
                          {dataset.task_type === 'survival' ? 'Survival' : 'Classification'}
                        </span>
                        {itemType === 'slides' && (
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                            dataset.aggregation_level === 'case'
                              ? 'bg-purple-50 text-purple-700 border border-purple-100/50'
                              : 'bg-orange-50 text-orange-700 border border-orange-100/50'
                          }`}>
                            {dataset.aggregation_level === 'case' ? (
                              <><Users className="w-3 h-3" />Case-Level</>
                            ) : (
                              <><FileImage className="w-3 h-3" />File-Level</>
                            )}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-3 sm:gap-4 text-xs sm:text-sm text-slate-500/90 pt-3 sm:pt-4 border-t border-slate-100">
                        <span className="flex items-center gap-1 sm:gap-1.5 font-medium whitespace-nowrap">
                          <Database className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-slate-400" />
                          {dataset.file_count}<span className="hidden sm:inline ml-1">{itemType}</span>
                        </span>
                        <span className="flex items-center gap-1 sm:gap-1.5 font-medium whitespace-nowrap">
                          <CheckCircle className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-slate-400" />
                          {formatBytes(dataset.total_size)}
                        </span>
                      </div>
                    </div>
                  </Card>
                )
              })}

              {/* Add New Dataset Card */}
              <button
                onClick={() => navigate('/register')}
                className="flex flex-col items-center justify-center p-6 rounded-xl border-2 border-dashed border-slate-200 hover:border-blue-400 hover:bg-blue-50/50 transition-all duration-300 group min-h-[220px]"
              >
                <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center mb-4 group-hover:bg-white group-hover:shadow-md transition-all">
                  <Upload className="w-6 h-6 text-slate-400 group-hover:text-blue-600" />
                </div>
                <h3 className="text-lg font-bold text-slate-600 group-hover:text-blue-700">New Dataset</h3>
                <p className="text-sm text-slate-400 text-center mt-2 group-hover:text-slate-500">
                  Register new files to create a collection
                </p>
              </button>
            </div>
          )}
        </>
      )}

      {/* === FILES VIEW (when a dataset is selected) === */}
      {selectedDatasetId && (
        <>
          {/* Loading State */}
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
            </div>
          )}

          {/* Error State */}
          {error && !loading && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
              <p className="font-medium">Error loading files</p>
              <p className="text-sm">{error}</p>
            </div>
          )}

          {/* Empty State */}
          {!loading && !error && items.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50">
              <div className="bg-white p-4 rounded-full border border-gray-200 shadow-sm mb-4">
                <Microscope className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">No files in this dataset</h3>
              <p className="text-sm text-gray-500 max-w-sm text-center">
                This dataset appears to be empty.
              </p>
            </div>
          )}
        </>
      )}

      {/* Search and Batch Actions */}
      {selectedDatasetId && !loading && !error && items.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3 mb-3 items-stretch sm:items-center justify-between">
          <div className="relative flex-1 max-w-md w-full">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 sm:h-5 w-4 sm:w-5 text-gray-400" />
            </div>
            <input
              type="text"
              className="block w-full pl-9 sm:pl-10 pr-3 py-2 border border-gray-300 rounded-lg leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm transition-all shadow-sm"
              placeholder="Search files..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setCurrentPage(1) // Reset to first page on search
              }}
            />
            {searchQuery && (
              <button
                className="absolute inset-y-0 right-0 pr-3 flex items-center"
                onClick={() => {
                  setSearchQuery('')
                  setCurrentPage(1)
                }}
              >
                <X className="h-4 w-4 text-gray-400 hover:text-gray-600" />
              </button>
            )}
          </div>

          {selectedIds.size > 0 && (
            // Hidden visually but kept in DOM if needed for accessibility or other screen readers? 
            // Actually let's just remove the visual rendering here since we move it to table header.
            // But ListPage has Edit/Delete specific actions which NewTaskPage doesn't have.
            // We should put these actions into the header as well.
            null
          )}
        </div>
      )}

      {/* Table - only show when a dataset is selected */}
      {selectedDatasetId && !loading && !error && items.length > 0 && (
        <>
          {items.length === 0 ? (
            <Card className="p-12 flex flex-col items-center justify-center bg-gray-50/50 border-dashed border-2 border-gray-200 rounded-2xl">
              <Search className="w-12 h-12 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-900">No matching files</h3>
              <p className="text-gray-500 text-sm mt-1">Try adjusting your search terms</p>
              <Button
                variant="ghost"
                className="mt-4 text-primary-600 hover:text-primary-700"
                onClick={() => setSearchQuery('')}
              >
                Clear Search
              </Button>
            </Card>
          ) : (
            <Card className="overflow-hidden shadow-sm border-gray-100 rounded-xl bg-white/50 backdrop-blur-sm min-h-[600px] flex flex-col">
              <div className="overflow-x-auto flex-1">
                <table className="w-full">
                  <thead>
                    <tr className={`h-[50px] bg-gray-50/80 border-b border-gray-100 backdrop-blur-md ${selectedIds.size > 0 ? 'bg-blue-50/50' : ''}`}>
                      <th className="px-3 sm:px-6 py-3 text-left w-10 sm:w-12">
                        <input
                          type="checkbox"
                          checked={allPageSelected}
                          onChange={handleSelectPage}
                          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                        />
                      </th>
                      {selectedIds.size > 0 ? (
                        <th colSpan={10} className="px-3 sm:px-6 py-3 text-left">
                           <div className="flex items-center justify-between w-full">
                            <div className="flex items-center gap-4">
                               <span className="text-xs sm:text-sm font-bold text-blue-900">
                                {selectedIds.size} selected
                              </span>
                              {!allFilteredSelected && (
                                 <button
                                  onClick={() => setSelectedIds(new Set())}
                                  className="text-[10px] sm:text-xs font-medium text-gray-500 hover:text-gray-700 underline"
                                >
                                  Clear selection
                                </button>
                              )}
                            </div>
                            <div className="flex items-center gap-3">
                              <button
                                onClick={handleBatchEditClick}
                                className="text-blue-600 hover:text-blue-700 text-xs sm:text-sm font-semibold flex items-center gap-1"
                              >
                                <Edit className="w-3.5 h-3.5" />
                                Edit
                              </button>
                              <button
                                onClick={handleBatchDeleteClick}
                                className="text-red-600 hover:text-red-700 text-xs sm:text-sm font-semibold flex items-center gap-1"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                Delete
                              </button>
                            </div>
                          </div>
                        </th>
                      ) : (
                        <>
                          <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Slide ID</th>
                          <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Type</th>
                          {selectedDatasetType === 'survival' ? (
                            <>
                              <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Time (M)</th>
                              <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Status</th>
                            </>
                          ) : (
                            <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Label</th>
                          )}
                          <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Patient Info</th>
                          <th className="px-3 sm:px-6 py-3 text-right text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Action</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white/40">
                     {/* Batch Selection Banner — show prompt to select all when page is selected */}
                      {allPageSelected && !allFilteredSelected && totalCount > pageSlides.length && (
                        <tr className="bg-blue-50/50">
                          <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                            <span className="font-medium">All {pageSlides.length} items on this page are selected.</span>
                            <button
                              onClick={handleSelectAllFiltered}
                              className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                            >
                              Select all {totalCount} items
                            </button>
                          </td>
                        </tr>
                      )}
                      {/* Show when all items are selected */}
                      {allFilteredSelected && totalCount > pageSlides.length && (
                        <tr className="bg-blue-50/50">
                          <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                            <span className="font-medium">All {totalCount} items are selected.</span>
                            <button
                              onClick={() => setSelectedIds(new Set())}
                              className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                            >
                              Clear selection
                            </button>
                          </td>
                        </tr>
                      )}

                    {hasMultiSlideCases && paginatedCases ? (
                      // Grouped view - show cases with expandable slides
                      paginatedCases.map(([caseId, slides]) => {
                        const isNoCase = caseId === '__no_case__'
                        const isMultiSlide = slides.length > 1
                        const isExpanded = expandedCases.has(caseId)
                        const allSelected = slides.every(s => selectedIds.has(s.wsi_id))
                        const someSelected = slides.some(s => selectedIds.has(s.wsi_id))

                        // For single-slide cases, render directly
                        if (!isMultiSlide) {
                          const it = slides[0]
                          const isSelected = selectedIds.has(it.wsi_id)
                          return (
                            <tr
                              key={it.wsi_id}
                              className={`group transition-all duration-200 border-l-2 ${isSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-white/60 border-transparent hover:border-gray-200'}`}
                            >
                              <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12">
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleSelection(it.wsi_id)}
                                  className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                                />
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex flex-col min-w-[120px] sm:min-w-[150px] min-h-[3.5rem] sm:min-h-[4rem] justify-center">
                                  <span className="text-sm sm:text-base font-semibold text-gray-900 truncate max-w-[150px] sm:max-w-[200px]" title={it.wsi_id}>{it.wsi_id}</span>
                                  <span className="text-[10px] sm:text-sm text-gray-500 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                  {it.case_id && !isNoCase && (
                                    <span className="text-[10px] sm:text-xs text-blue-600 mt-0.5 truncate max-w-[150px] sm:max-w-[200px]" title={`Case: ${it.case_id}`}>
                                      Case: {it.case_id}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {(() => {
                                  const fileType = getFileType(it.file_extension, it.file_size)
                                  return fileType === 'WSI' ? (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">WSI</span>
                                  ) : (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">Patch</span>
                                  )
                                })()}
                              </td>
                              {selectedDatasetType === 'survival' ? (
                                <>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {it.event_time != null ? (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 shadow-sm whitespace-nowrap">{it.event_time}</span>
                                    ) : (
                                      <span className="text-gray-300 text-[10px] sm:text-sm italic">Not set</span>
                                    )}
                                  </td>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {it.event_status != null ? (
                                      <span className={`inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium border shadow-sm whitespace-nowrap ${it.event_status === 1 ? 'bg-red-100/80 text-red-700 border-red-200/60' : 'bg-green-100/80 text-green-700 border-green-200/60'}`}>
                                        {it.event_status === 1 ? 'Event' : 'Censored'}
                                      </span>
                                    ) : (
                                      <span className="text-gray-300 text-[10px] sm:text-sm italic">Not set</span>
                                    )}
                                  </td>
                                </>
                              ) : (
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {it.label ? (
                                    <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">{it.label}</span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">No Label</span>
                                  )}
                                </td>
                              )}
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                  {!(it.age || it.gender || it.source) ? (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">Not specified</span>
                                  ) : (
                                    <>
                                      {it.source && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap"><span className="hidden sm:inline">Source: </span><span className="sm:ml-1 text-blue-900">{it.source}</span></span>}
                                      {it.age && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.age}y</span>}
                                      {it.gender && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.gender}</span>}
                                    </>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                                <div className="flex items-center justify-end gap-1 sm:gap-3 sm:opacity-60 group-hover:opacity-100 transition-opacity">
                                  <Link
                                    to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                    state={{
                                      fromDataset: true,
                                      datasetId: selectedDatasetId,
                                      datasetName: selectedDatasetName
                                    }}
                                    title="View File"
                                  >
                                    <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg"><Microscope className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
                                  </Link>
                                  {it.can_delete && <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" title="Edit Metadata" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>}
                                  {it.can_delete && <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" title="Delete File" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}><Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>}
                                </div>
                              </td>
                            </tr>
                          )
                        }

                        // Multi-slide case - render expandable group
                        return (
                          <React.Fragment key={caseId}>
                            {/* Case header row */}
                            <tr
                              className={`group transition-all duration-200 border-l-2 cursor-pointer ${someSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-gray-50/60 border-transparent hover:border-blue-200'}`}
                              onClick={() => toggleCaseExpansion(caseId)}
                            >
                              <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12" onClick={(e) => e.stopPropagation()}>
                                <input
                                  type="checkbox"
                                  checked={allSelected}
                                  ref={el => { if (el) el.indeterminate = someSelected && !allSelected }}
                                  onChange={(e) => {
                                    const newSelected = new Set(selectedIds)
                                    if (e.target.checked) {
                                      slides.forEach(s => newSelected.add(s.wsi_id))
                                    } else {
                                      slides.forEach(s => newSelected.delete(s.wsi_id))
                                    }
                                    setSelectedIds(newSelected)
                                  }}
                                  className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                                />
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex items-center gap-2 sm:gap-3 min-h-[3.5rem] sm:min-h-[4rem]">
                                  <ChevronDown className={`w-4 h-4 sm:w-5 sm:h-5 text-gray-400 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
                                  <div className="flex flex-col sm:flex-row sm:items-center sm:gap-3">
                                    <div className="flex items-center gap-2">
                                      <Users className="w-4 h-4 sm:w-5 sm:h-5 text-blue-500" />
                                      <span className="text-sm sm:text-base font-semibold text-gray-900">
                                        {isNoCase ? 'No Case ID' : `Case: ${caseId}`}
                                      </span>
                                    </div>
                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200">
                                      {slides.length} slides
                                    </span>
                                  </div>
                                </div>
                              </td>

                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {(() => {
                                  // eslint-disable-next-line
                                  const types = new Set(slides.map(s => getFileType(s.file_extension, s.file_size)))
                                  if (types.has('WSI') && types.has('Patch')) {
                                    return <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">Mixed</span>
                                  }
                                  const type = types.values().next().value || 'WSI'
                                  return type === 'WSI' ? (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">WSI</span>
                                  ) : (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">Patch</span>
                                  )
                                })()}
                              </td>

                              {selectedDatasetType === 'survival' ? (
                                <>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    <span className="text-gray-400 text-xs italic">See slides</span>
                                  </td>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {(() => {
                                      const events = slides.filter(s => s.event_status === 1).length
                                      const censored = slides.filter(s => s.event_status === 0).length
                                      if (events === 0 && censored === 0) return <span className="text-gray-300 text-xs italic">Not set</span>
                                      return (
                                        <div className="flex flex-col gap-1">
                                          {events > 0 && <span className="text-xs text-red-600 font-medium">{events} Event{events > 1 ? 's' : ''}</span>}
                                          {censored > 0 && <span className="text-xs text-green-600 font-medium">{censored} Censored</span>}
                                        </div>
                                      )
                                    })()}
                                  </td>
                                </>
                              ) : (
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {(() => {
                                    const labels = Array.from(new Set(slides.map(s => s.label).filter(Boolean)))
                                    if (labels.length === 0) return <span className="text-gray-300 text-xs italic">No Label</span>
                                    if (labels.length === 1) return <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">{labels[0]}</span>
                                    return (
                                      <div className="flex flex-wrap gap-1">
                                        {labels.slice(0, 2).map(l => (
                                          <span key={l} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">{l}</span>
                                        ))}
                                        {labels.length > 2 && <span className="text-xs text-gray-500">+{labels.length - 2}</span>}
                                      </div>
                                    )
                                  })()}
                                </td>
                              )}

                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                  {(() => {
                                    const sources = Array.from(new Set(slides.map(s => s.source as string).filter(Boolean)))
                                    const ages = Array.from(new Set(slides.map(s => s.age).filter((a: any) => a !== null && a !== undefined)))
                                    const genders = Array.from(new Set(slides.map(s => s.gender as string).filter(Boolean)))

                                    if (sources.length === 0 && ages.length === 0 && genders.length === 0) {
                                      return <span className="text-gray-300 text-[10px] sm:text-sm italic">Not specified</span>
                                    }

                                    return (
                                      <>
                                        {sources.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
                                            {sources.length === 1 ? <><span className="hidden sm:inline">Source: </span><span className="sm:ml-1 text-blue-900">{sources[0]}</span></> : `${sources.length} Sources`}
                                          </span>
                                        )}
                                        {ages.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                            {ages.length === 1 ? `${ages[0]}y` : `${Math.min(...ages as number[])}..${Math.max(...ages as number[])}y`}
                                          </span>
                                        )}
                                        {genders.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                            {genders.length === 1 ? genders[0] : 'Mixed'}
                                          </span>
                                        )}
                                      </>
                                    )
                                  })()}
                                </div>
                              </td>

                              <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                                <span className="text-xs text-gray-400 whitespace-nowrap">{isExpanded ? 'Collapse' : 'Expand'}</span>
                              </td>
                            </tr>
                            {/* Expanded slides */}
                            {isExpanded && slides.map((it) => {
                              const isSelected = selectedIds.has(it.wsi_id)
                              return (
                                <tr
                                  key={it.wsi_id}
                                  className={`group transition-all duration-200 border-l-4 ${isSelected ? 'bg-blue-50/40 border-blue-400' : 'bg-gray-50/30 hover:bg-white/60 border-blue-200'}`}
                                >
                                  <td className="px-3 sm:px-6 py-3 sm:py-4 w-10 sm:w-12 pl-6 sm:pl-10">
                                    <input
                                      type="checkbox"
                                      checked={isSelected}
                                      onChange={() => toggleSelection(it.wsi_id)}
                                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                                    />
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    <div className="flex flex-col min-w-[120px] sm:min-w-[150px] pl-4 sm:pl-6 min-h-[3rem] justify-center">
                                      <span className="text-xs sm:text-sm font-medium text-gray-700 truncate max-w-[150px] sm:max-w-[200px]" title={it.wsi_id}>{it.wsi_id}</span>
                                      <span className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                    </div>
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    {(() => {
                                      const fileType = getFileType(it.file_extension, it.file_size)
                                      return fileType === 'WSI' ? (
                                        <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">WSI</span>
                                      ) : (
                                        <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">Patch</span>
                                      )
                                    })()}
                                  </td>
                                  {selectedDatasetType === 'survival' ? (
                                    <>
                                      <td className="px-3 sm:px-6 py-3 sm:py-4">
                                        {it.event_time != null ? (
                                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 whitespace-nowrap">{it.event_time}</span>
                                        ) : (
                                          <span className="text-gray-300 text-[10px] italic">Not set</span>
                                        )}
                                      </td>
                                      <td className="px-3 sm:px-6 py-3 sm:py-4">
                                        {it.event_status != null ? (
                                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap ${it.event_status === 1 ? 'bg-red-100/80 text-red-700 border-red-200/60' : 'bg-green-100/80 text-green-700 border-green-200/60'}`}>
                                            {it.event_status === 1 ? 'Event' : 'Censored'}
                                          </span>
                                        ) : (
                                          <span className="text-gray-300 text-[10px] italic">Not set</span>
                                        )}
                                      </td>
                                    </>
                                  ) : (
                                    <td className="px-3 sm:px-6 py-3 sm:py-4">
                                      {it.label ? (
                                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 whitespace-nowrap">{it.label}</span>
                                      ) : (
                                        <span className="text-gray-300 text-[10px] italic">No Label</span>
                                      )}
                                    </td>
                                  )}
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    <div className="flex flex-wrap gap-1 items-center min-w-[80px]">
                                      {!(it.age || it.gender || it.source) ? (
                                        <span className="text-gray-300 text-[10px] italic">-</span>
                                      ) : (
                                        <>
                                          {it.source && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">{it.source}</span>}
                                          {it.age && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.age}y</span>}
                                          {it.gender && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.gender}</span>}
                                        </>
                                      )}
                                    </div>
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4 text-right">
                                    <div className="flex items-center justify-end gap-1 sm:gap-2 opacity-60 group-hover:opacity-100 transition-opacity">
                                      <Link
                                        to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                        state={{
                                          fromDataset: true,
                                          datasetId: selectedDatasetId,
                                          datasetName: selectedDatasetName
                                        }}
                                        title="View File"
                                      >
                                        <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg"><Microscope className="w-3 h-3 sm:w-4 sm:h-4" /></Button>
                                      </Link>
                                      {it.can_delete && <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" title="Edit Metadata" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit className="w-3 h-3 sm:w-4 sm:h-4" /></Button>}
                                      {it.can_delete && <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" title="Delete File" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}><Trash2 className="w-3 h-3 sm:w-4 sm:h-4" /></Button>}
                                    </div>
                                  </td>
                                </tr>
                              )
                            })}
                          </React.Fragment>
                        )
                      })
                    ) : (
                      // Flat view - no multi-slide cases
                      paginatedItems.map((it) => {
                        const isSelected = selectedIds.has(it.wsi_id)
                        return (
                          <tr
                            key={it.wsi_id}
                            className={`group transition-all duration-200 border-l-2 ${isSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-white/60 border-transparent hover:border-gray-200'}`}
                          >
                            <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelection(it.wsi_id)}
                                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                              />
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              <div className="flex flex-col min-w-[120px] sm:min-w-[150px] min-h-[3.5rem] sm:min-h-[4rem] justify-center">
                                <span className="text-sm sm:text-base font-semibold text-gray-900 truncate max-w-[150px] sm:max-w-[200px]" title={it.wsi_id}>{it.wsi_id}</span>
                                <span className="text-[10px] sm:text-sm text-gray-500 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                {it.case_id && !isPatchDataset && (
                                  <span className="text-[10px] sm:text-xs text-blue-600 mt-0.5 truncate max-w-[150px] sm:max-w-[200px]" title={`Case: ${it.case_id}`}>
                                    Case: {it.case_id}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              {(() => {
                                const fileType = getFileType(it.file_extension, it.file_size)
                                return fileType === 'WSI' ? (
                                  <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">
                                    WSI
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">
                                    Patch
                                  </span>
                                )
                              })()}
                            </td>
                            {selectedDatasetType === 'survival' ? (
                              <>
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {it.event_time != null ? (
                                    <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 shadow-sm whitespace-nowrap">
                                      {it.event_time}
                                    </span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">Not set</span>
                                  )}
                                </td>
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {it.event_status != null ? (
                                    <span className={`inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium border shadow-sm whitespace-nowrap ${it.event_status === 1
                                      ? 'bg-red-100/80 text-red-700 border-red-200/60'
                                      : 'bg-green-100/80 text-green-700 border-green-200/60'
                                      }`}>
                                      {it.event_status === 1 ? 'Event' : 'Censored'}
                                    </span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">Not set</span>
                                  )}
                                </td>
                              </>
                            ) : (
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {it.label ? (
                                  <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">
                                    {it.label}
                                  </span>
                                ) : (
                                  <span className="text-gray-300 text-[10px] sm:text-sm italic">No Label</span>
                                )}
                              </td>
                            )}
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                {!(it.age || it.gender || it.source) ? (
                                  <span className="text-gray-300 text-[10px] sm:text-sm italic">Not specified</span>
                                ) : (
                                  <>
                                    {it.source && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
                                        <span className="hidden sm:inline">Source: </span><span className="sm:ml-1 text-blue-900">{it.source}</span>
                                      </span>
                                    )}
                                    {it.age && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                        {it.age}y
                                      </span>
                                    )}
                                    {it.gender && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                        {it.gender}
                                      </span>
                                    )}
                                  </>
                                )}
                              </div>
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                              <div className="flex items-center justify-end gap-1 sm:gap-3 sm:opacity-60 group-hover:opacity-100 transition-opacity">
                                <Link
                                  to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                  state={{
                                    fromDataset: true,
                                    datasetId: selectedDatasetId,
                                    datasetName: selectedDatasetName
                                  }}
                                  title="View File"
                                >
                                  <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg">
                                    <Microscope className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                  </Button>
                                </Link>

                                {it.can_delete && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
                                    title="Edit Metadata"
                                    onClick={(e) => { e.preventDefault(); handleEditClick(it); }}
                                  >
                                    <Edit className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                  </Button>
                                )}

                                {it.can_delete && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg"
                                    title="Delete File"
                                    onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}
                                  >
                                    <Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                  </Button>
                                )}
                              </div>
                            </td>
                          </tr>
                        )
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination Controls */}
              <div className="px-3 sm:px-6 py-4 border-t border-gray-100 flex flex-col lg:flex-row items-center justify-between gap-6 lg:gap-4 bg-gray-50/30 backdrop-blur-sm rounded-b-xl">
                <div className="text-[11px] sm:text-sm text-gray-500 font-medium order-3 lg:order-1 text-center lg:text-left">
                  {hasMultiSlideCases ? (
                    <>
                      Showing <span className="text-gray-900">{totalCases === 0 ? 0 : startIndex + 1}</span> to{' '}
                      <span className="text-gray-900">{Math.min(startIndex + itemsPerPage, totalCases)}</span>{' '}
                      of <span className="text-gray-900">{totalCases}</span> cases
                      <span className="text-gray-400 font-normal ml-1 whitespace-nowrap">({totalCount} slides total)</span>
                    </>
                  ) : (
                    <>
                      Showing <span className="text-gray-900">{totalCount === 0 ? 0 : startIndex + 1}</span> to{' '}
                      <span className="text-gray-900">{Math.min(startIndex + itemsPerPage, totalCount)}</span>{' '}
                      of <span className="text-gray-900">{totalCount}</span> files
                    </>
                  )}
                </div>

                {totalPages > 1 && (
                  <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6 order-1 lg:order-2 w-full lg:w-auto justify-center">
                    {/* Goto Page */}
                    <div className="flex items-center justify-center gap-1.5 sm:gap-2 bg-white/50 px-3 py-1.5 rounded-full border border-gray-100 sm:border-transparent">
                      <span className="text-[11px] sm:text-sm text-gray-500 whitespace-nowrap">Go to</span>
                      <input
                        type="number"
                        min={1}
                        max={totalPages}
                        value={currentPage}
                        onChange={(e) => {
                          const val = parseInt(e.target.value)
                          if (!isNaN(val)) {
                            setCurrentPage(Math.min(Math.max(1, val), totalPages))
                          }
                        }}
                        className="w-10 sm:w-16 h-7 sm:h-9 px-1 sm:px-2 border border-gray-200 rounded-lg text-xs sm:text-sm text-center focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none transition-all font-semibold"
                      />
                      <span className="text-[11px] sm:text-sm text-gray-500 whitespace-nowrap">/ {totalPages}</span>
                    </div>

                    <div className="flex items-center gap-1.5 sm:gap-2 order-2 sm:order-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                        disabled={currentPage === 1}
                        className="h-8 w-8 sm:h-9 sm:w-9 p-0 border-gray-200 hover:bg-white hover:text-primary-600 disabled:opacity-40"
                      >
                        <ChevronLeft className="h-4 h-4 sm:h-5 sm:w-5" />
                      </Button>

                      <div className="flex items-center gap-1">
                        {Array.from({ length: totalPages }, (_, i) => i + 1)
                          .filter(p => p === 1 || p === totalPages || (p >= currentPage - 1 && p <= currentPage + 1))
                          .map((page, index, array) => (
                            <React.Fragment key={page}>
                              {index > 0 && array[index - 1] !== page - 1 && (
                                <span className="px-0.5 sm:px-1 text-gray-400 text-xs text-center">...</span>
                              )}
                              <Button
                                variant={currentPage === page ? 'default' : 'ghost'}
                                size="sm"
                                onClick={() => setCurrentPage(page)}
                                className={`h-8 w-8 sm:h-9 sm:w-9 p-0 text-xs sm:text-sm font-medium transition-all ${currentPage === page
                                  ? 'bg-primary-600 text-white shadow-md shadow-primary-200 hover:bg-primary-700'
                                  : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'
                                  }`}
                              >
                                {page}
                              </Button>
                            </React.Fragment>
                          ))}
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                        disabled={currentPage === totalPages}
                        className="h-8 w-8 sm:h-9 sm:w-9 p-0 border-gray-200 hover:bg-white hover:text-primary-600 disabled:opacity-40"
                      >
                        <ChevronRight className="h-4 h-4 sm:h-5 sm:w-5" />
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}
        </>
      )}

      {/* File Metadata Modal */}
      {showFileMetadataModal && (
        <FileMetadataModal
          selectedFiles={selectedFiles}
          fileMetadata={fileMetadata}
          onUpdateMetadata={updateFileMetadata}
          onCancel={() => {
            setShowFileMetadataModal(false)
            setSelectedFiles([])
            setFileMetadata(new Map())
            if (fileInputRef.current) {
              fileInputRef.current.value = ''
            }
          }}
          onConfirm={handleConfirmUpload}
          uploading={uploading}
        />
      )}


      {/* Delete Confirmation Modal */}
      {showDeleteModal && wsiToDelete && (
        <DeleteConfirmModal
          wsiToDelete={wsiToDelete}
          wsiStorageInfo={wsiStorageInfo}
          loadingStorageInfo={loadingStorageInfo}
          deleteMode={deleteMode}
          onDeleteModeChange={setDeleteMode}
          onCancel={() => {
            setShowDeleteModal(false)
            setWsiToDelete(null)
          }}
          onConfirm={handleConfirmDelete}
        />
      )}


      {/* Batch Delete Confirmation Modal */}
      {showBatchDeleteModal && (
        <BatchDeleteModal
          selectedIds={selectedIds}
          datasetToDeleteId={datasetToDeleteId}
          datasetToDeleteName={datasetToDeleteName}
          deleteMode={deleteMode}
          onDeleteModeChange={setDeleteMode}
          deleting={deleting}
          onCancel={() => setShowBatchDeleteModal(false)}
          onConfirm={handleConfirmBatchDelete}
        />
      )}

      {/* Edit Metadata Modal */}
      {showEditModal && editingWSI && (
        <EditMetadataModal
          editingWSI={editingWSI}
          editLabel={editLabel}
          editCaseId={editCaseId}
          editAge={editAge}
          editGender={editGender}
          editSource={editSource}
          onEditLabelChange={setEditLabel}
          onEditCaseIdChange={setEditCaseId}
          onEditAgeChange={setEditAge}
          onEditGenderChange={setEditGender}
          onEditSourceChange={setEditSource}
          updating={updating}
          onCancel={() => {
            setShowEditModal(false)
            setEditingWSI(null)
          }}
          onConfirm={handleConfirmEdit}
        />
      )}

      {/* Batch Edit Metadata Modal */}
      {showBatchEditModal && (
        <BatchEditModal
          selectedCount={selectedIds.size}
          batchEditLabel={batchEditLabel}
          batchEditCaseId={batchEditCaseId}
          batchEditAge={batchEditAge}
          batchEditGender={batchEditGender}
          batchEditSource={batchEditSource}
          onBatchEditLabelChange={setBatchEditLabel}
          onBatchEditCaseIdChange={setBatchEditCaseId}
          onBatchEditAgeChange={setBatchEditAge}
          onBatchEditGenderChange={setBatchEditGender}
          onBatchEditSourceChange={setBatchEditSource}
          batchUpdating={batchUpdating}
          onCancel={() => setShowBatchEditModal(false)}
          onConfirm={handleConfirmBatchEdit}
        />
      )}

      {/* Edit Dataset Modal */}
      {editingDatasetId && (
        <EditDatasetModal
          editingDatasetName={editingDatasetName}
          editingDatasetType={editingDatasetType}
          editingDatasetOriginalType={editingDatasetOriginalType}
          editingDatasetDataLevel={editingDatasetDataLevel}
          editingDatasetOriginalDataLevel={editingDatasetOriginalDataLevel}
          editingDatasetSaving={editingDatasetSaving}
          isSlideDataset={(() => {
            const ds = datasets.find(d => d.dataset_id === editingDatasetId)
            return ds ? getDatasetItemType(ds.total_size, ds.file_count) === 'slides' : false
          })()}
          onNameChange={setEditingDatasetName}
          onTypeChange={setEditingDatasetType}
          onDataLevelChange={setEditingDatasetDataLevel}
          onCancel={handleEditDatasetCancel}
          onSave={handleEditDatasetSave}
        />
      )}
    </div>
  )
}
