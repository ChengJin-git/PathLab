/**
 * ReviewSubmitStep Component
 *
 * Step 5: Review configuration and submit training task.
 */

import React from 'react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { CheckSquare, Settings, AlignLeft, Layers, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react'
import { DataLevel, TaskType, TrainingStatus, ConfigurationValidation } from '../../types/training'
import { AGGREGATORS } from '../../constants/training'

export interface ExtractorInfo {
  id: string
  name: string
  description: string
}

export interface ReviewSubmitStepProps {
  // Task info
  taskName: string
  taskType: TaskType
  taskDescription: string
  dataLevel: DataLevel
  selectedCount: number

  // Configuration
  tileSize: number
  stride: number
  pyramidLevel: number
  segUseOtsu: boolean
  aggregator: string
  featureExtractor: string
  availableExtractors: ExtractorInfo[]
  learningRate: number
  epochs: number
  trainBatchSize: number
  optimizer: string
  earlyStoppingPatience: number
  autoBalance: boolean

  // Validation
  validateConfiguration: ConfigurationValidation

  // Status
  trainingStatus: TrainingStatus
  submitError: string

  // Actions
  canProceed: boolean
  onBack: () => void
  onSubmit: () => void
  onClearError: () => void

  // Helpers
  parseErrorMessage: (error: string) => string
  getErrorSuggestion: (error: string) => string | null
}

export function ReviewSubmitStep({
  taskName,
  taskType,
  taskDescription,
  dataLevel,
  selectedCount,
  tileSize,
  stride,
  pyramidLevel,
  segUseOtsu,
  aggregator,
  featureExtractor,
  availableExtractors,
  learningRate,
  epochs,
  trainBatchSize,
  optimizer,
  earlyStoppingPatience,
  autoBalance,
  validateConfiguration,
  trainingStatus,
  submitError,
  canProceed,
  onBack,
  onSubmit,
  onClearError,
  parseErrorMessage,
  getErrorSuggestion,
}: ReviewSubmitStepProps) {
  return (
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
                <span className="text-xs sm:text-sm text-gray-900 truncate block capitalize">{taskType.replace('_', ' ')}</span>
              </div>
              <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Samples</span>
                <div className="flex items-center gap-1">
                  <span className="text-xs sm:text-sm text-gray-900">{selectedCount}</span>
                  <span className="text-[10px] sm:text-xs text-gray-400 lowercase">{dataLevel === 'wsi' ? 'Slides' : 'Images'}</span>
                </div>
              </div>
              <div className="p-2 sm:p-3 bg-gray-50/50 border border-gray-100 rounded-xl">
                <span className="text-[9px] sm:text-xs text-gray-400 block mb-0.5 uppercase tracking-wider">Epochs</span>
                <span className="text-xs sm:text-sm text-gray-900 font-mono">{epochs}</span>
              </div>
            </div>

            <div className="pt-3 sm:pt-4 border-t border-gray-100">
              <div className="flex items-center gap-2 mb-2">
                <AlignLeft className="w-4 h-4 text-gray-400" />
                <h4 className="text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">Description</h4>
              </div>
              <div className="p-3 bg-gray-50/50 rounded-xl border border-gray-100">
                <p className="text-[11px] sm:text-sm text-gray-600 leading-relaxed line-clamp-2">{taskDescription || 'No description provided.'}</p>
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
                    {dataLevel === 'wsi' ? AGGREGATORS.find((a) => a.id === aggregator)?.name : availableExtractors.find((e) => e.id === featureExtractor)?.name}
                  </div>
                  {dataLevel === 'wsi' && (
                    <div className="mt-1 text-[10px] sm:text-xs flex items-center gap-1.5 text-gray-500">
                      <span className="text-gray-400">Features:</span>
                      <span className="font-bold text-gray-700 truncate">{availableExtractors.find((e) => e.id === featureExtractor)?.name}</span>
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
                      <div className="text-[10px] text-gray-400">{stride > 0 ? `${stride}px Stride` : '0px Overlap'}</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-center pt-3">
                    <span className="text-gray-400 font-bold uppercase tracking-tight">Tissue Seg</span>
                    <div className="text-right">
                      <div className="font-bold text-gray-900">{segUseOtsu ? 'Otsu' : 'Threshold'}</div>
                      <div className="text-[10px] text-gray-400">Level {pyramidLevel}</div>
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
                  <button onClick={onClearError} className="mt-2 text-[10px] font-bold text-red-800 hover:text-red-900 underline underline-offset-2">
                    Review and retry
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-3 mt-6 sm:mt-8 pt-6 border-t border-gray-100">
        <Button variant="outline" onClick={onBack} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1">
          ← Edit Parameters
        </Button>
        <Button
          onClick={onSubmit}
          disabled={!canProceed || trainingStatus === 'submitting' || trainingStatus === 'validating'}
          className="w-full sm:w-auto px-10 py-2 sm:py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/20 font-bold text-xs sm:text-sm order-1 sm:order-2"
        >
          {trainingStatus === 'submitting' || trainingStatus === 'validating' ? 'Processing...' : 'Launch Training →'}
        </Button>
      </div>
    </>
  )
}

