import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, CheckCircle2, Loader2, Microscope, Scissors, Sparkles } from 'lucide-react'
import { getChatPatchInferenceTask, startChatPatchInference, type ChatPatchInferenceTask, type ChatPatchInferenceType } from '../../api'

export interface PatchInferenceModel {
  model_id: string
  model_name: string
  task_id?: string
  classes?: string[]
}

export interface PatchInferenceRun {
  task_id: string
  model_id: string
  model_name: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress?: number
  result?: ChatPatchInferenceTask['result'] | null
  error?: string | null
}

export interface PatchInferenceConfig {
  version?: number
  summary?: string
  source?: string
  source_confidence?: 'low' | 'medium' | 'high'
  image_index?: number
  classification_models?: PatchInferenceModel[]
  segmentation_models?: PatchInferenceModel[]
  classification_run?: PatchInferenceRun
  segmentation_run?: PatchInferenceRun
}

interface PatchInferenceCardProps {
  config: PatchInferenceConfig
  conversationId?: string
  messageId: string
  referenceImages?: string[]
  onPersistConfig?: (config: PatchInferenceConfig) => void | Promise<void>
  onToast?: (toast: { type: 'error' | 'success' | 'info'; message: string }) => void
}

export function parsePatchInferenceConfig(content: string): PatchInferenceConfig | null {
  const match = content.match(/\[PATCH_INFERENCE\]([\s\S]*?)\[\/PATCH_INFERENCE\]/)
  if (!match) return null
  try { return JSON.parse(match[1].trim()) } catch { return null }
}

export function removePatchInferenceBlock(content: string): string {
  return content.replace(/\[PATCH_INFERENCE\][\s\S]*?\[\/PATCH_INFERENCE\]/g, '').trim()
}

const toRun = (task: ChatPatchInferenceTask): PatchInferenceRun => ({
  task_id: task.task_id,
  model_id: task.model_id,
  model_name: task.model_name,
  status: task.status,
  progress: task.progress,
  result: task.result,
  error: task.error,
})

