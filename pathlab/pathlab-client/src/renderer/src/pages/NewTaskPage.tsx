import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, deleteWSI, updateWSIMetadata, createTrainingTask, fetchExtractors, getTrainingTask, TrainingTaskDetail } from '../api'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Search, Upload, Plus, Loader2, FolderOpen, CheckSquare, FileText, ImageIcon, Edit2, Trash2, ChevronLeft, ChevronRight, CheckCircle2, Settings, Layers, AlignLeft, Copy, ArrowRight } from 'lucide-react'

// Available feature extractors - order must match backend registry.py to avoid UI jump
const FEATURE_EXTRACTORS = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained CNN, 2048-dim, general-purpose baseline' },
  { id: 'vit_l_16', name: 'ViT-Large', description: 'ImageNet pretrained ViT-L/16, 1024-dim, general-purpose baseline' },
  { id: 'conch', name: 'CONCH', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)' },
  { id: 'uni', name: 'UNI', description: 'DINOv2 ViT-L/16, 1024-dim (Mahmood Lab)' },
  { id: 'uni2', name: 'UNI2', description: 'ViT-G/14, 1536-dim (Mahmood Lab)' },
  { id: 'virchow', name: 'Virchow', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)' },
  { id: 'virchow2', name: 'Virchow2', description: 'DINOv2 ViT-H/14, 1280-dim (Paige AI)' },
  { id: 'plip', name: 'PLIP', description: 'CLIP ViT-B/16, 512-dim (Zou Group)' },
  { id: 'phikon', name: 'Phikon', description: 'iBOT ViT-L/16, 1024-dim (Owkin)' },
  { id: 'phikon2', name: 'Phikon2', description: 'DINOv2 ViT-L/16, 1024-dim (Owkin)' },
  { id: 'patho_clip', name: 'PathoCLIP', description: 'CLIP fine-tuned, 512-dim (Hong Bu Lab)' },
  { id: 'openmidnight', name: 'OpenMidnight', description: 'ViT 1.1B, 1536-dim (SophontAI)' },
  { id: 'conch15', name: 'CONCH 1.5', description: 'CLIP ViT-B/16, 512-dim (Mahmood Lab)' },
  { id: 'H-Optimus-1', name: 'H-Optimus-1', description: 'ViT 1.1B, 1536-dim (Bioptimus)' },
  { id: 'H-Optimus-0', name: 'H-Optimus-0', description: 'ViT 1.1B, 1536-dim (Bioptimus)' },
  { id: 'mSTAR', name: 'mSTAR', description: 'ViT-L/16, 1024-dim (Smartlab)' },
  { id: 'GPFM', name: 'GPFM', description: 'DINOv2 ViT-L/14, 1024-dim (Smartlab)' },
]

// Available aggregators (for WSI-level)
const AGGREGATORS = [
  { id: 'abmil', name: 'ABMIL', description: 'Attention-based MIL (recommended)', detail: 'Learns importance weights for each patch' },
  { id: 'meanmil', name: 'MeanMIL', description: 'Simple average pooling', detail: 'Average of all patch features' },
  { id: 'maxmil', name: 'MaxMIL', description: 'Maximum activation pooling', detail: 'Takes maximum across patches' },
]

// Patch-level now uses same Feature Extractors as WSI-level (Foundation Model + Linear Probe)

// Tile size options
const TILE_SIZES = [256, 512, 1024]

