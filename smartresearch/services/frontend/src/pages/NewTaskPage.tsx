import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, uploadWSIByCSV, downloadCSVTemplate, deleteWSI, updateWSIMetadata, createTrainingTask } from '../api'
import { Download, Upload } from 'lucide-react'

// Available feature extractors
const FEATURE_EXTRACTORS = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained, general-purpose' },
  { id: 'vit_base', name: 'ViT-Base', description: 'Vision Transformer, advanced features' },
  { id: 'ctranspath', name: 'CTransPath', description: 'Pathology-specific, recommended' },
  { id: 'uni', name: 'UNI', description: 'Universal pathology foundation model' },
]

// Available aggregators (for WSI-level)
const AGGREGATORS = [
  { id: 'abmil', name: 'ABMIL', description: 'Attention-based MIL (recommended)', detail: 'Learns importance weights for each patch' },
  { id: 'mean', name: 'Mean Pooling', description: 'Simple average pooling', detail: 'Average of all patch features' },
  { id: 'max', name: 'Max Pooling', description: 'Maximum activation pooling', detail: 'Takes maximum across patches' },
]

// Available models (for Patch-level)
const PATCH_MODELS = [
  { id: 'resnet50', name: 'ResNet50', description: 'Deep residual network, 50 layers', detail: 'Good balance of accuracy and speed' },
  { id: 'resnet101', name: 'ResNet101', description: 'Deep residual network, 101 layers', detail: 'Higher capacity, slower training' },
  { id: 'vit_base', name: 'ViT-Base', description: 'Vision Transformer, base size', detail: 'Attention-based architecture' },
  { id: 'vit_large', name: 'ViT-Large', description: 'Vision Transformer, large size', detail: 'Higher capacity, requires more data' },
  { id: 'efficientnet_b0', name: 'EfficientNet-B0', description: 'Efficient convolutional network', detail: 'Optimized for efficiency' },
  { id: 'efficientnet_b4', name: 'EfficientNet-B4', description: 'Efficient convolutional network, larger', detail: 'Better accuracy, more compute' },
]

// Tile size options
const TILE_SIZES = [256, 512, 1024]

