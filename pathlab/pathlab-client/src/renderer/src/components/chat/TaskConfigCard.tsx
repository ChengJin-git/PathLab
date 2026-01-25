import { useState, useEffect } from 'react'
import { Play, AlertCircle, CheckCircle, Loader2, ChevronDown, ChevronUp, Layers } from 'lucide-react'
import { createTrainingTask, fetchWSIList, fetchDatasets, type TrainingTaskConfig, type DatasetSummary, type WSISummary, type SplitConfig } from '../../api'

// Simplified config from Agent (doesn't include wsi_ids, etc.)
export interface AgentTaskConfig {
  task_name: string
  task_type: 'classification' | 'survival_prediction'
  data_level: 'wsi' | 'patch'
  dataset_id?: string  // Dataset UUID from agent
  tile_size?: number
  encoder?: string
  aggregator?: string
  learning_rate?: number
  epochs?: number
  batch_size?: number
  optimizer?: string
  auto_balance?: boolean  // Auto-balance class weights for imbalanced datasets
  early_stopping_patience?: number  // Early stopping patience (default: 10)
  submitted_task_id?: string  // Set after successful submission for persistence
}

interface TaskConfigCardProps {
  config: AgentTaskConfig
  onSubmitSuccess?: (taskId: string) => void
  onSubmitError?: (error: string) => void
  onConfigChange?: (config: AgentTaskConfig) => void
}

interface ValidationError {
  field: string
  message: string
}

// Field definitions for rendering
// Feature extractors must match NewTaskPage.tsx FEATURE_EXTRACTORS
const FIELD_OPTIONS = {
  task_type: [
    { value: 'classification', label: 'Classification' },
    { value: 'survival_prediction', label: 'Survival Prediction' }
  ],
  data_level: [
    { value: 'wsi', label: 'WSI (Whole Slide)' },
    { value: 'patch', label: 'Patch' }
  ],
  tile_size: [
    { value: 256, label: '256px' },
    { value: 512, label: '512px (recommended)' },
    { value: 1024, label: '1024px' }
  ],
  encoder: [
    { value: 'resnet50', label: 'ResNet50' },
    { value: 'vit_l_16', label: 'ViT-Large' },
    { value: 'conch', label: 'CONCH' },
    { value: 'uni', label: 'UNI' },
    { value: 'uni2', label: 'UNI2' },
    { value: 'virchow', label: 'Virchow' },
    { value: 'virchow2', label: 'Virchow2' },
    { value: 'plip', label: 'PLIP' },
    { value: 'phikon', label: 'Phikon' },
    { value: 'phikon2', label: 'Phikon2' },
    { value: 'patho_clip', label: 'PathoCLIP' },
    { value: 'openmidnight', label: 'OpenMidnight' },
    { value: 'conch15', label: 'CONCH 1.5' },
    { value: 'H-Optimus-1', label: 'H-Optimus-1' },
    { value: 'H-Optimus-0', label: 'H-Optimus-0' },
    { value: 'mSTAR', label: 'mSTAR' },
    { value: 'GPFM', label: 'GPFM' }
  ],
  aggregator: [
    { value: 'abmil', label: 'ABMIL (recommended)' },
    { value: 'meanmil', label: 'MeanMIL' },
    { value: 'maxmil', label: 'MaxMIL' }
  ],
  optimizer: [
    { value: 'adam', label: 'Adam' },
    { value: 'sgd', label: 'SGD' },
    { value: 'adamw', label: 'AdamW' }
  ]
}

/**
 * Parse [TASK_CONFIG] block from message content
 */