export default function NewTaskPage() {
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1: Task Configuration
  const [taskName, setTaskName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'survival_prediction' | 'segmentation'>('classification')
  const [dataLevel, setDataLevel] = useState<'wsi' | 'patch'>('wsi')
  const [taskDescription, setTaskDescription] = useState('')

  // Step 2: Data Selection
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

  // Step 2: Data selection state for large datasets
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)
  const [searchQuery, setSearchQuery] = useState('')

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

  useEffect(() => {
    if (currentStep === 2) {
      loadWSIList()
    }
    if (currentStep === 3) {
      loadExtractors()
    }
    // For patch-level, also load extractors at Step 4 (since Step 3 is skipped for patch)
    if (currentStep === 4 && dataLevel === 'patch') {
      loadExtractors()
    }
  }, [currentStep, dataLevel])

  // Poll for task status in Step 6
  useEffect(() => {
    let intervalId: NodeJS.Timeout
    
    if (currentStep === 6 && submittedTaskId) {
      const poll = async () => {
        try {
          const task = await getTrainingTask(submittedTaskId)
          setPolledTask(task)
          // Stop polling if failed or completed (though user might stay to see 'completed')
          // But actually we want to see progress live.
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

  const loadExtractors = async () => {
    if (availableExtractors.length > 0) return
    setLoadingExtractors(true)
    try {
      const data = await fetchExtractors()
      // Merge with fallback to ensure all models are visible even if backend hasn't reloaded
      const merged = [...data]
      FEATURE_EXTRACTORS.forEach(fallback => {
        if (!merged.find(m => m.id === fallback.id)) {
          merged.push(fallback)
        }
      })
      setAvailableExtractors(merged)
    } catch (e) {
      console.error('Failed to load extractors:', e)
      setAvailableExtractors(FEATURE_EXTRACTORS)
    } finally {
      setLoadingExtractors(false)
    }
  }

  const loadWSIList = async () => {
    setLoading(true)
    try {
      const data = await fetchWSIList()
      setItems(data.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // Filter items based on data level
  const filteredItems = useMemo(() => {
    if (!items || items.length === 0) return []

    // WSI file extensions (excluding .tif/.tiff which need size check)
    const wsiExtensions = ['.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif', '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap', '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax']
    // Patch/image file extensions (excluding .tif/.tiff which need size check)
    const patchExtensions = ['.jpg', '.jpeg', '.png', '.bmp']
    // File size threshold: 100 MB in bytes
    const SIZE_THRESHOLD = 100 * 1024 * 1024

    return items.filter(item => {
      if (!item.wsi_path) return false
      const path = item.wsi_path.toLowerCase()

      // Handle .tif/.tiff files based on file size
      if (path.endsWith('.tif') || path.endsWith('.tiff')) {
        const fileSize = item.file_size || 0
        if (dataLevel === 'wsi') {
          // For WSI-level, show .tif/.tiff files >= 100 MB
          return fileSize >= SIZE_THRESHOLD
        } else {
          // For Patch-level, show .tif/.tiff files < 100 MB
          return fileSize < SIZE_THRESHOLD
        }
      }

      if (dataLevel === 'wsi') {
        // For WSI-level, show WSI files
        return wsiExtensions.some(ext => path.endsWith(ext))
      } else {
        // For Patch-level, show image files
        return patchExtensions.some(ext => path.endsWith(ext))
      }
    }).filter(item => {
      if (!searchQuery) return true
      const query = searchQuery.toLowerCase()
      return (
        (item.original_filename || '').toLowerCase().includes(query) ||
        (item.wsi_id || '').toLowerCase().includes(query) ||
        (item.label || '').toLowerCase().includes(query)
      )
    })
  }, [items, dataLevel, searchQuery])

  const filteredExtractors = useMemo(() => {
    const list = availableExtractors.length > 0 ? availableExtractors : FEATURE_EXTRACTORS
    if (!extractorSearch) return list
    return list.filter(e =>
      e.name.toLowerCase().includes(extractorSearch.toLowerCase()) ||
      e.description.toLowerCase().includes(extractorSearch.toLowerCase())
    )
  }, [availableExtractors, extractorSearch])

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

    setDeleting(true)
    try {
      await deleteWSI(wsiToDelete.wsi_id)
      setShowDeleteModal(false)
      setWsiToDelete(null)
      await loadWSIList()
    } catch (err) {
      console.error('Failed to delete WSI:', err)
      alert(`Failed to delete WSI: ${err}`)
    } finally {
      setDeleting(false)
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

    setDeleting(true)
    try {
      let successCount = 0
      let failedCount = 0

      for (const wsi_id of Array.from(selectedIds)) {
        try {
          await deleteWSI(wsi_id)
          successCount++
        } catch (err) {
          console.error(`Failed to delete ${wsi_id}:`, err)
          failedCount++
        }
      }

      setShowBatchDeleteModal(false)
      setSelectedIds(new Set())
      await loadWSIList()

      if (failedCount > 0) {
        alert(`Batch delete complete!\nSuccess: ${successCount}\nFailed: ${failedCount}`)
      }
    } catch (err) {
      console.error('Failed to batch delete:', err)
      alert(`Failed to batch delete: ${err}`)
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
      return 'Try disabling GPU or check GPU availability.'
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
          use_padding: true
        },
        model: {
          aggregator: dataLevel === 'wsi' ? aggregator : 'none',
          backbone: dataLevel === 'patch' ? featureExtractor : undefined,  // Patch-level uses feature extractor as backbone
          learning_rate: learningRate,
          epochs: epochs,
          optimizer: optimizer,
          batch_size: trainBatchSize
        }
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
      warnings.push('High epoch count (>200) may lead to overfitting and long training time')
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
    if (selectedIds.size < 5) {
      warnings.push('Small dataset (<5 slides) may lead to poor generalization')
    } else if (selectedIds.size > 500) {
      warnings.push('Large dataset (>500 slides) will require significant training time')
    }

    // Tile size checks
    if (tileSize < 256) {
      warnings.push('Small tile size (<256) may miss important context')
    } else if (tileSize > 1024) {
      warnings.push('Large tile size (>1024) will increase memory usage and processing time')
    }

    return {
      warnings,
      errors,
      isValid: errors.length === 0
    }
  }, [epochs, learningRate, trainBatchSize, selectedIds.size, tileSize])

  const canProceedStep1 = useMemo(() => {
    return taskName.trim().length > 0 && taskDescription.trim().length > 0
  }, [taskName, taskDescription])

  const canProceedStep2 = useMemo(() => {
    return selectedIds.size > 0
  }, [selectedIds])

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
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div className="max-w-7xl mx-auto space-y-5">
          {/* Header */}
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">New Analysis Task</h1>
              <p className="text-gray-500 mt-2">Create and train a new analysis model</p>
            </div>
          </div>

          {/* Progress Steps */}
          <Card className="px-8 py-6">
            <div className="flex items-center justify-between">
              {/* Step 1 */}
              <div className="flex items-center space-x-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 1 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 1 ? '✓' : '1'}
                </div>
                <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 1 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Task Setup
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-4 rounded-full transition-colors duration-500 ${currentStep > 1 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 2 */}
              <div className="flex items-center space-x-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 2 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 2 ? '✓' : '2'}
                </div>
                <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 2 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Data
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-4 rounded-full transition-colors duration-500 ${currentStep > 2 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 3 - Only for WSI-level */}
              {dataLevel === 'wsi' && (
                <>
                  <div className="flex items-center space-x-3">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 3 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                      }`}>
                      {currentStep > 3 ? '✓' : '3'}
                    </div>
                    <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 3 ? 'text-gray-900' : 'text-gray-400'}`}>
                      Preprocess
                    </span>
                  </div>
                  <div className={`flex-1 h-0.5 mx-4 rounded-full transition-colors duration-500 ${currentStep > 3 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>
                </>
              )}

              {/* Step 4 (or 3 for patch-level) */}
              <div className="flex items-center space-x-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 4 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 4 ? '✓' : (dataLevel === 'patch' ? '3' : '4')}
                </div>
                <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 4 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Model
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-4 rounded-full transition-colors duration-500 ${currentStep > 4 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 5 (or 4 for patch-level) */}
              <div className="flex items-center space-x-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 5 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 5 ? '✓' : (dataLevel === 'patch' ? '4' : '5')}
                </div>
                <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 5 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Submit
                </span>
              </div>
              <div className={`flex-1 h-0.5 mx-4 rounded-full transition-colors duration-500 ${currentStep > 5 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

              {/* Step 6 (or 5 for patch-level) */}
              <div className="flex items-center space-x-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shadow-sm transition-all duration-300 ${currentStep >= 6 ? 'bg-primary-600 text-white ring-2 ring-primary-100' : 'bg-gray-100 text-gray-400'
                  }`}>
                  {currentStep > 6 ? '✓' : (dataLevel === 'patch' ? '5' : '6')}
                </div>
                <span className={`font-semibold text-sm transition-colors duration-300 ${currentStep >= 6 ? 'text-gray-900' : 'text-gray-400'}`}>
                  Results
                </span>
              </div>
            </div>
          </Card>

          {/* Step 1: Task Configuration */}
          {currentStep === 1 && (
            <>
              <Card className="p-8">
                <h3 className="text-xl font-bold text-gray-900 mb-6">Task Configuration</h3>

                <div className="space-y-6">
                  <div>
                    <label className="block text-sm font-semibold text-gray-800 mb-2">
                      Task Name *
                    </label>
                    <input
                      type="text"
                      className="w-full px-4 py-3 text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
                      value={taskName}
                      onChange={(e) => setTaskName(e.target.value)}
                      placeholder="e.g., Lung Cancer Survival Prediction"
                    />
                  </div>
                  
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div>
                      <label className="block text-sm font-semibold text-gray-800 mb-2">
                        Task Type *
                      </label>
                      <div className="grid grid-cols-2 gap-4">
                        <div
                          onClick={() => setTaskType('classification')}
                          className={`relative p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${taskType === 'classification'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-sm ${taskType === 'classification' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>Classification</div>
                              <div className="text-xs text-gray-500 mt-1">Categorical labels</div>
                            </div>
                            <div className={`w-5 h-5 rounded-full border flex items-center justify-center transition-colors ${taskType === 'classification'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {taskType === 'classification' && (
                                <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
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
                          className={`relative p-4 border rounded-xl transition-all duration-200 group ${dataLevel === 'patch'
                            ? 'border-gray-100 bg-gray-50/50 cursor-not-allowed opacity-60'
                            : (taskType === 'survival_prediction' || taskType === 'segmentation')
                              ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20 cursor-pointer'
                              : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm cursor-pointer'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-sm leading-tight ${dataLevel === 'patch'
                                ? 'text-gray-400'
                                : (taskType === 'survival_prediction' || taskType === 'segmentation') ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>
                                {dataLevel === 'patch' ? 'Segmentation' : 'Survival Prediction'}
                              </div>
                              <div className={`text-xs mt-1 ${dataLevel === 'patch' ? 'text-primary-500 font-medium' : 'text-gray-500'}`}>
                                {dataLevel === 'patch' ? 'Coming soon' : 'Time-to-event outcomes'}
                              </div>
                            </div>
                            <div className={`w-5 h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'patch'
                              ? 'border-gray-200 bg-gray-50'
                              : (taskType === 'survival_prediction' || taskType === 'segmentation')
                                ? 'border-primary-500 bg-primary-500'
                                : 'border-gray-300'
                              }`}>
                              {dataLevel !== 'patch' && (taskType === 'survival_prediction' || taskType === 'segmentation') && (
                                <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-semibold text-gray-800 mb-2">
                        Data Level *
                      </label>
                      <div className="grid grid-cols-2 gap-4">
                        <div
                          onClick={() => {
                            setDataLevel('wsi')
                            setSelectedIds(new Set())
                            if (taskType === 'segmentation') setTaskType('survival_prediction')
                          }}
                          className={`relative p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${dataLevel === 'wsi'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-sm ${dataLevel === 'wsi' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>WSI-level</div>
                              <div className="text-xs text-gray-500 mt-1">Whole slides</div>
                            </div>
                            <div className={`w-5 h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'wsi'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {dataLevel === 'wsi' && (
                                <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
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
                          className={`relative p-4 border rounded-xl cursor-pointer transition-all duration-200 group ${dataLevel === 'patch'
                            ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20'
                            : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm'
                            }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <div className={`font-semibold text-sm ${dataLevel === 'patch' ? 'text-primary-700' : 'text-gray-900 group-hover:text-primary-600'}`}>Patch-level</div>
                              <div className="text-xs text-gray-500 mt-1">Image patches</div>
                            </div>
                            <div className={`w-5 h-5 rounded-full border flex items-center justify-center transition-colors ${dataLevel === 'patch'
                              ? 'border-primary-500 bg-primary-500'
                              : 'border-gray-300'
                              }`}>
                              {dataLevel === 'patch' && (
                                <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
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
                    <label className="block text-sm font-semibold text-gray-800 mb-2">
                      Description *
                    </label>
                    <textarea
                      className="w-full px-4 py-3 text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
                      value={taskDescription}
                      onChange={(e) => setTaskDescription(e.target.value)}
                      placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
                      rows={4}
                    />
                  </div>
                </div>
              </Card>

              <div className="flex justify-between items-center">
                <Button
                  variant="outline"
                  onClick={() => navigate(-1)}
                  className="px-6 py-2.5"
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => setCurrentStep(2)}
                  disabled={!canProceedStep1}
                  className="px-6 py-2.5"
                >
                  Next: Select Data →
                </Button>
              </div>
            </>
          )}

          {/* Step 2: Data Selection */}
          {currentStep === 2 && (
            <>
              <Card className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">Select Training Data</h3>
                    <p className="text-sm text-gray-600 mt-1">
                      Selected {selectedIds.size} {dataLevel === 'wsi' ? 'WSI file(s)' : 'image file(s)'} for training
                    </p>
                  </div>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => navigate('/register')}
                      className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium inline-flex items-center gap-2"
                    >
                      <Plus className="w-4 h-4" />
                      Register Files
                    </button>
                  </div>
                </div>

                {/* Registration Progress */}
                {uploadingFiles.size > 0 && (
                  <div className="mb-4 bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                    <h3 className="text-lg font-semibold text-gray-900 mb-4">
                      Registering Files ({Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}/{uploadingFiles.size})
                    </h3>
                    <div className="space-y-3">
                      {Array.from(uploadingFiles.entries()).map(([fileName, fileStatus]) => (
                        <div key={fileName} className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              {fileStatus.status === 'uploading' && (
                                <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-600 border-t-transparent"></div>
                              )}
                              {fileStatus.status === 'success' && (
                                <span className="text-green-600 text-lg">✓</span>
                              )}
                              {fileStatus.status === 'error' && (
                                <span className="text-red-600 text-lg">✗</span>
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


                {loading ? (
                  <div className="flex justify-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                  </div>
                ) : filteredItems.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    {dataLevel === 'wsi'
                      ? 'No WSI files available. Please register some WSI files first.'
                      : 'No image files available. Please register some image files first.'}
                  </div>
                ) : (
                  <>
                    {/* Batch Actions & Selection Info */}
                    {(selectedIds.size > 0) && (
                       <div className="mb-4 flex items-center justify-between bg-primary-50 px-4 py-2 rounded-lg border border-primary-100">
                         <div className="flex items-center gap-2">
                            <CheckSquare className="w-4 h-4 text-primary-600" />
                            <span className="text-sm font-medium text-primary-900">
                              {selectedIds.size} selected
                            </span>
                         </div>
                         <div className="flex gap-2">
                           <button onClick={() => setSelectedIds(new Set())} className="text-xs font-medium text-primary-700 hover:text-primary-800 hover:underline px-2">
                             Clear selection
                           </button>
                         </div>
                       </div>
                    )}
                    
                    <div className="bg-white border rounded-xl overflow-hidden shadow-sm min-h-[400px] flex flex-col">
                      <div className="overflow-x-auto flex-1">
                        <table className="min-w-full divide-y divide-gray-100">
                          <thead>
                            <tr className="bg-gray-50/50">
                              <th className="px-6 py-3 text-left w-6">
                                <input
                                  type="checkbox"
                                  checked={filteredItems.length > 0 && Array.from(selectedIds).length === filteredItems.length}
                                  onChange={(e) => {
                                      if (e.target.checked) {
                                          setSelectedIds(new Set(filteredItems.map(i => i.wsi_id)))
                                      } else {
                                          setSelectedIds(new Set())
                                      }
                                  }}
                                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-4 h-4 cursor-pointer"
                                />
                              </th>
                              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">File Name</th>
                              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Label</th>
                              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-24">Actions</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-50">
                            {filteredItems.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((item) => (
                              <tr 
                                key={item.wsi_id} 
                                className={`group transition-colors ${selectedIds.has(item.wsi_id) ? 'bg-primary-50/30' : 'hover:bg-gray-50'}`}
                                onClick={(e) => {
                                    // Toggle selection on row click unless clicking button/checkbox
                                    if ((e.target as HTMLElement).tagName !== 'BUTTON' && (e.target as HTMLElement).tagName !== 'INPUT') {
                                        toggleSelection(item.wsi_id)
                                    }
                                }}
                              >
                                <td className="px-6 py-2">
                                  <input
                                    type="checkbox"
                                    checked={selectedIds.has(item.wsi_id)}
                                    onChange={() => toggleSelection(item.wsi_id)}
                                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-4 h-4 cursor-pointer"
                                  />
                                </td>
                                <td className="px-6 py-2">
                                  <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg ${selectedIds.has(item.wsi_id) ? 'bg-white text-primary-600' : 'bg-gray-100 text-gray-500 group-hover:bg-white group-hover:shadow-sm transition-all'}`}>
                                      {dataLevel === 'wsi' ? <FileText className="w-5 h-5" /> : <ImageIcon className="w-5 h-5" />}
                                    </div>
                                    <div className="flex flex-col max-w-[300px]">
                                      <span className={`text-sm font-medium truncate ${selectedIds.has(item.wsi_id) ? 'text-primary-900' : 'text-gray-900'}`}>
                                        {item.original_filename}
                                      </span>
                                      <span className="text-[10px] text-gray-400 font-mono truncate" title={item.wsi_id}>
                                        ID: {item.wsi_id.split('-')[0]}...
                                      </span>
                                    </div>
                                  </div>
                                </td>
                                <td className="px-6 py-2">
                                  {item.label ? (
                                    <Badge variant="outline" className="bg-white">
                                      {item.label}
                                    </Badge>
                                  ) : (
                                    <span className="text-gray-400 text-xs italic">No label</span>
                                  )}
                                </td>
                                <td className="px-6 py-2">
                                   <div className="flex items-center gap-1">
                                      <button 
                                        onClick={() => handleEditClick(item)} 
                                        className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors"
                                        title="Edit metadata"
                                      >
                                          <Edit2 className="w-4 h-4" />
                                      </button>
                                      <button 
                                        onClick={() => handleDeleteClick(item.wsi_id, item.label, item.original_filename)}
                                        className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                                        title="Delete file"
                                      >
                                          <Trash2 className="w-4 h-4" />
                                      </button>
                                   </div>
                                </td>
                              </tr>
                            ))}
                            {/* Empty State Filler Rows to Maintain Height */}
                            {Array.from({ length: Math.max(0, pageSize - filteredItems.slice((currentPage - 1) * pageSize, currentPage * pageSize).length) }).map((_, idx) => (
                                <tr key={`empty-${idx}`} className="h-[73px]">
                                    <td colSpan={100}></td>
                                </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      
                      {/* Pagination Footer */}
                      <div className="border-t border-gray-100 bg-gray-50/50 px-6 py-4 flex items-center justify-between">
                         <div className="text-xs text-gray-500">
                             Showing <span className="font-medium">{(currentPage - 1) * pageSize + 1}</span> to <span className="font-medium">{Math.min(currentPage * pageSize, filteredItems.length)}</span> of <span className="font-medium">{filteredItems.length}</span> results
                         </div>
                         <div className="flex items-center gap-2">
                             <button
                               onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                               disabled={currentPage === 1}
                               className="p-2 rounded-lg border bg-white enabled:hover:bg-gray-50 disabled:opacity-50 transition-colors"
                             >
                                 <ChevronLeft className="w-4 h-4" />
                             </button>
                             <div className="flex items-center gap-1">
                             <span className="text-sm font-medium text-gray-700 px-2">Page {currentPage} of {Math.ceil(filteredItems.length / pageSize)}</span>
                             </div>
                             <button
                               onClick={() => setCurrentPage(p => Math.min(Math.ceil(filteredItems.length / pageSize), p + 1))}
                               disabled={currentPage === Math.ceil(filteredItems.length / pageSize) || filteredItems.length === 0}
                               className="p-2 rounded-lg border bg-white enabled:hover:bg-gray-50 disabled:opacity-50 transition-colors"
                             >
                                 <ChevronRight className="w-4 h-4" />
                             </button>
                         </div>
                      </div>
                    </div>
                  </>
                )}
              </Card>

              <div className="flex justify-between items-center mt-8">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(1)}
                  className="px-6 py-2.5 text-gray-600 hover:text-gray-900"
                >
                  ← Back
                </Button>
                <Button
                  onClick={() => setCurrentStep(dataLevel === 'patch' ? 4 : 3)}
                  disabled={!canProceedStep2}
                  className="px-8 py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/30 transition-all hover:-translate-y-0.5"
                >
                  {dataLevel === 'patch' ? 'Next: Model Config →' : 'Next: Preprocessing →'}
                </Button>
              </div>
            </>
          )}

          {/* Step 3: Preprocessing Configuration (WSI-level only) */}
          {currentStep === 3 && dataLevel === 'wsi' && (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6 h-[550px]">
                {/* Left Column: Configuration Parameters */}
                <Card className="lg:col-span-4 p-5 flex flex-col h-full overflow-y-auto">
                    <h3 className="text-md font-semibold text-gray-900 mb-3 flex items-center gap-2">
                       <Settings className="w-4 h-4" />
                       Configuration
                    </h3>

                    <div className="space-y-5">
                        {/* Patch Size */}
                        <div>
                           <label className="block text-sm font-medium text-gray-700 mb-1.5">Patch Size</label>
                           <div className="grid grid-cols-3 gap-2">
                                {TILE_SIZES.map(size => (
                                  <button
                                    key={size}
                                    onClick={() => setTileSize(size)}
                                    className={`px-2 py-2 text-sm border rounded-md transition-all ${tileSize === size
                                      ? 'border-primary-600 bg-primary-50 text-primary-700 font-medium'
                                      : 'border-gray-200 text-gray-600 hover:border-gray-300'
                                      }`}
                                  >
                                    {size}px
                                  </button>
                                ))}
                           </div>
                        </div>

                        {/* Stride & Level */}
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1.5">Stride</label>
                              <div className="relative">
                                  <input
                                    type="number"
                                    className="w-full pl-3 pr-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                                    value={stride}
                                    onChange={(e) => setStride(Number(e.target.value))}
                                    min={0}
                                  />
                              </div>
                            </div>
                            <div>
                               <label className="block text-xs font-medium text-gray-700 mb-1.5">Pyramid</label>
                               <select
                                 value={pyramidLevel}
                                 onChange={(e) => setPyramidLevel(Number(e.target.value))}
                                 className="w-full pl-2 pr-6 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                               >
                                 <option value={0}>L0 (Highest)</option>
                                 <option value={1}>L1</option>
                                 <option value={2}>L2</option>
                               </select>
                            </div>
                        </div>

                        <hr className="border-gray-100" />

                        {/* Batch Size (Moved from Feature Extraction) */}
                        <div>
                             <label className="block text-sm font-medium text-gray-700 mb-1.5">Batch Size</label>
                             <div className="flex items-center gap-2">
                                 <input
                                   type="number"
                                   className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                                   value={featureBatchSize}
                                   onChange={(e) => setFeatureBatchSize(Number(e.target.value))}
                                   min={1}
                                   max={512}
                                 />
                                 <span className="text-xs text-gray-400 whitespace-nowrap">GPU patches</span>
                             </div>
                        </div>

                        <hr className="border-gray-100" />

                        {/* Advanced Segmentation Settings */}
                        <div>
                           <label className="block text-sm font-medium text-gray-700 mb-2">Tissue Segmentation</label>
                           <div className="space-y-2">
                              <div className="flex items-center justify-between">
                                  <label className="text-xs text-gray-600">Saturation Threshold</label>
                                  <input
                                    type="number"
                                    className="w-16 px-2 py-1 text-xs border border-gray-300 rounded text-right"
                                    value={segSthresh}
                                    onChange={(e) => setSegSthresh(Number(e.target.value))}
                                  />
                              </div>
                              <div className="flex items-center justify-between">
                                  <label className="text-xs text-gray-600">Mask Threshold</label>
                                  <input
                                    type="number"
                                    className="w-16 px-2 py-1 text-xs border border-gray-300 rounded text-right"
                                    value={segMthresh}
                                    onChange={(e) => setSegMthresh(Number(e.target.value))}
                                  />
                              </div>
                              <div className="flex items-center justify-between">
                                  <label className="text-xs text-gray-600">Close Kernel</label>
                                  <input
                                    type="number"
                                    className="w-16 px-2 py-1 text-xs border border-gray-300 rounded text-right"
                                    value={segClose}
                                    onChange={(e) => setSegClose(Number(e.target.value))}
                                  />
                              </div>
                              <div className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    id="use_otsu"
                                    checked={segUseOtsu}
                                    onChange={(e) => setSegUseOtsu(e.target.checked)}
                                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-3.5 h-3.5"
                                  />
                                  <label htmlFor="use_otsu" className="text-xs text-gray-600 cursor-pointer select-none">Use Otsu Thresholding</label>
                              </div>
                           </div>
                        </div>
                    </div>
                </Card>

                {/* Right Column: Model Selection */}
                <Card className="lg:col-span-8 flex flex-col h-full overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                    <div className="p-4 border-b border-gray-100 bg-white flex-shrink-0 z-10">
                        <div className="flex items-center justify-between gap-4">
                            <div>
                              <h4 className="text-md font-semibold text-gray-900">Feature Extractor</h4>
                              <p className="text-xs text-gray-500">Select model architecture</p>
                            </div>
                            <div className="relative w-48">
                              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                              <input
                                type="text"
                                placeholder="Search..."
                                className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-light"
                                value={extractorSearch}
                                onChange={(e) => setExtractorSearch(e.target.value)}
                              />
                            </div>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto p-4 bg-gray-50/50">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                              {filteredExtractors.length > 0 ? (
                                filteredExtractors.map(extractor => (
                                  <div
                                    key={extractor.id}
                                    onClick={() => setFeatureExtractor(extractor.id)}
                                    className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-md ${featureExtractor === extractor.id
                                      ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                                      : 'bg-white border-gray-200 hover:border-gray-300'
                                      }`}
                                  >
                                    <div className="flex items-start justify-between mb-1">
                                        <div className="font-semibold text-gray-900 text-sm">{extractor.name}</div>
                                        {featureExtractor === extractor.id && (
                                            <CheckCircle2 className="w-4 h-4 text-primary-600" />
                                        )}
                                    </div>
                                    <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed">
                                        {extractor.description}
                                    </p>
                                  </div>
                                ))
                              ) : (
                                <div className="col-span-full py-12 text-center text-gray-400">
                                  No models found
                                </div>
                              )}
                        </div>
                    </div>
                </Card>
              </div>

              <div className="flex justify-between">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(2)}
                  className="px-6 py-2.5"
                >
                  ← Back
                </Button>
                <Button
                  onClick={() => setCurrentStep(4)}
                  disabled={!canProceedStep3}
                  className="px-6 py-2.5"
                >
                  Next: Model Configuration →
                </Button>
              </div>
            </>
          )}

          {/* Step 4: Model Configuration */}
          {currentStep === 4 && (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6 h-[480px]">
                {/* Left Column: Model Architecture */}
                <Card className="lg:col-span-8 flex flex-col h-full bg-gray-50/50 overflow-hidden">
                    <div className="p-5 pb-0 flex-shrink-0">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-md font-semibold text-gray-900 flex items-center gap-2">
                               <CheckCircle2 className="w-4 h-4" />
                               Feature Extractor
                            </h3>
                            {dataLevel === 'patch' && (
                              <div className="relative w-48">
                                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                                <input
                                  type="text"
                                  placeholder="Search..."
                                  className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-light bg-white"
                                  value={extractorSearch}
                                  onChange={(e) => setExtractorSearch(e.target.value)}
                                />
                              </div>
                            )}
                        </div>
                    </div>
                    
                    <div className="flex-1 overflow-y-auto p-5 pt-0 custom-scrollbar">
                        {/* Aggregation Method (WSI-level only) */}
                        {dataLevel === 'wsi' && (
                            <div className="space-y-3">
                              {AGGREGATORS.map(agg => (
                                <div
                                  key={agg.id}
                                  onClick={() => setAggregator(agg.id)}
                                  className={`p-4 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${aggregator === agg.id
                                    ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                                    : 'bg-white border-gray-200 hover:border-gray-300'
                                    }`}
                                >
                                  <div className="flex items-start justify-between">
                                    <div className="flex-1">
                                      <div className="flex items-center gap-2">
                                          <div className="font-semibold text-gray-900 text-sm">{agg.name}</div>
                                          {aggregator === agg.id && (
                                              <span className="text-[10px] bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full font-medium">Selected</span>
                                          )}
                                      </div>
                                      <div className="text-xs text-gray-500 mt-1 leading-relaxed">{agg.detail}</div>
                                    </div>
                                    <div className={`w-4 h-4 rounded-full border flex items-center justify-center flex-shrink-0 mt-0.5 ${aggregator === agg.id
                                      ? 'border-primary-500 bg-primary-500'
                                      : 'border-gray-300'
                                      }`}>
                                      {aggregator === agg.id && (
                                        <div className="w-1.5 h-1.5 bg-white rounded-full" />
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                        )}

                        {/* Feature Extractor (Patch-level) - Same as WSI feature extractors */}
                        {dataLevel === 'patch' && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-2">
                              {filteredExtractors.length > 0 ? (
                                filteredExtractors.map(extractor => (
                                  <div
                                    key={extractor.id}
                                    onClick={() => setFeatureExtractor(extractor.id)}
                                    className={`p-4 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${featureExtractor === extractor.id
                                      ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                                      : 'bg-white border-gray-200 hover:border-gray-300'
                                      }`}
                                  >
                                    <div className="flex items-start justify-between">
                                      <div className="flex-1">
                                        <div className="font-semibold text-gray-900 text-sm">{extractor.name}</div>
                                        <div className="text-xs text-gray-500 mt-1 line-clamp-2">{extractor.description}</div>
                                      </div>
                                      {featureExtractor === extractor.id && (
                                          <CheckCircle2 className="w-4 h-4 text-primary-600 flex-shrink-0" />
                                      )}
                                    </div>
                                  </div>
                                ))
                              ) : (
                                <div className="col-span-full py-12 text-center text-gray-400">
                                  No models found
                                </div>
                              )}
                            </div>
                        )}
                    </div>
                </Card>

                {/* Right Column: Training Parameters */}
                <Card className="lg:col-span-4 p-5 flex flex-col h-full bg-white overflow-y-auto custom-scrollbar">
                  <h3 className="text-md font-semibold text-gray-900 mb-4 flex items-center gap-2">
                     <Settings className="w-4 h-4" />
                     Training Params
                  </h3>

                  <div className="space-y-5">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1.5">Learning Rate</label>
                      <input
                        type="number"
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                        value={learningRate}
                        onChange={(e) => setLearningRate(Number(e.target.value))}
                        step={0.0001}
                        min={0.00001}
                        max={0.01}
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1.5">Epochs</label>
                          <input
                            type="number"
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                            value={epochs}
                            onChange={(e) => setEpochs(Number(e.target.value))}
                            min={1}
                            max={200}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1.5">Batch Size</label>
                          <input
                            type="number"
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                            value={trainBatchSize}
                            onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                            min={1}
                            max={dataLevel === 'wsi' ? 16 : 128}
                          />
                        </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1.5">Optimizer</label>
                      <select
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                        value={optimizer}
                        onChange={(e) => setOptimizer(e.target.value)}
                      >
                        <option value="adam">Adam</option>
                        <option value="sgd">SGD</option>
                        <option value="adamw">AdamW</option>
                      </select>
                    </div>
                    
                    <div className="pt-2 border-t border-gray-100 space-y-3">
                        <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1.5">Early Stopping (Patience)</label>
                            <input
                              type="number"
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500"
                              value={earlyStoppingPatience}
                              onChange={(e) => setEarlyStoppingPatience(Number(e.target.value))}
                              min={1}
                              max={50}
                            />
                        </div>
                        
                        <div className="flex items-center gap-2 pt-1">
                            <input
                              type="checkbox"
                              id="autoBalance"
                              checked={autoBalance}
                              onChange={(e) => setAutoBalance(e.target.checked)}
                              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-3.5 h-3.5"
                            />
                            <label htmlFor="autoBalance" className="text-xs text-gray-600 cursor-pointer select-none">Auto-balance class weights</label>
                        </div>
                    </div>
                  </div>
                </Card>
              </div>

              <div className="flex justify-between items-center mt-8">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(dataLevel === 'patch' ? 2 : 3)}
                  className="px-6 py-2.5 text-gray-600 hover:text-gray-900"
                >
                  ← Back
                </Button>
                <Button
                  onClick={() => setCurrentStep(5)}
                  disabled={!canProceedStep4}
                  className="px-8 py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/30 transition-all hover:-translate-y-0.5"
                >
                  Next: Start Training →
                </Button>
              </div>
            </>
          )}

          {/* Step 5: Submit Training Task */}
          {currentStep === 5 && (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[400px]">
                  {/* Summary Card */}
                  <Card className="p-6">
                     <h3 className="text-md font-semibold text-gray-900 mb-5 flex items-center gap-2">
                        <CheckSquare className="w-5 h-5 text-gray-500" />
                        Task Overview
                     </h3>
                     
                     <div className="space-y-6">
                        {/* Basic Info */}
                        <div className="grid grid-cols-2 gap-4">
                           <div className="p-3 bg-gray-50 rounded-lg">
                              <span className="text-xs text-gray-500 block mb-1">Task Name</span>
                              <span className="text-sm font-medium text-gray-900">{taskName}</span>
                           </div>
                           <div className="p-3 bg-gray-50 rounded-lg">
                              <span className="text-xs text-gray-500 block mb-1">Task Type</span>
                              <span className="text-sm font-medium text-gray-900 capitalize">
                                {taskType === 'survival_prediction' ? 'Survival Prediction' : taskType}
                              </span>
                           </div>
                           <div className="p-3 bg-gray-50 rounded-lg">
                              <span className="text-xs text-gray-500 block mb-1">Data Volume</span>
                              <div className="flex items-center gap-1.5">
                                 <span className="text-sm font-medium text-gray-900">{selectedIds.size}</span>
                                 <span className="text-xs text-gray-500">{dataLevel === 'wsi' ? 'slides' : 'images'}</span>
                              </div>
                           </div>
                           <div className="p-3 bg-gray-50 rounded-lg">
                              <span className="text-xs text-gray-500 block mb-1">Training Epochs</span>
                              <span className="text-sm font-medium text-gray-900 font-mono">
                                {epochs}
                              </span>
                           </div>
                        </div>

                        <div className="pt-4 border-t border-gray-100">
                             <div className="flex items-center gap-2 mb-3">
                                <AlignLeft className="w-4 h-4 text-gray-400" />
                                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Description</h4>
                             </div>
                             <div className="p-3 bg-gray-50 rounded-lg border border-gray-100/50">
                                <p className="text-sm text-gray-600 leading-relaxed line-clamp-3">
                                  {taskDescription || "No description provided."}
                                </p>
                             </div>
                        </div>

                        <div className="pt-4 border-t border-gray-100">
                             <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Pipeline Architecture</h4>
                             <div className="flex items-start gap-4">
                                 <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0 border border-indigo-100">
                                     <Layers className="w-5 h-5 text-indigo-600" />
                                 </div>
                                 <div className="flex-1">
                                      <div className="flex items-center justify-between">
                                        <div className="text-sm font-semibold text-gray-900">
                                            {dataLevel === 'wsi'
                                              ? AGGREGATORS.find(a => a.id === aggregator)?.name
                                              : (availableExtractors.length > 0 ? availableExtractors : FEATURE_EXTRACTORS).find(e => e.id === featureExtractor)?.name
                                            }
                                        </div>
                                      </div>

                                      {dataLevel === 'wsi' && (
                                        <div className="mt-2 text-xs flex items-center gap-1.5 text-gray-500">
                                            <span className="text-gray-400">Input Features:</span>
                                            <span className="font-medium text-gray-700">
                                              {(availableExtractors.length > 0 ? availableExtractors : FEATURE_EXTRACTORS).find(e => e.id === featureExtractor)?.name}
                                            </span>
                                        </div>
                                      )}
                                      {dataLevel === 'patch' && (
                                        <div className="mt-2 text-xs flex items-center gap-1.5 text-gray-500">
                                            <span className="text-gray-400">+ Linear Probe</span>
                                        </div>
                                      )}
                                 </div>
                             </div>
                        </div>
                     </div>
                  </Card>

                  {/* Config Details & Warnings */}
                  <div className="flex flex-col gap-6">
                      <Card className="p-6 flex-1">
                          <h3 className="text-md font-semibold text-gray-900 mb-5 flex items-center gap-2">
                            <Settings className="w-5 h-5 text-gray-500" />
                            Configuration Details
                          </h3>
                          
                          <div className="space-y-4 text-sm divide-y divide-gray-50">
                              {dataLevel === 'wsi' && (
                                <>
                                <div className="flex justify-between items-center pt-2">
                                    <span className="text-gray-500">Patching Strategy</span>
                                    <div className="text-right">
                                        <div className="font-medium font-mono text-gray-900">{tileSize}px Tiles</div>
                                        <div className="text-xs text-gray-400">
                                            {stride > 0 ? `Overlap ${stride}px` : 'Non-overlapping'}
                                        </div>
                                    </div>
                                </div>

                                <div className="flex justify-between items-center pt-2">
                                    <span className="text-gray-500">Tissue Segmentation</span>
                                    <div className="text-right">
                                        <div className="font-medium text-gray-900">
                                            {segUseOtsu ? 'Adaptive (Otsu)' : 'Manual Thresholds'}
                                        </div>
                                        <div className="text-xs text-gray-400">
                                            {segUseOtsu ? 'Auto-masking' : `Sat > ${segSthresh}, Mask < ${segMthresh}`} 
                                            <span className="mx-1">•</span>
                                            Level {pyramidLevel}
                                        </div>
                                    </div>
                                </div>
                                </>
                              )}
                              
                              <div className="flex justify-between items-center pt-2">
                                  <span className="text-gray-500">Optimizer Config</span>
                                  <div className="text-right">
                                      <div className="font-medium font-mono text-gray-900 capitalize">{optimizer}</div>
                                      <div className="text-xs text-gray-400">Learning Rate: {learningRate}</div>
                                  </div>
                              </div>

                              <div className="flex justify-between items-center pt-2">
                                  <span className="text-gray-500">Training Configurations</span>
                                  <div className="text-right">
                                      <div className="font-medium font-mono text-gray-900">Batch Size: {trainBatchSize}</div>
                                      <div className="text-xs text-gray-400">
                                          {autoBalance ? 'Class Balancing On' : 'Standard Sampling'}
                                          <span className="mx-1">•</span> 
                                          Patience {earlyStoppingPatience}
                                      </div>
                                  </div>
                              </div>
                          </div>
                      </Card>

                      {/* Warnings / Errors */}
                      {(validateConfiguration.errors.length > 0 || validateConfiguration.warnings.length > 0) && (
                         <div className={`rounded-xl p-4 border ${validateConfiguration.errors.length > 0 ? 'bg-red-50 border-red-100' : 'bg-amber-50 border-amber-100'}`}>
                             <div className="flex items-start gap-3">
                                 <div className={`mt-0.5 ${validateConfiguration.errors.length > 0 ? 'text-red-600' : 'text-amber-600'}`}>
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                                    </svg>
                                 </div>
                                 <div>
                                     <h4 className={`text-sm font-semibold mb-1 ${validateConfiguration.errors.length > 0 ? 'text-red-900' : 'text-amber-900'}`}>
                                         {validateConfiguration.errors.length > 0 ? 'Configuration Error' : 'Optimization Tips'}
                                     </h4>
                                     <ul className={`text-xs space-y-1 ${validateConfiguration.errors.length > 0 ? 'text-red-700' : 'text-amber-700'}`}>
                                        {[...validateConfiguration.errors, ...validateConfiguration.warnings].map((msg, i) => (
                                            <li key={i}>{msg}</li>
                                        ))}
                                     </ul>
                                 </div>
                             </div>
                         </div>
                      )}
                  </div>
              </div>

               {/* Status Display Area - Keeping original logic but styled */}
              {(trainingStatus !== 'idle' || submitError) && (
                 <div className="mt-6">
                    {trainingStatus === 'validating' && (
                        <div className="flex items-center justify-center p-4 bg-gray-50 rounded-xl border border-gray-100 text-gray-600 gap-3">
                            <Loader2 className="animate-spin w-5 h-5 text-primary-600" />
                            <span className="text-sm font-medium">Validating configuration...</span>
                        </div>
                    )}
                    {trainingStatus === 'submitting' && (
                        <div className="flex items-center justify-center p-4 bg-gray-50 rounded-xl border border-gray-100 text-gray-600 gap-3">
                            <Loader2 className="animate-spin w-5 h-5 text-primary-600" />
                            <span className="text-sm font-medium">Submitting training task...</span>
                        </div>
                    )}
                    {trainingStatus === 'submitted' && (
                        <div className="p-4 bg-green-50 rounded-xl border border-green-100 flex items-center justify-center gap-2 text-green-700">
                             <CheckCircle2 className="w-5 h-5" />
                             <span className="text-sm font-medium">Task submitted successfully! Redirecting...</span>
                        </div>
                    )}
                    {submitError && (
                        <div className="p-4 bg-red-50 rounded-xl border border-red-100">
                             <div className="flex items-start gap-3">
                                 <div className="text-red-600 mt-0.5">⚠️</div>
                                 <div className="flex-1">
                                     <h4 className="text-sm font-semibold text-red-900">Submission Failed</h4>
                                     <p className="text-sm text-red-700 mt-1">{parseErrorMessage(submitError)}</p>
                                     <button onClick={() => { setSubmitError(''); setTrainingStatus('idle'); }} className="mt-3 text-xs font-medium text-red-700 hover:text-red-800 underline">
                                         Try Again
                                     </button>
                                 </div>
                             </div>
                        </div>
                    )}
                 </div>
              )}

              <div className="flex justify-between mt-6">
                <Button variant="outline" onClick={() => setCurrentStep(4)} className="px-6 py-2.5">← Back</Button>
                <Button onClick={startTraining} disabled={!canProceedStep5} className="px-8 py-2.5 bg-green-600 hover:bg-green-700 text-white shadow-sm hover:shadow">
                  {trainingStatus === 'submitting' || trainingStatus === 'validating' ? 'Processing...' : 'Start Training'}
                </Button>
              </div>
            </>
          )}

          {/* Step 6: Task Submitted Successfully */}
          {currentStep === 6 && (
            <div className="flex flex-col items-center justify-center p-4 h-full">
                <Card className="w-full max-w-7xl overflow-hidden shadow-xl border-gray-100 ring-1 ring-black/5 bg-white">
                    <div className="grid grid-cols-1 lg:grid-cols-12 min-h-[440px]">
                        {/* Left Column: Success State & Actions (5 Columns) */}
                        <div className="lg:col-span-4 bg-gray-50/50 p-8 flex flex-col justify-center items-center text-center border-r border-gray-100">
                            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-5 ring-4 ring-green-50 shadow-sm animate-in zoom-in duration-300">
                                <CheckCircle2 className="w-8 h-8 text-green-600" />
                            </div>
                            
                            <h2 className="text-xl font-bold text-gray-900 mb-2 tracking-tight">Submission Successful</h2>
                            <p className="text-sm text-gray-500 mb-6 max-w-[200px] mx-auto leading-relaxed">
                                Your training task has been queued.
                            </p>

                            <div className="w-full max-w-xs bg-white p-1.5 pl-3 pr-1.5 border border-gray-200 rounded-lg flex items-center justify-between shadow-sm mb-6">
                                <div className="flex flex-col items-start overflow-hidden min-w-0">
                                   <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">Task ID</span>
                                   <code className="text-xs font-mono font-semibold text-gray-900 truncate w-full text-left" title={submittedTaskId}>{submittedTaskId}</code>
                                </div>
                                <Button 
                                    variant="ghost" 
                                    size="icon" 
                                    className="flex-shrink-0 h-7 w-7 rounded-md hover:bg-gray-50"
                                    onClick={() => navigator.clipboard.writeText(submittedTaskId)}
                                >
                                    <Copy className="w-3.5 h-3.5 text-gray-400" />
                                </Button>
                            </div>

                            <div className="flex flex-col gap-2.5 w-full max-w-xs">
                                <Button onClick={() => navigate('/task-list')} className="w-full bg-gray-900 hover:bg-black text-white h-10 text-sm shadow-md shadow-gray-200">
                                    Go to Task Manager
                                </Button>
                                <Button variant="outline" onClick={() => window.location.reload()} className="w-full h-10 text-sm border-gray-200 text-gray-600 bg-white hover:bg-gray-50">
                                    Create Another Task
                                </Button>
                            </div>
                        </div>

                        {/* Right Column: details & Pipeline (7 Columns) */}
                        <div className="lg:col-span-8 p-8 flex flex-col justify-center bg-white relative">
                             {/* Live Indicator */}
                             <div className="absolute top-6 right-6 flex items-center gap-1.5">
                                 <span className="relative flex h-2.5 w-2.5">
                                   <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${polledTask?.status === 'training' ? 'bg-indigo-400' : 'bg-green-400'}`}></span>
                                   <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${polledTask?.status === 'training' ? 'bg-indigo-500' : 'bg-green-500'}`}></span>
                                 </span>
                                 <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                                    {polledTask?.status || 'Active'}
                                 </span>
                             </div>

                             <div className="mb-8">
                                 <h3 className="text-xs font-bold text-gray-900 uppercase tracking-widest mb-4 border-b border-gray-50 pb-2">Task Summary</h3>
                                 <div className="grid grid-cols-2 gap-y-4 gap-x-6">
                                     <div>
                                         <div className="text-[10px] font-medium text-gray-400 mb-1 uppercase tracking-wider">Project Name</div>
                                         <div className="text-sm font-semibold text-gray-900 truncate pr-4" title={taskName}>{taskName}</div>
                                     </div>
                                     <div>
                                         <div className="text-[10px] font-medium text-gray-400 mb-1 uppercase tracking-wider">Dataset Volume</div>
                                         <div className="text-sm font-semibold text-gray-900">
                                             {selectedIds.size} <span className="text-xs font-medium text-gray-500">{dataLevel === 'wsi' ? 'Slides' : 'Images'}</span>
                                         </div>
                                     </div>
                                     <div>
                                         <div className="text-[10px] font-medium text-gray-400 mb-1 uppercase tracking-wider">Architecture</div>
                                         <div className="inline-flex items-center px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-xs font-medium border border-indigo-100">
                                             {dataLevel === 'wsi'
                                               ? AGGREGATORS.find(a => a.id === aggregator)?.name
                                               : (availableExtractors.length > 0 ? availableExtractors : FEATURE_EXTRACTORS).find(e => e.id === featureExtractor)?.name + ' + Linear Probe'
                                             }
                                         </div>
                                     </div>
                                     <div>
                                         <div className="text-[10px] font-medium text-gray-400 mb-1 uppercase tracking-wider">Configuration</div>
                                         <div className="text-sm font-semibold text-gray-900">{epochs} Epochs</div>
                                     </div>
                                 </div>
                             </div>

                             {/* Dynamic Pipeline Status */}
                             <div className="bg-gray-50/50 rounded-xl p-5 border border-gray-100">
                                <h3 className="text-[10px] font-bold text-gray-900 uppercase tracking-widest mb-4 flex items-center gap-2">
                                   <Layers className="w-3.5 h-3.5 text-gray-500" />
                                   Processing Pipeline
                                </h3>
                                <div className="space-y-4">
                                    {/* Step 1: Preprocessing */}
                                    <div className={`flex items-start gap-4 transition-opacity duration-300 ${
                                         ['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued') ? 'opacity-100' : 'opacity-50'
                                    }`}>
                                        <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${
                                            ['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued') 
                                                ? 'bg-blue-600 text-white ring-2 ring-blue-100' 
                                                : polledTask?.status !== 'queued' && polledTask?.status !== 'initializing' 
                                                    ? 'bg-green-500 text-white' // Done
                                                    : 'bg-gray-200 text-gray-400' // Future
                                        }`}>
                                            {(!['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued')) && (polledTask?.status !== 'failed') ? <CheckCircle2 className="w-3 h-3" /> : '1'}
                                        </div>
                                        <div>
                                            <div className="flex items-center gap-2">
                                                <div className="text-sm font-semibold text-gray-900">Initialization & Patching</div>
                                                {['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued') && (
                                                    <Loader2 className="w-3 h-3 text-blue-600 animate-spin" />
                                                )}
                                            </div>
                                            <div className="text-xs text-gray-500 mt-0.5">Automated ROI detection and tile extraction</div>
                                        </div>
                                    </div>

                                    {/* Step 2: Feature Extraction */}
                                    <div className={`flex items-start gap-4 transition-opacity duration-300 ${
                                         polledTask?.status === 'feature_extraction' ? 'opacity-100' : 'opacity-50'
                                    }`}>
                                        <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${
                                            polledTask?.status === 'feature_extraction'
                                                ? 'bg-blue-600 text-white ring-2 ring-blue-100' 
                                                : ['queued', 'initializing', 'preprocessing'].includes(polledTask?.status || 'queued')
                                                    ? 'bg-gray-200 text-gray-400' // Future
                                                    : 'bg-green-500 text-white' // Done
                                        }`}>
                                            {(['training', 'completed'].includes(polledTask?.status || '')) ? <CheckCircle2 className="w-3 h-3" /> : '2'}
                                        </div>
                                        <div>
                                            <div className="flex items-center gap-2">
                                                <div className="text-sm font-medium text-gray-900">Feature Extraction</div>
                                                {polledTask?.status === 'feature_extraction' && (
                                                    <Loader2 className="w-3 h-3 text-blue-600 animate-spin" />
                                                )}
                                            </div>
                                            <div className="text-xs text-gray-500 mt-0.5">Generating high-dimensional embeddings</div>
                                        </div>
                                    </div>

                                    {/* Step 3: Training */}
                                    <div className={`flex items-start gap-4 transition-opacity duration-300 ${
                                         polledTask?.status === 'training' ? 'opacity-100' : 'opacity-50'
                                    }`}>
                                        <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${
                                            polledTask?.status === 'training'
                                                ? 'bg-blue-600 text-white ring-2 ring-blue-100' 
                                                : polledTask?.status === 'completed' 
                                                    ? 'bg-green-500 text-white' 
                                                    : 'bg-gray-200 text-gray-400'
                                        }`}>
                                            {polledTask?.status === 'completed' ? <CheckCircle2 className="w-3 h-3" /> : '3'}
                                        </div>
                                        <div>
                                            <div className="flex items-center gap-2">
                                                <div className="text-sm font-medium text-gray-900">Model Training</div>
                                                {polledTask?.status === 'training' && (
                                                    <div className="flex items-center gap-1.5">
                                                        <Loader2 className="w-3 h-3 text-blue-600 animate-spin" />
                                                        <span className="text-[10px] font-mono text-blue-600 bg-blue-50 px-1 py-0.5 rounded">
                                                            {polledTask?.progress ? `${polledTask.progress.toFixed(1)}%` : '0%'}
                                                        </span>
                                                    </div>
                                                )}
                                            </div>
                                            <div className="text-xs text-gray-500 mt-0.5">Iterative optimization with validation</div>
                                        </div>
                                    </div>
                                </div>
                             </div>
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