export default function NewTaskPage() {
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1: Task Configuration
  const [taskName, setTaskName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'segmentation'>('classification')
  const [dataLevel, setDataLevel] = useState<'wsi' | 'patch'>('wsi')
  const [taskDescription, setTaskDescription] = useState('')
  
  // Step 2: Data Selection
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
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
  const [featureBatchSize, setFeatureBatchSize] = useState(256)

  // Step 4: Model Configuration
  const [aggregator, setAggregator] = useState('abmil')  // For WSI-level
  const [patchModel, setPatchModel] = useState('resnet50')  // For Patch-level
  const [learningRate, setLearningRate] = useState(0.0001)
  const [epochs, setEpochs] = useState(50)
  const [trainBatchSize, setTrainBatchSize] = useState(1)
  const [optimizer, setOptimizer] = useState('adam')
  const [earlyStoppingPatience, setEarlyStoppingPatience] = useState(10)
  const [autoBalance, setAutoBalance] = useState(true)

  // Step 5: Training & Execution
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'validating' | 'submitting' | 'submitted' | 'failed'>('idle')
  const [submittedTaskId, setSubmittedTaskId] = useState<string>('')
  const [submitError, setSubmitError] = useState<string>('')

  useEffect(() => {
    if (currentStep === 2) {
      loadWSIList()
    }
  }, [currentStep])

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
    })
  }, [items, dataLevel])

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

  const handleDeleteClick = (wsi_id: string, label: string) => {
    setWsiToDelete({ wsi_id, label })
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
          // Tissue segmentation parameters from Settings
          sthresh: Number(localStorage.getItem('seg_sthresh') || '5'),
          mthresh: Number(localStorage.getItem('seg_mthresh') || '7'),
          close: Number(localStorage.getItem('seg_close') || '4'),
          use_otsu: localStorage.getItem('seg_use_otsu') === 'true',
          contour_fn: localStorage.getItem('seg_contour_fn') || 'four_pt',
          use_padding: true
        },
        model: {
          aggregator: dataLevel === 'wsi' ? aggregator : 'none',
          backbone: dataLevel === 'patch' ? patchModel : undefined,
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

    // Estimate training time (rough estimation)
    const estimatedHours = (selectedIds.size * epochs * 0.05) // Very rough estimate
    if (estimatedHours > 24) {
      warnings.push(`Estimated training time: ~${estimatedHours.toFixed(1)} hours`)
    }

    return {
      warnings,
      errors,
      isValid: errors.length === 0,
      estimatedHours
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

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">New Analysis Task</h1>
        <p className="text-gray-600 mt-1">Create and train a new analysis model</p>
      </div>

      {/* Progress Steps */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          {/* Step 1 */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 1 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 1 ? '✓' : '1'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 1 ? 'text-gray-900' : 'text-gray-500'}`}>
              Task Setup
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 1 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 2 */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 2 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 2 ? '✓' : '2'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 2 ? 'text-gray-900' : 'text-gray-500'}`}>
              Data
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 2 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 3 - Only for WSI-level */}
          {dataLevel === 'wsi' && (
            <>
              <div className="flex items-center space-x-2">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
                  currentStep >= 3 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
                }`}>
                  {currentStep > 3 ? '✓' : '3'}
                </div>
                <span className={`font-medium text-sm ${currentStep >= 3 ? 'text-gray-900' : 'text-gray-500'}`}>
                  Preprocess
                </span>
              </div>
              <div className={`flex-1 h-1 mx-2 ${currentStep > 3 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>
            </>
          )}

          {/* Step 4 (or 3 for patch-level) */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 4 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 4 ? '✓' : (dataLevel === 'patch' ? '3' : '4')}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 4 ? 'text-gray-900' : 'text-gray-500'}`}>
              Model
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 4 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 5 (or 4 for patch-level) */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 5 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 5 ? '✓' : (dataLevel === 'patch' ? '4' : '5')}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 5 ? 'text-gray-900' : 'text-gray-500'}`}>
              Submit
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 5 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 6 (or 5 for patch-level) */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 6 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 6 ? '✓' : (dataLevel === 'patch' ? '5' : '6')}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 6 ? 'text-gray-900' : 'text-gray-500'}`}>
              Results
            </span>
          </div>
        </div>
      </div>

      {/* Step 1: Task Configuration */}
      {currentStep === 1 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Task Configuration</h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Task Name *
                </label>
                <input
                  type="text"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
                  value={taskName}
                  onChange={(e) => setTaskName(e.target.value)}
                  placeholder="e.g., Lung Cancer Classification"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  Task Type *
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div
                    onClick={() => setTaskType('classification')}
                    className={`relative p-4 border-2 rounded-lg cursor-pointer transition-all ${
                      taskType === 'classification'
                        ? 'border-blue-500 bg-blue-50 shadow-sm'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-gray-900">Classification</div>
                        <div className="text-xs text-gray-500 mt-1">Predict categorical labels</div>
                      </div>
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                        taskType === 'classification'
                          ? 'border-blue-500 bg-blue-500'
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
                    onClick={() => setTaskType('segmentation')}
                    className={`relative p-4 border-2 rounded-lg cursor-pointer transition-all ${
                      taskType === 'segmentation'
                        ? 'border-blue-500 bg-blue-50 shadow-sm'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-gray-900">Segmentation</div>
                        <div className="text-xs text-gray-500 mt-1">Segment regions of interest</div>
                      </div>
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                        taskType === 'segmentation'
                          ? 'border-blue-500 bg-blue-500'
                          : 'border-gray-300'
                      }`}>
                        {taskType === 'segmentation' && (
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
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  Data Level *
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div
                    onClick={() => {
                      setDataLevel('wsi')
                      setSelectedIds(new Set())
                    }}
                    className={`relative p-4 border-2 rounded-lg cursor-pointer transition-all ${
                      dataLevel === 'wsi'
                        ? 'border-blue-500 bg-blue-50 shadow-sm'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-gray-900">WSI-level</div>
                        <div className="text-xs text-gray-500 mt-1">Whole slide images (.svs, .ndpi, etc.)</div>
                      </div>
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                        dataLevel === 'wsi'
                          ? 'border-blue-500 bg-blue-500'
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
                    }}
                    className={`relative p-4 border-2 rounded-lg cursor-pointer transition-all ${
                      dataLevel === 'patch'
                        ? 'border-blue-500 bg-blue-50 shadow-sm'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-gray-900">Patch-level</div>
                        <div className="text-xs text-gray-500 mt-1">Image patches (.jpg, .png, etc.)</div>
                      </div>
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                        dataLevel === 'patch'
                          ? 'border-blue-500 bg-blue-500'
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

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Description *
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
                  value={taskDescription}
                  onChange={(e) => setTaskDescription(e.target.value)}
                  placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
                  rows={4}
                />
              </div>
            </div>
          </div>

          <div className="flex justify-between items-center">
            <button
              onClick={() => navigate('/')}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => setCurrentStep(2)}
              disabled={!canProceedStep1}
              className={`px-6 py-2.5 font-medium rounded-lg transition-all ${
                canProceedStep1
                  ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-md'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed opacity-60'
              }`}
            >
              Next: Select Data →
            </button>
          </div>
        </>
      )}

      {/* Step 2: Data Selection */}
      {currentStep === 2 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Select Training Data</h3>
                <p className="text-sm text-gray-600 mt-1">
                  Selected {selectedIds.size} {dataLevel === 'wsi' ? 'WSI file(s)' : 'image file(s)'} for training
                </p>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  Upload Files
                </button>
                <button
                  onClick={() => setShowCSVUploadModal(true)}
                  disabled={uploading}
                  className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  Upload CSV
                </button>
              </div>
            </div>

            {/* Upload Progress */}
            {uploadingFiles.size > 0 && (
              <div className="mb-4 bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">
                  Uploading Files ({Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}/{uploadingFiles.size})
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

            <input
              ref={fileInputRef}
              type="file"
              accept={dataLevel === 'wsi'
                ? ".svs,.svslide,.ndpi,.scn,.mrxs,.bif,.tif,.tiff,.vsi,.vms,.vmu,.kfb,.sdpc,.TMAP,.mds,.mdsx,.qptiff,.tron,.isyntax"
                : ".jpg,.jpeg,.png,.bmp,.tif,.tiff"}
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

            {loading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                {dataLevel === 'wsi'
                  ? 'No WSI files available. Please upload some WSI files first.'
                  : 'No image files available. Please upload some image files first.'}
              </div>
            ) : (
              <>
                {/* Batch Actions Bar */}
                {selectedIds.size > 0 && (
                  <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-center justify-between">
                    <span className="text-sm font-medium text-blue-900">
                      {selectedIds.size} {dataLevel === 'wsi' ? 'slide(s)' : 'image(s)'} selected
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={handleBatchEditClick}
                        className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium text-sm"
                      >
                        Edit Selected
                      </button>
                      <button
                        onClick={handleBatchDeleteClick}
                        className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-medium text-sm"
                      >
                        Delete Selected
                      </button>
                    </div>
                  </div>
                )}

                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        <input
                          type="checkbox"
                          checked={selectedIds.size === filteredItems.length && filteredItems.length > 0}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedIds(new Set(filteredItems.map(it => it.wsi_id)))
                            } else {
                              setSelectedIds(new Set())
                            }
                          }}
                          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{dataLevel === 'wsi' ? 'WSI ID' : 'Image ID'}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Label</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Age</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gender</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {filteredItems.map((it) => (
                      <tr key={it.wsi_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(it.wsi_id)}
                            onChange={() => toggleSelection(it.wsi_id)}
                            className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                          />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-900">{it.wsi_id}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{it.label || '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{it.age || '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{it.gender || '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{it.source || '-'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleEditClick(it)}
                              className="inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 transition-colors"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDeleteClick(it.wsi_id, it.label)}
                              className="inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md text-white bg-red-600 hover:bg-red-700 transition-colors"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(1)}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={() => setCurrentStep(dataLevel === 'patch' ? 4 : 3)}
              disabled={!canProceedStep2}
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
                canProceedStep2
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              {dataLevel === 'patch' ? 'Next: Model Config →' : 'Next: Preprocessing →'}
            </button>
          </div>
        </>
      )}

      {/* Step 3: Preprocessing Configuration (WSI-level only) */}
      {currentStep === 3 && dataLevel === 'wsi' && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Preprocessing Configuration</h3>

            {/* Patch Extraction */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Patch Extraction</h4>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-3">
                    Patch Size (pixels)
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    {TILE_SIZES.map(size => (
                      <div
                        key={size}
                        onClick={() => setTileSize(size)}
                        className={`p-3 border-2 rounded-lg cursor-pointer transition-all text-center ${
                          tileSize === size
                            ? 'border-blue-500 bg-blue-50 shadow-sm'
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-center justify-center">
                          <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center mr-2 ${
                            tileSize === size
                              ? 'border-blue-500 bg-blue-500'
                              : 'border-gray-300'
                          }`}>
                            {tileSize === size && (
                              <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                              </svg>
                            )}
                          </div>
                          <span className="font-semibold text-gray-900">{size}px</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-gray-500 mt-2">
                    Size of extracted patches (e.g., 256, 512)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Stride (0 = no overlap)
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={stride}
                    onChange={(e) => setStride(Number(e.target.value))}
                    min={0}
                    max={tileSize}
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Step size between patches (0 = no overlap)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Pyramid Level
                  </label>
                  <select
                    value={pyramidLevel}
                    onChange={(e) => setPyramidLevel(Number(e.target.value))}
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  >
                    <option value={0}>Level 0 (Highest Resolution)</option>
                    <option value={1}>Level 1</option>
                    <option value={2}>Level 2</option>
                    <option value={3}>Level 3</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    WSI pyramid level to extract from
                  </p>
                </div>
              </div>
            </div>

            {/* Feature Extraction */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Feature Extraction</h4>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-3">
                    Feature Extractor
                  </label>
                  <div className="space-y-3">
                    {FEATURE_EXTRACTORS.map(extractor => (
                      <div
                        key={extractor.id}
                        onClick={() => setFeatureExtractor(extractor.id)}
                        className={`p-3 border-2 rounded-lg cursor-pointer transition-all ${
                          featureExtractor === extractor.id
                            ? 'border-blue-500 bg-blue-50 shadow-sm'
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="font-semibold text-gray-900">{extractor.name}</div>
                            <div className="text-xs text-gray-600 mt-1">{extractor.description}</div>
                          </div>
                          <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ml-3 flex-shrink-0 ${
                            featureExtractor === extractor.id
                              ? 'border-blue-500 bg-blue-500'
                              : 'border-gray-300'
                          }`}>
                            {featureExtractor === extractor.id && (
                              <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                              </svg>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Batch Size
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={featureBatchSize}
                    onChange={(e) => setFeatureBatchSize(Number(e.target.value))}
                    min={1}
                    max={512}
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Number of patches to process in parallel (GPU required)
                  </p>
                </div>
              </div>
            </div>

            {/* Estimated Output */}
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
              <h4 className="text-sm font-semibold text-blue-900 mb-2">Estimated Output</h4>
              <div className="space-y-1 text-sm text-blue-800">
                <div>Estimated patches: ~{Math.floor(selectedIds.size * 15000).toLocaleString()}</div>
                <div>Storage required: ~{(selectedIds.size * 2.3).toFixed(1)} GB</div>
                <div>Estimated time: ~{Math.floor(selectedIds.size * 45)} minutes</div>
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(2)}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={() => setCurrentStep(4)}
              disabled={!canProceedStep3}
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
                canProceedStep3
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              Next: Model Configuration →
            </button>
          </div>
        </>
      )}

      {/* Step 4: Model Configuration */}
      {currentStep === 4 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Model Configuration</h3>

            {/* Aggregation Method (WSI-level only) */}
            {dataLevel === 'wsi' && (
              <div className="mb-6">
                <h4 className="text-md font-semibold text-gray-800 mb-3">Aggregation Method</h4>
                <p className="text-sm text-gray-600 mb-3">
                  Choose how to aggregate patch-level features into slide-level predictions
                </p>

                <div className="space-y-3">
                  {AGGREGATORS.map(agg => (
                    <div
                      key={agg.id}
                      onClick={() => setAggregator(agg.id)}
                      className={`p-4 border-2 rounded-lg cursor-pointer transition-all ${
                        aggregator === agg.id
                          ? 'border-blue-500 bg-blue-50 shadow-sm'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                          <div className="font-semibold text-gray-900">{agg.name}</div>
                          <div className="text-sm text-gray-600 mt-1">{agg.detail}</div>
                        </div>
                        <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ml-3 flex-shrink-0 ${
                          aggregator === agg.id
                            ? 'border-blue-500 bg-blue-500'
                            : 'border-gray-300'
                        }`}>
                          {aggregator === agg.id && (
                            <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Model Architecture (Patch-level only) */}
            {dataLevel === 'patch' && (
              <div className="mb-6">
                <h4 className="text-md font-semibold text-gray-800 mb-3">Model Architecture</h4>
                <p className="text-sm text-gray-600 mb-3">
                  Choose the backbone model for direct image classification
                </p>

                <div className="space-y-3">
                  {PATCH_MODELS.map(model => (
                    <div
                      key={model.id}
                      onClick={() => setPatchModel(model.id)}
                      className={`p-4 border-2 rounded-lg cursor-pointer transition-all ${
                        patchModel === model.id
                          ? 'border-blue-500 bg-blue-50 shadow-sm'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex-1">
                          <div className="font-semibold text-gray-900">{model.name}</div>
                          <div className="text-sm text-gray-600 mt-1">{model.detail}</div>
                        </div>
                        <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ml-3 flex-shrink-0 ${
                          patchModel === model.id
                            ? 'border-blue-500 bg-blue-500'
                            : 'border-gray-300'
                        }`}>
                          {patchModel === model.id && (
                            <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Training Parameters */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Training Parameters</h4>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Learning Rate
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={learningRate}
                    onChange={(e) => setLearningRate(Number(e.target.value))}
                    step={0.0001}
                    min={0.00001}
                    max={0.01}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Epochs
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={epochs}
                    onChange={(e) => setEpochs(Number(e.target.value))}
                    min={1}
                    max={200}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Batch Size {dataLevel === 'wsi' ? '(WSI-level)' : '(Patch-level)'}
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={trainBatchSize}
                    onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                    min={1}
                    max={dataLevel === 'wsi' ? 16 : 128}
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    {dataLevel === 'wsi'
                      ? 'Number of WSI slides per batch (typically 1-16)'
                      : 'Number of patches per batch (typically 16-128)'}
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Optimizer
                  </label>
                  <select
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={optimizer}
                    onChange={(e) => setOptimizer(e.target.value)}
                  >
                    <option value="adam">Adam</option>
                    <option value="sgd">SGD</option>
                    <option value="adamw">AdamW</option>
                  </select>
                </div>
              </div>

              <div className="mt-4">
                <label className="flex items-center space-x-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoBalance}
                    onChange={(e) => setAutoBalance(e.target.checked)}
                    className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                  />
                  <span className="text-sm text-gray-700">Auto-balance class weights</span>
                </label>
              </div>

              <div className="mt-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Early Stopping Patience
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  value={earlyStoppingPatience}
                  onChange={(e) => setEarlyStoppingPatience(Number(e.target.value))}
                  min={1}
                  max={50}
                />
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(dataLevel === 'patch' ? 2 : 3)}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={() => setCurrentStep(5)}
              disabled={!canProceedStep4}
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
                canProceedStep4
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              Next: Start Training →
            </button>
          </div>
        </>
      )}

      {/* Step 5: Submit Training Task */}
      {currentStep === 5 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Submit Training Task</h3>

            {/* Task Summary */}
            <div className="space-y-4 mb-6">
              <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
                <h4 className="text-sm font-semibold text-blue-900 mb-3">Task Summary</h4>

                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-3 text-sm mb-4">
                  <div>
                    <span className="text-blue-700">Task Name:</span>
                    <span className="ml-2 font-medium text-blue-900">{taskName}</span>
                  </div>
                  <div>
                    <span className="text-blue-700">Task Type:</span>
                    <span className="ml-2 font-medium text-blue-900 capitalize">{taskType}</span>
                  </div>
                  <div>
                    <span className="text-blue-700">Data Level:</span>
                    <span className="ml-2 font-medium text-blue-900">{dataLevel === 'wsi' ? 'WSI-level' : 'Patch-level'}</span>
                  </div>
                  <div>
                    <span className="text-blue-700">{dataLevel === 'wsi' ? 'WSI Slides' : 'Images'}:</span>
                    <span className="ml-2 font-medium text-blue-900">{selectedIds.size} {dataLevel === 'wsi' ? 'slides' : 'images'}</span>
                  </div>
                  <div>
                    <span className="text-blue-700">Estimated Time:</span>
                    <span className="ml-2 font-medium text-blue-900">
                      ~{validateConfiguration.estimatedHours < 1
                        ? `${(validateConfiguration.estimatedHours * 60).toFixed(0)} min`
                        : `${validateConfiguration.estimatedHours.toFixed(1)} hrs`}
                    </span>
                  </div>
                </div>

                {/* Preprocessing Config (WSI-level only) */}
                {dataLevel === 'wsi' && (
                  <div className="border-t border-blue-200 pt-3 mb-3">
                    <h5 className="text-xs font-semibold text-blue-800 mb-2">Preprocessing</h5>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-blue-600">Feature Extractor:</span>
                        <span className="ml-2 font-medium text-blue-900">{FEATURE_EXTRACTORS.find(e => e.id === featureExtractor)?.name}</span>
                      </div>
                      <div>
                        <span className="text-blue-600">Tile Size:</span>
                        <span className="ml-2 font-medium text-blue-900">{tileSize}px</span>
                      </div>
                      <div>
                        <span className="text-blue-600">Stride:</span>
                        <span className="ml-2 font-medium text-blue-900">{stride === 0 ? `${tileSize}px (no overlap)` : `${stride}px`}</span>
                      </div>
                      <div>
                        <span className="text-blue-600">Pyramid Level:</span>
                        <span className="ml-2 font-medium text-blue-900">{pyramidLevel}</span>
                      </div>
                      <div>
                        <span className="text-blue-600">Feature Batch Size:</span>
                        <span className="ml-2 font-medium text-blue-900">{featureBatchSize}</span>
                      </div>
                      <div>
                        <span className="text-blue-600">Device:</span>
                        <span className="ml-2 font-medium text-blue-900">GPU</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Model Config */}
                <div className="border-t border-blue-200 pt-3">
                  <h5 className="text-xs font-semibold text-blue-800 mb-2">Model</h5>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {dataLevel === 'wsi' && (
                      <div>
                        <span className="text-blue-600">Aggregator:</span>
                        <span className="ml-2 font-medium text-blue-900">{AGGREGATORS.find(a => a.id === aggregator)?.name}</span>
                      </div>
                    )}
                    {dataLevel === 'patch' && (
                      <div>
                        <span className="text-blue-600">Backbone:</span>
                        <span className="ml-2 font-medium text-blue-900">{PATCH_MODELS.find(m => m.id === patchModel)?.name}</span>
                      </div>
                    )}
                    <div>
                      <span className="text-blue-600">Epochs:</span>
                      <span className="ml-2 font-medium text-blue-900">{epochs}</span>
                    </div>
                    <div>
                      <span className="text-blue-600">Learning Rate:</span>
                      <span className="ml-2 font-medium text-blue-900">{learningRate}</span>
                    </div>
                    <div>
                      <span className="text-blue-600">Optimizer:</span>
                      <span className="ml-2 font-medium text-blue-900 capitalize">{optimizer}</span>
                    </div>
                    <div>
                      <span className="text-blue-600">Batch Size:</span>
                      <span className="ml-2 font-medium text-blue-900">{trainBatchSize}</span>
                    </div>
                    <div>
                      <span className="text-blue-600">Early Stopping:</span>
                      <span className="ml-2 font-medium text-blue-900">{earlyStoppingPatience} epochs</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Validation Errors */}
              {validateConfiguration.errors.length > 0 && (
                <div className="bg-red-50 rounded-lg p-4 border border-red-200">
                  <h4 className="text-sm font-semibold text-red-900 mb-2">Configuration Errors</h4>
                  <ul className="text-sm text-red-700 space-y-1">
                    {validateConfiguration.errors.map((err, i) => (
                      <li key={i}>• {err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Validation Warnings */}
              {validateConfiguration.warnings.length > 0 && validateConfiguration.errors.length === 0 && (
                <div className="bg-yellow-50 rounded-lg p-4 border border-yellow-200">
                  <h4 className="text-sm font-semibold text-yellow-900 mb-2">Configuration Warnings</h4>
                  <ul className="text-sm text-yellow-700 space-y-1">
                    {validateConfiguration.warnings.map((warn, i) => (
                      <li key={i}>• {warn}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Status Display */}
              {trainingStatus === 'validating' && (
                <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
                  <div className="flex items-center space-x-3">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                    <span className="text-sm font-medium text-blue-800">Validating configuration...</span>
                  </div>
                </div>
              )}

              {trainingStatus === 'submitting' && (
                <div className="bg-yellow-50 rounded-lg p-4 border border-yellow-200">
                  <div className="flex items-center space-x-3">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-yellow-600"></div>
                    <span className="text-sm font-medium text-yellow-800">Submitting training task...</span>
                  </div>
                </div>
              )}

              {trainingStatus === 'submitted' && (
                <div className="bg-green-50 rounded-lg p-4 border border-green-200">
                  <div className="flex items-center space-x-3">
                    <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-sm font-medium text-green-800">Task submitted successfully!</span>
                  </div>
                </div>
              )}

              {submitError && (
                <div className="bg-red-50 rounded-lg p-4 border border-red-200">
                  <div className="flex items-start space-x-3">
                    <svg className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <div className="flex-1">
                      <h4 className="text-sm font-semibold text-red-900 mb-1">Failed to submit task</h4>
                      <p className="text-sm text-red-700 mb-3">{parseErrorMessage(submitError)}</p>

                      {/* Error suggestion */}
                      {getErrorSuggestion(submitError) && (
                        <div className="bg-red-100 rounded p-2 mb-3">
                          <p className="text-xs text-red-800">
                            <strong>Suggestion:</strong> {getErrorSuggestion(submitError)}
                          </p>
                        </div>
                      )}

                      {/* Retry button */}
                      <button
                        onClick={() => {
                          setSubmitError('')
                          setTrainingStatus('idle')
                        }}
                        className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
                      >
                        Clear Error and Retry
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Information */}
              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-2">Important Information</h4>
                <ul className="text-sm text-gray-700 space-y-1">
                  <li>• Training is a long-running background process that may take hours</li>
                  <li>• After submission, you can monitor progress and logs in <strong>Task Manager</strong></li>
                  <li>• The system will process: Patch Extraction → Feature Extraction → Model Training</li>
                  <li>• You can safely close this page after submission</li>
                </ul>
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(4)}
              disabled={trainingStatus === 'validating' || trainingStatus === 'submitting' || trainingStatus === 'submitted'}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              ← Back
            </button>
            <button
              onClick={startTraining}
              disabled={
                !validateConfiguration.isValid ||
                trainingStatus === 'validating' ||
                trainingStatus === 'submitting' ||
                trainingStatus === 'submitted'
              }
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                trainingStatus === 'submitted'
                  ? 'bg-green-600 text-white'
                  : trainingStatus === 'failed'
                  ? 'bg-red-600 text-white hover:bg-red-700'
                  : 'bg-primary-600 text-white hover:bg-primary-700'
              }`}
            >
              {trainingStatus === 'validating' && 'Validating...'}
              {trainingStatus === 'submitting' && 'Submitting...'}
              {trainingStatus === 'submitted' && 'Submitted'}
              {trainingStatus === 'failed' && 'Retry Submission'}
              {trainingStatus === 'idle' && 'Submit Training Task'}
            </button>
          </div>
        </>
      )}

      {/* Step 6: Task Submitted Successfully */}
      {currentStep === 6 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            {/* Success Header */}
            <div className="text-center mb-6">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                <svg className="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-2">Training Task Submitted Successfully!</h3>
              <p className="text-gray-600">Your training task has been queued and will start processing shortly.</p>
            </div>

            {/* Task ID */}
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200 mb-6">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-blue-800 mb-1">Task ID</div>
                  <div className="text-lg font-mono font-bold text-blue-900">{submittedTaskId}</div>
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(submittedTaskId)
                    alert('Task ID copied to clipboard!')
                  }}
                  className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Copy ID
                </button>
              </div>
            </div>

            {/* Task Summary */}
            <div className="space-y-4 mb-6">
              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-3">Task Configuration</h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Task Name:</span>
                    <span className="ml-2 font-medium text-gray-900">{taskName}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Task Type:</span>
                    <span className="ml-2 font-medium text-gray-900 capitalize">{taskType}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Data Level:</span>
                    <span className="ml-2 font-medium text-gray-900 capitalize">{dataLevel === 'wsi' ? 'WSI-level' : 'Patch-level'}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">{dataLevel === 'wsi' ? 'WSI Slides' : 'Images'}:</span>
                    <span className="ml-2 font-medium text-gray-900">{selectedIds.size} {dataLevel === 'wsi' ? 'slides' : 'images'}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Epochs:</span>
                    <span className="ml-2 font-medium text-gray-900">{epochs}</span>
                  </div>
                  {dataLevel === 'wsi' && (
                    <div>
                      <span className="text-gray-600">Aggregator:</span>
                      <span className="ml-2 font-medium text-gray-900 uppercase">{aggregator}</span>
                    </div>
                  )}
                  {dataLevel === 'patch' && (
                    <div>
                      <span className="text-gray-600">Backbone:</span>
                      <span className="ml-2 font-medium text-gray-900">{PATCH_MODELS.find(m => m.id === patchModel)?.name}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Next Steps */}
              <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
                <h4 className="text-sm font-semibold text-green-900 mb-2">🎯 Next Steps</h4>
                <ul className="text-sm text-green-800 space-y-2">
                  <li className="flex items-start">
                    <span className="mr-2">1.</span>
                    <span>Go to <strong>Task Manager</strong> to monitor training progress and view live logs</span>
                  </li>
                  <li className="flex items-start">
                    <span className="mr-2">2.</span>
                    <span>Training will process: Patch Extraction → Feature Extraction → Model Training</span>
                  </li>
                  <li className="flex items-start">
                    <span className="mr-2">3.</span>
                    <span>Once completed, the trained model will be available in <strong>Checkpoint Manager</strong></span>
                  </li>
                  <li className="flex items-start">
                    <span className="mr-2">4.</span>
                    <span>You can use the model for inference on new slides in <strong>WSI Browser</strong></span>
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => navigate('/')}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              Back to Dashboard
            </button>
            <div className="flex gap-3">
              <button
                onClick={() => navigate(`/task/${submittedTaskId}`)}
                className="px-6 py-2.5 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 transition-colors"
              >
                View Task Details
              </button>
              <button
                onClick={() => navigate('/task-list')}
                className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
              >
                Go to Task Manager →
              </button>
            </div>
          </div>
        </>
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
              <div className="bg-white rounded-lg p-3 shadow-sm">
                <code className="text-xs text-gray-600 block">
                  <div className="text-purple-600 font-semibold">wsi_path,label,case_id</div>
                  <div className="mt-1">/path/slide1.svs,HSIL,case_001</div>
                  <div>/path/slide2.svs,LSIL,case_002</div>
                </code>
              </div>
              <p className="text-xs text-gray-500 mt-3">
                Note: Only the file path is required. Labels and IDs are optional.
              </p>
            </div>

            {/* Action Buttons */}
            <div className="space-y-3 mb-6">
              <button
                onClick={handleDownloadTemplate}
                className="w-full px-6 py-3.5 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-xl hover:from-green-700 hover:to-green-800 transition-all font-semibold flex items-center justify-center gap-3 shadow-lg shadow-green-200"
              >
                <Download className="w-5 h-5" />
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
                  <span className="text-sm font-medium text-gray-700">Slide ID:</span>
                  <span className="text-sm text-gray-900 font-semibold">{wsiToDelete.wsi_id}</span>
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
                You are about to delete <strong>{selectedIds.size} slide(s)</strong>
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
  )
}

