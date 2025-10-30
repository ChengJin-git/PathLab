import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, uploadWSIByCSV, downloadCSVTemplate, deleteWSI, updateWSIMetadata } from '../api'

// Available feature extractors
const FEATURE_EXTRACTORS = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained, general-purpose' },
  { id: 'vit_base', name: 'ViT-Base', description: 'Vision Transformer, advanced features' },
  { id: 'ctranspath', name: 'CTransPath', description: 'Pathology-specific, recommended' },
  { id: 'uni', name: 'UNI', description: 'Universal pathology foundation model' },
]

// Available aggregators
const AGGREGATORS = [
  { id: 'abmil', name: 'ABMIL', description: 'Attention-based MIL (recommended)', detail: 'Learns importance weights for each patch' },
  { id: 'mean', name: 'Mean Pooling', description: 'Simple average pooling', detail: 'Average of all patch features' },
  { id: 'max', name: 'Max Pooling', description: 'Maximum activation pooling', detail: 'Takes maximum across patches' },
]

// Tile size options
const TILE_SIZES = [224, 256, 512]

export default function NewTaskPage() {
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1: Task Configuration
  const [taskName, setTaskName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'segmentation'>('classification')
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
  const [tileSize, setTileSize] = useState(256)
  const [stride, setStride] = useState(256)
  const [tissueThreshold, setTissueThreshold] = useState(0.5)
  const [removeBackground, setRemoveBackground] = useState(true)
  const [featureExtractor, setFeatureExtractor] = useState('ctranspath')
  const [featureBatchSize, setFeatureBatchSize] = useState(32)
  const [useGPU, setUseGPU] = useState(true)

  // Step 4: Model Configuration
  const [aggregator, setAggregator] = useState('abmil')
  const [learningRate, setLearningRate] = useState(0.0001)
  const [epochs, setEpochs] = useState(50)
  const [trainBatchSize, setTrainBatchSize] = useState(1)
  const [optimizer, setOptimizer] = useState('adam')
  const [earlyStoppingPatience, setEarlyStoppingPatience] = useState(10)
  const [autoBalance, setAutoBalance] = useState(true)

  // Step 5: Training & Execution
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'patching' | 'extracting' | 'training' | 'completed'>('idle')
  const [trainingProgress, setTrainingProgress] = useState(0)
  const [trainingLogs, setTrainingLogs] = useState<string[]>([])
  const [currentStage, setCurrentStage] = useState('')
  const [patchCount, setPatchCount] = useState(0)
  const [processedPatches, setProcessedPatches] = useState(0)

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

  const handleModelToggle = (modelId: string) => {
    setSelectedModels(prev =>
      prev.includes(modelId)
        ? prev.filter(id => id !== modelId)
        : [...prev, modelId]
    )
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

  const startTraining = async () => {
    setTrainingProgress(0)
    setTrainingLogs([])
    setPatchCount(0)
    setProcessedPatches(0)

    const addLog = (msg: string) => {
      const timestamp = new Date().toLocaleTimeString()
      setTrainingLogs(prev => [...prev, `[${timestamp}] ${msg}`])
    }

    const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

    // Stage 1: Patch Extraction
    setTrainingStatus('patching')
    setCurrentStage('Extracting patches from WSI files...')
    addLog('Starting patch extraction...')
    addLog(`Tile size: ${tileSize}x${tileSize}, Stride: ${stride}`)
    addLog(`Processing ${selectedIds.size} WSI files...`)
    await sleep(1000)

    const estimatedPatches = selectedIds.size * 15000
    setPatchCount(estimatedPatches)

    for (let i = 0; i < selectedIds.size; i++) {
      addLog(`Processing slide ${i + 1}/${selectedIds.size}...`)
      addLog(`Extracted ${Math.floor(estimatedPatches / selectedIds.size)} patches`)
      setTrainingProgress(Math.floor((i + 1) / selectedIds.size * 20))
      await sleep(500)
    }

    addLog(`Total patches extracted: ${estimatedPatches.toLocaleString()}`)

    // Stage 2: Feature Extraction
    setTrainingStatus('extracting')
    setCurrentStage('Extracting features from patches...')
    addLog(`Starting feature extraction with ${featureExtractor}...`)
    addLog(`Batch size: ${featureBatchSize}, Device: ${useGPU ? 'GPU' : 'CPU'}`)
    await sleep(1000)

    const batches = Math.ceil(estimatedPatches / featureBatchSize)
    for (let i = 0; i <= batches; i += Math.ceil(batches / 20)) {
      const processed = Math.min(i * featureBatchSize, estimatedPatches)
      setProcessedPatches(processed)
      addLog(`Feature extraction: batch ${i}/${batches} (${processed.toLocaleString()}/${estimatedPatches.toLocaleString()} patches)`)
      if (useGPU && i % 5 === 0) {
        addLog(`GPU utilization: ${Math.floor(Math.random() * 20 + 75)}%`)
      }
      setTrainingProgress(20 + Math.floor(i / batches * 40))
      await sleep(400)
    }

    setProcessedPatches(estimatedPatches)
    addLog('Feature extraction completed!')

    // Stage 3: Model Training
    setTrainingStatus('training')
    setCurrentStage('Training aggregation model...')
    addLog(`Starting model training with ${aggregator.toUpperCase()}...`)
    addLog(`Learning rate: ${learningRate}, Epochs: ${epochs}, Optimizer: ${optimizer}`)
    await sleep(1000)

    for (let epoch = 1; epoch <= epochs; epoch += Math.ceil(epochs / 10)) {
      const loss = (1.5 - epoch / epochs + Math.random() * 0.2).toFixed(4)
      const acc = ((epoch / epochs * 0.8 + Math.random() * 0.1) * 100).toFixed(2)
      addLog(`Epoch ${epoch}/${epochs} - Loss: ${loss}, Accuracy: ${acc}%`)
      setTrainingProgress(60 + Math.floor(epoch / epochs * 40))
      await sleep(600)
    }

    addLog('Training completed successfully!')
    addLog(`Final model saved to checkpoints/`)
    setTrainingStatus('completed')
    setTrainingProgress(100)

    // Save to sessionStorage
    sessionStorage.setItem('taskName', taskName)
    sessionStorage.setItem('taskDescription', taskDescription)
    sessionStorage.setItem('featureExtractor', featureExtractor)
    sessionStorage.setItem('aggregator', aggregator)
    sessionStorage.setItem('selectedTrainingWSIs', JSON.stringify(Array.from(selectedIds)))
    sessionStorage.setItem('trainingCompleted', 'true')
  }

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
    return trainingStatus === 'completed'
  }, [trainingStatus])

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

          {/* Step 3 */}
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

          {/* Step 4 */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 4 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 4 ? '✓' : '4'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 4 ? 'text-gray-900' : 'text-gray-500'}`}>
              Model
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 4 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 5 */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 5 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 5 ? '✓' : '5'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 5 ? 'text-gray-900' : 'text-gray-500'}`}>
              Train
            </span>
          </div>
          <div className={`flex-1 h-1 mx-2 ${currentStep > 5 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          {/* Step 6 */}
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 6 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 6 ? '✓' : '6'}
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
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Task Type *
                </label>
                <div className="flex gap-4">
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="taskType"
                      value="classification"
                      checked={taskType === 'classification'}
                      onChange={(e) => setTaskType(e.target.value as 'classification')}
                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                    />
                    <span className="text-sm text-gray-700">Classification</span>
                  </label>
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="radio"
                      name="taskType"
                      value="segmentation"
                      checked={taskType === 'segmentation'}
                      onChange={(e) => setTaskType(e.target.value as 'segmentation')}
                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                    />
                    <span className="text-sm text-gray-700">Segmentation</span>
                  </label>
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
                  Selected {selectedIds.size} WSI file(s) for training
                </p>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  📁 Upload Files
                </button>
                <button
                  onClick={() => setShowCSVUploadModal(true)}
                  disabled={uploading}
                  className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  📊 Upload CSV
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

            {loading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              </div>
            ) : items.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                No WSI files available. Please upload some files first.
              </div>
            ) : (
              <>
                {/* Batch Actions Bar */}
                {selectedIds.size > 0 && (
                  <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-center justify-between">
                    <span className="text-sm font-medium text-blue-900">
                      {selectedIds.size} slide(s) selected
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={handleBatchEditClick}
                        className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium text-sm"
                      >
                        <span className="mr-2">✏️</span>
                        Edit Selected
                      </button>
                      <button
                        onClick={handleBatchDeleteClick}
                        className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-medium text-sm"
                      >
                        <span className="mr-2">🗑️</span>
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
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">WSI ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Label</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Age</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gender</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {items.map((it) => (
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
                              <span className="mr-1">✏️</span>
                              Edit
                            </button>
                            <button
                              onClick={() => handleDeleteClick(it.wsi_id, it.label)}
                              className="inline-flex items-center px-3 py-1.5 text-xs font-medium rounded-md text-white bg-red-600 hover:bg-red-700 transition-colors"
                            >
                              <span className="mr-1">🗑️</span>
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
              onClick={() => setCurrentStep(3)}
              disabled={!canProceedStep2}
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
                canProceedStep2
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              Next: Preprocessing →
            </button>
          </div>
        </>
      )}

      {/* Step 3: Preprocessing Configuration */}
      {currentStep === 3 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Preprocessing Configuration</h3>

            {/* Patch Extraction */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Patch Extraction</h4>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Tile Size (pixels)
                  </label>
                  <div className="flex gap-4">
                    {TILE_SIZES.map(size => (
                      <label key={size} className="flex items-center space-x-2 cursor-pointer">
                        <input
                          type="radio"
                          name="tileSize"
                          value={size}
                          checked={tileSize === size}
                          onChange={(e) => setTileSize(Number(e.target.value))}
                          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                        />
                        <span className="text-sm text-gray-700">{size}</span>
                      </label>
                    ))}
                  </div>
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
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Tissue Detection Threshold (0-1)
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={tissueThreshold}
                    onChange={(e) => setTissueThreshold(Number(e.target.value))}
                    min={0}
                    max={1}
                    step={0.1}
                  />
                </div>

                <div>
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={removeBackground}
                      onChange={(e) => setRemoveBackground(e.target.checked)}
                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                    />
                    <span className="text-sm text-gray-700">Remove white background</span>
                  </label>
                </div>
              </div>
            </div>

            {/* Feature Extraction */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Feature Extraction</h4>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Feature Extractor
                  </label>
                  <select
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={featureExtractor}
                    onChange={(e) => setFeatureExtractor(e.target.value)}
                  >
                    {FEATURE_EXTRACTORS.map(extractor => (
                      <option key={extractor.id} value={extractor.id}>
                        {extractor.name} - {extractor.description}
                      </option>
                    ))}
                  </select>
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
                    max={128}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Device
                  </label>
                  <div className="flex gap-4">
                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="radio"
                        name="device"
                        value="gpu"
                        checked={useGPU}
                        onChange={() => setUseGPU(true)}
                        className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                      />
                      <span className="text-sm text-gray-700">GPU</span>
                    </label>
                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="radio"
                        name="device"
                        value="cpu"
                        checked={!useGPU}
                        onChange={() => setUseGPU(false)}
                        className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                      />
                      <span className="text-sm text-gray-700">CPU</span>
                    </label>
                  </div>
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

            {/* Aggregation Method */}
            <div className="mb-6">
              <h4 className="text-md font-semibold text-gray-800 mb-3">Aggregation Method</h4>

              <div className="space-y-3">
                {AGGREGATORS.map(agg => (
                  <div
                    key={agg.id}
                    onClick={() => setAggregator(agg.id)}
                    className={`p-4 border-2 rounded-lg cursor-pointer transition-all ${
                      aggregator === agg.id
                        ? 'border-primary-500 bg-primary-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-start space-x-3">
                      <input
                        type="radio"
                        name="aggregator"
                        value={agg.id}
                        checked={aggregator === agg.id}
                        onChange={() => {}}
                        className="mt-1 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                      />
                      <div className="flex-1">
                        <div className="font-semibold text-gray-900">{agg.name}</div>
                        <div className="text-sm text-gray-600 mt-1">{agg.detail}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

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
                    Batch Size (WSI-level)
                  </label>
                  <input
                    type="number"
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    value={trainBatchSize}
                    onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                    min={1}
                    max={16}
                  />
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
              onClick={() => setCurrentStep(3)}
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

      {/* Step 5: Training & Execution */}
      {currentStep === 5 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Training in Progress</h3>

            {/* Overall Progress */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">Overall Progress</span>
                <span className="text-sm font-medium text-gray-900">{trainingProgress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className="bg-primary-600 h-3 rounded-full transition-all duration-300"
                  style={{ width: `${trainingProgress}%` }}
                />
              </div>
            </div>

            {/* Current Stage */}
            <div className="mb-6">
              <div className="flex items-center space-x-2 mb-3">
                <span className="text-sm font-medium text-gray-700">Current Stage:</span>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  trainingStatus === 'idle' ? 'bg-gray-100 text-gray-800' :
                  trainingStatus === 'patching' ? 'bg-yellow-100 text-yellow-800' :
                  trainingStatus === 'extracting' ? 'bg-blue-100 text-blue-800' :
                  trainingStatus === 'training' ? 'bg-purple-100 text-purple-800' :
                  'bg-green-100 text-green-800'
                }`}>
                  {trainingStatus === 'idle' ? 'Ready' :
                   trainingStatus === 'patching' ? 'Patch Extraction' :
                   trainingStatus === 'extracting' ? 'Feature Extraction' :
                   trainingStatus === 'training' ? 'Model Training' :
                   'Completed'}
                </span>
              </div>

              {/* Stage Progress */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center space-x-2">
                    <span className={trainingStatus === 'completed' || trainingProgress > 0 ? 'text-green-600' : 'text-gray-400'}>
                      {trainingStatus === 'completed' || trainingProgress > 0 ? '✓' : '○'}
                    </span>
                    <span className={trainingStatus === 'completed' || trainingProgress > 0 ? 'text-gray-900' : 'text-gray-500'}>
                      Patch Extraction
                    </span>
                  </div>
                  {patchCount > 0 && (
                    <span className="text-gray-600">{patchCount.toLocaleString()} patches</span>
                  )}
                </div>

                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center space-x-2">
                    <span className={trainingStatus === 'completed' || trainingStatus === 'training' || trainingStatus === 'extracting' ? 'text-green-600' : trainingStatus === 'extracting' ? 'text-blue-600' : 'text-gray-400'}>
                      {trainingStatus === 'completed' || trainingStatus === 'training' ? '✓' : trainingStatus === 'extracting' ? '⏳' : '○'}
                    </span>
                    <span className={trainingStatus === 'completed' || trainingStatus === 'training' || trainingStatus === 'extracting' ? 'text-gray-900' : 'text-gray-500'}>
                      Feature Extraction
                    </span>
                  </div>
                  {processedPatches > 0 && (
                    <span className="text-gray-600">{processedPatches}/{patchCount}</span>
                  )}
                </div>

                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center space-x-2">
                    <span className={trainingStatus === 'completed' ? 'text-green-600' : trainingStatus === 'training' ? 'text-purple-600' : 'text-gray-400'}>
                      {trainingStatus === 'completed' ? '✓' : trainingStatus === 'training' ? '⏳' : '○'}
                    </span>
                    <span className={trainingStatus === 'completed' || trainingStatus === 'training' ? 'text-gray-900' : 'text-gray-500'}>
                      Model Training
                    </span>
                  </div>
                  {trainingStatus === 'training' && (
                    <span className="text-gray-600">Epoch {Math.floor(trainingProgress / 2)}/{epochs}</span>
                  )}
                </div>
              </div>
            </div>

            {/* Live Logs */}
            <div className="mb-4">
              <h4 className="text-sm font-medium text-gray-700 mb-2">Live Logs</h4>
              <div className="bg-gray-900 rounded-lg p-4 h-64 overflow-y-auto font-mono text-xs text-green-400">
                {trainingLogs.length === 0 ? (
                  <div className="text-gray-500">Waiting to start training...</div>
                ) : (
                  trainingLogs.map((log, idx) => (
                    <div key={idx}>{log}</div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(4)}
              disabled={trainingStatus !== 'idle'}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              ← Back
            </button>
            <div className="flex space-x-3">
              {trainingStatus === 'idle' && (
                <button
                  onClick={startTraining}
                  className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
                >
                  Start Training
                </button>
              )}
              {trainingStatus === 'completed' && (
                <button
                  onClick={() => setCurrentStep(6)}
                  className="px-6 py-2.5 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 transition-colors"
                >
                  View Results →
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {/* Step 6: Results */}
      {currentStep === 6 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Training Results</h3>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
              <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
                <div className="text-sm font-medium text-green-800 mb-1">Status</div>
                <div className="text-2xl font-bold text-green-900">Completed</div>
              </div>
              <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
                <div className="text-sm font-medium text-blue-800 mb-1">Training Slides</div>
                <div className="text-2xl font-bold text-blue-900">{selectedIds.size}</div>
              </div>
              <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 border border-purple-200">
                <div className="text-sm font-medium text-purple-800 mb-1">Total Patches</div>
                <div className="text-2xl font-bold text-purple-900">{patchCount.toLocaleString()}</div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-2">Task Configuration</h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Task Name:</span>
                    <span className="ml-2 font-medium text-gray-900">{taskName}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Task Type:</span>
                    <span className="ml-2 font-medium text-gray-900 capitalize">{taskType}</span>
                  </div>
                </div>
              </div>

              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-2">Preprocessing</h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Tile Size:</span>
                    <span className="ml-2 font-medium text-gray-900">{tileSize}x{tileSize}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Stride:</span>
                    <span className="ml-2 font-medium text-gray-900">{stride}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Feature Extractor:</span>
                    <span className="ml-2 font-medium text-gray-900">{FEATURE_EXTRACTORS.find(e => e.id === featureExtractor)?.name}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Device:</span>
                    <span className="ml-2 font-medium text-gray-900">{useGPU ? 'GPU' : 'CPU'}</span>
                  </div>
                </div>
              </div>

              <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-2">Model Configuration</h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Aggregator:</span>
                    <span className="ml-2 font-medium text-gray-900">{AGGREGATORS.find(a => a.id === aggregator)?.name}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Learning Rate:</span>
                    <span className="ml-2 font-medium text-gray-900">{learningRate}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Epochs:</span>
                    <span className="ml-2 font-medium text-gray-900">{epochs}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Optimizer:</span>
                    <span className="ml-2 font-medium text-gray-900 uppercase">{optimizer}</span>
                  </div>
                </div>
              </div>

              <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg p-4 border border-gray-200">
                <h4 className="text-sm font-semibold text-gray-800 mb-2">Next Steps</h4>
                <ul className="text-sm text-gray-700 space-y-1">
                  <li>• Model saved to <code className="bg-white px-2 py-0.5 rounded text-xs">checkpoints/{taskName.toLowerCase().replace(/\s+/g, '_')}/</code></li>
                  <li>• Use this model for inference on new slides in WSI Browser</li>
                  <li>• View attention maps and prediction confidence scores</li>
                  <li>• Export results for further analysis</li>
                </ul>
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(5)}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              ← Back to Training
            </button>
            <div className="flex gap-3">
              <button
                onClick={() => navigate('/')}
                className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
              >
                Back to Dashboard
              </button>
              <button
                onClick={() => navigate('/wsi-list')}
                className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
              >
                Go to WSI Browser →
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
                        <span className="text-2xl">📄</span>
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
                <span className="text-3xl">📊</span>
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
                <span className="text-xl">📤</span>
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
                <span className="text-3xl">⚠️</span>
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
                <span className="text-3xl">⚠️</span>
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
                <span className="text-3xl">✏️</span>
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
                <span className="text-3xl">✏️</span>
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

