import { useState } from 'react'
import { motion } from 'framer-motion'
import { Box, Database, Tag, Brain, Network, Fingerprint, Activity, Download, Loader2, LineChart, FolderKanban } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { downloadTrainedModelExport } from '../../api'
import { Card, CardContent } from '../ui/card'
import { cn } from '../../lib/utils'
import { isSegmentationTask, isSurvivalTask } from '../../constants/training'

export interface ModelInfo {
  id: string
  name: string
  task_type: string
  data_type: string
  feature_extractor?: string
  architecture?: string
  embedding_dim?: number
  classes?: string[]
  created_at?: string
  task_id?: string
  task_name?: string
  source_dataset_id?: string | null
  dataset_names?: string[]
}

export interface ModelListConfig {
  models: ModelInfo[]
}

const MAX_VISIBLE_MODELS = 5

interface ModelListCardProps {
  config: ModelListConfig
  onToast?: (toast: { type: 'error' | 'success' | 'info'; message: string }) => void
}

/**
 * Parse [MODEL_LIST] block from message content
 */
export function parseModelListConfig(content: string): ModelListConfig | null {
  const match = content.match(/\[MODEL_LIST\]([\s\S]*?)\[\/MODEL_LIST\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch (e) {
    console.error('Failed to parse model list config:', e)
    return null
  }
}

/**
 * Remove [MODEL_LIST] block from content
 */
export function removeModelListBlock(content: string): string {
  return content.replace(/\[MODEL_LIST\]([\s\S]*?)\[\/MODEL_LIST\]/g, '').trim()
}

export function ModelListCard({ config, onToast }: ModelListCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { models } = config
  const visibleModels = Array.isArray(models) ? models.slice(0, MAX_VISIBLE_MODELS) : []
  const [exportingModelId, setExportingModelId] = useState<string | null>(null)

  const preserveChatReturnContext = () => {
    const messagesContainer = document.querySelector('[data-chat-messages-container]')
    if (messagesContainer) {
      sessionStorage.setItem('ai-chat-scroll-position', String(messagesContainer.scrollTop))
    }
    const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
    if (conversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', conversationId)
    }
  }

  const handleViewAnalysis = (model: ModelInfo) => {
    if (!model.task_id) {
      onToast?.({ type: 'error', message: t('chatComponents.modelList.taskUnavailable') })
      return
    }
    preserveChatReturnContext()
    navigate(`/results?task=${encodeURIComponent(model.task_id)}`, { state: { fromAIChat: true } })
  }

  const handleViewTask = (model: ModelInfo) => {
    if (!model.task_id) {
      onToast?.({ type: 'error', message: t('chatComponents.modelList.taskUnavailable') })
      return
    }
    preserveChatReturnContext()
    navigate(`/task/${encodeURIComponent(model.task_id)}`, { state: { fromAIChat: true } })
  }

  const handleExportModel = async (model: ModelInfo) => {
    if (exportingModelId === model.id) return
    setExportingModelId(model.id)
    try {
      await downloadTrainedModelExport(model.id)
      onToast?.({ type: 'success', message: t('chatComponents.modelList.exportReady', { name: model.name }) })
    } catch (error) {
      console.error('Failed to export model from AI chat:', error)
      const message = error instanceof Error ? error.message : t('chatComponents.modelList.exportFailed')
      onToast?.({ type: 'error', message })
    } finally {
      setExportingModelId(current => current === model.id ? null : current)
    }
  }

  if (!visibleModels || visibleModels.length === 0) {
    return (
      <Card className="w-full max-w-full border-dashed bg-muted/20">
        <CardContent className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <Box className="w-10 h-10 mb-2 opacity-20" />
          <p className="text-sm">{t('chatComponents.modelList.noModelsFound')}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="mt-3 w-full max-w-full space-y-2">
      <div className="flex items-center gap-1.5 px-0.5">
        <Brain className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium text-foreground/60">
          {t('chatComponents.modelList.title', { count: visibleModels.length })}
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {visibleModels.map((model, index) => {
          const isSegType = isSegmentationTask(model.task_type)
          const isSurvival = isSurvivalTask(model.task_type)
          const isExporting = exportingModelId === model.id

          return (
            <motion.div
              key={model.id || index}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <div className={cn(
                "rounded-xl border border-gray-100 bg-white shadow-sm overflow-hidden",
                isSurvival
                  ? "border-l-[3px] border-l-orange-300"
                  : isSegType
                  ? "border-l-[3px] border-l-violet-300"
                  : "border-l-[3px] border-l-blue-300"
              )}>
                {/* Header */}
                <div className="px-3 pt-3 pb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-gray-900 truncate leading-tight" title={model.name}>
                      {model.name}
                    </span>
                    <span className={cn(
                      "text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 leading-none",
                      isSurvival ? "bg-orange-50 text-orange-600"
                        : isSegType ? "bg-violet-50 text-violet-600"
                        : "bg-blue-50 text-blue-600"
                    )}>
                      {isSurvival
                        ? t('chatComponents.modelList.survival')
                        : isSegType
                        ? t('chatComponents.modelList.segmentation')
                        : t('chatComponents.modelList.classification')}
                    </span>
                  </div>

                  {/* Metadata chips */}
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 bg-gray-50 border border-gray-100 px-1.5 py-0.5 rounded">
                      <Database className="w-2.5 h-2.5" />
                      {model.data_type === 'wsi'
                        ? t('chatComponents.modelList.wsi')
                        : t('chatComponents.modelList.patch')}
                    </span>
                    {(model.feature_extractor || model.architecture) && (() => {
                      const archLabel = isSegType && model.architecture && model.feature_extractor
                        ? `${model.architecture} + ${model.feature_extractor}`
                        : model.architecture || model.feature_extractor
                      return (
                        <span
                          className="inline-flex items-center gap-1 text-[11px] text-gray-500 bg-gray-50 border border-gray-100 px-1.5 py-0.5 rounded truncate max-w-[180px]"
                          title={archLabel}
                        >
                          <Network className="w-2.5 h-2.5 shrink-0" />
                          {archLabel}
                        </span>
                      )
                    })()}
                  </div>
                </div>

                {/* IDs */}
                <div className="px-3 pb-2 grid grid-cols-2 gap-x-3 gap-y-1.5">
                  <div>
                    <div className="flex items-center gap-0.5 text-[10px] text-gray-400 mb-0.5">
                      <Fingerprint className="w-2.5 h-2.5" />
                      {t('chatComponents.modelList.modelId')}
                    </div>
                    <p
                      className="font-mono text-[10px] text-gray-600 bg-gray-50 rounded px-1.5 py-0.5 truncate"
                      title={model.id}
                    >
                      {model.id}
                    </p>
                  </div>
                  {(model.task_name || model.task_id) && (
                    <div>
                      <div className="flex items-center gap-0.5 text-[10px] text-gray-400 mb-0.5">
                        <Activity className="w-2.5 h-2.5" />
                        {model.task_name
                          ? t('chatComponents.modelList.taskName')
                          : t('chatComponents.modelList.taskId')}
                      </div>
                      <p
                        className="text-[10px] text-gray-600 bg-gray-50 rounded px-1.5 py-0.5 truncate"
                        title={model.task_name || model.task_id}
                      >
                        {model.task_name || model.task_id}
                      </p>
                    </div>
                  )}
                </div>

                {/* Classes */}
                {model.classes && model.classes.length > 0 && (
                  <div className="px-3 pb-2.5 flex items-center gap-1.5 flex-wrap">
                    <Tag className="w-3 h-3 text-gray-300 shrink-0" />
                    {model.classes.map((cls) => (
                      <span
                        key={`${model.id}-${cls}`}
                        className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded-full leading-none"
                      >
                        {cls}
                      </span>
                    ))}
                  </div>
                )}

                {/* Action bar */}
                <div className="border-t border-gray-100 grid grid-cols-3 divide-x divide-gray-100">
                  <button
                    type="button"
                    className="flex items-center justify-center gap-1 py-2 text-[11px] font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
                    onClick={() => handleViewAnalysis(model)}
                  >
                    <LineChart className="w-3.5 h-3.5 shrink-0" />
                    {t('chatComponents.modelList.viewAnalysis')}
                  </button>
                  <button
                    type="button"
                    className="flex items-center justify-center gap-1 py-2 text-[11px] font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
                    onClick={() => handleViewTask(model)}
                  >
                    <FolderKanban className="w-3.5 h-3.5 shrink-0" />
                    {t('chatComponents.modelList.viewTask')}
                  </button>
                  <button
                    type="button"
                    disabled={isExporting}
                    className="flex items-center justify-center gap-1 py-2 text-[11px] font-medium text-primary hover:bg-primary/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    onClick={() => void handleExportModel(model)}
                  >
                    {isExporting
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                      : <Download className="w-3.5 h-3.5 shrink-0" />}
                    {isExporting
                      ? t('chatComponents.modelList.exportingModel')
                      : t('chatComponents.modelList.exportModel')}
                  </button>
                </div>
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
