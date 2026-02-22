/**
 * NewTaskPage - Training Task Creation Wizard
 *
 * Uses custom hooks for state management and step components for UI rendering.
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
import { formatBytes } from '../lib/utils'

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
  const { t } = useTranslation()
  const { addDeleteWSITask, hasUploadingTasks } = useBackgroundTask()

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
    event_time?: number
    event_status?: number
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

  // Auto-adjust default parameters when taskType changes (System-wide defaults: Cls=50, Survival=30)
  useEffect(() => {
    if (wizard.taskType === 'survival') {
      trainingConfig.setEpochs(30)
    } else {
      trainingConfig.setEpochs(50)
    }
  }, [wizard.taskType])

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
  const parseErrorMessage = (error: string): string => {
    if (error.includes('Failed to create training task:')) {
      return error.replace('Failed to create training task:', '').trim()
    }
    return error
  }

  const getErrorSuggestion = (error: string): string | null => {
    const errorLower = error.toLowerCase()
    // External storage connectivity errors (check first - most specific)
    if (errorLower.includes('external storage not responding') ||
        (errorLower.includes('storage') && errorLower.includes('timed out'))) {
      return t('newTask.errors.storageUnreachable')
    }
    if (errorLower.includes('not accessible') && errorLower.includes('file')) {
      return t('newTask.errors.filesNotAccessible')
    }
    if (errorLower.includes('network') || errorLower.includes('fetch')) {
      return t('newTask.errors.networkError')
    }
    if (errorLower.includes('wsi') || errorLower.includes('slide')) {
      return t('newTask.errors.invalidLabels')
    }
    if (errorLower.includes('gpu') || errorLower.includes('cuda')) {
      return t('newTask.errors.gpuRequired')
    }
    if (errorLower.includes('vram') || errorLower.includes('out of memory') || errorLower.includes('oom')) {
      return t('newTask.errors.gpuMemoryExceeded')
    }
    if (errorLower.includes('timeout') || errorLower.includes('timed out')) {
      return t('newTask.errors.serverTimeout')
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
      alert(t('newTask.errors.failedDeleteWsi', { error: String(err) }))
    } finally {
      setDeleting(false)
    }
  }

  const handleBatchDeleteClick = () => {
    if (dataSelection.selectedIds.size === 0) {
      alert(t('newTask.errors.selectAtLeastOneToDelete'))
      return
    }
    // Use inline confirmation for batch delete
    if (confirm(t('newTask.errors.confirmBatchDelete', { count: dataSelection.selectedIds.size }))) {
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
      alert(t('newTask.errors.failedBatchDelete', { error: String(err) }))
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
      event_time: wsi.event_time ?? undefined,
      event_status: wsi.event_status ?? undefined,
    })
    setShowEditModal(true)
  }

  const handleConfirmEdit = async (data: {
    label: string
    case_id: string
    age: string
    gender: string
    source: string
    event_time: string
    event_status: string
  }) => {
    if (!editingWSI) return
    setUpdating(true)
    try {
      const age = data.age ? parseInt(data.age) : undefined
      const event_time = data.event_time ? parseFloat(data.event_time) : undefined
      const event_status = data.event_status ? parseInt(data.event_status) : undefined

      await updateWSIMetadata(editingWSI.wsi_id, {
        label: data.label,
        case_id: data.case_id,
        age: age,
        gender: data.gender,
        source: data.source,
        event_time: event_time,
        event_status: event_status,
      })
      setShowEditModal(false)
      setEditingWSI(null)
      if (dataSelection.selectedDatasetId) {
        await dataSelection.reloadItems()
      }
    } catch (err) {
      console.error('Failed to update WSI metadata:', err)
      alert(t('newTask.errors.failedUpdateMetadata', { error: String(err) }))
    } finally {
      setUpdating(false)
    }
  }

  const handleBatchEditClick = () => {
    if (dataSelection.selectedIds.size === 0) {
      alert(t('newTask.errors.selectAtLeastOneToEdit'))
      return
    }
    setShowBatchEditModal(true)
  }

  const handleConfirmBatchEdit = async (data: {
    label: string
    case_id: string
    age: string
    gender: string
    source: string
    event_time: string
    event_status: string
  }) => {
    if (dataSelection.selectedIds.size === 0) return
    const hasUpdates =
      data.label ||
      data.case_id ||
      data.age ||
      data.gender ||
      data.source ||
      data.event_time ||
      data.event_status

    if (!hasUpdates) {
      setShowBatchEditModal(false)
      return
    }
    setBatchUpdating(true)
    try {
      const age = data.age ? parseInt(data.age) : undefined
      const event_time = data.event_time ? parseFloat(data.event_time) : undefined
      const event_status = data.event_status ? parseInt(data.event_status) : undefined

      const request = {
        wsi_ids: Array.from(dataSelection.selectedIds),
        label: data.label || undefined,
        case_id: data.case_id || undefined,
        age: age,
        gender: data.gender || undefined,
        source: data.source || undefined,
        event_time: event_time,
        event_status: event_status,
      }
      await startBatchUpdateMetadataTask(request)
      setShowBatchEditModal(false)
      dataSelection.clearSelection()
      alert(t('newTask.errors.batchUpdateStarted', { count: request.wsi_ids.length }))
    } catch (err) {
      console.error('Failed to start batch edit:', err)
      alert(t('newTask.errors.failedBatchEdit', { error: String(err) }))
    } finally {
      setBatchUpdating(false)
    }
  }

  // ========== Training Submission ==========
  const startTraining = async () => {
    wizard.setTrainingStatus('validating')
    wizard.setSubmitError('')
    wizard.setSubmittedTaskId('')

    // Check if there are any uploading tasks (upload or batch_import)
    if (hasUploadingTasks()) {
      wizard.setSubmitError(t('newTask.errors.uploadInProgress'))
      wizard.setTrainingStatus('failed')
      return
    }

    await new Promise((resolve) => setTimeout(resolve, 300))
    wizard.setTrainingStatus('submitting')

    try {
      // Build split config
      let splitConfig: any = undefined
      if (trainingConfig.splitStrategy === 'manual') {
        if (!dataSelection.hasPreDefinedSplits) {
          throw new Error(t('newTask.errors.noPreDefinedSplits'))
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
        data_type: wizard.dataLevel,
        task_description: wizard.taskDescription,
        wsi_ids: Array.from(dataSelection.selectedIds),
        preprocessing: {
          // Note: tile_size removed - auto-determined by PrePATH-style tiling
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
      errors.push(t('newTask.validation.epochsPositive'))
    } else if (trainingConfig.epochs > 200) {
      warnings.push(t('newTask.validation.highEpochs'))
    }

    if (trainingConfig.learningRate <= 0) {
      errors.push(t('newTask.validation.learningRatePositive'))
    } else if (trainingConfig.learningRate > 0.01) {
      warnings.push(t('newTask.validation.highLearningRate'))
    } else if (trainingConfig.learningRate < 0.00001) {
      warnings.push(t('newTask.validation.lowLearningRate'))
    }

    if (trainingConfig.trainBatchSize <= 0) {
      errors.push(t('newTask.validation.batchSizePositive'))
    }

    if (dataSelection.selectedIds.size < 10) {
      warnings.push(t('newTask.validation.smallDataset'))
    }

    // Check for single-class tasks (classification or survival)
    if (wizard.taskType === 'classification') {
      const classes = Object.keys(splitValidation.classDistribution).filter((k) => k !== '__unlabeled__')
      if (classes.length < 2) {
        errors.push(t('newTask.validation.classificationMinClasses'))
      }
    } else if (wizard.taskType === 'survival') {
      const eventCount = splitValidation.classDistribution['__event__'] || 0
      const censoredCount = splitValidation.classDistribution['__censored__'] || 0
      if (eventCount === 0 || censoredCount === 0) {
        const missingType = eventCount === 0 ? 'Event (status=1)' : 'Censored (status=0)'
        errors.push(t('newTask.validation.survivalBothRequired', { missingType }))
      }
    }

    // Note: tile_size validation removed - now auto-determined by PrePATH-style tiling

    if (trainingConfig.splitStrategy === 'k_fold') {
      if (!splitValidation.kFoldValidation.isValid) {
        errors.push(splitValidation.kFoldValidation.message || t('newTask.validation.kFoldUnavailable'))
      } else if (trainingConfig.kFoldSplits > splitValidation.kFoldValidation.maxK) {
        errors.push(t('newTask.validation.kFoldExceedsMax', { k: trainingConfig.kFoldSplits, maxK: splitValidation.kFoldValidation.maxK }))
      }
    }

    if (trainingConfig.splitStrategy === 'random') {
      if (!splitValidation.randomSplitValidation.isValid) {
        errors.push(splitValidation.randomSplitValidation.message || t('newTask.validation.randomSplitUnavailable'))
      }
    }

    return { warnings, errors, isValid: errors.length === 0 }
  }, [
    trainingConfig.epochs,
    trainingConfig.learningRate,
    trainingConfig.trainBatchSize,
    trainingConfig.splitStrategy,
    trainingConfig.kFoldSplits,
    dataSelection.selectedIds.size,
    splitValidation.kFoldValidation,
    splitValidation.randomSplitValidation,
    splitValidation.classDistribution,
    wizard.taskType,
    t,
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
              title={t('newTask.title')}
              description={t('newTask.description')}
              className="flex-1"
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate('/dashboard')}
                className="gap-2 w-full sm:w-auto"
              >
                <ArrowLeft className="w-4 h-4" />
                {t('newTask.backToDashboard')}
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
