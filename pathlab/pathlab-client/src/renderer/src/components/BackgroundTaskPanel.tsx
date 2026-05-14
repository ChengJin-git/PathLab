/**
 * Background Task Panel Component
 *
 * A floating panel that displays background task progress.
 * Shows in bottom-left corner with minimize/expand functionality.
 * Displays both local tasks (upload/delete) and server tasks (training).
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { TFunction } from 'i18next'
import { useNavigate } from 'react-router-dom'
import { useBackgroundTask, BackgroundTask, TaskItem, TaskStatus } from '../contexts/BackgroundTaskContext'
import { cn } from '../lib/utils'
import { Tooltip } from './ui/tooltip'
import {
  TRAINING_STATUS_LABELS,
  VALIDATION_STATUS_LABELS,
  ANALYSIS_STATUS_LABELS
} from '../constants/status'

const StatusIcon: React.FC<{ status: TaskStatus; className?: string }> = ({ status, className }) => {
  switch (status) {
    case 'pending':
      return (
        <svg className={cn("w-4 h-4 text-gray-400", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="12" r="10" strokeWidth="2" />
        </svg>
      )
    case 'running':
      return (
        <svg className={cn("w-4 h-4 text-blue-500 animate-spin", className)} fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )
    case 'success':
      return (
        <svg className={cn("w-4 h-4 text-green-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
        </svg>
      )
    case 'error':
      return (
        <svg className={cn("w-4 h-4 text-red-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      )
    case 'cancelled':
      return (
        <svg className={cn("w-4 h-4 text-gray-500", className)} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
        </svg>
      )
  }
}

const TaskItemRow: React.FC<{ item: TaskItem }> = ({ item }) => {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-2 py-1 text-xs">
      <StatusIcon status={item.status} className="flex-shrink-0" />
      <span className="flex-1 truncate text-gray-600" title={item.name}>{item.name}</span>
      {item.status === 'running' && (
        <span className="text-gray-400">{item.progress}%</span>
      )}
      {item.error && (
        <span className="text-red-500 truncate max-w-[100px]" title={item.error}>{t('backgroundTask.error')}</span>
      )}
    </div>
  )
}

const getTypeLabel = (task: BackgroundTask, t: TFunction): string => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isInAnalysisPhase = !!(task as any)._analysisTaskId

  switch (task.type) {
    case 'upload':
      return t('backgroundTask.typeLabels.upload')
    case 'delete_wsi':
      return t('backgroundTask.typeLabels.deleteFiles')
    case 'delete_task':
      return t('backgroundTask.typeLabels.deleteTasks')
    case 'training':
      if (task.serverTaskStatus) {
        return t(`backgroundTask.serverStatus.training.${task.serverTaskStatus}`, { defaultValue: TRAINING_STATUS_LABELS[task.serverTaskStatus] || task.serverTaskStatus })
      }
      return t('backgroundTask.typeLabels.training')
    case 'external_validation':
      if (isInAnalysisPhase) {
        return t('backgroundTask.typeLabels.analyzingResults')
      }
      if (task.serverTaskStatus) {
        return t(`backgroundTask.serverStatus.validation.${task.serverTaskStatus}`, { defaultValue: VALIDATION_STATUS_LABELS[task.serverTaskStatus] || task.serverTaskStatus })
      }
      return t('backgroundTask.typeLabels.externalValidation')
    case 'batch_inference':
      if (task.serverTaskStatus) {
        return t(`backgroundTask.serverStatus.batchInference.${task.serverTaskStatus}`, { defaultValue: VALIDATION_STATUS_LABELS[task.serverTaskStatus] || task.serverTaskStatus })
      }
      return t('backgroundTask.typeLabels.batchInference')
    case 'analysis': {
      const analysisTypeLabel = task.analysisType === 'external'
        ? t('backgroundTask.typeLabels.externalAnalysis')
        : t('backgroundTask.typeLabels.internalAnalysis')
      if (task.serverTaskStatus === 'completed') {
        return t('backgroundTask.serverStatus.training.completed', { defaultValue: ANALYSIS_STATUS_LABELS['completed'] || 'Completed' })
      }
      if (task.serverTaskStatus === 'cancelled') {
        return t('backgroundTask.serverStatus.training.cancelled', { defaultValue: ANALYSIS_STATUS_LABELS['cancelled'] || 'Cancelled' })
      }
      if (task.serverTaskStatus === 'failed') {
        return t('backgroundTask.serverStatus.training.failed', { defaultValue: ANALYSIS_STATUS_LABELS['failed'] || 'Failed' })
      }
      return analysisTypeLabel
    }
    case 'migration':
      return t('backgroundTask.typeLabels.storage')
    case 'batch_import':
      return t('backgroundTask.typeLabels.batchImport')
    case 'batch_update_metadata':
      return t('backgroundTask.typeLabels.metadataUpdate')
    case 'delete_dataset':
      return t('backgroundTask.typeLabels.deleteDataset')
    case 'cleanup_empty_datasets':
      return t('backgroundTask.typeLabels.cleanupEmptyDatasets')
    case 'unbind_dataset':
      return t('backgroundTask.typeLabels.unbindDataset')
    case 'reset_derived_data':
      return t('backgroundTask.typeLabels.resetDerivedData')
    case 'delete_external':
      return t('backgroundTask.typeLabels.deleteExternal')
    case 'extraction':
      return t('backgroundTask.typeLabels.extraction')
    default:
      return t('backgroundTask.typeLabels.task')
  }
}

function getNavigableTaskId(task: BackgroundTask): string | null {
  if (!task.isServerTask) return null
  if (task.type === 'training') return task.id.replace(/^training_/, '')
  if (task.type === 'external_validation') return task.id.replace(/^extval_/, '')
  if (task.type === 'batch_inference') return task.id.replace(/^batchinf_/, '')
  if (task.type === 'analysis') return task.trainingTaskId || null
  return null
}

const TaskCard: React.FC<{
  task: BackgroundTask;
  onCancel: () => void;
  onCancelServer: () => Promise<boolean>;
  onRemove: () => void;
  onNavigate?: () => void;
}> = ({
  task, onCancel, onCancelServer, onRemove, onNavigate
}) => {
    const { t } = useTranslation()
    const [isCancelling, setIsCancelling] = React.useState(false)
    const [expanded, setExpanded] = React.useState(task.status === 'running')
    const [showCancelConfirm, setShowCancelConfirm] = React.useState(false)
    const isServerTask = task.isServerTask === true
    const isTrainingTask = task.type === 'training'
    const isExternalValidationTask = task.type === 'external_validation'
    const isBatchInferenceTask = task.type === 'batch_inference'
    const isAnalysisTask = task.type === 'analysis'
    const isActiveTask = task.status === 'running' || task.status === 'pending'

    const typeLabel = getTypeLabel(task, t)

    const getProgressBarColor = () => {
      if (task.type === 'training' && task.serverTaskStatus) {
        switch (task.serverTaskStatus) {
          case 'extracting':
            return 'bg-orange-500'
          case 'training':
            return 'bg-purple-500'
          default:
            return 'bg-blue-500'
        }
      }
      return 'bg-blue-500'
    }

    return (
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
        <div
          className={cn(
            "flex gap-3 p-3 cursor-pointer hover:bg-gray-50",
            expanded ? "items-start" : "items-center"
          )}
          onClick={() => setExpanded(!expanded)}
        >
          <div className={cn(expanded ? "mt-1" : "flex-shrink-0")}>
            <StatusIcon status={task.status} />
          </div>
          <div className="flex-1 min-w-0">
            {expanded ? (
              <div className="flex flex-col gap-1 items-start w-full transition-all">
                <div className="flex items-center justify-between w-full">
                  <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                    {typeLabel}
                  </span>
                  <div className="flex items-center gap-3">
                    {task.successCount > 0 && (
                      <span className="text-green-600 font-bold text-xs flex items-center">
                        {task.successCount}
                        <svg className="w-2.5 h-2.5 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    )}
                    {task.skippedCount !== undefined && task.skippedCount > 0 && (
                      <span className="text-gray-500 font-bold text-xs flex items-center" title={t('backgroundTask.skipped')}>
                        {task.skippedCount}
                        <svg className="w-2.5 h-2.5 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M18 12H6" />
                        </svg>
                      </span>
                    )}
                    {task.failedCount > 0 && (
                      <span className="text-red-500 font-bold text-xs flex items-center">
                        {task.failedCount}
                        <svg className="w-2.5 h-2.5 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </span>
                    )}
                    {(task.status === 'running' || task.status === 'pending') && (
                      <span className="text-xs font-bold text-blue-600">
                        {task.totalProgress}%
                      </span>
                    )}
                  </div>
                </div>
                {task.type === 'migration' ? (
                  <div className="flex flex-col text-sm font-medium text-left w-full">
                    <span className="text-gray-500 text-xs">{t('backgroundTask.relocatingTo')}</span>
                    <span className="break-words text-gray-700 leading-tight">{task.title}</span>
                  </div>
                ) : (
                  <div className="text-sm font-semibold text-gray-900 break-words text-left leading-normal w-full">
                    {task.title}
                    {task.taskCategory && (
                      <span className="text-xs font-normal text-gray-400 ml-1">
                        ({t(`backgroundTask.taskCategory.${task.taskCategory}`, { defaultValue: task.taskCategory })})
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2 w-full min-w-0 h-5">
                <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider flex-shrink-0 leading-none">
                  {task.type === 'batch_import' ? t('backgroundTask.typeLabels.import') : 
                   task.type === 'batch_update_metadata' ? t('backgroundTask.typeLabels.metadata') : typeLabel}
                </span>
                <span className="text-sm font-medium text-gray-700 truncate flex-1 min-w-0 leading-none">
                  {task.taskCategory
                    ? `${task.title} (${t(`backgroundTask.taskCategory.${task.taskCategory}`, { defaultValue: task.taskCategory })})`
                    : task.title}
                </span>
                <div className="flex items-center gap-2 flex-shrink-0 leading-none">
                  {task.successCount > 0 && (
                    <span className="text-green-600 font-bold text-[11px] flex items-center leading-none">
                      {task.successCount}
                      <svg className="w-2.5 h-2.5 ml-0.25" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                      </svg>
                    </span>
                  )}
                  {task.skippedCount !== undefined && task.skippedCount > 0 && (
                    <span className="text-gray-500 font-bold text-[11px] flex items-center leading-none">
                      {task.skippedCount}
                      <svg className="w-2.5 h-2.5 ml-0.25" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M18 12H6" />
                      </svg>
                    </span>
                  )}
                  {task.failedCount > 0 && (
                    <span className="text-red-500 font-bold text-[11px] flex items-center leading-none">
                      {task.failedCount}
                      <svg className="w-2.5 h-2.5 ml-0.25" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </span>
                  )}
                  {(task.status === 'running' || task.status === 'pending') && (
                    <span className="text-xs font-bold text-blue-600 leading-none">
                      {task.totalProgress}%
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className={cn("flex flex-row items-center gap-1 h-5", expanded ? "self-start mt-0.5 h-auto" : "")}>
            {onNavigate && !showCancelConfirm && (
              <Tooltip content={t('backgroundTask.viewDetail')}>
                <button
                  onClick={(e) => { e.stopPropagation(); onNavigate() }}
                  className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-primary-600"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </button>
              </Tooltip>
            )}
            {isActiveTask && !showCancelConfirm && (
              <Tooltip content={t('backgroundTask.cancel')}>
                <button
                  onClick={async (e) => {
                    e.stopPropagation()
                    setShowCancelConfirm(true)
                  }}
                  disabled={isCancelling}
                  className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-red-600 disabled:opacity-50"
                >
                  {isCancelling ? (
                    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                </button>
              </Tooltip>
            )}

            {showCancelConfirm && (
              <div 
                className="flex items-center gap-1 animate-in slide-in-from-right-2 duration-200"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="text-[10px] uppercase font-bold text-gray-400 mr-1">{t('backgroundTask.confirm')}</div>
                <Tooltip content={t('backgroundTask.confirmStop')}>
                  <button
                    onClick={async () => {
                      setIsCancelling(true)
                      setShowCancelConfirm(false)
                      if (isServerTask) {
                        await onCancelServer()
                      } else {
                        onCancel()
                      }
                      setIsCancelling(false)
                    }}
                    className="h-5 w-5 flex items-center justify-center text-red-600 bg-red-50 hover:bg-red-100 rounded-md transition-all shadow-sm ring-1 ring-inset ring-red-100"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                    </svg>
                  </button>
                </Tooltip>
                <Tooltip content={t('backgroundTask.keepRunning')}>
                  <button
                    onClick={() => setShowCancelConfirm(false)}
                    className="h-5 w-5 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </Tooltip>
              </div>
            )}
            
            {!isActiveTask && (
              <Tooltip content={t('backgroundTask.close')}>
                <button
                  onClick={(e) => { e.stopPropagation(); onRemove() }}
                  className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-gray-700"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </Tooltip>
            )}
            <svg
              className={cn("w-3.5 h-3.5 text-gray-300 transition-transform", expanded && "rotate-180")}
              fill="none" viewBox="0 0 24 24" stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
        {expanded && (
          <div className="px-3 pb-3 border-t border-gray-100 flex flex-col gap-2">
            {(task.status === 'running' || task.status === 'pending') && (
              <div className="mt-2 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={cn("h-full transition-all duration-300", getProgressBarColor())}
                  style={{ width: `${task.totalProgress}%` }}
                />
              </div>
            )}
            {task.items.length > 0 && !(task.items.length === 1 && (task.items[0].name === task.title || isTrainingTask || isExternalValidationTask || isBatchInferenceTask || isAnalysisTask) && isServerTask) && task.type !== 'extraction' && (
              <div className="max-h-40 overflow-y-auto mt-1">
                {task.items.map(item => <TaskItemRow key={item.id} item={item} />)}
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

export function BackgroundTaskPanel(): React.ReactElement | null {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const {
    tasks,
    isProcessing,
    isPanelExpanded,
    togglePanel,
    cancelTask,
    cancelServerTask,
    removeTask,
    clearCompletedTasks,
    subscribeTrainingSSE,
    subscribeAnalysisSSE,
    subscribeStorageSSE
  } = useBackgroundTask()
  const panelRef = React.useRef<HTMLDivElement>(null)
  const isOpen = isPanelExpanded

  React.useEffect(() => {
    const unsubTraining = subscribeTrainingSSE()
    const unsubAnalysis = subscribeAnalysisSSE()
    const unsubStorage = subscribeStorageSSE()
    return () => {
      unsubTraining()
      unsubAnalysis()
      unsubStorage()
    }
  }, [subscribeTrainingSSE, subscribeAnalysisSSE, subscribeStorageSSE])

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (isOpen && panelRef.current && !panelRef.current.contains(event.target as Node)) {
        togglePanel()
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [isOpen, togglePanel])

  const activeCount = tasks.filter(t => t.status === 'running' || t.status === 'pending').length
  const runningCount = tasks.filter(t => t.status === 'running').length
  const pendingCount = tasks.filter(t => t.status === 'pending').length
  const finishedCount = tasks.filter(t => t.status === 'success' || t.status === 'error' || t.status === 'cancelled').length
  const successCount = tasks.filter(t => t.status === 'success').length
  const failedCount = tasks.filter(t => t.status === 'error').length
  const cancelledCount = tasks.filter(t => t.status === 'cancelled').length

  const getStatusSummary = () => {
    const parts: string[] = []
    if (runningCount > 0) parts.push(`${runningCount} ${t('backgroundTask.statusSummary.running')}`)
    if (pendingCount > 0) parts.push(`${pendingCount} ${t('backgroundTask.statusSummary.queued')}`)
    if (successCount > 0) parts.push(`${successCount} ${t('backgroundTask.statusSummary.completed')}`)
    if (failedCount > 0) parts.push(`${failedCount} ${t('backgroundTask.statusSummary.failed')}`)
    if (cancelledCount > 0) parts.push(`${cancelledCount} ${t('backgroundTask.statusSummary.cancelled')}`)
    
    if (parts.length === 0) return `${tasks.length} ${t('backgroundTask.statusSummary.tasksHistory')}`
    return parts.join(', ')
  }

  return (
    <div className="relative" ref={panelRef}>
      <Tooltip content={t('backgroundTask.title')}>
        <button
          onClick={togglePanel}
          className={cn(
            "p-2 rounded-lg transition-colors relative",
            isOpen ? "bg-gray-100 text-primary-600" : "text-gray-500 hover:text-primary-600 hover:bg-gray-100"
          )}
        >
          <svg className={cn("w-5 h-5", isProcessing && "animate-pulse")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>

          {activeCount > 0 && (
            <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-blue-500 rounded-full border-2 border-white"></span>
          )}
          {activeCount === 0 && finishedCount > 0 && (
            <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-gray-400 rounded-full border-2 border-white"></span>
          )}
        </button>
      </Tooltip>

      {isOpen && (
        <div className={cn(
          "bg-white rounded-xl shadow-xl border border-gray-200 z-50 overflow-hidden flex flex-col",
          "fixed top-16 left-2 right-2 mt-2 max-h-[75vh]",
          "sm:absolute sm:top-full sm:right-0 sm:left-auto sm:w-[450px] sm:max-h-[80vh] sm:mt-2 sm:mr-0"
        )}>
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
            <div>
              <h3 className="font-semibold text-gray-900">{t('backgroundTask.tasks')}</h3>
              <p className="text-xs text-gray-500">
                {getStatusSummary()}
              </p>
            </div>
            {!isProcessing && finishedCount > 0 && (
              <button
                onClick={clearCompletedTasks}
                className="text-xs text-blue-600 hover:text-blue-700 hover:underline px-2 py-1"
              >
                {t('backgroundTask.clearAll')}
              </button>
            )}
          </div>

          {tasks.length === 0 ? (
            <div className="p-8 text-center text-gray-500 flex flex-col items-center">
              <svg className="w-12 h-12 text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm">{t('backgroundTask.noActiveTasks')}</p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-2 space-y-2 bg-gray-50/50">
              {tasks.map(task => {
                const navigableId = getNavigableTaskId(task)
                return (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onCancel={() => cancelTask(task.id)}
                    onCancelServer={() => cancelServerTask(task)}
                    onRemove={() => removeTask(task)}
                    onNavigate={navigableId ? () => {
                      navigate(`/task/${navigableId}`)
                      if (isOpen) togglePanel()
                    } : undefined}
                  />
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
