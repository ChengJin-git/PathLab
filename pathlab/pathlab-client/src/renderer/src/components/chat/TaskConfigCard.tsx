import { useState, useEffect } from 'react'
import { Play, AlertCircle, CheckCircle, Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import { createTrainingTask, fetchWSIList, type TrainingTaskConfig, type WSISummary } from '../../api'

// Simplified config from Agent (doesn't include wsi_ids, etc.)
export interface AgentTaskConfig {
  task_name: string
  task_type: 'classification' | 'survival_prediction'
  data_level: 'wsi' | 'patch'
  tile_size?: number
  encoder?: string
  aggregator?: string
  learning_rate?: number
  epochs?: number
  batch_size?: number
  optimizer?: string
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
    { value: 'resnet50', label: 'ResNet50 (fast)' },
    { value: 'uni', label: 'UNI (best quality)' },
    { value: 'ctranspath', label: 'CTransPath' },
    { value: 'vit_l_16', label: 'ViT-Large' }
  ],
  aggregator: [
    { value: 'abmil', label: 'ABMIL (recommended)' },
    { value: 'meanmil', label: 'MeanMIL' },
    { value: 'maxmil', label: 'MaxMIL' }
  ],
  optimizer: [
    { value: 'adam', label: 'Adam' },
    { value: 'sgd', label: 'SGD' }
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
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [selectedWSIs, setSelectedWSIs] = useState<string[]>([])
  const [availableWSIs, setAvailableWSIs] = useState<WSISummary[]>([])
  const [isLoadingWSIs, setIsLoadingWSIs] = useState(false)

  // Load available WSIs
  useEffect(() => {
    loadWSIs()
  }, [])

  const loadWSIs = async () => {
    setIsLoadingWSIs(true)
    try {
      const result = await fetchWSIList()
      setAvailableWSIs(result.items)
    } catch (error) {
      console.error('Failed to load WSIs:', error)
    } finally {
      setIsLoadingWSIs(false)
    }
  }

  const updateConfig = (field: keyof AgentTaskConfig, value: any) => {
    const newConfig = { ...config, [field]: value }
    setConfig(newConfig)
    onConfigChange?.(newConfig)
    // Clear validation error for this field
    setValidationErrors(prev => prev.filter(e => e.field !== field))
  }

  const validate = (): boolean => {
    const errors: ValidationError[] = []
    if (!config.task_name?.trim()) {
      errors.push({ field: 'task_name', message: 'Task name is required' })
    }
    if (selectedWSIs.length === 0) {
      errors.push({ field: 'wsi_ids', message: 'Please select at least one slide' })
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
      // Build full TrainingTaskConfig
      const fullConfig: TrainingTaskConfig = {
        task_name: config.task_name,
        task_type: config.task_type as 'classification' | 'survival_prediction' | 'segmentation',
        data_level: config.data_level,
        task_description: `Created by PathLab Agent`,
        wsi_ids: selectedWSIs,
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
          early_stopping_patience: 10
        }
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

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-primary-50 to-blue-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <Play className="w-4 h-4 text-primary-600" />
          Training Configuration
        </h3>
        <p className="text-sm text-gray-500 mt-1">Review and edit settings, then start training</p>
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
            className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-primary-100 focus:border-primary-400 ${
              getFieldError('task_name') ? 'border-red-300 bg-red-50' : 'border-gray-200'
            }`}
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
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
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
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
            >
              {FIELD_OPTIONS.data_level.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* WSI Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Select Slides ({selectedWSIs.length} selected)
          </label>
          {isLoadingWSIs ? (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading slides...
            </div>
          ) : availableWSIs.length === 0 ? (
            <p className="text-sm text-amber-600 py-2">No slides available. Please upload slides first.</p>
          ) : (
            <div className={`border rounded-lg max-h-32 overflow-y-auto ${
              getFieldError('wsi_ids') ? 'border-red-300 bg-red-50' : 'border-gray-200'
            }`}>
              {availableWSIs.map(wsi => (
                <label key={wsi.wsi_id} className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedWSIs.includes(wsi.wsi_id)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedWSIs(prev => [...prev, wsi.wsi_id])
                      } else {
                        setSelectedWSIs(prev => prev.filter(id => id !== wsi.wsi_id))
                      }
                      setValidationErrors(prev => prev.filter(err => err.field !== 'wsi_ids'))
                    }}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  <span className="text-sm text-gray-700 truncate">{wsi.original_filename}</span>
                </label>
              ))}
            </div>
          )}
          {getFieldError('wsi_ids') && (
            <p className="text-xs text-red-500 mt-1">{getFieldError('wsi_ids')}</p>
          )}
        </div>

        {/* Encoder & Aggregator */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Encoder</label>
            <select
              value={config.encoder || 'resnet50'}
              onChange={(e) => updateConfig('encoder', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
            >
              {FIELD_OPTIONS.encoder.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          {config.data_level === 'wsi' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Aggregator</label>
              <select
                value={config.aggregator || 'abmil'}
                onChange={(e) => updateConfig('aggregator', e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-primary-100"
              >
                {FIELD_OPTIONS.aggregator.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Advanced Settings Toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
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
                className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm"
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
                className={`w-full px-2 py-1.5 border rounded text-sm ${
                  getFieldError('learning_rate') ? 'border-red-300' : 'border-gray-200'
                }`}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Epochs</label>
              <input
                type="number"
                value={config.epochs || 50}
                onChange={(e) => updateConfig('epochs', parseInt(e.target.value))}
                className={`w-full px-2 py-1.5 border rounded text-sm ${
                  getFieldError('epochs') ? 'border-red-300' : 'border-gray-200'
                }`}
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
