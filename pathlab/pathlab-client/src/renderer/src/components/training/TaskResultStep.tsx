/**
 * TaskResultStep Component
 *
 * Step 6: Display task submission result and training progress.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { CheckCircle2, XCircle, Copy, Layers, AlertCircle, Loader2 } from 'lucide-react'
import { DataLevel, ExtractorOption, AGGREGATORS } from '../../constants/training'
import { TrainingTaskDetail } from '../../api'

export interface TaskResultStepProps {
  // Task info
  taskName: string
  dataLevel: DataLevel
  selectedCount: number
  epochs: number
  submittedTaskId: string

  // Model info
  aggregator: string
  featureExtractor: string
  availableExtractors: ExtractorOption[]

  // Polled task status
  polledTask: TrainingTaskDetail | null

  // Helpers
  getErrorSuggestion: (error: string) => string | null
}

export function TaskResultStep({
  taskName,
  dataLevel,
  selectedCount,
  epochs,
  submittedTaskId,
  aggregator,
  featureExtractor,
  availableExtractors,
  polledTask,
  getErrorSuggestion,
}: TaskResultStepProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const handleCopyTaskId = () => {
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
  }

  const getStatusColor = () => {
    switch (polledTask?.status) {
      case 'failed':
        return { ping: 'bg-red-400', dot: 'bg-red-500', text: 'text-red-500' }
      case 'cancelled':
        return { ping: 'bg-gray-400', dot: 'bg-gray-500', text: 'text-gray-500' }
      case 'completed':
        return { ping: 'bg-green-400', dot: 'bg-green-500', text: 'text-green-600' }
      case 'training':
        return { ping: 'bg-indigo-400', dot: 'bg-indigo-500', text: 'text-gray-400' }
      default:
        return { ping: 'bg-blue-400', dot: 'bg-blue-500', text: 'text-gray-400' }
    }
  }

  const statusColor = getStatusColor()

  return (
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
                <h2 className="text-lg sm:text-xl font-bold text-red-900 mb-1 sm:mb-2 tracking-tight">{t('training.taskResult.trainingFailed')}</h2>
                <p className="text-xs sm:text-sm text-red-600 mb-4 sm:mb-6 max-w-[280px] mx-auto leading-relaxed font-medium break-words overflow-hidden">
                  {polledTask?.error_message || t('training.taskResult.errorOccurred')}
                </p>
                {getErrorSuggestion(polledTask?.error_message || '') && (
                  <div className="w-full max-w-xs bg-red-50 border border-red-100 rounded-xl p-3 mb-4">
                    <p className="text-[10px] sm:text-xs text-red-700 font-medium">{getErrorSuggestion(polledTask?.error_message || '')}</p>
                  </div>
                )}
              </>
            ) : polledTask?.status === 'cancelled' ? (
              <>
                <div className="w-12 h-12 sm:w-16 sm:h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-gray-50 shadow-sm animate-in zoom-in duration-300">
                  <XCircle className="w-6 h-6 sm:w-8 sm:h-8 text-gray-500" />
                </div>
                <h2 className="text-lg sm:text-xl font-bold text-gray-700 mb-1 sm:mb-2 tracking-tight">{t('training.taskResult.trainingCancelled')}</h2>
                <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">{t('training.taskResult.taskCancelledDesc')}</p>
              </>
            ) : polledTask?.status === 'completed' ? (
              <>
                <div className="w-12 h-12 sm:w-16 sm:h-16 bg-green-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-green-50 shadow-sm animate-in zoom-in duration-300">
                  <CheckCircle2 className="w-6 h-6 sm:w-8 sm:h-8 text-green-600" />
                </div>
                <h2 className="text-lg sm:text-xl font-bold text-gray-900 mb-1 sm:mb-2 tracking-tight">{t('training.taskResult.trainingComplete')}</h2>
                <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">{t('training.taskResult.modelReady')}</p>
              </>
            ) : (
              <>
                <div className="w-12 h-12 sm:w-16 sm:h-16 bg-green-100 rounded-full flex items-center justify-center mb-4 sm:mb-5 ring-4 ring-green-50 shadow-sm animate-in zoom-in duration-300">
                  <CheckCircle2 className="w-6 h-6 sm:w-8 sm:h-8 text-green-600" />
                </div>
                <h2 className="text-lg sm:text-xl font-bold text-gray-900 mb-1 sm:mb-2 tracking-tight">{t('training.taskResult.submissionSuccessful')}</h2>
                <p className="text-xs sm:text-sm text-gray-400 mb-4 sm:mb-6 max-w-[200px] mx-auto leading-relaxed font-medium">{t('training.taskResult.taskQueued')}</p>
              </>
            )}

            {/* Task ID */}
            <div className="w-full max-w-xs bg-white p-1 sm:p-1.5 pl-3 pr-1.5 border border-gray-200 rounded-xl flex items-center justify-between shadow-sm mb-4 sm:mb-6">
              <div className="flex flex-col items-start overflow-hidden min-w-0">
                <span className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">{t('training.taskResult.taskId')}</span>
                <code className="text-[10px] sm:text-xs font-mono font-bold text-gray-900 truncate w-full text-left" title={submittedTaskId}>
                  {submittedTaskId}
                </code>
              </div>
              <Button variant="ghost" size="icon" className="flex-shrink-0 h-7 w-7 rounded-md hover:bg-gray-50" onClick={handleCopyTaskId}>
                <Copy className="w-3.5 h-3.5 text-gray-400" />
              </Button>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-col gap-2 w-full max-w-xs">
              <Button onClick={() => navigate('/task-list')} className="w-full bg-gray-900 hover:bg-black text-white h-9 sm:h-10 text-xs sm:text-sm font-bold shadow-md shadow-gray-200">
                {t('training.taskResult.goToTaskManager')}
              </Button>
              <Button
                variant="outline"
                onClick={() => window.location.reload()}
                className="w-full h-9 sm:h-10 text-xs sm:text-sm border-gray-200 text-gray-500 bg-white hover:bg-gray-50 font-bold"
              >
                {t('training.taskResult.createAnother')}
              </Button>
            </div>
          </div>

          {/* Right Column: Details & Pipeline Status */}
          <div className="lg:w-2/3 p-6 sm:p-8 flex flex-col justify-center bg-white relative">
            {/* Live Indicator */}
            <div className="hidden sm:flex absolute top-6 right-6 items-center gap-1.5">
              <span className="relative flex h-2.5 w-2.5">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${statusColor.ping}`}></span>
                <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${statusColor.dot}`}></span>
              </span>
              <span className={`text-[10px] font-bold uppercase tracking-wider ${statusColor.text}`}>{polledTask?.status || t('training.taskResult.queued')}</span>
            </div>

            {/* Task Summary */}
            <div className="mb-6 sm:mb-8">
              <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-4 border-b border-gray-50 pb-2">{t('training.taskResult.taskSummary')}</h3>
              <div className="grid grid-cols-2 gap-y-3 sm:gap-y-4 gap-x-4 sm:gap-x-6">
                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">{t('training.taskResult.project')}</div>
                  <div className="text-xs sm:text-sm font-bold text-gray-900 truncate pr-4" title={taskName}>
                    {taskName}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">{t('training.taskResult.volume')}</div>
                  <div className="text-xs sm:text-sm font-bold text-gray-900">
                    {selectedCount} <span className="text-[10px] sm:text-xs font-medium text-gray-400">{dataLevel === 'wsi' ? t('training.taskResult.slides') : t('training.taskResult.images')}</span>
                  </div>
                </div>
                <div className="col-span-1">
                  <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">{t('training.taskResult.model')}</div>
                  <div className="inline-flex items-center px-2 py-0.5 rounded-lg bg-indigo-50 text-indigo-700 text-[10px] sm:text-xs font-bold border border-indigo-100 truncate max-w-full">
                    {dataLevel === 'wsi' ? AGGREGATORS.find((a) => a.id === aggregator)?.name : availableExtractors.find((e) => e.id === featureExtractor)?.name}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-gray-400 mb-1 uppercase tracking-wider">{t('training.taskResult.config')}</div>
                  <div className="text-xs sm:text-sm font-bold text-gray-900">{t('training.taskResult.epochsCount', { count: epochs })}</div>
                </div>
              </div>
            </div>

            {/* Dynamic Pipeline Status */}
            <div className="bg-gray-50/50 rounded-2xl p-4 sm:p-5 border border-gray-100">
              <h3 className="text-[10px] font-bold text-gray-900 uppercase tracking-widest mb-4 flex items-center gap-2">
                <Layers className="w-3.5 h-3.5 text-primary-600" />
                {t('training.taskResult.pipelineStatus')}
              </h3>
              <div className="space-y-4">
                {/* Step 1: Preprocessing (WSI only) */}
                {dataLevel === 'wsi' && (
                  <PipelineStep
                    stepNumber={1}
                    title={t('training.taskResult.patching')}
                    description={t('training.taskResult.patchingDesc')}
                    isActive={['queued', 'patching'].includes(polledTask?.status || 'queued')}
                    isCompleted={!['queued', 'patching'].includes(polledTask?.status || 'queued') && polledTask?.status !== 'failed'}
                    isFailed={false}
                  />
                )}

                {/* Step 2: Feature Extraction (WSI only) */}
                {dataLevel === 'wsi' && (
                  <PipelineStep
                    stepNumber={2}
                    title={t('training.taskResult.featureExtraction')}
                    description={t('training.taskResult.featureExtractionDesc')}
                    isActive={polledTask?.status === 'feature_extraction'}
                    isCompleted={['training', 'completed'].includes(polledTask?.status || '')}
                    isFailed={false}
                  />
                )}

                {/* Step 3: Training */}
                <PipelineStep
                  stepNumber={dataLevel === 'patch' ? 2 : 3}
                  title={t('training.taskResult.modelTraining')}
                  description={t('training.taskResult.modelTrainingDesc')}
                  isActive={polledTask?.status === 'training'}
                  isCompleted={polledTask?.status === 'completed'}
                  isFailed={polledTask?.status === 'failed' && (polledTask?.progress ?? 0) >= 66}
                  progress={
                    polledTask?.status === 'training'
                      ? dataLevel === 'patch'
                        ? Math.max(0, Math.min(100, Math.round((((polledTask?.progress ?? 0) - 66) / (100 - 66)) * 100)))
                        : polledTask?.progress ?? 0
                      : undefined
                  }
                />
              </div>
            </div>

            {/* Error Details Panel - shown when task failed */}
            {polledTask?.status === 'failed' && polledTask?.error_message && (
              <div className="mt-4 bg-red-50 rounded-2xl p-4 sm:p-5 border border-red-100 overflow-hidden">
                <h3 className="text-[10px] font-bold text-red-900 uppercase tracking-widest mb-3 flex items-center gap-2">
                  <AlertCircle className="w-3.5 h-3.5 text-red-600" />
                  {t('training.taskResult.errorDetails')}
                </h3>
                <div className="bg-white rounded-xl p-3 border border-red-100 overflow-x-auto">
                  <p className="text-xs text-red-700 font-medium break-words whitespace-pre-wrap">{polledTask.error_message}</p>
                </div>
                {getErrorSuggestion(polledTask.error_message) && (
                  <div className="mt-3 flex items-start gap-2">
                    <span className="text-sm">💡</span>
                    <p className="text-[10px] sm:text-xs text-red-600 font-medium">{getErrorSuggestion(polledTask.error_message)}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  )
}

/** Helper component for pipeline step display */
interface PipelineStepProps {
  stepNumber: number
  title: string
  description: string
  isActive: boolean
  isCompleted: boolean
  isFailed: boolean
  progress?: number
}

function PipelineStep({ stepNumber, title, description, isActive, isCompleted, isFailed, progress }: PipelineStepProps) {
  const { t } = useTranslation()

  const getStepStyles = () => {
    if (isActive) return 'bg-primary-600 text-white ring-2 ring-primary-100'
    if (isCompleted) return 'bg-green-500 text-white'
    if (isFailed) return 'bg-red-500 text-white'
    return 'bg-gray-200 text-gray-400'
  }

  return (
    <div className={`flex items-start gap-4 transition-opacity duration-300 ${isActive || isFailed ? 'opacity-100' : 'opacity-50'}`}>
      <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shadow-sm transition-colors ${getStepStyles()}`}>
        {isCompleted ? <CheckCircle2 className="w-3 h-3" /> : isFailed ? <XCircle className="w-3 h-3" /> : stepNumber}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <div className="text-xs sm:text-sm font-bold text-gray-900">{title}</div>
          {isActive && (
            <div className="flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 text-primary-600 animate-spin" />
              {progress !== undefined && (
                <span className="text-[9px] font-bold text-primary-600 bg-primary-100 px-1 py-0.5 rounded">{progress.toFixed(1)}%</span>
              )}
            </div>
          )}
          {isFailed && <span className="text-[9px] font-bold text-red-600 bg-red-100 px-1.5 py-0.5 rounded">{t('training.taskResult.failed')}</span>}
        </div>
        <div className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate">{description}</div>
      </div>
    </div>
  )
}