export function parseTaskConfig(content: string): AgentTaskConfig | null {
  const match = content.match(/\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [TASK_CONFIG] block from content for display
 */
export function removeTaskConfigBlock(content: string): string {
  return content.replace(/\[TASK_CONFIG\][\s\S]*?\[\/TASK_CONFIG\]/g, '').trim()
}

export function TaskConfigCard({ config: initialConfig, onSubmitSuccess, onSubmitError, onConfigChange }: TaskConfigCardProps) {
  const [config, setConfig] = useState<AgentTaskConfig>(initialConfig)
  const [isSubmitting, setIsSubmitting] = useState(false)
  // Initialize submitStatus based on whether task was already submitted (persisted in config)
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>(
    initialConfig.submitted_task_id ? 'success' : 'idle'
  )
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Dataset selection state
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(initialConfig.dataset_id || null)
  const [availableDatasets, setAvailableDatasets] = useState<DatasetSummary[]>([])
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  const [datasetWSIs, setDatasetWSIs] = useState<WSISummary[]>([])
  const [datasetWSIIds, setDatasetWSIIds] = useState<string[]>([])

  // Split strategy state
  const [splitStrategy, setSplitStrategy] = useState<'random' | 'k_fold' | 'manual'>('random')
  const [kFoldSplits, setKFoldSplits] = useState(5)
  const [hasPreDefinedSplits, setHasPreDefinedSplits] = useState(false)
  const [predefinedSplitCounts, setPredefinedSplitCounts] = useState<{ train: number, val: number, test: number }>({ train: 0, val: 0, test: 0 })

  // File selection state (only used when user wants to select specific files)
  const [useEntireDataset, setUseEntireDataset] = useState(true)
  const [selectedWSIIds, setSelectedWSIIds] = useState<Set<string>>(new Set())

  // Load available datasets on mount
  useEffect(() => {
    loadDatasets()
  }, [])

  // When dataset is selected, load its WSIs
  useEffect(() => {
    if (selectedDatasetId) {
      loadDatasetWSIs(selectedDatasetId)
    } else {
      setDatasetWSIs([])
      setDatasetWSIIds([])
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
    }
  }, [selectedDatasetId])

  // Check for pre-defined splits when WSIs are loaded
  useEffect(() => {
    if (datasetWSIs.length === 0) {
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
      return
    }

    // Count pre-defined splits
    const counts = { train: 0, val: 0, test: 0 }
    let hasAnySplit = false

    datasetWSIs.forEach(wsi => {
      if (wsi.split) {
        hasAnySplit = true
        const s = wsi.split.toLowerCase()
        if (s === 'train') counts.train++
        else if (s === 'val' || s === 'validation') counts.val++
        else if (s === 'test') counts.test++
      }
    })

    setPredefinedSplitCounts(counts)
    const hasSplits = hasAnySplit && counts.train > 0
    setHasPreDefinedSplits(hasSplits)

    // Auto-select manual split if available, or fallback if currently manual but no splits
    if (!hasSplits && splitStrategy === 'manual') {
      setSplitStrategy('random')
    }
  }, [datasetWSIs, splitStrategy])

  const loadDatasets = async () => {
    setIsLoadingDatasets(true)
    try {
      const result = await fetchDatasets()
      setAvailableDatasets(result.items)
      // If agent provided a dataset_id, verify it exists
      if (initialConfig.dataset_id) {
        const found = result.items.find(d => d.dataset_id === initialConfig.dataset_id)
        if (found) {
          setSelectedDatasetId(initialConfig.dataset_id)
        }
      }
    } catch (error) {
      console.error('Failed to load datasets:', error)
    } finally {
      setIsLoadingDatasets(false)
    }
  }

  const loadDatasetWSIs = async (datasetId: string) => {
    try {
      const result = await fetchWSIList(datasetId)
      setDatasetWSIs(result.items)
      setDatasetWSIIds(result.items.map(wsi => wsi.wsi_id))
      // Reset file selection when dataset changes
      setSelectedWSIIds(new Set())
      setUseEntireDataset(true)
    } catch (error) {
      console.error('Failed to load dataset WSIs:', error)
      setDatasetWSIs([])
      setDatasetWSIIds([])
    }
  }

  const updateConfig = (field: keyof AgentTaskConfig, value: any) => {
    const newConfig = { ...config, [field]: value }
    setConfig(newConfig)
    onConfigChange?.(newConfig)
    // Clear validation error for this field
    setValidationErrors(prev => prev.filter(e => e.field !== field))
  }

  // Get the WSI IDs to use (either entire dataset or selected files)
  const getWSIIdsToUse = (): string[] => {
    if (useEntireDataset) {
      return datasetWSIIds
    }
    return Array.from(selectedWSIIds)
  }

  const validate = (): boolean => {
    const errors: ValidationError[] = []
    if (!config.task_name?.trim()) {
      errors.push({ field: 'task_name', message: 'Task name is required' })
    }
    if (!selectedDatasetId) {
      errors.push({ field: 'dataset_id', message: 'Please select a dataset' })
    }
    const wsiIdsToUse = getWSIIdsToUse()
    if (wsiIdsToUse.length === 0) {
      errors.push({ field: 'dataset_id', message: useEntireDataset ? 'Selected dataset has no files' : 'Please select at least one file' })
    }
    if (splitStrategy === 'manual' && !hasPreDefinedSplits) {
      errors.push({ field: 'split', message: 'No pre-defined splits found. Please upload a split CSV or use Random/K-Fold split.' })
    }
    if (config.learning_rate && (config.learning_rate <= 0 || config.learning_rate > 1)) {
      errors.push({ field: 'learning_rate', message: 'Learning rate must be between 0 and 1' })
    }
    if (config.epochs && (config.epochs < 1 || config.epochs > 1000)) {
      errors.push({ field: 'epochs', message: 'Epochs must be between 1 and 1000' })
    }
    setValidationErrors(errors)
    return errors.length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setIsSubmitting(true)
    setSubmitStatus('idle')
    setErrorMessage('')

    try {
      const wsiIdsToUse = getWSIIdsToUse()

      // Build split config based on strategy
      let splitConfig: SplitConfig
      if (splitStrategy === 'manual') {
        // Construct manual splits from WSI data
        const manualSplits: Record<string, string> = {}
        datasetWSIs
          .filter(wsi => wsiIdsToUse.includes(wsi.wsi_id) && wsi.split)
          .forEach(wsi => {
            let s = wsi.split!.toLowerCase()
            if (s === 'validation') s = 'val'
            manualSplits[wsi.wsi_id] = s
          })
        splitConfig = { strategy: 'manual', manual_splits: manualSplits }
      } else if (splitStrategy === 'k_fold') {
        splitConfig = { strategy: 'k_fold', n_splits: kFoldSplits }
      } else {
        splitConfig = { strategy: 'random', ratios: { train: 0.7, val: 0.1, test: 0.2 } }
      }

      // Build full TrainingTaskConfig
      const fullConfig: TrainingTaskConfig = {
        task_name: config.task_name,
        task_type: config.task_type as 'classification' | 'survival_prediction' | 'segmentation',
        data_level: config.data_level,
        task_description: `Created by PathLab Agent`,
        wsi_ids: wsiIdsToUse,
        preprocessing: {
          tile_size: config.tile_size || 512,
          stride: 0,
          level: 0,
          feature_extractor: config.encoder || 'resnet50',
          feature_batch_size: 32,
          use_gpu: true
        },
        model: {
          aggregator: config.aggregator || 'abmil',
          learning_rate: config.learning_rate || 0.0001,
          epochs: config.epochs || 50,
          optimizer: config.optimizer || 'adam',
          batch_size: config.batch_size || 1,
          auto_balance: config.auto_balance ?? true,  // Default to true for imbalanced datasets
          early_stopping_patience: config.early_stopping_patience ?? 10
        },
        split_config: splitConfig
      }
      const result = await createTrainingTask(fullConfig)
      setSubmitStatus('success')
      onSubmitSuccess?.(result.task_id)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to create task'
      setSubmitStatus('error')
      setErrorMessage(msg)
      onSubmitError?.(msg)
    } finally {
      setIsSubmitting(false)
    }
  }

  const getFieldError = (field: string) => validationErrors.find(e => e.field === field)?.message

  // Form is disabled after successful submission
  const isFormDisabled = submitStatus === 'success' || isSubmitting

  // Common disabled styles
  const disabledInputClass = isFormDisabled ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''
  const disabledSelectClass = isFormDisabled ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Play className="w-4 h-4 text-primary-600" />
          Training Configuration
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          {submitStatus === 'success' ? 'Task submitted successfully' : 'Review and edit settings, then start training'}
        </p>
      </div>

      {/* Form Fields */}
      <div className="p-5 space-y-4">
        {/* Task Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Task Name</label>
          <input
            type="text"
            value={config.task_name || ''}
            onChange={(e) => updateConfig('task_name', e.target.value)}
            disabled={isFormDisabled}
            className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-primary-100 focus:border-primary-400 ${
              getFieldError('task_name') ? 'border-red-300 bg-red-50' : 'border-gray-200'
            } ${disabledInputClass}`}
            placeholder="e.g., Lung Cancer Classification"
          />
          {getFieldError('task_name') && (
            <p className="text-xs text-red-500 mt-1">{getFieldError('task_name')}</p>
          )}
        </div>

        {/* Task Type & Data Level */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Task Type</label>
            <select
              value={config.task_type}
              onChange={(e) => updateConfig('task_type', e.target.value)}
              disabled={isFormDisabled}
              className={`w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100 ${disabledSelectClass}`}
            >
              {FIELD_OPTIONS.task_type.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Data Level</label>
            <select
              value={config.data_level}
              onChange={(e) => updateConfig('data_level', e.target.value)}
              disabled={isFormDisabled}
              className={`w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100 ${disabledSelectClass}`}
            >
              {FIELD_OPTIONS.data_level.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Dataset Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Select Dataset {selectedDatasetId && datasetWSIs.length > 0 && (
              <span className="text-gray-500 font-normal">
                ({useEntireDataset ? datasetWSIs.length : selectedWSIIds.size} files will be used)
              </span>
            )}
          </label>
          {isLoadingDatasets ? (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading datasets...
            </div>
          ) : availableDatasets.length === 0 ? (
            <p className="text-sm text-amber-600 py-2">No datasets available. Please upload data first.</p>
          ) : (
            <select
              value={selectedDatasetId || ''}
              onChange={(e) => {
                const newDatasetId = e.target.value || null
                setSelectedDatasetId(newDatasetId)
                setValidationErrors(prev => prev.filter(err => err.field !== 'dataset_id'))
              }}
              disabled={isFormDisabled}
              className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-primary-100 ${
                getFieldError('dataset_id') ? 'border-red-300 bg-red-50' : 'border-gray-200'
              } ${disabledSelectClass}`}
            >
              <option value="">-- Select a dataset --</option>
              {availableDatasets.map(dataset => (
                <option key={dataset.dataset_id || 'uncategorized'} value={dataset.dataset_id || ''}>
                  {dataset.dataset_name} ({dataset.file_count} files)
                </option>
              ))}
            </select>
          )}
          {getFieldError('dataset_id') && (
            <p className="text-xs text-red-500 mt-1">{getFieldError('dataset_id')}</p>
          )}
        </div>

        {/* Use Entire Dataset Toggle & File Selection */}
        {selectedDatasetId && datasetWSIs.length > 0 && (
          <div className="space-y-3">
            <label className={`flex items-center gap-2 ${isFormDisabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
              <input
                type="checkbox"
                checked={useEntireDataset}
                onChange={(e) => {
                  setUseEntireDataset(e.target.checked)
                  if (e.target.checked) {
                    setSelectedWSIIds(new Set())
                  }
                }}
                disabled={isFormDisabled}
                className={`rounded border-gray-300 text-primary-600 focus:ring-primary-500 ${isFormDisabled ? 'cursor-not-allowed' : ''}`}
              />
              <span className={`text-sm ${isFormDisabled ? 'text-gray-500' : 'text-gray-700'}`}>Use entire dataset ({datasetWSIs.length} files)</span>
            </label>

            {/* File selection (only when not using entire dataset) */}
            {!useEntireDataset && (
              <div className={`border border-gray-200 rounded-lg max-h-40 overflow-y-auto ${isFormDisabled ? 'opacity-60' : ''}`}>
                <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-600">
                    Select files ({selectedWSIIds.size}/{datasetWSIs.length} selected)
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      if (selectedWSIIds.size === datasetWSIs.length) {
                        setSelectedWSIIds(new Set())
                      } else {
                        setSelectedWSIIds(new Set(datasetWSIs.map(w => w.wsi_id)))
                      }
                    }}
                    disabled={isFormDisabled}
                    className={`text-xs text-primary-600 hover:text-primary-700 ${isFormDisabled ? 'cursor-not-allowed opacity-50' : ''}`}
                  >
                    {selectedWSIIds.size === datasetWSIs.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                {datasetWSIs.map(wsi => (
                  <label key={wsi.wsi_id} className={`flex items-center gap-2 px-3 py-2 ${isFormDisabled ? 'cursor-not-allowed' : 'hover:bg-gray-50 cursor-pointer'}`}>
                    <input
                      type="checkbox"
                      checked={selectedWSIIds.has(wsi.wsi_id)}
                      onChange={(e) => {
                        const newSet = new Set(selectedWSIIds)
                        if (e.target.checked) {
                          newSet.add(wsi.wsi_id)
                        } else {
                          newSet.delete(wsi.wsi_id)
                        }
                        setSelectedWSIIds(newSet)
                      }}
                      disabled={isFormDisabled}
                      className={`rounded border-gray-300 text-primary-600 focus:ring-primary-500 ${isFormDisabled ? 'cursor-not-allowed' : ''}`}
                    />
                    <span className={`text-sm truncate flex-1 ${isFormDisabled ? 'text-gray-500' : 'text-gray-700'}`}>{wsi.original_filename}</span>
                    {wsi.label && <span className="text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">{wsi.label}</span>}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Split Strategy Configuration */}
        {selectedDatasetId && datasetWSIs.length > 0 && (
          <div className={`border border-gray-100 rounded-lg p-4 bg-gray-50 ${isFormDisabled ? 'opacity-70' : ''}`}>
            <div className="flex items-center gap-2 mb-3">
              <Layers className="w-4 h-4 text-gray-500" />
              <span className="text-sm font-medium text-gray-700">Data Split Strategy</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {/* Random Split */}
              <button
                type="button"
                onClick={() => !isFormDisabled && setSplitStrategy('random')}
                disabled={isFormDisabled}
                className={`p-3 rounded-lg border text-left transition-all ${
                  splitStrategy === 'random'
                    ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                    : 'bg-white border-gray-200 hover:border-primary-300'
                } ${isFormDisabled ? 'cursor-not-allowed' : ''}`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <div className={`w-3 h-3 rounded-full border flex items-center justify-center ${
                    splitStrategy === 'random' ? 'border-primary-600' : 'border-gray-400'
                  }`}>
                    {splitStrategy === 'random' && <div className="w-1.5 h-1.5 rounded-full bg-primary-600" />}
                  </div>
                  <span className={`font-medium text-xs ${isFormDisabled ? 'text-gray-500' : 'text-gray-900'}`}>Random</span>
                </div>
                <p className="text-[10px] text-gray-500 ml-4.5">70/10/20 split</p>
              </button>

              {/* K-Fold */}
              <button
                type="button"
                onClick={() => !isFormDisabled && setSplitStrategy('k_fold')}
                disabled={isFormDisabled}
                className={`p-3 rounded-lg border text-left transition-all ${
                  splitStrategy === 'k_fold'
                    ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                    : 'bg-white border-gray-200 hover:border-primary-300'
                } ${isFormDisabled ? 'cursor-not-allowed' : ''}`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <div className={`w-3 h-3 rounded-full border flex items-center justify-center ${
                    splitStrategy === 'k_fold' ? 'border-primary-600' : 'border-gray-400'
                  }`}>
                    {splitStrategy === 'k_fold' && <div className="w-1.5 h-1.5 rounded-full bg-primary-600" />}
                  </div>
                  <span className={`font-medium text-xs ${isFormDisabled ? 'text-gray-500' : 'text-gray-900'}`}>K-Fold CV</span>
                </div>
                <p className="text-[10px] text-gray-500 ml-4.5">Cross-validation</p>
              </button>

              {/* Manual Split (CSV) */}
              <button
                type="button"
                onClick={() => !isFormDisabled && hasPreDefinedSplits && setSplitStrategy('manual')}
                disabled={isFormDisabled || !hasPreDefinedSplits}
                className={`p-3 rounded-lg border text-left transition-all ${
                  splitStrategy === 'manual'
                    ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500'
                    : hasPreDefinedSplits && !isFormDisabled
                    ? 'bg-white border-gray-200 hover:border-primary-300'
                    : 'bg-gray-100 border-gray-200 cursor-not-allowed opacity-60'
                }`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <div className={`w-3 h-3 rounded-full border flex items-center justify-center ${
                    splitStrategy === 'manual' ? 'border-primary-600' : 'border-gray-400'
                  }`}>
                    {splitStrategy === 'manual' && <div className="w-1.5 h-1.5 rounded-full bg-primary-600" />}
                  </div>
                  <span className={`font-medium text-xs ${isFormDisabled ? 'text-gray-500' : 'text-gray-900'}`}>Custom</span>
                </div>
                <p className="text-[10px] text-gray-500 ml-4.5">
                  {hasPreDefinedSplits ? 'From CSV' : 'No splits found'}
                </p>
              </button>
            </div>

            {/* Split Strategy Details */}
            <div className="mt-3">
              {splitStrategy === 'random' && (
                <div className="flex items-center gap-3 text-xs text-gray-600 bg-white p-2 rounded border border-gray-100">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span>Train: 70%</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span>Val: 10%</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500"></span>Test: 20%</span>
                </div>
              )}
              {splitStrategy === 'k_fold' && (
                <div className="flex items-center gap-2 bg-white p-2 rounded border border-gray-100">
                  <label className="text-xs text-gray-600">Folds (K):</label>
                  <input
                    type="number"
                    min={2}
                    max={10}
                    value={kFoldSplits}
                    onChange={(e) => setKFoldSplits(Math.max(2, Math.min(10, parseInt(e.target.value) || 5)))}
                    disabled={isFormDisabled}
                    className={`w-14 px-2 py-1 text-xs border border-gray-200 rounded focus:ring-1 focus:ring-primary-500 ${disabledInputClass}`}
                  />
                </div>
              )}
              {splitStrategy === 'manual' && hasPreDefinedSplits && (
                <div className="flex items-center gap-3 text-xs text-gray-600 bg-green-50 p-2 rounded border border-green-100">
                  <CheckCircle className="w-3.5 h-3.5 text-green-600" />
                  <span>Train: {predefinedSplitCounts.train}</span>
                  <span>Val: {predefinedSplitCounts.val}</span>
                  <span>Test: {predefinedSplitCounts.test}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Encoder & Model (Aggregator for WSI, Linear Probe for Patch) */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {config.data_level === 'patch' ? 'Feature Extractor' : 'Encoder'}
            </label>
            <select
              value={config.encoder || 'resnet50'}
              onChange={(e) => updateConfig('encoder', e.target.value)}
              disabled={isFormDisabled}
              className={`w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100 ${disabledSelectClass}`}
            >
              {FIELD_OPTIONS.encoder.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          {config.data_level === 'wsi' ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Aggregator</label>
              <select
                value={config.aggregator || 'abmil'}
                onChange={(e) => updateConfig('aggregator', e.target.value)}
                disabled={isFormDisabled}
                className={`w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100 ${disabledSelectClass}`}
              >
                {FIELD_OPTIONS.aggregator.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
              <div className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-gray-100 text-gray-500">
                Linear Probe
              </div>
              <p className="text-[10px] text-gray-400 mt-1">Frozen extractor + trainable linear layer</p>
            </div>
          )}
        </div>

        {/* Advanced Settings Toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className={`flex items-center gap-1 text-sm ${isFormDisabled ? 'text-gray-400' : 'text-gray-500 hover:text-gray-700'}`}
        >
          {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          Advanced Settings
        </button>

        {/* Advanced Settings */}
        {showAdvanced && (
          <div className="grid grid-cols-3 gap-4 pt-2 border-t border-gray-100">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Tile Size</label>
              <select
                value={config.tile_size || 512}
                onChange={(e) => updateConfig('tile_size', Number(e.target.value))}
                disabled={isFormDisabled}
                className={`w-full px-2 py-1.5 border border-gray-200 rounded text-sm ${disabledSelectClass}`}
              >
                {FIELD_OPTIONS.tile_size.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Learning Rate</label>
              <input
                type="number"
                step="0.0001"
                value={config.learning_rate || 0.0001}
                onChange={(e) => updateConfig('learning_rate', parseFloat(e.target.value))}
                disabled={isFormDisabled}
                className={`w-full px-2 py-1.5 border rounded text-sm ${
                  getFieldError('learning_rate') ? 'border-red-300' : 'border-gray-200'
                } ${disabledInputClass}`}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Epochs</label>
              <input
                type="number"
                value={config.epochs || 50}
                onChange={(e) => updateConfig('epochs', parseInt(e.target.value))}
                disabled={isFormDisabled}
                className={`w-full px-2 py-1.5 border rounded text-sm ${
                  getFieldError('epochs') ? 'border-red-300' : 'border-gray-200'
                } ${disabledInputClass}`}
              />
            </div>
          </div>
        )}
      </div>

      {/* Error Message */}
      {submitStatus === 'error' && errorMessage && (
        <div className="mx-5 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-700">Failed to create task</p>
            <p className="text-xs text-red-600 mt-0.5">{errorMessage}</p>
          </div>
        </div>
      )}

      {/* Success Message */}
      {submitStatus === 'success' && (
        <div className="mx-5 mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-green-500" />
          <p className="text-sm font-medium text-green-700">Task created successfully!</p>
        </div>
      )}

      {/* Submit Button */}
      <div className="px-5 py-4 bg-gray-50 border-t border-gray-100">
        <button
          onClick={handleSubmit}
          disabled={isSubmitting || submitStatus === 'success'}
          className="w-full py-2.5 bg-primary-600 text-white rounded-lg font-medium text-sm
                     hover:bg-primary-700 active:bg-primary-800
                     disabled:bg-gray-300 disabled:cursor-not-allowed
                     flex items-center justify-center gap-2 transition-colors"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating Task...
            </>
          ) : submitStatus === 'success' ? (
            <>
              <CheckCircle className="w-4 h-4" />
              Task Created
            </>
          ) : (
            <>
              <Play className="w-4 h-4" />
              Start Training
            </>
          )}
        </button>
      </div>
    </div>
  )
}