export function PatchInferenceCard({ config, conversationId, messageId, referenceImages = [], onPersistConfig, onToast }: PatchInferenceCardProps) {
  const { t } = useTranslation()
  const [submittingType, setSubmittingType] = useState<ChatPatchInferenceType | null>(null)
  const [liveTasks, setLiveTasks] = useState<Record<string, ChatPatchInferenceTask>>({})
  const configRef = useRef(config)

  useEffect(() => { configRef.current = config }, [config])

  const selectedImage = useMemo(() => referenceImages[config.image_index ?? 0] ?? null, [referenceImages, config.image_index])

  useEffect(() => {
    const runs = [
      { type: 'classification' as const, run: config.classification_run },
      { type: 'segmentation' as const, run: config.segmentation_run },
    ].filter(({ run }) => run?.task_id)
    if (!runs.length) return

    let cancelled = false
    const poll = async () => {
      for (const { type, run } of runs) {
        if (!run?.task_id) continue
        try {
          const task = await getChatPatchInferenceTask(run.task_id)
          if (cancelled) return
          setLiveTasks(prev => ({ ...prev, [type]: task }))
          if ((task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') && onPersistConfig) {
            const current = configRef.current
            const currentRun = type === 'classification' ? current.classification_run : current.segmentation_run
            if (currentRun?.task_id === task.task_id && (currentRun.status !== task.status || currentRun.error !== task.error || !currentRun.result)) {
              await onPersistConfig({
                ...current,
                ...(type === 'classification' ? { classification_run: toRun(task) } : { segmentation_run: toRun(task) })
              })
            }
          }
        } catch {
          // Ignore transient polling errors.
        }
      }
    }

    void poll()
    const timer = window.setInterval(() => { void poll() }, 2500)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [config.classification_run?.task_id, config.segmentation_run?.task_id, onPersistConfig])

  const handleStart = async (type: ChatPatchInferenceType, model: PatchInferenceModel) => {
    if (!conversationId || !selectedImage) {
      onToast?.({ type: 'error', message: t('chatComponents.patchInference.missingImage') })
      return
    }
    const numericMessageId = Number(messageId)
    if (!Number.isFinite(numericMessageId)) {
      onToast?.({ type: 'error', message: t('chatComponents.patchInference.notReady') })
      return
    }

    try {
      setSubmittingType(type)
      const task = await startChatPatchInference({
        conversation_id: conversationId,
        message_id: numericMessageId,
        inference_type: type,
        model_id: model.model_id,
        image_data_url: selectedImage,
        source: config.source ?? null,
      })
      setLiveTasks(prev => ({ ...prev, [type]: task }))
      await onPersistConfig?.({
        ...configRef.current,
        ...(type === 'classification' ? { classification_run: toRun(task) } : { segmentation_run: toRun(task) })
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : t('chatComponents.patchInference.startFailed')
      onToast?.({ type: 'error', message })
    } finally {
      setSubmittingType(null)
    }
  }

  const renderSection = (type: ChatPatchInferenceType, models: PatchInferenceModel[] = [], run?: PatchInferenceRun) => {
    const liveTask = liveTasks[type]
    const effectiveRun = liveTask ? toRun(liveTask) : run
    const isBusy = submittingType === type || effectiveRun?.status === 'queued' || effectiveRun?.status === 'running'
    const statusLabel = effectiveRun ? t(`chatComponents.patchInference.status.${effectiveRun.status}`) : ''
    const title = type === 'classification' ? t('chatComponents.patchInference.classificationTitle') : t('chatComponents.patchInference.segmentationTitle')
    const icon = type === 'classification' ? <Microscope className="w-4 h-4" /> : <Scissors className="w-4 h-4" />

    return (
      <div className="rounded-xl border border-gray-200 bg-white/80 p-3 space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-800">{icon}{title}</div>
        {effectiveRun ? (
          <div className="space-y-2 text-sm text-gray-700">
            <div className="flex items-center justify-between gap-3">
              <span className="truncate">{effectiveRun.model_name}</span>
              <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">{statusLabel}</span>
            </div>
            {isBusy && <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden"><div className="h-full bg-blue-500" style={{ width: `${effectiveRun.progress ?? 15}%` }} /></div>}
            {effectiveRun.status === 'completed' && type === 'classification' && effectiveRun.result?.predicted_label && (
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-green-700"><CheckCircle2 className="w-4 h-4" />{effectiveRun.result.predicted_label}</div>
                <div className="space-y-1 text-xs text-gray-600">
                  {(effectiveRun.result.top_predictions ?? []).map(item => <div key={item.label} className="flex justify-between"><span>{item.label}</span><span>{(item.score * 100).toFixed(1)}%</span></div>)}
                </div>
              </div>
            )}
            {effectiveRun.status === 'completed' && type === 'segmentation' && (
              <div className="space-y-1 text-xs text-gray-600">
                {(effectiveRun.result?.coverage_by_class ?? []).map(item => <div key={item.label} className="flex justify-between"><span>{item.label}</span><span>{(item.coverage_ratio * 100).toFixed(1)}%</span></div>)}
                {!effectiveRun.result?.coverage_by_class?.length && <div>{t('chatComponents.patchInference.noSegmentationMask')}</div>}
              </div>
            )}
            {(effectiveRun.status === 'failed' || effectiveRun.status === 'cancelled') && (
              <div className="flex items-start gap-2 text-red-700 text-xs"><AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />{effectiveRun.error || t('chatComponents.patchInference.failed')}</div>
            )}
          </div>
        ) : models.length > 0 ? (
          <div className="space-y-2">
            {models.map(model => (
              <button
                key={model.model_id}
                onClick={() => void handleStart(type, model)}
                disabled={Boolean(submittingType) || !selectedImage}
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-left hover:border-blue-300 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div className="font-medium text-sm text-gray-800">{model.model_name}</div>
                {!!model.classes?.length && <div className="text-xs text-gray-500 truncate">{model.classes.join(', ')}</div>}
              </button>
            ))}
          </div>
        ) : (
          <div className="text-xs text-gray-500">{t('chatComponents.patchInference.noModel')}</div>
        )}
      </div>
    )
  }

  const visibleSections = ([
    { type: 'classification' as const, models: config.classification_models ?? [], run: config.classification_run },
    { type: 'segmentation' as const, models: config.segmentation_models ?? [], run: config.segmentation_run },
  ]).filter(({ models, run }) => Boolean(run?.task_id || models.length > 0))

  return (
    <div className="mt-4 rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white p-4 shadow-sm space-y-4">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl bg-blue-100 text-blue-700"><Sparkles className="w-4 h-4" /></div>
        <div className="min-w-0">
          <div className="font-semibold text-gray-900">{t('chatComponents.patchInference.title')}</div>
          <div className="text-sm text-gray-600">{config.summary || t('chatComponents.patchInference.summaryFallback')}</div>
          {config.source && <div className="text-xs text-gray-500 mt-1">{t('chatComponents.patchInference.source')}: {config.source}</div>}
        </div>
      </div>

      {!selectedImage && !config.classification_run?.task_id && !config.segmentation_run?.task_id && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          {t('chatComponents.patchInference.missingImage')}
        </div>
      )}

      {(submittingType === 'classification' || submittingType === 'segmentation') && (
        <div className="flex items-center gap-2 text-sm text-blue-700"><Loader2 className="w-4 h-4 animate-spin" />{t('chatComponents.patchInference.submitting')}</div>
      )}

      {visibleSections.length > 0 ? (
        <div className={`grid gap-3 ${visibleSections.length > 1 ? 'md:grid-cols-2' : ''}`}>
          {visibleSections.map(({ type, models, run }) => (
            <div key={type}>{renderSection(type, models, run)}</div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-500">{t('chatComponents.patchInference.noModel')}</div>
      )}
    </div>
  )
}

export default PatchInferenceCard