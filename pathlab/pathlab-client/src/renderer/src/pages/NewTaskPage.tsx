import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../contexts/ToastContext'
import { fetchWSIList, fetchDatasets, uploadWSIFile, deleteWSI, updateWSIMetadata, createTrainingTask, fetchExtractors, getTrainingTask, TrainingTaskDetail, DatasetSummary, startBatchUpdateMetadataTask } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Search, Upload, Plus, Loader2, FolderOpen, CheckSquare, FileText, ImageIcon, Edit2, Trash2, ChevronLeft, ChevronRight, CheckCircle2, XCircle, Settings, Layers, AlignLeft, Copy, ArrowRight, ArrowLeft, Download, AlertCircle, UploadCloud, Split, Target, Users, Microscope, ChevronDown } from 'lucide-react'
import { AGGREGATORS, TILE_SIZES } from '../constants/training'

export default function NewTaskPage() {
  const { error: toastError } = useToast()
  const navigate = useNavigate()
  const { addDeleteWSITask } = useBackgroundTask()
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1: Task Configuration
  const [taskName, setTaskName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'survival_prediction' | 'segmentation'>('classification')
  const [dataLevel, setDataLevel] = useState<'wsi' | 'patch'>('wsi')
  const [taskDescription, setTaskDescription] = useState('')

  // Step 2: Data Selection - Dataset selection (two-tier navigation)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  // selectedDatasetId is used for API calls, selectedDatasetName is used for display
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [selectedDatasetName, setSelectedDatasetName] = useState<string>('')

  // Step 2: Data Selection - File selection within dataset
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>>(new Map())

  // File upload with metadata modal
  const [showFileMetadataModal, setShowFileMetadataModal] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileMetadata, setFileMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())

  // Delete confirmation modal
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [wsiToDelete, setWsiToDelete] = useState<{ wsi_id: string; label: string; original_filename?: string } | null>(null)
  const [deleting, setDeleting] = useState(false)
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

  // Case grouping - tracks which case_ids are expanded
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set())

  // Helper function to toggle case expansion
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

  // Helper function to determine file type (WSI or Patch)
  const getFileType = (wsiPath: string | null, fileSize: number | null): 'WSI' | 'Patch' => {
    if (!wsiPath) return 'WSI'
    const path = wsiPath.toLowerCase()

    // Patch/image file extensions
    const patchExtensions = ['.png', '.jpg', '.jpeg', '.bmp']

    // Check if it's a patch image format
    if (patchExtensions.some(ext => path.endsWith(ext))) {
      return 'Patch'
    }

    // For .tif/.tiff files, check file size (100 MB threshold)
    if (path.endsWith('.tif') || path.endsWith('.tiff')) {
      const SIZE_THRESHOLD = 100 * 1024 * 1024 // 100 MB
      return (fileSize || 0) >= SIZE_THRESHOLD ? 'WSI' : 'Patch'
    }

    // Default to WSI for other formats
    return 'WSI'
  }

  // Batch edit metadata
  const [batchEditLabel, setBatchEditLabel] = useState('')
  const [batchEditCaseId, setBatchEditCaseId] = useState('')
  const [batchEditAge, setBatchEditAge] = useState('')
  const [batchEditGender, setBatchEditGender] = useState('')
  const [batchEditSource, setBatchEditSource] = useState('')
  const [batchUpdating, setBatchUpdating] = useState(false)

  // Step 3: Preprocessing Configuration
  const [tileSize, setTileSize] = useState(512)
  const [stride, setStride] = useState(0)
  const [pyramidLevel, setPyramidLevel] = useState(0)
  const [featureExtractor, setFeatureExtractor] = useState('resnet50')
  const [featureBatchSize, setFeatureBatchSize] = useState(64)
  const [availableExtractors, setAvailableExtractors] = useState<{ id: string; name: string; description: string }[]>([])
  const [loadingExtractors, setLoadingExtractors] = useState(false)
  const [extractorSearch, setExtractorSearch] = useState('')

  // Advanced Segmentation Settings
  const [segSthresh, setSegSthresh] = useState(Number(localStorage.getItem('seg_sthresh') || '8'))
  const [segMthresh, setSegMthresh] = useState(Number(localStorage.getItem('seg_mthresh') || '7'))
  const [segClose, setSegClose] = useState(Number(localStorage.getItem('seg_close') || '4'))
  const [segUseOtsu, setSegUseOtsu] = useState(localStorage.getItem('seg_use_otsu') === 'true')

  // Filter Parameters
  const [filterAreaThresh, setFilterAreaThresh] = useState(Number(localStorage.getItem('filter_a_t') || '1'))
  const [filterHoleArea, setFilterHoleArea] = useState(Number(localStorage.getItem('filter_a_h') || '256'))
  const [filterMaxHoles, setFilterMaxHoles] = useState(Number(localStorage.getItem('filter_max_n_holes') || '100'))

  // Step 2: Data selection state for large datasets
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)
  const [searchQuery, setSearchQuery] = useState('')
  const [splitRatio, setSplitRatio] = useState(70)

  // Step 4: Model Configuration
  const [aggregator, setAggregator] = useState('abmil')  // For WSI-level (aggregator)
  // Note: Patch-level uses featureExtractor directly (same as WSI feature extraction)
  const [learningRate, setLearningRate] = useState(0.0001)
  const [epochs, setEpochs] = useState(50)
  const [trainBatchSize, setTrainBatchSize] = useState(64)
  const [optimizer, setOptimizer] = useState('adam')
  const [earlyStoppingPatience, setEarlyStoppingPatience] = useState(10)
  const [autoBalance, setAutoBalance] = useState(true)

  // Step 5: Training & Execution
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'validating' | 'submitting' | 'submitted' | 'failed'>('idle')
  const [submittedTaskId, setSubmittedTaskId] = useState<string>('')
  const [submitError, setSubmitError] = useState<string>('')

  // Step 6: Polling state
  const [polledTask, setPolledTask] = useState<TrainingTaskDetail | null>(null)

  // Split Strategy State
  const [splitStrategy, setSplitStrategy] = useState<'random' | 'k_fold' | 'manual'>('random')
  const [kFoldSplits, setKFoldSplits] = useState(5)
  const [randomSeed, setRandomSeed] = useState(42)  // Random seed for reproducibility (also serves as invisible watermark)
  const [hasPreDefinedSplits, setHasPreDefinedSplits] = useState(false)
  const [predefinedSplitCounts, setPredefinedSplitCounts] = useState<{ train: number, val: number, test: number }>({ train: 0, val: 0, test: 0 })

  useEffect(() => {
    if (currentStep === 2) {
      // Load datasets when entering Step 2
      loadDatasets()
    }
    if (currentStep === 3) {
      loadExtractors()
    }
    // For patch-level, also load extractors at Step 4 (since Step 3 is skipped for patch)
    if (currentStep === 4 && dataLevel === 'patch') {
      loadExtractors()
    }
  }, [currentStep, dataLevel])

  // Reset dataset selection when dataLevel or taskType changes (user went back to Step 1 and changed settings)
  useEffect(() => {
    // Reset to dataset list view and clear selections
    setSelectedDatasetId(null)
    setSelectedDatasetName('')
    setItems([])
    setSelectedIds(new Set())
  }, [dataLevel, taskType])

  // Load files when a dataset is selected or data level changes
  useEffect(() => {
    if (selectedDatasetId) {
      loadWSIList(selectedDatasetId)
    } else {
      setItems([])
    }
  }, [selectedDatasetId, dataLevel])
  // Check for pre-defined splits when selection changes
  useEffect(() => {
    if (selectedIds.size === 0) {
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
      return
    }

    // Check if ALL selected items have a split defined
    const selectedItems = items.filter(item => selectedIds.has(item.wsi_id))
    if (selectedItems.length === 0) return

    const counts = { train: 0, val: 0, test: 0 }
    let hasMissing = false

    selectedItems.forEach(item => {
      if (!item.split) {
        hasMissing = true
      } else {
        const s = item.split.toLowerCase()
        if (s === 'train') counts.train++
        else if (s === 'val' || s === 'validation') counts.val++
        else if (s === 'test') counts.test++
      }
    })

    setPredefinedSplitCounts(counts)
    const hasSplits = !hasMissing && (counts.train > 0)
    setHasPreDefinedSplits(hasSplits)

    // Auto-select manual if available, otherwise fallback to random if currently manual
    if (hasSplits && splitStrategy !== 'manual') {
      // Optional: Auto-select? Maybe not.
    } else if (!hasSplits && splitStrategy === 'manual') {
      setSplitStrategy('random')
    }

  }, [selectedIds, items, splitStrategy])

  // Poll for task status in Step 6
  useEffect(() => {
    let intervalId: NodeJS.Timeout

    if (currentStep === 6 && submittedTaskId) {
      const poll = async () => {
        try {
          const task = await getTrainingTask(submittedTaskId)
          setPolledTask(task)
          // Stop polling if task is in terminal state
          if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
            if (intervalId) {
              clearInterval(intervalId)
            }
          }
        } catch (error) {
          console.error("Failed to poll task status", error)
        }
      }

      poll() // Immediate first run
      intervalId = setInterval(poll, 2000)
    }

    return () => {
      if (intervalId) clearInterval(intervalId)
    }
  }, [currentStep, submittedTaskId])

  async function loadExtractors() {
    if (availableExtractors.length > 0) return
    setLoadingExtractors(true)
    try {
      const data = await fetchExtractors()
      setAvailableExtractors(data)
    } catch (e) {
      console.error('Failed to load extractors:', e)
      // If API fails, leave empty - user will see loading error
      setAvailableExtractors([])
    } finally {
      setLoadingExtractors(false)
    }
  }

  async function loadDatasets() {
    setDatasetsLoading(true)
    try {
      // Pass dataLevel to filter datasets by file type (wsi or patch)
      const data = await fetchDatasets(dataLevel)
      setDatasets(data.items || [])
    } catch (e) {
      console.error('Failed to load datasets:', e)
    } finally {
      setDatasetsLoading(false)
    }
  }

  async function loadWSIList(datasetId: string) {
    setLoading(true)
    try {
      // Pass dataLevel to backend to filter by file type (wsi or patch)
      const data = await fetchWSIList(datasetId, dataLevel)
      setItems(data.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // Filter datasets by task type (classification datasets for classification, survival datasets for survival)
  const filteredDatasets = useMemo(() => {
    if (!datasets || datasets.length === 0) return []
    // Map task type to compatible dataset types
    // - classification -> only 'classification' datasets
    // - survival_prediction -> only 'survival' datasets
    // - segmentation -> only 'classification' datasets (segmentation works on labeled patches)
    const compatibleDatasetType = taskType === 'survival_prediction' ? 'survival' : 'classification'
    return datasets.filter(dataset => dataset.dataset_type === compatibleDatasetType)
  }, [datasets, taskType])

  // Filter items by search query (file type filtering is now handled by backend)
  const filteredItems = useMemo(() => {
    if (!items || items.length === 0) return []
    if (!searchQuery) return items

    const query = searchQuery.toLowerCase()
    return items.filter(item => (
      (item.original_filename || '').toLowerCase().includes(query) ||
      (item.wsi_id || '').toLowerCase().includes(query) ||
      (item.label || '').toLowerCase().includes(query)
    ))
  }, [items, searchQuery])

  // Group items by case_id
  const groupedByCaseId = useMemo(() => {
    const groups = new Map<string, typeof filteredItems>()
    const NO_CASE = '__no_case__'

    filteredItems.forEach(item => {
      const caseId = item.case_id || NO_CASE
      if (!groups.has(caseId)) {
        groups.set(caseId, [])
      }
      groups.get(caseId)!.push(item)
    })

    // Convert to array and sort: cases with multiple slides first, then by case_id
    const sortedGroups = Array.from(groups.entries()).sort((a, b) => {
      // Put "no case" group at the end
      if (a[0] === NO_CASE) return 1
      if (b[0] === NO_CASE) return -1
      // Sort by number of slides (descending), then by case_id
      if (b[1].length !== a[1].length) return b[1].length - a[1].length
      return a[0].localeCompare(b[0])
    })

    return sortedGroups
  }, [filteredItems])

  // Check if this is a patch dataset (majority of files are patches)
  const isPatchDataset = useMemo(() => {
    if (filteredItems.length === 0) return false
    const patchCount = filteredItems.filter(item => getFileType(item.wsi_path, item.file_size) === 'Patch').length
    return patchCount > filteredItems.length / 2
  }, [filteredItems])

  // Check if we should use grouping UI
  const hasMultiSlideCases = useMemo(() => {
    // Check if any item has a valid case_id
    const hasAnyCaseId = filteredItems.some(item => item.case_id && item.case_id.trim() !== '')
    if (!hasAnyCaseId) return false

    if (isPatchDataset) return false

    // Check if there are any multi-slide cases
    return groupedByCaseId.some(([caseId, slides]) => caseId !== '__no_case__' && slides.length > 1)
  }, [filteredItems, groupedByCaseId, isPatchDataset])

  // Pagination logic
  const totalCases = groupedByCaseId.length
  const totalPages = hasMultiSlideCases
    ? Math.ceil(totalCases / pageSize)
    : Math.ceil(filteredItems.length / pageSize)

  // Update logic to ensure currentPage is valid
  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(totalPages)
    } else if (totalPages === 0 && currentPage !== 1) {
      setCurrentPage(1)
    }
  }, [totalPages, currentPage])

  const startIndex = (currentPage - 1) * pageSize

  // Get paginated cases or items
  const paginatedCases = hasMultiSlideCases
    ? groupedByCaseId.slice(startIndex, startIndex + pageSize)
    : null
  const paginatedItems = hasMultiSlideCases
    ? [] // Not used when grouping
    : filteredItems.slice(startIndex, startIndex + pageSize)

  // Batch selection logic
  const pageSlides = useMemo(() => {
    if (hasMultiSlideCases && paginatedCases) {
      return paginatedCases.flatMap(([, slides]) => slides)
    }
    return paginatedItems || []
  }, [hasMultiSlideCases, paginatedCases, paginatedItems])

  const allPageSelected = pageSlides.length > 0 && pageSlides.every(s => selectedIds.has(s.wsi_id))
  
  const allFilteredSelected = filteredItems.length > 0 && filteredItems.every(s => selectedIds.has(s.wsi_id))

  const handleSelectPage = () => {
    // If all items are selected (Global Select All), unchecking the master checkbox should clear ALL selection
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

  const handleSelectAllFiltered = () => {
     setSelectedIds(new Set(filteredItems.map(i => i.wsi_id)))
  }


  // Calculate class distribution for k-fold validation (classification) or survival data count (survival)
  const classDistribution = useMemo(() => {
    const selectedItems = filteredItems.filter(item => selectedIds.has(item.wsi_id))
    const distribution: Record<string, number> = {}

    selectedItems.forEach(item => {
      if (taskType === 'survival_prediction') {
        // For survival tasks, check event_time and event_status
        const hasSurvivalData = item.event_time != null && item.event_status != null
        const key = hasSurvivalData ? '__has_survival__' : '__unlabeled__'
        distribution[key] = (distribution[key] || 0) + 1
      } else {
        // For classification tasks, check label
        const label = item.label || '__unlabeled__'
        distribution[label] = (distribution[label] || 0) + 1
      }
    })

    return distribution
  }, [filteredItems, selectedIds, taskType])

  // Calculate maximum allowed k for k-fold based on class distribution (or survival data count)
  const kFoldValidation = useMemo(() => {
    const isSurvival = taskType === 'survival_prediction'

    if (isSurvival) {
      // For survival tasks, check if we have samples with survival data
      const totalWithSurvival = classDistribution['__has_survival__'] || 0
      const unlabeledCount = classDistribution['__unlabeled__'] || 0

      if (totalWithSurvival < 2) {
        return {
          isValid: false,
          maxK: 0,
          minSamplesPerClass: 0,
          numClasses: 0,
          unlabeledCount,
          totalLabeled: totalWithSurvival,
          message: 'No samples with survival data found. Please set event_time and event_status for your slides.'
        }
      }

      // Max K is limited by total samples for survival (no stratification needed)
      const maxK = totalWithSurvival

      return {
        isValid: maxK >= 2,
        maxK,
        minSamplesPerClass: totalWithSurvival,
        numClasses: 1, // Not applicable for survival
        unlabeledCount,
        totalLabeled: totalWithSurvival,
        message: maxK < 2
          ? `At least 2 samples with survival data are required for k-fold.`
          : undefined
      }
    }

    // Classification task logic
    const classes = Object.keys(classDistribution).filter(k => k !== '__unlabeled__')
    const numClasses = classes.length
    const unlabeledCount = classDistribution['__unlabeled__'] || 0
    const totalLabeled = Object.entries(classDistribution)
      .filter(([k]) => k !== '__unlabeled__')
      .reduce((sum, [, count]) => sum + count, 0)

    // If no labeled samples or only one class, k-fold is not meaningful
    if (numClasses < 2) {
      return {
        isValid: false,
        maxK: 0,
        minSamplesPerClass: 0,
        numClasses,
        unlabeledCount,
        totalLabeled,
        message: numClasses === 0
          ? 'No labeled samples found. Please assign labels to your slides.'
          : 'At least 2 classes are required for classification training.'
      }
    }

    // Find the minimum samples per class
    const minSamplesPerClass = Math.min(
      ...classes.map(c => classDistribution[c])
    )

    // Maximum k is limited by the class with fewest samples
    const maxK = minSamplesPerClass

    return {
      isValid: maxK >= 2,
      maxK,
      minSamplesPerClass,
      numClasses,
      unlabeledCount,
      totalLabeled,
      message: maxK < 2
        ? `Each class needs at least 2 samples for k-fold. Current minimum: ${minSamplesPerClass} samples.`
        : undefined
    }
  }, [classDistribution, taskType])

  // Calculate validation for random 7:1:2 split
  // For stratified split, each class needs enough samples to appear in all splits
  // Val is 10%, so need at least 10 samples per class to guarantee 1 in val
  const randomSplitValidation = useMemo(() => {
    const isSurvival = taskType === 'survival_prediction'

    if (isSurvival) {
      // For survival tasks, check if we have samples with survival data
      const totalWithSurvival = classDistribution['__has_survival__'] || 0
      const unlabeledCount = classDistribution['__unlabeled__'] || 0

      // For 7:1:2 split, need at least 10 samples to ensure val set has at least 1
      const minRequired = 10

      return {
        isValid: totalWithSurvival >= minRequired,
        minRequired,
        minSamplesPerClass: totalWithSurvival,
        numClasses: 1, // Not applicable for survival
        unlabeledCount,
        totalLabeled: totalWithSurvival,
        message: totalWithSurvival < minRequired
          ? `Random 7:1:2 split requires at least ${minRequired} samples with survival data. Current: ${totalWithSurvival}.`
          : undefined
      }
    }

    // Classification task logic
    const classes = Object.keys(classDistribution).filter(k => k !== '__unlabeled__')
    const numClasses = classes.length
    const unlabeledCount = classDistribution['__unlabeled__'] || 0
    const totalLabeled = Object.entries(classDistribution)
      .filter(([k]) => k !== '__unlabeled__')
      .reduce((sum, [, count]) => sum + count, 0)

    if (numClasses < 2) {
      return {
        isValid: false,
        minRequired: 0,
        numClasses,
        unlabeledCount,
        totalLabeled,
        message: numClasses === 0
          ? 'No labeled samples found. Please assign labels to your slides.'
          : 'At least 2 classes are required for classification training.'
      }
    }

    // Find the minimum samples per class
    const minSamplesPerClass = Math.min(...classes.map(c => classDistribution[c]))

    // For 7:1:2 split, val is 10%, so need at least 10 samples per class
    // to ensure each class has at least 1 sample in val set
    const minRequiredPerClass = 10
    const minRequired = numClasses * minRequiredPerClass

    return {
      isValid: minSamplesPerClass >= minRequiredPerClass,
      minRequired,
      minSamplesPerClass,
      numClasses,
      unlabeledCount,
      totalLabeled,
      message: minSamplesPerClass < minRequiredPerClass
        ? `Random 7:1:2 split requires at least ${minRequiredPerClass} samples per class. Class with fewest samples has ${minSamplesPerClass}. Total minimum: ${minRequired} samples.`
        : undefined
    }
  }, [classDistribution, taskType])

  // Auto-adjust kFoldSplits when maxK changes
  useEffect(() => {
    if (splitStrategy === 'k_fold' && kFoldValidation.maxK > 0 && kFoldSplits > kFoldValidation.maxK) {
      setKFoldSplits(Math.max(2, kFoldValidation.maxK))
    }
  }, [splitStrategy, kFoldValidation.maxK, kFoldSplits])

  const filteredExtractors = useMemo(() => {
    if (!extractorSearch) return availableExtractors
    return availableExtractors.filter(e =>
      e.name.toLowerCase().includes(extractorSearch.toLowerCase()) ||
      e.description.toLowerCase().includes(extractorSearch.toLowerCase())
    )
  }, [availableExtractors, extractorSearch])

  // Format bytes to human readable size
  const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes || bytes === 0) return '0 B'
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

      if (selectedDatasetId) {
        await loadWSIList(selectedDatasetId)
      }

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
    }
  }

  const updateFileMetadata = (fileName: string, field: 'label' | 'case_id' | 'age' | 'gender' | 'source', value: string) => {
    const newMetadata = new Map(fileMetadata)
    const current = newMetadata.get(fileName) || { label: '', case_id: '', age: '', gender: '', source: '' }
    newMetadata.set(fileName, { ...current, [field]: value })
    setFileMetadata(newMetadata)
  }

  const handleDeleteClick = (wsi_id: string, label: string, original_filename?: string) => {
    setWsiToDelete({ wsi_id, label, original_filename })
    setShowDeleteModal(true)
  }

  const handleConfirmDelete = async () => {
    if (!wsiToDelete) return

    try {
      addDeleteWSITask([wsiToDelete.wsi_id], 'standard')
      setShowDeleteModal(false)
      setWsiToDelete(null)
      // Delayed refresh
      if (selectedDatasetId) {
        setTimeout(() => loadWSIList(selectedDatasetId), 500)
      }
    } catch (err) {
      console.error('Failed to delete WSI:', err)
      alert(`Failed to delete WSI: ${err}`)
    }
  }

  const handleBatchDeleteClick = () => {
    if (selectedIds.size === 0) {
      alert('Please select at least one slide to delete')
      return
    }
    setShowBatchDeleteModal(true)
  }

  const handleConfirmBatchDelete = async () => {
    if (selectedIds.size === 0) return

    try {
      addDeleteWSITask(Array.from(selectedIds), 'standard')
      setShowBatchDeleteModal(false)
      setSelectedIds(new Set())
      // Delayed refresh
      if (selectedDatasetId) {
        setTimeout(() => loadWSIList(selectedDatasetId), 500)
      }
    } catch (err) {
      console.error('Failed to batch delete:', err)
      alert(`Failed to batch delete: ${err}`)
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
      if (selectedDatasetId) {
        await loadWSIList(selectedDatasetId)
      }
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
      alert(`Metadata update started for ${request.wsi_ids.length} items. Check notification center for progress.`)
    } catch (err) {
      console.error('Failed to start batch edit:', err)
      alert(`Failed to start batch edit: ${err}`)
    } finally {
      setBatchUpdating(false)
    }
  }

  const parseErrorMessage = (error: string): string => {
    // Extract meaningful error message
    if (error.includes('Failed to create training task:')) {
      return error.replace('Failed to create training task:', '').trim()
    }
    return error
  }

  const getErrorSuggestion = (error: string): string | null => {
    const errorLower = error.toLowerCase()

    if (errorLower.includes('network') || errorLower.includes('fetch')) {
      return 'Check your network connection and try again.'
    }
    if (errorLower.includes('wsi') || errorLower.includes('slide')) {
      return 'Ensure all selected WSI files have valid labels.'
    }
    if (errorLower.includes('gpu') || errorLower.includes('cuda')) {
      return 'A CUDA-capable GPU is required. Please check GPU availability and CUDA driver installation.'
    }
    if (errorLower.includes('timeout')) {
      return 'The server is taking too long to respond. Please try again later.'
    }

    return null
  }

  const startTraining = async () => {
    // 1. Validation phase
    setTrainingStatus('validating')
    setSubmitError('')
    setSubmittedTaskId('')

    // Simulate validation delay
    await new Promise(resolve => setTimeout(resolve, 300))

    // 2. Submission phase
    setTrainingStatus('submitting')

    try {
      // Build split config
      let splitConfig: any = undefined
      if (splitStrategy === 'manual') {
        if (!hasPreDefinedSplits) {
          throw new Error("No pre-defined splits found in selected dataset. Please upload a split CSV in the dataset view.")
        }

        // Construct split map from items
        const manualSplits: Record<string, string> = {}
        items.filter(item => selectedIds.has(item.wsi_id) && item.split).forEach(item => {
          let s = item.split.toLowerCase()
          if (s === 'validation') s = 'val'
          manualSplits[item.wsi_id] = s
        })

        splitConfig = {
          strategy: 'manual',
          manual_splits: manualSplits,
          seed: randomSeed
        }
      } else if (splitStrategy === 'k_fold') {
        splitConfig = {
          strategy: 'k_fold',
          n_splits: kFoldSplits,
          seed: randomSeed
        }
      } else {
        splitConfig = {
          strategy: 'random',
          ratios: { train: 0.7, val: 0.1, test: 0.2 },
          seed: randomSeed
        }
      }

      // Submit training task to backend
      const result = await createTrainingTask({
        task_name: taskName,
        task_type: taskType,
        data_level: dataLevel,
        task_description: taskDescription,
        wsi_ids: Array.from(selectedIds),
        preprocessing: {
          tile_size: tileSize,
          stride: stride,
          level: pyramidLevel,
          feature_extractor: featureExtractor,
          feature_batch_size: featureBatchSize,
          use_gpu: true,  // Always use GPU for feature extraction
          // Tissue segmentation parameters
          sthresh: segSthresh,
          mthresh: segMthresh,
          close: segClose,
          use_otsu: segUseOtsu,
          contour_fn: 'four_pt',
          use_padding: true,
          // Filter parameters
          a_t: filterAreaThresh,
          a_h: filterHoleArea,
          max_n_holes: filterMaxHoles
        },
        model: {
          aggregator: dataLevel === 'wsi' ? aggregator : 'none',
          backbone: dataLevel === 'patch' ? featureExtractor : undefined,  // Patch-level uses feature extractor as backbone
          learning_rate: learningRate,
          epochs: epochs,
          optimizer: optimizer,
          batch_size: trainBatchSize,
          auto_balance: autoBalance,
          early_stopping_patience: earlyStoppingPatience
        },
        split_config: splitConfig
      })

      // Task submitted successfully
      setSubmittedTaskId(result.task_id)
      setTrainingStatus('submitted')

      // Delay transition to show success state
      setTimeout(() => {
        setCurrentStep(6)
      }, 800)
    } catch (err) {
      console.error('Failed to submit training task:', err)
      setSubmitError(String(err))
      setTrainingStatus('failed')
    }
  }

  // Configuration validation
  const validateConfiguration = useMemo(() => {
    const warnings: string[] = []
    const errors: string[] = []

    // Parameter range checks
    if (epochs <= 0) {
      errors.push('Epochs must be greater than 0')
    } else if (epochs > 200) {
      warnings.push('High epoch count (>200) may lead to overfitting')
    }

    if (learningRate <= 0) {
      errors.push('Learning rate must be greater than 0')
    } else if (learningRate > 0.01) {
      warnings.push('High learning rate (>0.01) may cause training instability')
    } else if (learningRate < 0.00001) {
      warnings.push('Very low learning rate (<0.00001) may result in slow convergence')
    }

    if (trainBatchSize <= 0) {
      errors.push('Batch size must be greater than 0')
    }

    // Dataset size checks
    if (selectedIds.size < 10) {
      warnings.push('Small dataset (<10 files) may lead to poor generalization')
    }

    // Tile size checks
    if (tileSize < 256) {
      warnings.push('Small tile size (<256) may miss important context')
    } else if (tileSize > 1024) {
      warnings.push('Large tile size (>1024) will increase GPU memory usage')
    }

    // K-Fold validation
    if (splitStrategy === 'k_fold') {
      if (!kFoldValidation.isValid) {
        errors.push(kFoldValidation.message || 'K-Fold cross-validation is not available with current data')
      } else if (kFoldSplits > kFoldValidation.maxK) {
        errors.push(`K=${kFoldSplits} exceeds maximum allowed (${kFoldValidation.maxK}) based on class distribution`)
      }
    }

    // Random split validation
    if (splitStrategy === 'random') {
      if (!randomSplitValidation.isValid) {
        errors.push(randomSplitValidation.message || 'Random split is not available with current data')
      }
    }

    return {
      warnings,
      errors,
      isValid: errors.length === 0
    }
  }, [epochs, learningRate, trainBatchSize, selectedIds.size, tileSize, splitStrategy, kFoldValidation, kFoldSplits, randomSplitValidation])

  const canProceedStep1 = useMemo(() => {
    return taskName.trim().length > 0 && taskDescription.trim().length > 0
  }, [taskName, taskDescription])

  const canProceedStep2 = useMemo(() => {
    if (selectedIds.size === 0) return false

    // Check split strategy validation
    if (splitStrategy === 'random' && !randomSplitValidation.isValid) return false
    if (splitStrategy === 'k_fold' && !kFoldValidation.isValid) return false
    if (splitStrategy === 'k_fold' && kFoldSplits > kFoldValidation.maxK) return false

    return true
  }, [selectedIds, splitStrategy, randomSplitValidation.isValid, kFoldValidation.isValid, kFoldValidation.maxK, kFoldSplits])

  const canProceedStep3 = useMemo(() => {
    return true // Preprocessing config is always valid (has defaults)
  }, [])

  const canProceedStep4 = useMemo(() => {
    return true // Model config is always valid (has defaults)
  }, [])

  const canProceedStep5 = useMemo(() => {
    return validateConfiguration.isValid
  }, [validateConfiguration])

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto p-2 sm:p-6 custom-scrollbar">
        <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <PageHeader
              title="New Analysis Task"
              description="Create and train a new analysis model"
              className="flex-1"
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate('/dashboard')}
                className="gap-2 w-full sm:w-auto"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to Dashboard
              </Button>
            </PageHeader>
          </div>

          {/* Progress Steps */}
          <Card className="p-3 sm:p-6 overflow-x-auto scrollbar-none">
            <div className="flex items-center justify-between min-w-[500px] px-1">
              {/* Step 1 */}
              <div className="flex items-center space-x-2 sm:space-x-3">
                <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 1 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 1 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : '1'}
                </div>
                <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 1 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Task Setup
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${currentStep > 1 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 2 */}
              <div className="flex items-center space-x-2 sm:space-x-3">
                <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 2 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 2 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : '2'}
                </div>
                <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 2 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Data
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${currentStep > 2 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 3 - Only for WSI-level */}
              {dataLevel === 'wsi' && (
                <>
                  <div className="flex items-center space-x-2 sm:space-x-3">
                    <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 3 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                      }`}>
                      {currentStep > 3 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : '3'}
                    </div>
                    <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 3 ? 'text-gray-900' : 'text-gray-400'}`}>
                      Preprocess
                    </span>
                  </div>
                  <div className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${currentStep > 3 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>
                </>
              )}

              {/* Step 4 (or 3 for patch-level) */}
              <div className="flex items-center space-x-2 sm:space-x-3">
                <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 4 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 4 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : (dataLevel === 'patch' ? '3' : '4')}
                </div>
                <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 4 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Model
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${currentStep > 4 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 5 (or 4 for patch-level) */}
              <div className="flex items-center space-x-2 sm:space-x-3">
                <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 5 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 5 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : (dataLevel === 'patch' ? '4' : '5')}
                </div>
                <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 5 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Submit
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${currentStep > 5 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 6 (or 5 for patch-level) */}
              <div className="flex items-center space-x-2 sm:space-x-3">
                <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${currentStep >= 6 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 6 ? <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" /> : (dataLevel === 'patch' ? '5' : '6')}
                </div>
                <span className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${currentStep >= 6 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Results
                </span>
              </div>
            </div>
          </Card>

          {/* Step 1: Task Configuration */}
          {currentStep === 1 && (
            <>
              <Card className="p-4 sm:p-8 border-gray-100 shadow-sm">
                <h3 className="text-lg sm:text-xl font-bold text-gray-900 mb-4 sm:mb-6">Task Configuration</h3>

                <div className="space-y-4 sm:space-y-6">
                  <div>
                    <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">
                      Task Name *
                    </label>
                    <input
                      type="text"
                      className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
                      value={taskName}
                      onChange={(e) => setTaskName(e.target.value)}
                      placeholder="e.g., Lung Cancer Survival Prediction"
                    />
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-8">
                    <div>
                      <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">
                        Task Type *
                      </label>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                        <div
                          onClick={() => setTaskType('classification')}
                          className={`relative p-3 sm:p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${taskType === 'classification'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-xs sm:text-sm ${taskType === 'classification' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>Classification</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 sm:mt-1">Categorical labels</div>
                            </div>
                            <div className={`w-4 h-4 sm:w-5 sm:h-5 rounded-full border flex items-center justify-center transition-colors ${taskType === 'classification'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {taskType === 'classification' && (
                                <svg className="w-2.5 h-2.5 sm:w-3 sm:h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                          </div>
                        </div>
                        <div
                          onClick={() => {
                            if (dataLevel === 'patch') return; // Disable for patch-level
                            setTaskType('survival_prediction')
                          }}
                          className={`relative p-3 sm:p-4 border rounded-xl transition-all duration-200 group ${dataLevel === 'patch'
                            ? 'border-gray-100 bg-gray-50/50 cursor-not-allowed opacity-60'
                            : (taskType === 'survival_prediction' || taskType === 'segmentation')
                              ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20 cursor-pointer'
                              : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm cursor-pointer'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-xs sm:text-sm leading-tight ${dataLevel === 'patch'
                                ? 'text-gray-400'
                                : (taskType === 'survival_prediction' || taskType === 'segmentation') ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>
                                {dataLevel === 'patch' ? 'Segmentation' : 'Survival Prediction'}
                              </div>
                              <div className={`text-[10px] sm:text-xs mt-0.5 sm:mt-1 ${dataLevel === 'patch' ? 'text-primary-500 font-medium' : 'text-gray-500'}`}>
                                {dataLevel === 'patch' ? 'Coming soon' : 'Time-to-event outcomes'}
                              </div>
                            </div>
                            <div className={`w-4 h-4 sm:w-5 sm:h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'patch'
                              ? 'border-gray-200 bg-gray-50'
                              : (taskType === 'survival_prediction' || taskType === 'segmentation')
                                ? 'border-primary-500 bg-primary-500'
                                : 'border-gray-300'
                              }`}>
                              {dataLevel !== 'patch' && (taskType === 'survival_prediction' || taskType === 'segmentation') && (
                                <svg className="w-2.5 h-2.5 sm:w-3 sm:h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">
                        Data Level *
                      </label>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                        <div
                          onClick={() => {
                            setDataLevel('wsi')
                            setSelectedIds(new Set())
                            if (taskType === 'segmentation') setTaskType('survival_prediction')
                          }}
                          className={`relative p-3 sm:p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${dataLevel === 'wsi'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-xs sm:text-sm ${dataLevel === 'wsi' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>WSI-level</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 sm:mt-1">Whole slides</div>
                            </div>
                            <div className={`w-4 h-4 sm:w-5 sm:h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'wsi'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {dataLevel === 'wsi' && (
                                <svg className="w-2.5 h-2.5 sm:w-3 sm:h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                          </div>
                        </div>
                        <div
                          onClick={() => {
                            setDataLevel('patch')
                            setSelectedIds(new Set())
                            // Since patch-level only supports classification for now
                            setTaskType('classification')
                          }}
                          className={`relative p-3 sm:p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${dataLevel === 'patch'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-xs sm:text-sm ${dataLevel === 'patch' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>Patch-level</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 sm:mt-1">Image patches</div>
                            </div>
                            <div className={`w-4 h-4 sm:w-5 sm:h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'patch'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {dataLevel === 'patch' && (
                                <svg className="w-2.5 h-2.5 sm:w-3 sm:h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">
                      Description *
                    </label>
                    <textarea
                      className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
                      value={taskDescription}
                      onChange={(e) => setTaskDescription(e.target.value)}
                      placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
                      rows={3}
                    />
                  </div>
                </div>
              </Card>

              <div className="flex flex-col sm:flex-row justify-between items-center gap-3 mt-4 sm:mt-6">
                <Button
                  variant="outline"
                  onClick={() => navigate(-1)}
                  className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-sm sm:text-base order-2 sm:order-1"
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => setCurrentStep(2)}
                  disabled={!canProceedStep1}
                  className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-sm sm:text-base order-1 sm:order-2"
                >
                  Next: Select Data →
                </Button>
              </div>
            </>
          )}

          {/* Step 2: Data Selection */}
          {currentStep === 2 && (
            <>
              <Card className="p-3 sm:p-6 border-gray-100 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4 sm:mb-6">
                  <div className="flex-1 min-w-0">
                    {selectedDatasetId ? (
                      <>
                        <div className="flex items-center gap-2 mb-1.5">
                          <button
                            onClick={() => {
                              setSelectedDatasetId(null)
                              setSelectedDatasetName('')
                              setItems([])
                              setSelectedIds(new Set())
                            }}
                            className="text-xs sm:text-sm text-primary-600 hover:text-primary-700 font-semibold flex items-center gap-1 transition-colors"
                          >
                            <ChevronLeft className="w-3.5 h-3.5" />
                            Back to Datasets
                          </button>
                        </div>
                        <h3 className="text-base sm:text-lg font-bold text-gray-900 truncate">
                          Dataset: {selectedDatasetName}
                        </h3>
                        <p className="text-[11px] sm:text-sm text-gray-500 mt-1">
                          Select slides for training ({selectedIds.size} currently selected)
                        </p>
                      </>
                    ) : (
                      <>
                        <h3 className="text-base sm:text-lg font-bold text-gray-900">Select Dataset</h3>
                        <p className="text-[11px] sm:text-sm text-gray-500 mt-1">
                          Choose a source dataset for your analysis task
                          {selectedIds.size > 0 && (
                            <span className="ml-2 text-primary-600 font-bold">
                              ({selectedIds.size} files selected)
                            </span>
                          )}
                        </p>
                      </>
                    )}
                  </div>
                  <div className="flex shrink-0">
                    <button
                      onClick={() => navigate('/register')}
                      className="w-full sm:w-auto px-4 py-2 sm:py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-all text-xs sm:text-sm font-bold shadow-md shadow-primary-500/20 flex items-center justify-center gap-2 group"
                    >
                      <Plus className="w-4 h-4 group-hover:rotate-90 transition-transform duration-300" />
                      Register Files
                    </button>
                  </div>
                </div>

                {/* Registration Progress */}
                {uploadingFiles.size > 0 && (
                  <div className="mb-6 bg-gray-50/50 rounded-xl border border-gray-100 p-4 sm:p-6">
                    <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4">
                      Registering Files ({Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}/{uploadingFiles.size})
                    </h3>
                    <div className="space-y-4">
                      {Array.from(uploadingFiles.entries()).map(([fileName, fileStatus]) => (
                        <div key={fileName} className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              {fileStatus.status === 'uploading' && (
                                <Loader2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 animate-spin" />
                              )}
                              {fileStatus.status === 'success' && (
                                <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-green-500" />
                              )}
                              {fileStatus.status === 'error' && (
                                <AlertCircle className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-red-500" />
                              )}
                              <span className="text-xs sm:text-sm font-medium text-gray-900 truncate">{fileName}</span>
                            </div>
                            <span className={`text-[10px] sm:text-xs font-bold leading-none ${fileStatus.status === 'success' ? 'text-green-600' :
                              fileStatus.status === 'error' ? 'text-red-600' : 'text-primary-600'
                              }`}>
                              {fileStatus.status === 'uploading' && `${Math.round(fileStatus.progress)}%`}
                              {fileStatus.status === 'success' && 'DONE'}
                              {fileStatus.status === 'error' && 'FAILED'}
                            </span>
                          </div>
                          {/* Progress Bar */}
                          <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-300 ${fileStatus.status === 'success' ? 'bg-green-500' :
                                fileStatus.status === 'error' ? 'bg-red-500' :
                                  'bg-primary-500'
                                }`}
                              style={{ width: `${fileStatus.progress}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Dataset Selection View (when no dataset selected) */}
                {!selectedDatasetId && (
                  <>
                    {datasetsLoading ? (
                      <div className="flex flex-col items-center justify-center py-12">
                        <Loader2 className="w-8 h-8 text-primary-600 animate-spin mb-3" />
                        <p className="text-sm text-gray-500 font-medium">Loading datasets...</p>
                      </div>
                    ) : filteredDatasets.length === 0 ? (
                      <div className="text-center py-12 sm:py-16 bg-gray-50/50 rounded-2xl border-2 border-dashed border-gray-200">
                        <FolderOpen className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                        <p className="text-base sm:text-lg font-bold text-gray-700">
                          {datasets.length === 0
                            ? 'No datasets found'
                            : `No ${taskType === 'survival_prediction' ? 'survival' : 'classification'} datasets found`}
                        </p>
                        <p className="text-xs sm:text-sm text-gray-500 mt-1">
                          {datasets.length === 0
                            ? 'Register some files first to build your database.'
                            : taskType === 'survival_prediction'
                              ? 'Register datasets with event_time and event_status for survival analysis.'
                              : 'Register datasets with class labels for classification tasks.'}
                        </p>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 px-0.5">
                        {filteredDatasets.map((dataset) => (
                          <div
                            key={dataset.dataset_id ?? dataset.dataset_name}
                            onClick={() => { setSelectedDatasetId(dataset.dataset_id); setSelectedDatasetName(dataset.dataset_name); }}
                            className="p-4 sm:p-5 bg-white border border-gray-200 rounded-xl hover:border-primary-400 hover:shadow-lg hover:shadow-primary-600/5 transition-all cursor-pointer group relative overflow-hidden"
                          >
                            <div className="absolute top-0 right-0 p-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                              <ArrowRight className="w-4 h-4 text-primary-500" />
                            </div>
                            <div className="flex items-start gap-3 sm:gap-4">
                              <div className="shrink-0 p-2 sm:p-2.5 bg-primary-50 rounded-xl group-hover:bg-primary-100 transition-colors">
                                <FolderOpen className="w-5 h-5 sm:w-6 sm:h-6 text-primary-600" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <h4 className="font-bold text-gray-900 truncate group-hover:text-primary-700 transition-colors text-sm sm:text-base">
                                  {dataset.dataset_name}
                                </h4>
                                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 sm:mt-2">
                                  <span className="text-[10px] sm:text-xs font-semibold text-gray-500 flex items-center gap-1">
                                    <FileText className="w-3 h-3" />
                                    {dataset.file_count} slides
                                  </span>
                                  <span className="hidden sm:inline w-1 h-1 bg-gray-300 rounded-full"></span>
                                  <span className="text-[10px] sm:text-xs font-semibold text-gray-500">
                                    {formatBytes(dataset.total_size)}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {/* File Selection View (when dataset is selected) */}
                {selectedDatasetId && (
                  <div className="space-y-4">
                    <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm flex flex-col">
                      <div className="overflow-x-auto scrollbar-none">
                        <table className="w-full">
                          <thead>
                            <tr className={`bg-gray-50/80 border-b border-gray-100 backdrop-blur-md ${selectedIds.size > 0 ? 'bg-primary-50/50' : ''}`}>
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
                                  <div className="flex items-center gap-4">
                                     <span className="text-xs sm:text-sm font-bold text-primary-900">
                                      {selectedIds.size} selected
                                    </span>
                                    {selectedIds.size > 0 && !allFilteredSelected && (
                                       <button
                                        onClick={() => setSelectedIds(new Set())}
                                        className="text-[10px] sm:text-xs font-medium text-gray-500 hover:text-gray-700 underline"
                                      >
                                        Clear selection
                                      </button>
                                    )}
                                  </div>
                                </th>
                              ) : (
                                <>
                                  <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Slide ID</th>
                                  <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Type</th>
                                  {taskType === 'survival_prediction' ? (
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
                          <tbody className="divide-y divide-gray-100">
                             {/* Batch Selection Banner */}
                            {allPageSelected && !allFilteredSelected && (
                               <tr className="bg-blue-50/50">
                                <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                                  <span className="font-medium">All {pageSlides.length} items on this page are selected.</span>
                                  <button 
                                    onClick={handleSelectAllFiltered}
                                    className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                                  >
                                    Select all {filteredItems.length} items in list
                                  </button>
                                </td>
                              </tr>
                            )}
                            {allFilteredSelected && filteredItems.length > pageSlides.length && (
                               <tr className="bg-blue-50/50">
                                <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                                  <span className="font-medium">All {filteredItems.length} items in list are selected.</span>
                                  <button 
                                    onClick={() => setSelectedIds(new Set())}
                                    className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                                  >
                                    Clear selection
                                  </button>
                                </td>
                              </tr>
                            )}

                            {loading ? (
                              <tr>
                                <td colSpan={100} className="py-12 sm:py-20 text-center">
                                  <Loader2 className="w-8 h-8 text-primary-600 animate-spin mx-auto mb-3" />
                                  <span className="text-xs sm:text-sm text-gray-500 font-medium italic">Loading files...</span>
                                </td>
                              </tr>
                            ) : filteredItems.length === 0 ? (
                              <tr>
                                <td colSpan={100} className="py-12 sm:py-20 text-center text-gray-500 italic text-xs sm:text-sm">
                                  No files found.
                                </td>
                              </tr>
                            ) : hasMultiSlideCases && paginatedCases ? (
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
                                          const fileType = getFileType(it.wsi_path, it.file_size)
                                          return fileType === 'WSI' ? (
                                            <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">WSI</span>
                                          ) : (
                                            <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">Patch</span>
                                          )
                                        })()}
                                      </td>
                                      {taskType === 'survival_prediction' ? (
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
                                          <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" title="Edit Metadata" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
                                          <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" title="Delete File" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}><Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
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
                                          const types = new Set(slides.map(s => getFileType(s.wsi_path, s.file_size)))
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

                                      {taskType === 'survival_prediction' ? (
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
                                              const fileType = getFileType(it.wsi_path, it.file_size)
                                              return fileType === 'WSI' ? (
                                                <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">WSI</span>
                                              ) : (
                                                <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">Patch</span>
                                              )
                                            })()}
                                          </td>
                                          {taskType === 'survival_prediction' ? (
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
                                              <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" title="Edit Metadata" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit2 className="w-3 h-3 sm:w-4 sm:h-4" /></Button>
                                              <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" title="Delete File" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}><Trash2 className="w-3 h-3 sm:w-4 sm:h-4" /></Button>
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
                              paginatedItems && paginatedItems.map((it) => {
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
                                        const fileType = getFileType(it.wsi_path, it.file_size)
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
                                    {taskType === 'survival_prediction' ? (
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
                                        <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" title="Edit Metadata" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
                                        <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" title="Delete File" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label, it.original_filename); }}><Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
                                      </div>
                                    </td>
                                  </tr>
                                )
                              })
                            )}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination Footer */}
                      <div className="border-t border-gray-100 bg-gray-50/50 px-4 py-3 sm:px-6 sm:py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
                        <div className="text-[10px] sm:text-xs text-gray-500 font-medium">
                          Showing <span className="font-bold text-gray-900">{Math.min(hasMultiSlideCases ? totalCases : filteredItems.length, (currentPage - 1) * pageSize + 1)}</span>-
                          <span className="font-bold text-gray-900">{Math.min(currentPage * pageSize, hasMultiSlideCases ? totalCases : filteredItems.length)}</span> of
                          <span className="font-bold text-gray-900 ml-1">{hasMultiSlideCases ? totalCases : filteredItems.length} {hasMultiSlideCases ? 'Cases' : 'Items'}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                            disabled={currentPage === 1 || filteredItems.length === 0}
                            className="p-1.5 sm:p-2 rounded-xl border bg-white enabled:hover:bg-gray-50 disabled:opacity-30 transition-all font-bold"
                          >
                            <ChevronLeft className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                          </button>
                          <span className="text-[10px] sm:text-xs font-bold text-gray-600 px-2">
                            {currentPage} / {Math.max(1, Math.ceil((hasMultiSlideCases ? totalCases : filteredItems.length) / pageSize))}
                          </span>
                          <button
                            onClick={() => setCurrentPage(p => Math.min(Math.ceil((hasMultiSlideCases ? totalCases : filteredItems.length) / pageSize), p + 1))}
                            disabled={currentPage === Math.ceil((hasMultiSlideCases ? totalCases : filteredItems.length) / pageSize) || filteredItems.length === 0}
                            className="p-1.5 sm:p-2 rounded-xl border bg-white enabled:hover:bg-gray-50 disabled:opacity-30 transition-all font-bold"
                          >
                            <ChevronRight className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </Card>

              {/* Data Split Strategy */}
              {selectedDatasetId && selectedIds.size > 0 && (
                <Card className="mt-6 p-6">
                  <h3 className="text-md font-semibold text-gray-900 mb-4 flex items-center gap-2">
                    <Layers className="w-5 h-5 text-gray-500" />
                    Data Split Configuration
                  </h3>

                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {/* Random Split */}
                      <div
                        onClick={() => setSplitStrategy('random')}
                        className={`p-4 rounded-xl border cursor-pointer transition-all ${splitStrategy === 'random'
                          ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                          : 'bg-white border-gray-200 hover:border-primary-300'}`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${splitStrategy === 'random' ? 'border-primary-600' : 'border-gray-400'}`}>
                            {splitStrategy === 'random' && <div className="w-2 h-2 rounded-full bg-primary-600" />}
                          </div>
                          <span className="font-medium text-sm text-gray-900">Random Split</span>
                        </div>
                        <p className="text-xs text-gray-500 ml-6">
                          Standard 70/10/20 split (Train/Val/Test).
                        </p>
                      </div>

                      {/* K-Fold */}
                      <div
                        onClick={() => setSplitStrategy('k_fold')}
                        className={`p-4 rounded-xl border cursor-pointer transition-all ${splitStrategy === 'k_fold'
                          ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                          : 'bg-white border-gray-200 hover:border-primary-300'}`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${splitStrategy === 'k_fold' ? 'border-primary-600' : 'border-gray-400'}`}>
                            {splitStrategy === 'k_fold' && <div className="w-2 h-2 rounded-full bg-primary-600" />}
                          </div>
                          <span className="font-medium text-sm text-gray-900">K-Fold CV</span>
                        </div>
                        <p className="text-xs text-gray-500 ml-6">
                          Cross-validation with K folds.
                        </p>
                      </div>

                      {/* Manual Split */}
                      {/* Manual Split */}
                      {hasPreDefinedSplits ? (
                        <div
                          onClick={() => setSplitStrategy('manual')}
                          className={`p-4 rounded-xl border cursor-pointer transition-all ${splitStrategy === 'manual'
                            ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                            : 'bg-white border-gray-200 hover:border-primary-300'}`}
                        >
                          <div className="flex items-center gap-2 mb-2">
                            <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${splitStrategy === 'manual' ? 'border-primary-600' : 'border-gray-400'}`}>
                              {splitStrategy === 'manual' && <div className="w-2 h-2 rounded-full bg-primary-600" />}
                            </div>
                            <span className="font-medium text-sm text-gray-900">Custom Split</span>
                          </div>
                          <p className="text-xs text-gray-500 ml-6">
                            Use existing defined splits.
                          </p>
                        </div>
                      ) : (
                        <div
                          onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
                          className="p-4 rounded-xl border border-gray-200 bg-gray-50 hover:bg-gray-100 hover:border-gray-300 cursor-pointer transition-all flex flex-col justify-center"
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <UploadCloud className="w-4 h-4 text-gray-500" />
                            <span className="font-medium text-sm text-gray-600">Upload Splits</span>
                          </div>
                          <p className="text-xs text-blue-600">
                            No splits found. Click to upload CSV.
                          </p>
                        </div>
                      )}
                    </div>

                    {/* Conditional Inputs */}
                    <div className="mt-4 pl-1">
                      {splitStrategy === 'random' && (
                        <div className="space-y-3">
                          <div className="flex items-center gap-4 text-sm text-gray-600 bg-gray-50 p-3 rounded-lg border border-gray-100">
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-green-500"></span>
                              <span>Train: 70%</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                              <span>Val: 10%</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                              <span>Test: 20%</span>
                            </div>
                          </div>

                          {/* Random split validation messages */}
                          {!randomSplitValidation.isValid && (
                            <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
                              <div className="flex items-start gap-2">
                                <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                                <div className="text-sm text-red-700">
                                  <p className="font-medium">Cannot use Random 7:1:2 split</p>
                                  <p className="text-xs mt-1">{randomSplitValidation.message}</p>
                                </div>
                              </div>
                            </div>
                          )}

                          {randomSplitValidation.isValid && (
                            <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
                              <div className="text-xs text-blue-700">
                                <p className="font-medium mb-1">
                                  {randomSplitValidation.numClasses} classes, {randomSplitValidation.totalLabeled} labeled samples
                                </p>
                                <p className="text-blue-600">
                                  Expected: ~{Math.floor(randomSplitValidation.totalLabeled * 0.7)} train, ~{Math.floor(randomSplitValidation.totalLabeled * 0.1)} val, ~{Math.floor(randomSplitValidation.totalLabeled * 0.2)} test
                                </p>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {splitStrategy === 'k_fold' && (
                        <div className="space-y-3">
                          <div className="flex items-center gap-4">
                            <label className="text-sm font-medium text-gray-700">Number of Folds (K):</label>
                            <input
                              type="number"
                              min={2}
                              max={Math.min(10, kFoldValidation.maxK || 10)}
                              value={kFoldSplits}
                              onChange={(e) => {
                                const maxAllowed = Math.min(10, kFoldValidation.maxK || 10)
                                setKFoldSplits(Math.max(2, Math.min(maxAllowed, parseInt(e.target.value) || 5)))
                              }}
                              disabled={!kFoldValidation.isValid}
                              className={`w-20 px-3 py-1.5 text-sm border rounded-md focus:ring-1 focus:ring-primary-500 ${!kFoldValidation.isValid ? 'border-red-300 bg-red-50' : 'border-gray-300'
                                }`}
                            />
                            {kFoldValidation.isValid && kFoldValidation.maxK < 10 && (
                              <span className="text-xs text-amber-600">
                                (max {kFoldValidation.maxK} based on class distribution)
                              </span>
                            )}
                          </div>

                          {/* K-Fold validation messages */}
                          {!kFoldValidation.isValid && (
                            <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
                              <div className="flex items-start gap-2">
                                <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                                <div className="text-sm text-red-700">
                                  <p className="font-medium">Cannot use K-Fold cross-validation</p>
                                  <p className="text-xs mt-1">{kFoldValidation.message}</p>
                                </div>
                              </div>
                            </div>
                          )}

                          {kFoldValidation.isValid && (
                            <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
                              <div className="text-xs text-blue-700">
                                <p className="font-medium mb-1">
                                  {kFoldSplits}-Fold CV: {kFoldValidation.numClasses} classes, {kFoldValidation.totalLabeled} labeled samples
                                </p>
                                <p className="text-blue-600">
                                  Each fold will have ~{Math.floor(kFoldValidation.totalLabeled / kFoldSplits)} samples for validation
                                </p>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {splitStrategy === 'manual' && (
                        <div className="space-y-3">
                          {hasPreDefinedSplits ? (
                            <div className="p-3 bg-green-50 border border-green-100 rounded-lg">
                              <div className="flex items-center gap-2 mb-2">
                                <CheckCircle2 className="w-4 h-4 text-green-600" />
                                <span className="text-sm font-medium text-green-800">Ready to use pre-defined splits</span>
                              </div>
                              <div className="grid grid-cols-3 gap-2 text-xs">
                                <div className="bg-white p-2 rounded border border-green-100">
                                  <span className="text-gray-500 block">Train</span>
                                  <span className="font-semibold text-gray-900">{predefinedSplitCounts.train}</span>
                                </div>
                                <div className="bg-white p-2 rounded border border-green-100">
                                  <span className="text-gray-500 block">Val</span>
                                  <span className="font-semibold text-gray-900">{predefinedSplitCounts.val}</span>
                                </div>
                                <div className="bg-white p-2 rounded border border-green-100">
                                  <span className="text-gray-500 block">Test</span>
                                  <span className="font-semibold text-gray-900">{predefinedSplitCounts.test}</span>
                                </div>
                              </div>
                            </div>
                          ) : (
                            <div className="text-sm text-amber-600 bg-amber-50 p-4 rounded-lg border border-amber-100 flex flex-col gap-3">
                              <div className="flex items-start gap-2">
                                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                                <span>
                                  No split configuration found for this dataset. You can upload a CSV file with split assignments (train/val/test) in the Registration page.
                                </span>
                              </div>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
                                className="self-start ml-6 bg-white hover:bg-amber-50 border-amber-200 text-amber-700"
                              >
                                Go to Registration & Upload Splits
                              </Button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              )}

              {/* Bottom Navigation Buttons */}
              <div className="mt-8 sm:mt-12 flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 border-t border-gray-100">
                <button
                  onClick={() => setCurrentStep(1)}
                  className="w-full sm:w-auto px-6 py-2.5 border border-gray-200 text-gray-600 rounded-xl hover:bg-gray-50 transition-all font-bold text-xs sm:text-sm flex items-center justify-center gap-2"
                >
                  <ChevronLeft className="w-4 h-4" />
                  Back to Parameters
                </button>
                <button
                  onClick={() => setCurrentStep(dataLevel === 'patch' ? 4 : 3)}
                  disabled={!canProceedStep2}
                  className="w-full sm:w-auto px-8 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl shadow-lg shadow-primary-500/20 transition-all font-bold text-xs sm:text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {dataLevel === 'patch' ? 'Next: Model Config' : 'Next: Preprocessing'}
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </>
          )}

          {/* Step 3: Preprocessing Configuration (WSI-level only) */}
          {currentStep === 3 && dataLevel === 'wsi' && (
            <>
              <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 mb-6">
                {/* Left Column: Configuration Parameters */}
                <Card className="flex-1 p-3 sm:p-6 border-gray-100 shadow-sm">
                  <div className="flex items-center gap-2 sm:gap-3 mb-4 sm:mb-6">
                    <div className="p-1.5 sm:p-2 bg-blue-50 rounded-xl">
                      <Settings className="w-4 h-4 sm:w-5 sm:h-5 text-blue-600" />
                    </div>
                    <div>
                      <h4 className="text-xs sm:text-base font-bold text-gray-900">Tiling Parameters</h4>
                      <p className="text-[10px] sm:text-xs text-gray-400 mt-0.5">Configure patch extraction and filtering</p>
                    </div>
                  </div>

                  <div className="space-y-4 sm:space-y-5">
                    {/* Patch Size */}
                    <div>
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Patch Size</label>
                      <div className="grid grid-cols-3 gap-2">
                        {TILE_SIZES.map(size => (
                          <button
                            key={size}
                            onClick={() => setTileSize(size)}
                            className={`px-2 py-1.5 sm:py-2 text-[11px] sm:text-sm border rounded-xl transition-all font-bold ${tileSize === size
                              ? 'border-primary-600 bg-primary-50 text-primary-700 shadow-sm'
                              : 'border-gray-100 text-gray-400 hover:border-gray-200 bg-gray-50/50'
                              }`}
                          >
                            {size}px
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Stride & Level */}
                    <div className="grid grid-cols-2 gap-3 sm:gap-4">
                      <div>
                        <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Stride</label>
                        <input
                          type="number"
                          className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm bg-gray-50 border-gray-100 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-bold"
                          value={stride}
                          onChange={(e) => setStride(Number(e.target.value))}
                          min={0}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Pyramid</label>
                        <select
                          value={pyramidLevel}
                          onChange={(e) => setPyramidLevel(Number(e.target.value))}
                          className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm bg-gray-50 border-gray-100 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-bold outline-none"
                        >
                          <option value={0}>L0 (Max)</option>
                          <option value={1}>L1 (1/4)</option>
                          <option value={2}>L2 (1/16)</option>
                        </select>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-gray-50">
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 mt-3">Batch Size</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="number"
                          className="flex-1 px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm bg-gray-50 border-gray-100 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-bold"
                          value={featureBatchSize}
                          onChange={(e) => setFeatureBatchSize(Number(e.target.value))}
                          min={1}
                        />
                        <span className="text-[9px] sm:text-xs text-gray-400 font-medium whitespace-nowrap">GPU patches</span>
                      </div>
                    </div>

                    <div className="pt-4 border-t border-gray-50">
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Tissue Segmentation</label>
                      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                        <div className="flex flex-col gap-1">
                          <label className="text-[9px] sm:text-xs text-gray-500 font-medium">Sat. Thresh</label>
                          <input
                            type="number"
                            className="px-3 py-1.5 text-[11px] bg-gray-50 border-gray-100 rounded-lg focus:border-primary-400 transition-all font-bold"
                            value={segSthresh}
                            onChange={(e) => setSegSthresh(Number(e.target.value))}
                          />
                        </div>
                        <div className="flex flex-col gap-1">
                          <label className="text-[9px] sm:text-xs text-gray-500 font-medium">Mask Thresh</label>
                          <input
                            type="number"
                            className="px-3 py-1.5 text-[11px] bg-gray-50 border-gray-100 rounded-lg focus:border-primary-400 transition-all font-bold"
                            value={segMthresh}
                            onChange={(e) => setSegMthresh(Number(e.target.value))}
                          />
                        </div>
                      </div>
                      <div className="flex items-center gap-2 mt-4">
                        <input
                          type="checkbox"
                          id="use_otsu"
                          checked={segUseOtsu}
                          onChange={(e) => setSegUseOtsu(e.target.checked)}
                          className="w-3.5 h-3.5 text-primary-600 rounded border-gray-300 focus:ring-primary-500 cursor-pointer"
                        />
                        <label htmlFor="use_otsu" className="text-[10px] sm:text-xs text-gray-600 font-bold cursor-pointer select-none">Use Otsu Thresholding</label>
                      </div>
                    </div>
                  </div>
                </Card>

                {/* Right Column: Model Selection */}
                <Card className="lg:col-span-8 flex flex-col min-h-[400px] h-full overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                  <div className="p-3 sm:p-4 border-b border-gray-100 bg-white flex-shrink-0 z-10">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
                      <div>
                        <h4 className="text-sm sm:text-base font-bold text-gray-900">Feature Extractor</h4>
                        <p className="text-[10px] sm:text-xs text-gray-500">Select model architecture</p>
                      </div>
                      <div className="relative w-full sm:w-48">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                        <input
                          type="text"
                          placeholder="Search..."
                          className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-light"
                          value={extractorSearch}
                          onChange={(e) => setExtractorSearch(e.target.value)}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto p-3 sm:p-4 bg-gray-50/50">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                      {filteredExtractors.length > 0 ? (
                        filteredExtractors.map(extractor => (
                          <div
                            key={extractor.id}
                            onClick={() => setFeatureExtractor(extractor.id)}
                            className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${featureExtractor === extractor.id
                              ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                              : 'bg-white border-gray-100 hover:border-gray-200'
                              }`}
                          >
                            <div className="flex items-start justify-between mb-0.5">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{extractor.name}</div>
                              {featureExtractor === extractor.id && (
                                <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />
                              )}
                            </div>
                            <p className="text-[10px] sm:text-xs text-gray-500 line-clamp-1 leading-relaxed">
                              {extractor.description}
                            </p>
                          </div>
                        ))
                      ) : (
                        <div className="col-span-full py-12 text-center text-[10px] sm:text-xs text-gray-400 font-medium">
                          No models found
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              </div>

              <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(2)}
                  className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1"
                >
                  ← Back to Data
                </Button>
                <Button
                  onClick={() => setCurrentStep(4)}
                  disabled={!canProceedStep3}
                  className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-1 sm:order-2"
                >
                  Next: Model Config →
                </Button>
              </div>
            </>
          )}

          {/* Step 4: Model Configuration */}
          {currentStep === 4 && (
            <>
              <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 mb-6">
                {/* Left Column: Model Architecture */}
                <Card className="flex-1 lg:max-w-3xl flex flex-col bg-gray-50/50 overflow-hidden min-h-[350px]">
                  <div className="p-4 sm:p-5 pb-0 flex-shrink-0">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                      <h3 className="text-sm sm:text-base font-bold text-gray-900 flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-primary-600" />
                        {dataLevel === 'wsi' ? 'Aggregation Method' : 'Feature Extractor'}
                      </h3>
                      {dataLevel === 'patch' && (
                        <div className="relative w-full sm:w-48">
                          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                          <input
                            type="text"
                            placeholder="Search..."
                            className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 transition-all bg-white"
                            value={extractorSearch}
                            onChange={(e) => setExtractorSearch(e.target.value)}
                          />
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto p-4 sm:p-5 pt-0 custom-scrollbar">
                    {/* Aggregation Method (WSI-level only) */}
                    {dataLevel === 'wsi' && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                        {AGGREGATORS.map(agg => (
                          <div
                            key={agg.id}
                            onClick={() => setAggregator(agg.id)}
                            className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${aggregator === agg.id
                              ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                              : 'bg-white border-gray-100 hover:border-gray-200'
                              }`}
                          >
                            <div className="flex items-start justify-between mb-0.5">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{agg.name}</div>
                              {aggregator === agg.id && (
                                <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />
                              )}
                            </div>
                            <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2">{agg.detail}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Feature Extractor (Patch-level) */}
                    {dataLevel === 'patch' && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 pb-2">
                        {filteredExtractors.map(extractor => (
                          <div
                            key={extractor.id}
                            onClick={() => setFeatureExtractor(extractor.id)}
                            className={`p-3 sm:p-4 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${featureExtractor === extractor.id
                              ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                              : 'bg-white border-gray-100 hover:border-gray-200'
                              }`}
                          >
                            <div className="flex items-start justify-between">
                              <div className="flex-1 min-w-0">
                                <div className="font-bold text-gray-900 text-xs sm:text-sm truncate">{extractor.name}</div>
                                <div className="text-[10px] sm:text-xs text-gray-500 mt-1 line-clamp-1">{extractor.description}</div>
                              </div>
                              {featureExtractor === extractor.id && (
                                <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </Card>

                {/* Right Column: Training Parameters */}
                <Card className="flex-1 lg:max-w-md p-4 sm:p-5 flex flex-col bg-white overflow-hidden shadow-sm border-gray-100">
                  <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4 flex items-center gap-2">
                    <Settings className="w-4 h-4 text-primary-600" />
                    Training Params
                  </h3>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Learning Rate</label>
                      <input
                        type="number"
                        className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none transition-all"
                        value={learningRate}
                        onChange={(e) => setLearningRate(Number(e.target.value))}
                        step={0.0001}
                        min={0.00001}
                        max={0.01}
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Epochs</label>
                        <input
                          type="number"
                          className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                          value={epochs}
                          onChange={(e) => setEpochs(Number(e.target.value))}
                          min={1}
                          max={200}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Batch Size</label>
                        <input
                          type="number"
                          className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                          value={trainBatchSize}
                          onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                          min={1}
                          max={dataLevel === 'wsi' ? 16 : 128}
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Optimizer</label>
                      <select
                        className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                        value={optimizer}
                        onChange={(e) => setOptimizer(e.target.value)}
                      >
                        <option value="adam">Adam</option>
                        <option value="sgd">SGD</option>
                        <option value="adamw">AdamW</option>
                      </select>
                    </div>

                    <div className="pt-3 border-t border-gray-50 space-y-3">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Patience</label>
                          <input
                            type="number"
                            className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                            value={earlyStoppingPatience}
                            onChange={(e) => setEarlyStoppingPatience(Number(e.target.value))}
                            min={1}
                            max={50}
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Random Seed</label>
                          <input
                            type="number"
                            className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                            value={randomSeed}
                            onChange={(e) => setRandomSeed(parseInt(e.target.value) || 0)}
                            min={0}
                          />
                        </div>
                      </div>

                      <div className="flex items-center gap-2 pt-1">
                        <input
                          type="checkbox"
                          id="autoBalance"
                          checked={autoBalance}
                          onChange={(e) => setAutoBalance(e.target.checked)}
                          className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-3.5 h-3.5 cursor-pointer"
                        />
                        <label htmlFor="autoBalance" className="text-[11px] sm:text-xs text-gray-600 font-bold cursor-pointer select-none">Auto-balance classes</label>
                      </div>
                    </div>
                  </div>
                </Card>
              </div>

              <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(dataLevel === 'patch' ? 2 : 3)}
                  className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1"
                >
                  ← Back
                </Button>
                <Button
                  onClick={() => setCurrentStep(5)}
                  disabled={!canProceedStep4}
                  className="w-full sm:w-auto px-8 py-2 sm:py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/20 text-xs sm:text-sm order-1 sm:order-2"
                >
                  Next: Review Task →
                </Button>
              </div>
            </>
          )}

          {/* Step 5: Submit Training Task */}
          {currentStep === 5 && (
            <>
              <div className="flex flex-col lg:flex-row gap-4 sm:gap-6">
                {/* Summary Card */}
                <Card className="flex-1 p-4 sm:p-6 bg-white border-gray-100 shadow-sm">
                  <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4 sm:mb-6 flex items-center gap-2">
                    <CheckSquare className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
                    Task Overview
                  </h3>

                  <div className="space-y-4 sm:space-y-6">
                    {/* Basic Info */}
                    <div className="grid grid-cols-2 gap-2 sm:gap-4 font-bold">
                      <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                        <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Project Name</span>
                        <span className="text-xs sm:text-sm text-gray-900 truncate block">{taskName}</span>
                      </div>
                      <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                        <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Task Type</span>
                        <span className="text-xs sm:text-sm text-gray-900 truncate block capitalize">
                          {taskType.replace('_', ' ')}
                        </span>
                      </div>
                      <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                        <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Samples</span>
                        <div className="flex items-center gap-1">
                          <span className="text-xs sm:text-sm text-gray-900">{selectedIds.size}</span>
                          <span className="text-[10px] sm:text-xs text-gray-400 lowercase">{dataLevel === 'wsi' ? 'Slides' : 'Images'}</span>
                        </div>
                      </div>
                      <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                        <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Epochs</span>
                        <span className="text-xs sm:text-sm text-gray-900 font-mono">
                          {epochs}
                        </span>
                      </div>
                    </div>

                    <div className="pt-3 sm:pt-4 border-t border-gray-100">
                      <div className="flex items-center gap-2 mb-2">
                        <AlignLeft className="w-4 h-4 text-gray-400" />
                        <h4 className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">Description</h4>
                      </div>
                      <div className="p-3 bg-gray-50/50 rounded-xl border border-gray-100">
                        <p className="text-[11px] sm:text-sm text-gray-600 leading-relaxed line-clamp-2">
                          {taskDescription || "No description provided."}
                        </p>
                      </div>
                    </div>

                    <div className="pt-3 sm:pt-4 border-t border-gray-100">
                      <h4 className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Pipeline Architecture</h4>
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-primary-50 flex items-center justify-center flex-shrink-0 border border-primary-100">
                          <Layers className="w-4 h-4 sm:w-5 sm:h-5 text-primary-600" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[11px] sm:text-sm font-bold text-gray-900 truncate">
                            {dataLevel === 'wsi'
                              ? AGGREGATORS.find(a => a.id === aggregator)?.name
                              : availableExtractors.find(e => e.id === featureExtractor)?.name
                            }
                          </div>
                          {dataLevel === 'wsi' && (
                            <div className="mt-1 text-[10px] sm:text-xs flex items-center gap-1.5 text-gray-500">
                              <span className="text-gray-400">Features:</span>
                              <span className="font-bold text-gray-700 truncate">
                                {availableExtractors.find(e => e.id === featureExtractor)?.name}
                              </span>
                            </div>
                          )}
                          {dataLevel === 'patch' && (
                            <div className="mt-1 text-[10px] flex items-center gap-1 text-gray-400">
                              <span>+ Linear Probe Layer</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>

                {/* Config Details & Warnings */}
                <div className="flex-1 flex flex-col gap-4 sm:gap-6">
                  <Card className="p-4 sm:p-6 bg-white border-gray-100 shadow-sm flex-1">
                    <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4 flex items-center gap-2">
                      <Settings className="w-4 h-4 text-primary-600" />
                      Detailed Config
                    </h3>

                    <div className="space-y-4 text-[11px] sm:text-sm divide-y divide-gray-50">
                      {dataLevel === 'wsi' && (
                        <>
                          <div className="flex justify-between items-center pt-3">
                            <span className="text-gray-400 font-bold uppercase tracking-tight">Patching</span>
                            <div className="text-right">
                              <div className="font-bold text-gray-900">{tileSize}px Tiles</div>
                              <div className="text-[10px] text-gray-400">
                                {stride > 0 ? `${stride}px Stride` : '0px Overlap'}
                              </div>
                            </div>
                          </div>

                          <div className="flex justify-between items-center pt-3">
                            <span className="text-gray-400 font-bold uppercase tracking-tight">Tissue Seg</span>
                            <div className="text-right">
                              <div className="font-bold text-gray-900">
                                {segUseOtsu ? 'Otsu' : 'Threshold'}
                              </div>
                              <div className="text-[10px] text-gray-400">
                                Level {pyramidLevel}
                              </div>
                            </div>
                          </div>
                        </>
                      )}

                      <div className="flex justify-between items-center pt-3">
                        <span className="text-gray-400 font-bold uppercase tracking-tight">Learning</span>
                        <div className="text-right">
                          <div className="font-bold text-gray-900 capitalize">{optimizer}</div>
                          <div className="text-[10px] text-gray-400 font-mono">LR: {learningRate}</div>
                        </div>
                      </div>

                      <div className="flex justify-between items-center pt-3">
                        <span className="text-gray-400 font-bold uppercase tracking-tight">Data Strategy</span>
                        <div className="text-right">
                          <div className="font-bold text-gray-900">Batch: {trainBatchSize}</div>
                          <div className="text-[10px] text-gray-400">
                            {autoBalance ? 'Balanced' : 'Standard'} • Pati. {earlyStoppingPatience}
                          </div>
                        </div>
                      </div>
                    </div>
                  </Card>

                  {/* Warnings / Errors */}
                  {(validateConfiguration.errors.length > 0 || validateConfiguration.warnings.length > 0) && (
                    <div className={`rounded-xl p-3 sm:p-4 border ${validateConfiguration.errors.length > 0 ? 'bg-red-50 border-red-100' : 'bg-amber-50 border-amber-100'}`}>
                      <div className="flex items-start gap-3">
                        <div className={`mt-0.5 ${validateConfiguration.errors.length > 0 ? 'text-red-500' : 'text-amber-500'}`}>
                          <AlertCircle className="w-4 h-4 sm:w-5 sm:h-5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className={`text-xs sm:text-sm font-bold mb-1 ${validateConfiguration.errors.length > 0 ? 'text-red-900' : 'text-amber-900'}`}>
                            {validateConfiguration.errors.length > 0 ? 'Fix required' : 'System suggestions'}
                          </h4>
                          <ul className={`text-[10px] sm:text-xs space-y-0.5 font-medium ${validateConfiguration.errors.length > 0 ? 'text-red-700' : 'text-amber-700'}`}>
                            {[...validateConfiguration.errors, ...validateConfiguration.warnings].map((msg, i) => (
                              <li key={i} className="flex gap-1.5">
                                <span className="opacity-50">•</span>
                                <span className="flex-1">{msg}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Status Display Area */}
              {(trainingStatus !== 'idle' || submitError) && (
                <div className="mt-4 sm:mt-6">
                  {trainingStatus === 'validating' && (
                    <div className="flex items-center justify-center p-3 sm:p-4 bg-gray-50 rounded-xl border border-gray-100 text-gray-500 font-bold text-xs sm:text-sm gap-2">
                      <Loader2 className="animate-spin w-4 h-4 text-primary-600" />
                      Validating configuration...
                    </div>
                  )}
                  {trainingStatus === 'submitting' && (
                    <div className="flex items-center justify-center p-3 sm:p-4 bg-gray-50 rounded-xl border border-gray-100 text-gray-500 font-bold text-xs sm:text-sm gap-2">
                      <Loader2 className="animate-spin w-4 h-4 text-primary-600" />
                      Submitting training task...
                    </div>
                  )}
                  {trainingStatus === 'submitted' && (
                    <div className="p-3 sm:p-4 bg-green-50 rounded-xl border border-green-100 flex items-center justify-center gap-2 text-green-700 font-bold text-xs sm:text-sm">
                      <CheckCircle2 className="w-4 h-4" />
                      Success! Preparing results view...
                    </div>
                  )}
                  {submitError && (
                    <div className="p-3 sm:p-4 bg-red-50 rounded-xl border border-red-100">
                      <div className="flex items-start gap-3">
                        <AlertCircle className="text-red-600 w-4 h-4 sm:w-5 sm:h-5 mt-0.5" />
                        <div className="flex-1">
                          <h4 className="text-xs sm:text-sm font-bold text-red-900">Submission Failed</h4>
                          <p className="text-[11px] sm:text-xs text-red-700 mt-1 font-medium">{parseErrorMessage(submitError)}</p>
                          {getErrorSuggestion(submitError) && (
                            <p className="text-[10px] sm:text-xs text-red-600 mt-2 font-medium flex items-start gap-1">
                              <span>💡</span>
                              <span>{getErrorSuggestion(submitError)}</span>
                            </p>
                          )}
                          <button onClick={() => { setSubmitError(''); setTrainingStatus('idle'); }} className="mt-2 text-[10px] font-bold text-red-800 hover:text-red-900 underline underline-offset-2">
                            Review and retry
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col sm:flex-row justify-between items-center gap-3 mt-6 sm:mt-8 pt-6 border-t border-gray-100">
                <Button variant="outline" onClick={() => setCurrentStep(4)} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1">
                  ← Edit Parameters
                </Button>
                <Button
                  onClick={startTraining}
                  disabled={!canProceedStep5 || trainingStatus === 'submitting' || trainingStatus === 'validating'}
                  className="w-full sm:w-auto px-10 py-2 sm:py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/20 font-bold text-xs sm:text-sm order-1 sm:order-2"
                >
                  {trainingStatus === 'submitting' || trainingStatus === 'validating' ? 'Processing...' : 'Launch Training →'}
                </Button>
              </div>
            </>
          )}

          {/* Step 6: Task Submitted - Status Display */}
          {currentStep === 6 && (
            <div className="flex flex-col items-center justify-center p-2 sm:p-4 min-h-full">
              <Card className="w-full max-w-7xl overflow-hidden shadow-xl border-gray-100 ring-1 ring-black/5 bg-white">
                <div className="flex flex-col lg:flex-row">
                  {/* Left Column: Status State & Actions */}
                  <div className="lg:w-1/3 bg-gray-50/50 p-6 sm:p-8 flex flex-col justify-center items-center text-center border-b lg:border-b-0 lg:border-r border-gray-100">
                    {/* Dynamic Status Icon */}
                    {polledTask?.status === 'failed' ? (
                      <>
                        <div className="w-12 h-12 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-red-50 shadow-sm animate-in zoom-in duration-300">
                          <XCircle className="w-6 h-6 sm:w-8 sm:h-8 text-red-600" />
                        </div>
                        <h2 className="text-lg sm:text-xl font-bold text-red-900 mb-1 sm:mb-2 tracking-tight">Training Failed</h2>
                        <p className="text-xs sm:text-sm text-red-600 mb-4 sm:mb-6 max-w-[220px] mx-auto leading-relaxed font-medium">
                          {polledTask?.error_message || 'An error occurred during training.'}
                        </p>
                        {/* Error Suggestion */}
                        {getErrorSuggestion(polledTask?.error_message || '') && (
                          <div className="w-full max-w-xs bg-red-50 border border-red-100 rounded-xl p-3 mb-4">
                            <p className="text-[10px] sm:text-xs text-red-700 font-medium">
                              {getErrorSuggestion(polledTask?.error_message || '')}
                            </p>
                          </div>
                        )}
                      </>
                    ) : polledTask?.status === 'cancelled' ? (
                      <>
                        <div className="w-12 h-12 sm:w-16 sm:h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-gray-50 shadow-sm animate-in zoom-in duration-300">
                          <XCircle className="w-6 h-6 sm:w-8 sm:h-8 text-gray-500" />
                        </div>
                        <h2 className="text-lg sm:text-xl font-bold text-gray-700 mb-1 sm:mb-2 tracking-tight">Training Cancelled</h2>
                        <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">
                          The training task was cancelled.
                        </p>
                      </>
                    ) : polledTask?.status === 'completed' ? (
                      <>
                        <div className="w-12 h-12 sm:w-16 sm:h-16 bg-green-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-green-50 shadow-sm animate-in zoom-in duration-300">
                          <CheckCircle2 className="w-6 h-6 sm:w-8 sm:h-8 text-green-600" />
                        </div>
                        <h2 className="text-lg sm:text-xl font-bold text-gray-900 mb-1 sm:mb-2 tracking-tight">Training Complete</h2>
                        <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">
                          Your model is ready to use.
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="w-12 h-12 sm:w-16 sm:h-16 bg-green-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-green-50 shadow-sm animate-in zoom-in duration-300">
                          <CheckCircle2 className="w-6 h-6 sm:w-8 sm:h-8 text-green-600" />
                        </div>
                        <h2 className="text-lg sm:text-xl font-bold text-gray-900 mb-1 sm:mb-2 tracking-tight">Submission Successful</h2>
                        <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">
                          Your training task has been queued.
                        </p>
                      </>
                    )}

                    <div className="w-full max-w-xs bg-white p-1 sm:p-1.5 pl-3 pr-1.5 border border-gray-200 rounded-xl flex items-center justify-between shadow-sm mb-4 sm:mb-6">
                      <div className="flex flex-col items-start overflow-hidden min-w-0">
                        <span className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">Task ID</span>
                        <code className="text-[10px] sm:text-xs font-mono font-bold text-gray-900 truncate w-full text-left" title={submittedTaskId}>{submittedTaskId}</code>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="flex-shrink-0 h-7 w-7 rounded-md hover:bg-gray-50"
                        onClick={() => {
                          if (navigator.clipboard && navigator.clipboard.writeText) {
                            navigator.clipboard.writeText(submittedTaskId)
                          } else {
                            // Fallback for Electron or non-secure contexts
                            const textArea = document.createElement('textarea')
                            textArea.value = submittedTaskId
                            textArea.style.position = 'fixed'
                            textArea.style.opacity = '0'
                            document.body.appendChild(textArea)
                            textArea.select()
                            document.execCommand('copy')
                            document.body.removeChild(textArea)
                          }
                        }}
                      >
                        <Copy className="w-3.5 h-3.5 text-gray-400" />
                      </Button>
                    </div>

                    <div className="flex flex-col gap-2 w-full max-w-xs">
                      <Button onClick={() => navigate('/task-list')} className="w-full bg-gray-900 hover:bg-black text-white h-9 sm:h-10 text-xs sm:text-sm font-bold shadow-md shadow-gray-200">
                        Go to Task Manager
                      </Button>
                      <Button variant="outline" onClick={() => window.location.reload()} className="w-full h-9 sm:h-10 text-xs sm:text-sm border-gray-200 text-gray-500 bg-white hover:bg-gray-50 font-bold">
                        Create Another Task
                      </Button>
                    </div>
                  </div>

                  {/* Right Column: details & Pipeline */}
                  <div className="lg:w-2/3 p-6 sm:p-8 flex flex-col justify-center bg-white relative">
                    {/* Live Indicator */}
                    <div className="hidden sm:flex absolute top-6 right-6 items-center gap-1.5">
                      <span className="relative flex h-2.5 w-2.5">
                        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${polledTask?.status === 'failed' ? 'bg-red-400' :
                          polledTask?.status === 'cancelled' ? 'bg-gray-400' :
                            polledTask?.status === 'completed' ? 'bg-green-400' :
                              polledTask?.status === 'training' ? 'bg-indigo-400' : 'bg-blue-400'
                          }`}></span>
                        <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${polledTask?.status === 'failed' ? 'bg-red-500' :
                          polledTask?.status === 'cancelled' ? 'bg-gray-500' :
                            polledTask?.status === 'completed' ? 'bg-green-500' :
                              polledTask?.status === 'training' ? 'bg-indigo-500' : 'bg-blue-500'
                          }`}></span>
                      </span>
                      <span className={`text-[10px] font-bold uppercase tracking-wider ${polledTask?.status === 'failed' ? 'text-red-500' :
                        polledTask?.status === 'cancelled' ? 'text-gray-500' :
                          polledTask?.status === 'completed' ? 'text-green-600' : 'text-gray-400'
                        }`}>
                        {polledTask?.status || 'Queued'}
                      </span>
                    </div>

                    <div className="mb-6 sm:mb-8">
                      <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-4 border-b border-gray-50 pb-2">Task Summary</h3>
                      <div className="grid grid-cols-2 gap-y-3 sm:gap-y-4 gap-x-4 sm:gap-x-6">
                        <div>
                          <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">Project</div>
                          <div className="text-xs sm:text-sm font-bold text-gray-900 truncate pr-4" title={taskName}>{taskName}</div>
                        </div>
                        <div>
                          <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">Volume</div>
                          <div className="text-xs sm:text-sm font-bold text-gray-900">
                            {selectedIds.size} <span className="text-[10px] sm:text-xs font-medium text-gray-400">{dataLevel === 'wsi' ? 'Slides' : 'Images'}</span>
                          </div>
                        </div>
                        <div className="col-span-1">
                          <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">Model</div>
                          <div className="inline-flex items-center px-2 py-0.5 rounded-lg bg-indigo-50 text-indigo-700 text-[10px] sm:text-xs font-bold border border-indigo-100 truncate max-w-full">
                            {dataLevel === 'wsi'
                              ? AGGREGATORS.find(a => a.id === aggregator)?.name
                              : availableExtractors.find(e => e.id === featureExtractor)?.name
                            }
                          </div>
                        </div>
                        <div>
                          <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">Config</div>
                          <div className="text-xs sm:text-sm font-bold text-gray-900">{epochs} Epochs</div>
                        </div>
                      </div>
                    </div>

                    {/* Dynamic Pipeline Status */}
                    <div className="bg-gray-50/50 rounded-2xl p-4 sm:p-5 border border-gray-100">
                      <h3 className="text-[10px] font-bold text-gray-900 uppercase tracking-widest mb-4 flex items-center gap-2">
                        <Layers className="w-3.5 h-3.5 text-primary-600" />
                        Pipeline Status
                      </h3>
                      <div className="space-y-4">
                        {/* Step 1: Preprocessing (WSI only) */}
                        {dataLevel === 'wsi' && (
                          <div className={`flex items-start gap-4 transition-opacity duration-300 ${['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued') ? 'opacity-100' : 'opacity-50'
                            }`}>
                            <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued')
                              ? 'bg-primary-600 text-white ring-2 ring-primary-100'
                              : polledTask?.status !== 'queued' && polledTask?.status !== 'initializing'
                                ? 'bg-green-500 text-white'
                                : 'bg-gray-200 text-gray-400'
                              }`}>
                              {(!['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued')) && (polledTask?.status !== 'failed') ? <CheckCircle2 className="w-3 h-3" /> : '1'}
                            </div>
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <div className="text-xs sm:text-sm font-bold text-gray-900">Patching</div>
                                {['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued') && (
                                  <Loader2 className="w-3 h-3 text-primary-600 animate-spin" />
                                )}
                              </div>
                              <div className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate">ROI detection and extraction</div>
                            </div>
                          </div>
                        )}

                        {/* Step 2: Feature Extraction (WSI only) */}
                        {dataLevel === 'wsi' && (
                          <div className={`flex items-start gap-4 transition-opacity duration-300 ${polledTask?.status === 'feature_extraction' ? 'opacity-100' : 'opacity-50'
                            }`}>
                            <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${polledTask?.status === 'feature_extraction'
                              ? 'bg-primary-600 text-white ring-2 ring-primary-100'
                              : ['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued')
                                ? 'bg-gray-200 text-gray-400'
                                : 'bg-green-500 text-white'
                              }`}>
                              {(['training', 'completed'].includes(polledTask?.status || '')) ? <CheckCircle2 className="w-3 h-3" /> : '2'}
                            </div>
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <div className="text-xs sm:text-sm font-bold text-gray-900">Feature Extraction</div>
                                {polledTask?.status === 'feature_extraction' && (
                                  <Loader2 className="w-3 h-3 text-primary-600 animate-spin" />
                                )}
                              </div>
                              <div className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate">Generating embeddings</div>
                            </div>
                          </div>
                        )}

                        {/* Step 3: Training */}
                        <div className={`flex items-start gap-4 transition-opacity duration-300 ${polledTask?.status === 'training' ? 'opacity-100' :
                          polledTask?.status === 'failed' && polledTask?.progress >= 66 ? 'opacity-100' : 'opacity-50'
                          }`}>
                          <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${polledTask?.status === 'training'
                            ? 'bg-primary-600 text-white ring-2 ring-primary-100'
                            : polledTask?.status === 'completed'
                              ? 'bg-green-500 text-white'
                              : polledTask?.status === 'failed' && polledTask?.progress >= 66
                                ? 'bg-red-500 text-white'
                                : 'bg-gray-200 text-gray-400'
                            }`}>
                            {polledTask?.status === 'completed' ? <CheckCircle2 className="w-3 h-3" /> :
                              polledTask?.status === 'failed' && polledTask?.progress >= 66 ? <XCircle className="w-3 h-3" /> :
                                (dataLevel === 'patch' ? '2' : '3')}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <div className="text-xs sm:text-sm font-bold text-gray-900">Model Training</div>
                              {polledTask?.status === 'training' && (
                                <div className="flex items-center gap-1.5">
                                  <Loader2 className="w-3 h-3 text-primary-600 animate-spin" />
                                  <span className="text-[9px] font-bold text-primary-600 bg-primary-100 px-1 py-0.5 rounded">
                                    {polledTask?.progress
                                      ? (dataLevel === 'patch'
                                        ? `${Math.max(0, Math.min(100, Math.round(((polledTask.progress - 66) / (100 - 66)) * 100)))}%`
                                        : `${polledTask.progress.toFixed(1)}%`)
                                      : '0%'}
                                  </span>
                                </div>
                              )}
                              {polledTask?.status === 'failed' && polledTask?.progress >= 66 && (
                                <span className="text-[9px] font-bold text-red-600 bg-red-100 px-1.5 py-0.5 rounded">
                                  FAILED
                                </span>
                              )}
                            </div>
                            <div className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate">Optimization and validation</div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Error Details Panel - shown when task failed */}
                    {polledTask?.status === 'failed' && polledTask?.error_message && (
                      <div className="mt-4 bg-red-50 rounded-2xl p-4 sm:p-5 border border-red-100">
                        <h3 className="text-[10px] font-bold text-red-900 uppercase tracking-widest mb-3 flex items-center gap-2">
                          <AlertCircle className="w-3.5 h-3.5 text-red-600" />
                          Error Details
                        </h3>
                        <div className="bg-white rounded-xl p-3 border border-red-100">
                          <p className="text-xs text-red-700 font-medium break-words">
                            {polledTask.error_message}
                          </p>
                        </div>
                        {getErrorSuggestion(polledTask.error_message) && (
                          <div className="mt-3 flex items-start gap-2">
                            <span className="text-sm">💡</span>
                            <p className="text-[10px] sm:text-xs text-red-600 font-medium">
                              {getErrorSuggestion(polledTask.error_message)}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            </div>
          )}

          {/* File Metadata Modal */}
          {showFileMetadataModal && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
              <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
                {/* Header */}
                <div className="p-6 border-b border-gray-200">
                  <h3 className="text-2xl font-bold text-gray-900">Set Metadata for Files</h3>
                  <p className="text-gray-600 mt-1">Add labels and case IDs for each file (optional)</p>
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
                                  {taskType === 'survival_prediction' ? 'Label (Survival Outcome)' : 'Label (Disease Classification)'}
                                </label>
                                <input
                                  type="text"
                                  placeholder={taskType === 'survival_prediction' ? 'e.g., Surviving, Expired' : 'e.g., Benign, Malignant, Grade 1'}
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
                                  Age
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
                        Register All Files
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Delete Confirmation Modal */}
          {showDeleteModal && wsiToDelete && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
              <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
                {/* Header */}
                <div className="text-center mb-6">
                  <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  </div>
                  <h3 className="text-2xl font-bold text-gray-900 mb-2">Delete Slide?</h3>
                  <p className="text-gray-600">This action cannot be undone</p>
                </div>

                {/* WSI Info */}
                <div className="bg-gray-50 rounded-lg p-4 mb-6">
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm font-medium text-gray-700">Filename:</span>
                      <span className="text-sm text-gray-900 font-semibold">{wsiToDelete.original_filename || wsiToDelete.wsi_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm font-medium text-gray-700">Label:</span>
                      <span className="text-sm text-gray-900">{wsiToDelete.label || 'Unknown'}</span>
                    </div>
                  </div>
                </div>

                {/* Warning */}
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-6">
                  <p className="text-sm text-red-800">
                    <strong>Warning:</strong> This will permanently delete the slide file, all analysis results, and associated data.
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

          {/* Batch Delete Confirmation Modal */}
          {showBatchDeleteModal && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
              <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
                {/* Header */}
                <div className="text-center mb-6">
                  <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  </div>
                  <h3 className="text-2xl font-bold text-gray-900 mb-2">Delete Multiple Slides?</h3>
                  <p className="text-gray-600">This action cannot be undone</p>
                </div>

                {/* Info */}
                <div className="bg-gray-50 rounded-lg p-4 mb-6">
                  <p className="text-sm text-gray-900">
                    You are about to delete <strong>{selectedIds.size} file(s)</strong>
                  </p>
                </div>

                {/* Warning */}
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-6">
                  <p className="text-sm text-red-800">
                    <strong>Warning:</strong> This will permanently delete all selected slides, their files, analysis results, and associated data.
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
                    <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
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
                    {taskType === 'survival_prediction' ? 'Label (Survival Outcome)' : 'Label (Disease Classification)'}
                  </label>
                  <input
                    type="text"
                    value={editLabel}
                    onChange={(e) => setEditLabel(e.target.value)}
                    placeholder={taskType === 'survival_prediction' ? 'e.g., Surviving, Expired' : 'e.g., Benign, Malignant, Grade 1'}
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
                    Age
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
                  <input
                    type="text"
                    value={editGender}
                    onChange={(e) => setEditGender(e.target.value)}
                    placeholder="e.g., Male, Female"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
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
                    <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </div>
                  <h3 className="text-2xl font-bold text-gray-900 mb-2">Batch Edit Metadata</h3>
                  <p className="text-gray-600">Update {selectedIds.size} slide(s)</p>
                </div>

                {/* Info Message */}
                <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-800">
                    Note: Leave fields empty to keep existing values unchanged
                  </p>
                </div>

                {/* Label Input */}
                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {taskType === 'survival_prediction' ? 'Label (Survival Outcome)' : 'Label (Disease Classification)'}
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
                    Age
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
                  <input
                    type="text"
                    value={batchEditGender}
                    onChange={(e) => setBatchEditGender(e.target.value)}
                    placeholder="Leave empty to keep existing"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
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
      </div>
    </div>
  )
}

