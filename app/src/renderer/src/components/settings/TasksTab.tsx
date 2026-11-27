import { useState, useEffect, useCallback } from 'react'
import { useAsyncAction } from '../../lib/hooks/useAsyncAction'
import { useTranslation } from 'react-i18next'
import { Layers, RefreshCw, Minus, Plus, CheckCircle, Cpu, AlertCircle } from 'lucide-react'
import { Card } from '../ui/card'
import { Tooltip } from '../ui/tooltip'
import { getQueueStatus, updateQueueConfig, getQueueConfig } from '../../api/queue'
import type { QueueStatus } from '../../api/queue'
import { ShowConfirmDialog } from './ConfirmDialog'
import { useResearchText } from '../autoresearch/researchText'

export interface TasksTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export function TasksTab({ showConfirmDialog, closeConfirmDialog }: TasksTabProps) {
  const { t } = useTranslation()
  const { text } = useResearchText()
  const [researchLimit, setResearchLimit] = useState(2)
  const [researchSavedLimit, setResearchSavedLimit] = useState(2)
  const [savingResearchLimit, setSavingResearchLimit] = useState(false)
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null)
  const [maxConcurrent, setMaxConcurrent] = useState<number | null>(null)
  const [loadingQueue, setLoadingQueue] = useState(false)
  const [queueError, setQueueError] = useState<string | null>(null)
  const [taskTimeout, setTaskTimeout] = useState('259200')
  const [taskSaved, setTaskSaved] = useState(false)
  const [taskSaving, runTaskSaving] = useAsyncAction<void>()

  const loadQueueStatus = useCallback(async () => {
    setLoadingQueue(true); setQueueError(null)
    try { const status = await getQueueStatus(); setQueueStatus(status) }
    catch (err) { console.error('Failed to load queue status:', err); setQueueError(err instanceof Error ? err.message : t('settings.tasksTab.failedToLoadQueueStatus')) }
    finally { setLoadingQueue(false) }
  }, [t])

  const loadTaskConfig = useCallback(async () => {
    try {
      const config = await getQueueConfig()
      setTaskTimeout(String(config.task_timeout))
      setMaxConcurrent((current) => current ?? config.max_concurrent)
      setResearchLimit(config.max_autoresearch_concurrent)
      setResearchSavedLimit(config.max_autoresearch_concurrent)
    }
    catch (err) { console.error('Failed to load task config:', err) }
  }, [])

  // Load on mount + auto-refresh
  useEffect(() => { loadQueueStatus(); loadTaskConfig() }, [loadQueueStatus, loadTaskConfig])
  useEffect(() => {
    const interval = setInterval(loadQueueStatus, 15000)
    return () => clearInterval(interval)
  }, [loadQueueStatus])

  const handleUpdateMaxConcurrent = useCallback(async (newValue: number) => {
    try {
      const result = await updateQueueConfig({ max_concurrent: newValue })
      setMaxConcurrent(result.config.max_concurrent)
      const status = await getQueueStatus()
      setQueueStatus({
        ...status,
        max_concurrent: result.config.max_concurrent
      })
    }
    catch (err) { console.error('Failed to update queue config:', err); setQueueError(err instanceof Error ? err.message : t('settings.tasksTab.failedToUpdateQueueConfig')) }
  }, [t])

  const handleTaskSave = (e: React.FormEvent) => {
    e.preventDefault()
    void runTaskSaving(async () => {
      const timeout = parseInt(taskTimeout, 10)
      if (isNaN(timeout) || timeout < 60 || timeout > 259200) throw new Error(t('settings.tasksTab.timeoutRangeError'))
      await updateQueueConfig({ task_timeout: timeout })
      setTaskSaved(true); setTimeout(() => setTaskSaved(false), 3000)
    }).catch((err: unknown) => {
      console.error('Failed to save task config:', err)
      showConfirmDialog({ title: t('settings.tasksTab.error'), message: err instanceof Error ? err.message : t('settings.tasksTab.failedToSaveConfig'), confirmText: t('settings.tasksTab.ok'), confirmVariant: 'danger', showCancel: false, onConfirm: () => closeConfirmDialog() })
    })
  }
  const saveResearchLimit = async () => {
    if (savingResearchLimit || researchLimit === researchSavedLimit) return
    setSavingResearchLimit(true); setQueueError(null)
    try {
      const result = await updateQueueConfig({ max_autoresearch_concurrent: researchLimit })
      setResearchSavedLimit(result.config.max_autoresearch_concurrent)
      setResearchLimit(result.config.max_autoresearch_concurrent)
    } catch (err) { setQueueError(err instanceof Error ? err.message : text.saveFailed) }
    finally { setSavingResearchLimit(false) }
  }
  const isSingleGPU = queueStatus?.gpu_count === 1
  const displayedMaxConcurrent = maxConcurrent ?? queueStatus?.max_concurrent ?? 1
  const queueDiagnosis = queueStatus
    ? (() => {
        if (!queueStatus.is_running) {
          return {
            tone: 'red' as const,
            message: t('settings.tasksTab.diagnosisQueueStopped')
          }
        }
        if (queueStatus.pending_count === 0) {
          return {
            tone: 'blue' as const,
            message: t('settings.tasksTab.diagnosisNoPending')
          }
        }
        if (queueStatus.running_count >= queueStatus.max_concurrent) {
          return {
            tone: 'amber' as const,
            message: t('settings.tasksTab.diagnosisWaitingForSlot', {
              running: queueStatus.running_count,
              max: queueStatus.max_concurrent
            })
          }
        }
        if (queueStatus.vram_available === false) {
          return {
            tone: 'amber' as const,
            message: t('settings.tasksTab.diagnosisWaitingForVram', {
              details: queueStatus.vram_status || t('settings.tasksTab.vramStatusUnknown')
            })
          }
        }
        return {
          tone: 'green' as const,
          message: t('settings.tasksTab.diagnosisAutoStart')
        }
      })()
    : null
  const diagnosisClasses = queueDiagnosis?.tone === 'red'
    ? 'bg-red-50 border-red-200 text-red-800'
    : queueDiagnosis?.tone === 'amber'
      ? 'bg-amber-50 border-amber-200 text-amber-800'
      : queueDiagnosis?.tone === 'green'
        ? 'bg-green-50 border-green-200 text-green-800'
        : 'bg-blue-50 border-blue-200 text-blue-800'

  return (
    <div className="space-y-6">
      <Card className="p-4 sm:p-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
            <Layers className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
            <span className="break-words">{t('settings.tasksTab.title')}</span>
          </h2>
          <div className="flex items-center gap-3 self-end sm:self-auto">
            {queueStatus && (
              <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-50 rounded-md">
                <Cpu className="w-4 h-4 text-blue-600" />
                <span className="text-sm font-medium text-blue-700">
                  {t('settings.tasksTab.gpuCount', { count: queueStatus.gpu_count })}
                </span>
              </div>
            )}
            <Tooltip content={t('settings.tasksTab.refreshQueueStatus')}>
              <button
                type="button"
                onClick={loadQueueStatus}
                disabled={loadingQueue}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loadingQueue ? 'animate-spin' : ''}`} />
              </button>
            </Tooltip>
          </div>
        </div>

        {queueError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {queueError}
          </div>
        )}

        {queueStatus ? (
          <div className="space-y-6">
            {/* Compact Status Bar */}
            <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-8 items-center">
                {/* Left Column: Queue State + Running Tasks */}
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 w-full">
                  <div className="flex items-center gap-3 min-w-fit flex-shrink-0 justify-between sm:justify-start">
                    <div className="flex items-center gap-3">
                      <div className={`w-3 h-3 rounded-full flex-shrink-0 ${queueStatus.is_running ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`} />
                      <span className="text-sm font-bold text-gray-700 whitespace-nowrap">
                        {queueStatus.is_running ? t('settings.tasksTab.queueActive') : t('settings.tasksTab.queueStopped')}
                      </span>
                    </div>
                  </div>
                  <div className="hidden sm:block w-px h-6 bg-gray-300 mx-1" />
                  <div className="flex-1 flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm min-w-0">
                    <span className="text-sm font-medium text-gray-500 truncate mr-2">{t('settings.tasksTab.runningTasks')}</span>
                    <span className="text-base font-bold text-gray-900">{queueStatus.running_count}</span>
                  </div>
                </div>
                {/* Right Column: Pending Tasks */}
                <div className="w-full">
                  <div className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm w-full">
                    <span className="text-sm font-medium text-gray-500 truncate">{t('settings.tasksTab.pendingTasks')}</span>
                    <span className="text-base font-bold text-gray-900">{queueStatus.pending_count}</span>
                  </div>
                </div>
              </div>
            </div>

            {queueDiagnosis && (
              <div className={`p-4 rounded-xl border ${diagnosisClasses}`}>
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div className="space-y-1">
                    <p className="text-sm font-semibold">{t('settings.tasksTab.diagnosisTitle')}</p>
                    <p className="text-sm leading-6">{queueDiagnosis.message}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Settings Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
              {/* Max Concurrent */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('settings.tasksTab.maxConcurrentTasks')}
                </label>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center w-full">
                    <div className={`flex items-center bg-white border border-gray-300 rounded-lg overflow-hidden shadow-sm transition-colors w-full ${isSingleGPU ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary-400'}`}>
                      <Tooltip content={isSingleGPU ? t('settings.tasksTab.disabledSingleGPU') : t('settings.tasksTab.decrease')}>
                        <button
                          type="button"
                          onClick={() => handleUpdateMaxConcurrent(Math.max(1, displayedMaxConcurrent - 1))}
                          disabled={isSingleGPU}
                          className={`p-2.5 text-gray-600 transition-colors border-r border-gray-200 flex-shrink-0 ${isSingleGPU ? 'cursor-not-allowed' : 'hover:bg-gray-50 active:bg-gray-100'}`}
                        >
                          <Minus className="w-4 h-4" />
                        </button>
                      </Tooltip>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={displayedMaxConcurrent}
                        disabled={isSingleGPU}
                        onChange={(e) => {
                          const val = parseInt(e.target.value);
                          if (!isNaN(val)) {
                            handleUpdateMaxConcurrent(Math.min(10, Math.max(1, val)));
                          }
                        }}
                        className={`flex-1 py-1.5 text-center font-bold text-gray-900 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none bg-transparent text-sm ${isSingleGPU ? 'cursor-not-allowed' : ''}`}
                      />
                      <Tooltip content={isSingleGPU ? t('settings.tasksTab.disabledSingleGPU') : t('settings.tasksTab.increase')}>
                        <button
                          type="button"
                          onClick={() => handleUpdateMaxConcurrent(Math.min(10, displayedMaxConcurrent + 1))}
                          disabled={isSingleGPU}
                          className={`p-2.5 text-gray-600 transition-colors border-l border-gray-200 flex-shrink-0 ${isSingleGPU ? 'cursor-not-allowed' : 'hover:bg-gray-50 active:bg-gray-100'}`}
                        >
                          <Plus className="w-4 h-4" />
                        </button>
                      </Tooltip>
                    </div>
                  </div>
                  {isSingleGPU ? (
                    <p className="text-xs text-amber-600 leading-tight">
                      {t('settings.tasksTab.singleGPUNotice')}
                    </p>
                  ) : (
                    <p className="text-xs text-gray-500 leading-tight">
                      {t('settings.tasksTab.concurrencyDescription')}
                    </p>
                  )}
                </div>
              </div>

              {/* Timeout */}
              <div>
                <form onSubmit={handleTaskSave} className="flex flex-col gap-2 h-full justify-between">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      {t('settings.tasksTab.taskTimeout')}
                    </label>
                    <div className="flex items-center gap-0 w-full rounded-lg shadow-sm overflow-hidden border border-gray-300 focus-within:ring-2 focus-within:ring-primary-500 focus-within:border-transparent transition-all">
                      <input
                        type="number"
                        value={taskTimeout}
                        onChange={(e) => setTaskTimeout(e.target.value)}
                        min="60"
                        max="259200"
                        className="flex-1 px-3 py-2 border-none focus:ring-0 text-sm font-medium"
                        placeholder="86400"
                      />
                      <button
                        type="submit"
                        disabled={taskSaving}
                        className={`flex-shrink-0 px-4 py-2 text-sm font-bold text-white transition-all active:scale-95 border-l border-gray-300 ${taskSaved
                          ? 'bg-green-600 hover:bg-green-700'
                          : taskSaving
                            ? 'bg-gray-400 cursor-not-allowed'
                            : 'bg-primary-600 hover:bg-primary-700'
                          } focus:outline-none`}
                      >
                        {taskSaved ? (
                          <span className="flex items-center">
                            <CheckCircle className="w-3.5 h-3.5 mr-1.5" />
                            {t('settings.tasksTab.saved')}
                          </span>
                        ) : taskSaving ? t('settings.tasksTab.saving') : t('settings.tasksTab.save')}
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 italic">
                    {t('settings.tasksTab.timeoutDescription')}
                  </p>
                </form>
              </div>
            </div>

            <section className="border-t border-gray-200 pt-6" aria-label={text.concurrencyTitle}>
              <div className="flex items-start justify-between gap-4"><div><label htmlFor="research-concurrency" className="text-sm font-medium text-gray-700">{text.concurrencyTitle}</label><p className="mt-1 max-w-2xl text-xs leading-5 text-gray-500">{text.concurrencyHint}</p></div><output htmlFor="research-concurrency" className="rounded-lg border border-gray-300 bg-white px-3 py-1 font-mono text-lg font-semibold text-gray-900 shadow-sm">{researchLimit}</output></div>
              <input id="research-concurrency" type="range" min={1} max={10} step={1} value={researchLimit} disabled={savingResearchLimit} onChange={e => setResearchLimit(Number(e.target.value))} className="mt-5 w-full cursor-pointer accent-gray-700" />
              <div className="mt-1 flex justify-between text-xs text-gray-500"><span>1</span><span>10</span></div>
              <div className="mt-3 flex items-center justify-between gap-3"><p className="text-xs text-gray-500">{text.concurrencyApply}</p><button type="button" onClick={() => void saveResearchLimit()} disabled={savingResearchLimit || researchLimit === researchSavedLimit} className="shrink-0 rounded-lg border border-gray-300 bg-white px-4 py-2 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-40">{savingResearchLimit ? text.saving : text.save}</button></div>
            </section>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-4 h-4 mt-0.5 text-slate-600 flex-shrink-0" />
                <div className="space-y-2 text-sm text-slate-700">
                  <p className="font-semibold text-slate-900">{t('settings.tasksTab.whyQueuedTitle')}</p>
                  <p>{t('settings.tasksTab.whyQueuedIntro')}</p>
                  <ul className="list-disc pl-5 space-y-1.5">
                    <li>{t('settings.tasksTab.reasonConcurrency')}</li>
                    <li>{t('settings.tasksTab.reasonGpuVram')}</li>
                    <li>{t('settings.tasksTab.reasonSharedQueue')}</li>
                    <li>{t('settings.tasksTab.reasonCancellation')}</li>
                    <li>{t('settings.tasksTab.reasonRecovery')}</li>
                  </ul>
                </div>
              </div>
            </div>

            {/* Task List (if active) */}
            {(queueStatus.running_tasks?.length > 0 || queueStatus.pending_task_ids.length > 0) && (
              <div className="pt-4 border-t border-gray-100 space-y-3">
                {queueStatus.running_tasks?.length > 0 && (
                  <div className="flex items-start gap-3">
                    <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">{t('settings.tasksTab.running')}</span>
                    <div className="flex flex-wrap gap-2">
                      {queueStatus.running_tasks.map((task) => (
                        <span key={task.task_id} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-100">
                          {task.task_id.length > 8 ? `${task.task_id.slice(0, 8)}...` : task.task_id}
                          {task.gpu !== null && (
                            <span className="ml-1 px-1 bg-blue-100 text-blue-700 rounded text-[9px]">
                              GPU{task.gpu}
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {queueStatus.pending_task_ids.length > 0 && (
                  <div className="flex items-start gap-3">
                    <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">{t('settings.tasksTab.pending')}</span>
                    <div className="flex flex-wrap gap-2">
                      {queueStatus.pending_task_ids.map((taskId) => (
                        <span key={taskId} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-100">
                          {taskId.length > 8 ? `${taskId.slice(0, 8)}...` : taskId}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : loadingQueue ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin text-primary-500 opacity-50" />
          </div>
        ) : (
          <div className="text-center py-12 bg-gray-50 rounded-xl border border-dashed border-gray-200 text-gray-500">
            {t('settings.tasksTab.unableToLoadQueue')}
          </div>
        )}
      </Card>
    </div>
  )
}
