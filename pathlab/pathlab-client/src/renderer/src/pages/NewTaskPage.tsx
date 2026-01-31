/**
 * NewTaskPage - Training Task Creation Wizard
 *
 * Uses custom hooks for state management and step components for UI rendering.
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import {
  fetchExtractors,
  createTrainingTask,
  getTrainingTask,
  updateWSIMetadata,
  startBatchUpdateMetadataTask,
  TrainingTaskDetail,
} from '../api'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/button'
import { ArrowLeft } from 'lucide-react'

// Custom hooks
import { useTaskWizard } from '../lib/useTaskWizard'
import { useDataSelection } from '../lib/useDataSelection'
import { useTrainingConfig } from '../lib/useTrainingConfig'
import { useSplitValidation } from '../lib/useSplitValidation'

// Step components
import {
  StepProgressBar,
  TaskSetupStep,
  DataSelectionStep,
  PreprocessingStep,
  ModelConfigStep,
  ReviewSubmitStep,
  TaskResultStep,
  DeleteConfirmModal,
  EditMetadataModal,
  BatchEditModal,
} from '../components/training'

// Types
import { WSIItem } from '../types/training'

export default function NewTaskPage() {
  const navigate = useNavigate()
  const { addDeleteWSITask } = useBackgroundTask()

  // ========== Custom Hooks ==========
  const wizard = useTaskWizard()
  const dataSelection = useDataSelection({
    dataLevel: wizard.dataLevel,
    taskType: wizard.taskType,
  })
  const trainingConfig = useTrainingConfig()
  const splitValidation = useSplitValidation({
    items: dataSelection.filteredItems,
    selectedIds: dataSelection.selectedIds,
    taskType: wizard.taskType,
    dataLevel: wizard.dataLevel,
  })

  // ========== Additional Local State ==========
  // Extractor state
  const [availableExtractors, setAvailableExtractors] = useState<
    { id: string; name: string; description: string }[]
  >([])
  const [extractorSearch, setExtractorSearch] = useState('')

  // Delete modal
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [wsiToDelete, setWsiToDelete] = useState<{
    wsi_id: string
    label: string
    original_filename?: string
  } | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Edit modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingWSI, setEditingWSI] = useState<{
    wsi_id: string
    label: string
    case_id: string
    age?: number
    gender?: string
    source?: string
  } | null>(null)
  const [updating, setUpdating] = useState(false)

  // Batch edit modal
  const [showBatchEditModal, setShowBatchEditModal] = useState(false)
  const [batchUpdating, setBatchUpdating] = useState(false)

  // Polling state
  const [polledTask, setPolledTask] = useState<TrainingTaskDetail | null>(null)

  // ========== Computed Values ==========
  const filteredExtractors = useMemo(() => {
    if (!extractorSearch) return availableExtractors
    return availableExtractors.filter(
      (e) =>
        e.name.toLowerCase().includes(extractorSearch.toLowerCase()) ||
        e.description.toLowerCase().includes(extractorSearch.toLowerCase())
    )
  }, [availableExtractors, extractorSearch])

  // ========== Effects ==========
  // Load datasets when entering Step 2
  useEffect(() => {
    if (wizard.currentStep === 2) {
      dataSelection.loadDatasets()
    }
  }, [wizard.currentStep])

  // Load extractors when entering Step 3 (or Step 4 for patch-level)
  useEffect(() => {
    if (wizard.currentStep === 3) {
      loadExtractors()
    }
    if (wizard.currentStep === 4 && wizard.dataLevel === 'patch') {
      loadExtractors()
    }
  }, [wizard.currentStep, wizard.dataLevel])

  // Auto-adjust kFoldSplits when maxK changes
  useEffect(() => {
    if (
      trainingConfig.splitStrategy === 'k_fold' &&
      splitValidation.kFoldValidation.maxK > 0 &&
      trainingConfig.kFoldSplits > splitValidation.kFoldValidation.maxK
    ) {
      trainingConfig.setKFoldSplits(Math.max(2, splitValidation.kFoldValidation.maxK))
    }
  }, [trainingConfig.splitStrategy, splitValidation.kFoldValidation.maxK, trainingConfig.kFoldSplits])

  // Auto-fallback to random if manual is selected but no predefined splits
  useEffect(() => {
    if (trainingConfig.splitStrategy === 'manual' && !dataSelection.hasPreDefinedSplits) {
      trainingConfig.setSplitStrategy('random')
    }
  }, [dataSelection.hasPreDefinedSplits, trainingConfig.splitStrategy])

  // Poll for task status in Step 6
  useEffect(() => {
    let intervalId: NodeJS.Timeout

    if (wizard.currentStep === 6 && wizard.submittedTaskId) {
      const poll = async () => {
        try {
          const task = await getTrainingTask(wizard.submittedTaskId)
          setPolledTask(task)
          if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
            if (intervalId) clearInterval(intervalId)
          }
        } catch (error) {
          console.error('Failed to poll task status', error)
        }
      }

      poll()
      intervalId = setInterval(poll, 2000)
    }

    return () => {
      if (intervalId) clearInterval(intervalId)
    }
  }, [wizard.currentStep, wizard.submittedTaskId])

  // ========== API Functions ==========
  async function loadExtractors() {
    if (availableExtractors.length > 0) return
    try {
      const data = await fetchExtractors()
      setAvailableExtractors(data)
    } catch (e) {
      console.error('Failed to load extractors:', e)
      setAvailableExtractors([])
    }
  }

  // ========== Helper Functions ==========
  const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes || bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const parseErrorMessage = (error: string): string => {
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

  // ========== Delete Handlers ==========
  const handleDeleteClick = (wsi_id: string, label: string, original_filename?: string) => {
    setWsiToDelete({ wsi_id, label, original_filename })
    setShowDeleteModal(true)
  }

  const handleConfirmDelete = async () => {
    if (!wsiToDelete) return
    setDeleting(true)
    try {
      addDeleteWSITask([wsiToDelete.wsi_id], 'standard')
      setShowDeleteModal(false)
      setWsiToDelete(null)
      if (dataSelection.selectedDatasetId) {
        setTimeout(() => dataSelection.reloadItems(), 500)
      }
    } catch (err) {
      console.error('Failed to delete WSI:', err)
      alert(`Failed to delete WSI: ${err}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleBatchDeleteClick = () => {
    if (dataSelection.selectedIds.size === 0) {
      alert('Please select at least one slide to delete')
      return
    }
    // Use inline confirmation for batch delete
    if (confirm(`Are you sure you want to delete ${dataSelection.selectedIds.size} selected items?`)) {
      handleConfirmBatchDelete()
    }
  }

  const handleConfirmBatchDelete = async () => {
    if (dataSelection.selectedIds.size === 0) return
    try {
      addDeleteWSITask(Array.from(dataSelection.selectedIds), 'standard')
      dataSelection.clearSelection()
      if (dataSelection.selectedDatasetId) {
        setTimeout(() => dataSelection.reloadItems(), 500)
      }
    } catch (err) {
      console.error('Failed to batch delete:', err)
      alert(`Failed to batch delete: ${err}`)
    }
  }

  // ========== Edit Handlers ==========
  const handleEditClick = (wsi: WSIItem) => {
    setEditingWSI({
      wsi_id: wsi.wsi_id,
      label: wsi.label || '',
      case_id: wsi.case_id || '',
      age: wsi.age ?? undefined,
      gender: wsi.gender ?? undefined,
      source: wsi.source ?? undefined,
    })
    setShowEditModal(true)
  }

  const handleConfirmEdit = async (data: { label: string; case_id: string; age: string; gender: string; source: string }) => {
    if (!editingWSI) return
    setUpdating(true)
    try {
      const age = data.age ? parseInt(data.age) : undefined
      await updateWSIMetadata(editingWSI.wsi_id, {
        label: data.label,
        case_id: data.case_id,
        age: age,
        gender: data.gender,
        source: data.source,
      })
      setShowEditModal(false)
      setEditingWSI(null)
      if (dataSelection.selectedDatasetId) {
        await dataSelection.reloadItems()
      }
    } catch (err) {
      console.error('Failed to update WSI metadata:', err)
      alert(`Failed to update metadata: ${err}`)
    } finally {
      setUpdating(false)
    }
  }

  const handleBatchEditClick = () => {
    if (dataSelection.selectedIds.size === 0) {
      alert('Please select at least one slide to edit')
      return
    }
    setShowBatchEditModal(true)
  }

  const handleConfirmBatchEdit = async (data: { label: string; case_id: string; age: string; gender: string; source: string }) => {
    if (dataSelection.selectedIds.size === 0) return
    const hasUpdates = data.label || data.case_id || data.age || data.gender || data.source
    if (!hasUpdates) {
      setShowBatchEditModal(false)
      return
    }
    setBatchUpdating(true)
    try {
      const age = data.age ? parseInt(data.age) : undefined
      const request = {
        wsi_ids: Array.from(dataSelection.selectedIds),
        label: data.label || undefined,
        case_id: data.case_id || undefined,
        age: age,
        gender: data.gender || undefined,
        source: data.source || undefined,
      }
      await startBatchUpdateMetadataTask(request)
      setShowBatchEditModal(false)
      dataSelection.clearSelection()
      alert(`Metadata update started for ${request.wsi_ids.length} items. Check notification center for progress.`)
    } catch (err) {
      console.error('Failed to start batch edit:', err)
      alert(`Failed to start batch edit: ${err}`)
    } finally {
      setBatchUpdating(false)
    }
  }

  // ========== Training Submission ==========
  const startTraining = async () => {
    wizard.setTrainingStatus('validating')
    wizard.setSubmitError('')
    wizard.setSubmittedTaskId('')

    await new Promise((resolve) => setTimeout(resolve, 300))
    wizard.setTrainingStatus('submitting')

    try {
      // Build split config
      let splitConfig: any = undefined
      if (trainingConfig.splitStrategy === 'manual') {
        if (!dataSelection.hasPreDefinedSplits) {
          throw new Error('No pre-defined splits found. Please upload a split CSV in the dataset view.')
        }
        const manualSplits: Record<string, string> = {}
        dataSelection.items
          .filter((item) => dataSelection.selectedIds.has(item.wsi_id) && item.split)
          .forEach((item) => {
            let s = item.split!.toLowerCase()
            if (s === 'validation') s = 'val'
            manualSplits[item.wsi_id] = s
          })
        splitConfig = {
          strategy: 'manual',
          manual_splits: manualSplits,
          seed: trainingConfig.randomSeed,
        }
      } else if (trainingConfig.splitStrategy === 'k_fold') {
        splitConfig = {
          strategy: 'k_fold',
          n_splits: trainingConfig.kFoldSplits,
          seed: trainingConfig.randomSeed,
        }
      } else {
        splitConfig = {
          strategy: 'random',
          ratios: { train: 0.7, val: 0.1, test: 0.2 },
          seed: trainingConfig.randomSeed,
        }
      }

      const result = await createTrainingTask({
        task_name: wizard.taskName,
        task_type: wizard.taskType,
        data_level: wizard.dataLevel,
        task_description: wizard.taskDescription,
        wsi_ids: Array.from(dataSelection.selectedIds),
        preprocessing: {
          tile_size: trainingConfig.tileSize,
          stride: trainingConfig.stride,
          level: trainingConfig.pyramidLevel,
          feature_extractor: trainingConfig.featureExtractor,
          feature_batch_size: trainingConfig.featureBatchSize,
          use_gpu: true,
          sthresh: trainingConfig.segSthresh,
          mthresh: trainingConfig.segMthresh,
          close: trainingConfig.segClose,
          use_otsu: trainingConfig.segUseOtsu,
          contour_fn: 'four_pt',
          use_padding: true,
          a_t: trainingConfig.filterAreaThresh,
          a_h: trainingConfig.filterHoleArea,
          max_n_holes: trainingConfig.filterMaxHoles,
        },
        model: {
          aggregator: wizard.dataLevel === 'wsi' ? trainingConfig.aggregator : 'none',
          backbone: wizard.dataLevel === 'patch' ? trainingConfig.featureExtractor : undefined,
          learning_rate: trainingConfig.learningRate,
          epochs: trainingConfig.epochs,
          optimizer: trainingConfig.optimizer,
          batch_size: trainingConfig.trainBatchSize,
          auto_balance: trainingConfig.autoBalance,
          early_stopping_patience: trainingConfig.earlyStoppingPatience,
        },
        split_config: splitConfig,
      })

      wizard.setSubmittedTaskId(result.task_id)
      wizard.setTrainingStatus('submitted')

      setTimeout(() => {
        wizard.setCurrentStep(6)
      }, 800)
    } catch (err) {
      console.error('Failed to submit training task:', err)
      wizard.setSubmitError(String(err))
      wizard.setTrainingStatus('failed')
    }
  }

  // ========== File Upload Handlers ==========
  // ========== Configuration Validation ==========
  const validateConfiguration = useMemo(() => {
    const warnings: string[] = []
    const errors: string[] = []

    if (trainingConfig.epochs <= 0) {
      errors.push('Epochs must be greater than 0')
    } else if (trainingConfig.epochs > 200) {
      warnings.push('High epoch count (>200) may lead to overfitting')
    }

    if (trainingConfig.learningRate <= 0) {
      errors.push('Learning rate must be greater than 0')
    } else if (trainingConfig.learningRate > 0.01) {
      warnings.push('High learning rate (>0.01) may cause training instability')
    } else if (trainingConfig.learningRate < 0.00001) {
      warnings.push('Very low learning rate (<0.00001) may result in slow convergence')
    }

    if (trainingConfig.trainBatchSize <= 0) {
      errors.push('Batch size must be greater than 0')
    }

    if (dataSelection.selectedIds.size < 10) {
      warnings.push('Small dataset (<10 files) may lead to poor generalization')
    }

    if (trainingConfig.tileSize < 256) {
      warnings.push('Small tile size (<256) may miss important context')
    } else if (trainingConfig.tileSize > 1024) {
      warnings.push('Large tile size (>1024) will increase GPU memory usage')
    }

    if (trainingConfig.splitStrategy === 'k_fold') {
      if (!splitValidation.kFoldValidation.isValid) {
        errors.push(splitValidation.kFoldValidation.message || 'K-Fold cross-validation is not available')
      } else if (trainingConfig.kFoldSplits > splitValidation.kFoldValidation.maxK) {
        errors.push(`K=${trainingConfig.kFoldSplits} exceeds maximum allowed (${splitValidation.kFoldValidation.maxK})`)
      }
    }

    if (trainingConfig.splitStrategy === 'random') {
      if (!splitValidation.randomSplitValidation.isValid) {
        errors.push(splitValidation.randomSplitValidation.message || 'Random split is not available')
      }
    }

    return { warnings, errors, isValid: errors.length === 0 }
  }, [
    trainingConfig.epochs,
    trainingConfig.learningRate,
    trainingConfig.trainBatchSize,
    trainingConfig.tileSize,
    trainingConfig.splitStrategy,
    trainingConfig.kFoldSplits,
    dataSelection.selectedIds.size,
    splitValidation.kFoldValidation,
    splitValidation.randomSplitValidation,
  ])

  const canProceedStep1 = useMemo(() => {
    return wizard.taskName.trim().length > 0 && wizard.taskDescription.trim().length > 0
  }, [wizard.taskName, wizard.taskDescription])

  const canProceedStep2 = useMemo(() => {
    if (dataSelection.selectedIds.size === 0) return false
    if (trainingConfig.splitStrategy === 'random' && !splitValidation.randomSplitValidation.isValid) return false
    if (trainingConfig.splitStrategy === 'k_fold' && !splitValidation.kFoldValidation.isValid) return false
    if (trainingConfig.splitStrategy === 'k_fold' && trainingConfig.kFoldSplits > splitValidation.kFoldValidation.maxK) return false
    return true
  }, [
    dataSelection.selectedIds.size,
    trainingConfig.splitStrategy,
    trainingConfig.kFoldSplits,
    splitValidation.randomSplitValidation.isValid,
    splitValidation.kFoldValidation.isValid,
    splitValidation.kFoldValidation.maxK,
  ])

  const canProceedStep3 = true
  const canProceedStep4 = true
  const canProceedStep5 = validateConfiguration.isValid

  // ========== JSX Rendering ==========
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
          <StepProgressBar currentStep={wizard.currentStep} dataLevel={wizard.dataLevel} />

          {/* Step 1: Task Setup */}
          {wizard.currentStep === 1 && (
            <TaskSetupStep
              taskName={wizard.taskName}
              setTaskName={wizard.setTaskName}
              taskType={wizard.taskType}
              setTaskType={wizard.setTaskType}
              dataLevel={wizard.dataLevel}
              setDataLevel={wizard.setDataLevel}
              taskDescription={wizard.taskDescription}
              setTaskDescription={wizard.setTaskDescription}
              canProceed={canProceedStep1}
              onNext={() => wizard.setCurrentStep(2)}
            />
          )}

          {/* Step 2: Data Selection */}
          {wizard.currentStep === 2 && (
            <DataSelectionStep
              taskType={wizard.taskType}
              dataLevel={wizard.dataLevel}
              datasets={dataSelection.filteredDatasets}
              datasetsLoading={dataSelection.datasetsLoading}
              selectedDatasetId={dataSelection.selectedDatasetId}
              selectedDatasetName={dataSelection.selectedDatasetName}
              onSelectDataset={(id, name) => {
                dataSelection.selectDataset(id, name)
              }}
              onBackToDatasets={() => dataSelection.selectDataset(null, '')}
              items={dataSelection.filteredItems}
              loading={dataSelection.loading}
              selectedIds={dataSelection.selectedIds}
              toggleSelection={dataSelection.toggleSelection}
              setSelectedIds={dataSelection.setSelectedIds}
              expandedCases={dataSelection.expandedCases}
              toggleCaseExpansion={dataSelection.toggleCaseExpansion}
              hasMultiSlideCases={dataSelection.hasMultiSlideCases}
              groupedByCaseId={dataSelection.groupedByCaseId}
              paginatedCases={dataSelection.paginatedCases}
              isPatchDataset={dataSelection.isPatchDataset}
              totalCases={dataSelection.totalCases}
              currentPage={dataSelection.currentPage}
              setCurrentPage={dataSelection.setCurrentPage}
              pageSize={dataSelection.pageSize}
              setPageSize={dataSelection.setPageSize}
              totalPages={dataSelection.totalPages}
              pageSlides={dataSelection.pageSlides}
              searchQuery={dataSelection.searchQuery}
              setSearchQuery={dataSelection.setSearchQuery}
              allPageSelected={dataSelection.allPageSelected}
              allFilteredSelected={dataSelection.allFilteredSelected}
              handleSelectPage={dataSelection.handleSelectPage}
              handleSelectAllFiltered={dataSelection.handleSelectAllFiltered}
              onDeleteClick={handleDeleteClick}
              onEditClick={handleEditClick}
              onBatchDeleteClick={handleBatchDeleteClick}
              onBatchEditClick={handleBatchEditClick}
              formatBytes={formatBytes}
              getFileType={dataSelection.getFileType}
              splitStrategy={trainingConfig.splitStrategy}
              setSplitStrategy={trainingConfig.setSplitStrategy}
              kFoldSplits={trainingConfig.kFoldSplits}
              setKFoldSplits={trainingConfig.setKFoldSplits}
              randomSeed={trainingConfig.randomSeed}
              setRandomSeed={trainingConfig.setRandomSeed}
              hasPreDefinedSplits={dataSelection.hasPreDefinedSplits}
              predefinedSplitCounts={dataSelection.predefinedSplitCounts}
              classDistribution={splitValidation.classDistribution}
              kFoldValidation={splitValidation.kFoldValidation}
              randomSplitValidation={splitValidation.randomSplitValidation}
              canProceed={canProceedStep2}
              onBack={() => wizard.setCurrentStep(1)}
              onNext={() => wizard.setCurrentStep(wizard.dataLevel === 'wsi' ? 3 : 4)}
            />
          )}

          {/* Step 3: Preprocessing (WSI-level only) */}
          {wizard.currentStep === 3 && wizard.dataLevel === 'wsi' && (
            <PreprocessingStep
              tileSize={trainingConfig.tileSize}
              setTileSize={trainingConfig.setTileSize}
              stride={trainingConfig.stride}
              setStride={trainingConfig.setStride}
              pyramidLevel={trainingConfig.pyramidLevel}
              setPyramidLevel={trainingConfig.setPyramidLevel}
              featureExtractor={trainingConfig.featureExtractor}
              setFeatureExtractor={trainingConfig.setFeatureExtractor}
              featureBatchSize={trainingConfig.featureBatchSize}
              setFeatureBatchSize={trainingConfig.setFeatureBatchSize}
              filteredExtractors={filteredExtractors}
              extractorSearch={extractorSearch}
              setExtractorSearch={setExtractorSearch}
              segSthresh={trainingConfig.segSthresh}
              setSegSthresh={trainingConfig.setSegSthresh}
              segMthresh={trainingConfig.segMthresh}
              setSegMthresh={trainingConfig.setSegMthresh}
              segUseOtsu={trainingConfig.segUseOtsu}
              setSegUseOtsu={trainingConfig.setSegUseOtsu}
              canProceed={canProceedStep3}
              onBack={() => wizard.setCurrentStep(2)}
              onNext={() => wizard.setCurrentStep(4)}
            />
          )}

          {/* Step 4: Model Configuration */}
          {wizard.currentStep === 4 && (
            <ModelConfigStep
              dataLevel={wizard.dataLevel}
              aggregator={trainingConfig.aggregator}
              setAggregator={trainingConfig.setAggregator}
              featureExtractor={trainingConfig.featureExtractor}
              setFeatureExtractor={trainingConfig.setFeatureExtractor}
              filteredExtractors={filteredExtractors}
              extractorSearch={extractorSearch}
              setExtractorSearch={setExtractorSearch}
              learningRate={trainingConfig.learningRate}
              setLearningRate={trainingConfig.setLearningRate}
              epochs={trainingConfig.epochs}
              setEpochs={trainingConfig.setEpochs}
              trainBatchSize={trainingConfig.trainBatchSize}
              setTrainBatchSize={trainingConfig.setTrainBatchSize}
              optimizer={trainingConfig.optimizer}
              setOptimizer={trainingConfig.setOptimizer}
              earlyStoppingPatience={trainingConfig.earlyStoppingPatience}
              setEarlyStoppingPatience={trainingConfig.setEarlyStoppingPatience}
              randomSeed={trainingConfig.randomSeed}
              setRandomSeed={trainingConfig.setRandomSeed}
              autoBalance={trainingConfig.autoBalance}
              setAutoBalance={trainingConfig.setAutoBalance}
              canProceed={canProceedStep4}
              onBack={() => wizard.setCurrentStep(wizard.dataLevel === 'wsi' ? 3 : 2)}
              onNext={() => wizard.setCurrentStep(5)}
            />
          )}

          {/* Step 5: Review & Submit */}
          {wizard.currentStep === 5 && (
            <ReviewSubmitStep
              taskName={wizard.taskName}
              taskType={wizard.taskType}
              dataLevel={wizard.dataLevel}
              taskDescription={wizard.taskDescription}
              selectedCount={dataSelection.selectedIds.size}
              tileSize={trainingConfig.tileSize}
              stride={trainingConfig.stride}
              pyramidLevel={trainingConfig.pyramidLevel}
              segUseOtsu={trainingConfig.segUseOtsu}
              aggregator={trainingConfig.aggregator}
              featureExtractor={trainingConfig.featureExtractor}
              availableExtractors={availableExtractors}
              learningRate={trainingConfig.learningRate}
              epochs={trainingConfig.epochs}
              trainBatchSize={trainingConfig.trainBatchSize}
              optimizer={trainingConfig.optimizer}
              earlyStoppingPatience={trainingConfig.earlyStoppingPatience}
              autoBalance={trainingConfig.autoBalance}
              validateConfiguration={validateConfiguration}
              trainingStatus={wizard.trainingStatus}
              submitError={wizard.submitError}
              parseErrorMessage={parseErrorMessage}
              getErrorSuggestion={getErrorSuggestion}
              canProceed={canProceedStep5}
              onBack={() => wizard.setCurrentStep(4)}
              onSubmit={startTraining}
              onClearError={() => wizard.setSubmitError('')}
            />
          )}

          {/* Step 6: Task Results */}
          {wizard.currentStep === 6 && (
            <TaskResultStep
              taskName={wizard.taskName}
              dataLevel={wizard.dataLevel}
              selectedCount={dataSelection.selectedIds.size}
              epochs={trainingConfig.epochs}
              submittedTaskId={wizard.submittedTaskId}
              aggregator={trainingConfig.aggregator}
              featureExtractor={trainingConfig.featureExtractor}
              availableExtractors={availableExtractors}
              polledTask={polledTask}
              getErrorSuggestion={getErrorSuggestion}
            />
          )}

          {/* Delete Confirmation Modal */}
          {showDeleteModal && wsiToDelete && (
            <DeleteConfirmModal
              mode="single"
              wsiToDelete={wsiToDelete}
              deleting={deleting}
              onConfirm={handleConfirmDelete}
              onCancel={() => {
                setShowDeleteModal(false)
                setWsiToDelete(null)
              }}
            />
          )}

          {/* Edit Metadata Modal */}
          {showEditModal && editingWSI && (
            <EditMetadataModal
              taskType={wizard.taskType}
              editingWSI={editingWSI}
              updating={updating}
              onConfirm={handleConfirmEdit}
              onCancel={() => {
                setShowEditModal(false)
                setEditingWSI(null)
              }}
            />
          )}

          {/* Batch Edit Modal */}
          {showBatchEditModal && (
            <BatchEditModal
              taskType={wizard.taskType}
              selectedCount={dataSelection.selectedIds.size}
              updating={batchUpdating}
              onConfirm={handleConfirmBatchEdit}
              onCancel={() => setShowBatchEditModal(false)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
