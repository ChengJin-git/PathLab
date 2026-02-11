import React, { useState, useRef, useEffect, useLayoutEffect, useMemo, useCallback } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'

import {
  chatWithAI,
  getConversations,
  createConversation,
  getConversation,
  deleteConversation,
  updateMessage,
  addMessage,
  deleteMessagesFrom,
  submitMessageFeedback,
  getConversationFeedbacks,
  type Conversation,
  type ChatMessage,
  type ChatMessageContent,
  type MessageFeedback
} from '../api'
import { useVoiceSession } from '../lib/useVoiceSession'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as XLSX from 'xlsx'
import {
  Send, Loader2, Bot, User, MessageSquare, Trash2, Plus, Clock,
  Mic, MicOff, Paperclip, X, Rocket, Database,
  FlaskConical, Microscope, ArrowLeft, Sparkles, FileSpreadsheet, PanelLeft, History,
  ThumbsUp, ThumbsDown, Square
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { AudioVisualizer } from '../components/common/AudioVisualizer'
import { OptionButtons, parseOptions, removeOptionsBlock } from '../components/chat/OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from '../components/chat/TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from '../components/chat/ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from '../components/chat/CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from '../components/chat/NavigationCard'
import { CSVPreviewCard, parseCSVPreview, removeCSVPreviewBlock } from '../components/chat/CSVPreviewCard'
import { InferenceConfigCard, parseInferenceConfig, removeInferenceConfigBlock } from '../components/chat/InferenceConfigCard'
import { AnalysisConfigCard, parseAnalysisConfig, removeAnalysisConfigBlock } from '../components/chat/AnalysisConfigCard'
import { MetricCard, parseMetricConfig, removeMetricConfigBlock } from '../components/chat/MetricCard'
import { ChartCard, parseChartConfig, removeChartConfigBlock } from '../components/chat/ChartCard'
import { QuickAnalysisViewer, parseQuickAnalysisConfig, removeQuickAnalysisConfigBlock, CachedAnalysisData } from '../components/chat/QuickAnalysisViewer'
import { TaskHistoryCard, parseTaskHistoryConfig, removeTaskHistoryConfigBlock, CachedTaskData } from '../components/chat/TaskHistoryCard'
import { CancelTaskCard, parseCancelTaskConfig, removeCancelTaskBlock } from '../components/chat/CancelTaskCard'
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from '../components/chat/DatasetRegistrationCard'
import { MetadataUploadCard, parseMetadataUploadConfig, removeMetadataUploadBlock } from '../components/chat/MetadataUploadCard'
import { removeVoiceControlBlock } from '../components/chat/VoiceControlBlock'
import {
  TaskConfigSkeleton,
  OptionButtonsSkeleton,
  InferenceConfigSkeleton,
  AnalysisConfigSkeleton,
  ChartSkeleton,
  MetricSkeleton,
  ImageRecommendationSkeleton,
  CSVActionSkeleton,
  NavigationCardSkeleton,
  QuickAnalysisViewerSkeleton,
  GenericCardSkeleton,
  cardTransition
} from '../components/chat/CardSkeletons'


interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[] // base64 images for display
  timestamp: Date
  csvAttachments?: { fileName: string; content: string }[] // CSV file contents for processing
}

interface ImageAttachment {
  id: string
  file: File
  preview: string // base64 data URL for preview
  base64: string // base64 data for API
}

interface FileAttachment {
  id: string
  file: File
  name: string
  type: 'csv' | 'xlsx'
  content: string // text content for CSV, parsed content for XLSX
  preview: string[] // first few rows for preview
}

/**
 * Strip persistence-only fields from config blocks before sending message content to the AI API.
 * This prevents the AI from seeing and copying fields like submitted_task_id into new responses,
 * which would cause new config cards to initialize as already submitted.
 */
function sanitizeConfigBlocksForAI(content: string): string {
  // Fields to strip per config block type
  const PERSISTENCE_FIELDS: Record<string, string[]> = {
    TASK_CONFIG: ['submitted_task_id'],
    INFERENCE_CONFIG: ['submitted_task_id'],
    ANALYSIS_CONFIG: ['submitted_analysis_id', 'external_validation_task_id'],
    DATASET_REGISTRATION: ['submitted_task_id', 'submitted_file_count', 'submitted_dataset_name', 'submitted_mode'],
  }

  let sanitized = content
  for (const [blockType, fields] of Object.entries(PERSISTENCE_FIELDS)) {
    const regex = new RegExp(`\\[${blockType}\\]([\\s\\S]*?)\\[\\/${blockType}\\]`, 'g')
    sanitized = sanitized.replace(regex, (match, json) => {
      try {
        const config = JSON.parse(json.trim())
        let changed = false
        for (const field of fields) {
          if (field in config) {
            delete config[field]
            changed = true
          }
        }
        if (!changed) return match
        return `[${blockType}]\n${JSON.stringify(config, null, 2)}\n[/${blockType}]`
      } catch {
        return match
      }
    })
  }
  return sanitized
}

// Scenario cards for guided experience
const SCENARIO_CARDS = [
  {
    id: 'start-fresh',
    icon: Rocket,
    title: 'Fresh Start',
    description: 'Begin a new pathology research project',
    prompt: 'I want to start a new pathology research project. Can you help me understand what options I have?',
    color: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-50 hover:bg-blue-100',
    iconColor: 'text-blue-600'
  },
  {
    id: 'train-model',
    icon: Database,
    title: 'Train Model',
    description: 'I have a dataset ready for training',
    prompt: 'I have a dataset of pathology images and want to train a deep learning model. What do I need to configure?',
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-50 hover:bg-purple-100',
    iconColor: 'text-purple-600'
  },
  {
    id: 'test-model',
    icon: FlaskConical,
    title: 'Test Model',
    description: 'Run inference with a trained model',
    prompt: 'I have a trained model and want to run inference. How do I proceed?',
    color: 'from-green-500 to-emerald-500',
    bgColor: 'bg-green-50 hover:bg-green-100',
    iconColor: 'text-green-600'
  },
  {
    id: 'browse-images',
    icon: Microscope,
    title: 'Browse Images',
    description: 'Browse and analyze WSI or patches',
    prompt: 'I want to browse and analyze some pathology images (WSI or patches). Can you help me find the right ones based on my needs?',
    color: 'from-orange-500 to-amber-500',
    bgColor: 'bg-orange-50 hover:bg-orange-100',
    iconColor: 'text-orange-600'
  }
]

// Props interface for AssistantMessage component
interface AssistantMessageProps {
  content: string
  messageId: string
  onOptionSelect: (text: string) => void
  onTaskSubmitSuccess: (taskId: string, messageId: string) => void
  onInferenceSubmitSuccess: (taskId: string, messageId: string) => void
  onInternalAnalysisSubmitSuccess: (taskId: string, analysisId: string, messageId: string) => void
  onTaskSubmitError: (error: string) => void
  onTaskHistoryDataLoaded: (data: CachedTaskData[], messageId: string) => void
  onQuickAnalysisDataLoaded: (data: CachedAnalysisData, messageId: string) => void
  onHelpfulnessFeedback: (
    messageId: string,
    helpfulness: 'helpful' | 'not_helpful',
    relatedTaskId: string,
    taskType?: 'training' | 'inference' | 'analysis' | 'registration',
    taskTitle?: string
  ) => void
  savedHelpfulnessFeedback?: 'helpful' | 'not_helpful' | null
  isStreaming: boolean
  isLoading: boolean
  csvContent?: string
  csvFileName?: string
  onToast: (toast: { type: 'error' | 'success' | 'info'; message: string }) => void
  onRegistrationSuccess: (taskId: string, fileCount: number, datasetName: string, mode: 'existing' | 'new', messageId: string) => void
  onMetadataUploadSuccess: (result: import('../api').UploadSplitsResponse, datasetId: string, messageId: string) => void
  submitTaskTrigger?: number  // When this changes, trigger submit on TaskConfigCard
  cancelTaskTrigger?: number  // When this changes, trigger cancel on CancelTaskCard
}

// All special block tag names used in the chat
const SPECIAL_BLOCK_TAGS = [
  'OPTIONS',
  'TASK_CONFIG',
  'IMAGE_RECOMMENDATION',
  'CSV_ACTION',
  'NAVIGATE',
  'INFERENCE_CONFIG',
  'ANALYSIS_CONFIG',
  'METRIC_CONFIG',
  'CHART_CONFIG',
  'QUICK_ANALYSIS_CONFIG',
  'CSV_PREVIEW',
  'CANCEL_TASK',
  'TASK_HISTORY_CONFIG',
  'VOICE_CONTROL',
  'SUBMIT_TASK',  // Voice command to trigger submit on existing TaskConfigCard
  'CANCEL_TASK_NOW',  // Voice command to trigger cancel on existing CancelTaskCard
  'DATASET_UPLOAD',
  'METADATA_UPLOAD'
]

/**
 * Identify any incomplete/streaming special blocks in content.
 * Returns the cleaned content (without the incomplete block) and the tag of the incomplete block.
 */
function getIncompleteBlock(content: string): { content: string; incompleteTag: string | null } {
  let result = content
  let incompleteTag: string | null = null

  for (const tag of SPECIAL_BLOCK_TAGS) {
    // Pattern: [TAG_NAME] exists but [/TAG_NAME] doesn't exist
    const openTag = `[${tag}]`
    const closeTag = `[/${tag}]`
    const openIndex = result.indexOf(openTag)

    // Check if tag is opened but not closed
    // Also ensuring regular text before the tag is preserved
    if (openIndex !== -1 && result.indexOf(closeTag) === -1) {
      // Remove everything from the opening tag to the end for display
      result = result.substring(0, openIndex).trim()
      incompleteTag = tag
      break // Assume only one incomplete block at a time
    }
  }
  return { content: result, incompleteTag }
}

// Parse [SUBMIT_TASK] block - triggers submit on existing TaskConfigCard
function parseSubmitTask(content: string): boolean {
  const match = content.match(/\[SUBMIT_TASK\]([\s\S]*?)\[\/SUBMIT_TASK\]/)
  return !!match
}

// Remove [SUBMIT_TASK] block from content
function removeSubmitTaskBlock(content: string): string {
  return content.replace(/\[SUBMIT_TASK\][\s\S]*?\[\/SUBMIT_TASK\]/g, '').trim()
}

// Parse [CANCEL_TASK_NOW] block - triggers cancel on existing CancelTaskCard
function parseCancelTaskNow(content: string): boolean {
  const match = content.match(/\[CANCEL_TASK_NOW\]([\s\S]*?)\[\/CANCEL_TASK_NOW\]/)
  return !!match
}

// Remove [CANCEL_TASK_NOW] block from content
function removeCancelTaskNowBlock(content: string): string {
  return content.replace(/\[CANCEL_TASK_NOW\][\s\S]*?\[\/CANCEL_TASK_NOW\]/g, '').trim()
}


// Assistant message component with special markup parsing
// Defined outside of AIChatPage to prevent re-creation on every render
const AssistantMessage = React.memo(function AssistantMessage({
  content,
  messageId,
  onOptionSelect,
  onTaskSubmitSuccess,
  onInferenceSubmitSuccess,
  onInternalAnalysisSubmitSuccess,
  onTaskSubmitError,
  onTaskHistoryDataLoaded,
  onQuickAnalysisDataLoaded,
  onHelpfulnessFeedback,
  savedHelpfulnessFeedback,
  isStreaming,
  isLoading,
  csvContent,
  csvFileName,
  onToast,
  onRegistrationSuccess,
  onMetadataUploadSuccess,
  submitTaskTrigger,
  cancelTaskTrigger
}: AssistantMessageProps) {
  // Parse special blocks
  const options = parseOptions(content)
  const taskConfig = parseTaskConfig(content)
  const imageRecommendation = parseImageRecommendation(content)
  const csvAction = parseCSVAction(content)
  const navigateBlock = parseNavigateBlock(content)
  const inferenceConfig = parseInferenceConfig(content)
  const analysisConfig = parseAnalysisConfig(content)
  const metricConfig = parseMetricConfig(content)
  const chartConfig = parseChartConfig(content)
  const quickAnalysisConfig = parseQuickAnalysisConfig(content)
  const taskHistoryConfig = parseTaskHistoryConfig(content)
  const cancelTaskConfig = parseCancelTaskConfig(content)
  const datasetRegistrationConfig = parseDatasetRegistrationConfig(content)
  const metadataUploadConfig = parseMetadataUploadConfig(content)

  // Remove special blocks from display content
  // Keep the text content but strip out the special markup blocks
  let displayContent = content
  if (options) displayContent = removeOptionsBlock(displayContent)
  if (taskConfig) displayContent = removeTaskConfigBlock(displayContent)
  if (imageRecommendation) displayContent = removeImageRecommendationBlock(displayContent)
  if (csvAction) displayContent = removeCSVActionBlock(displayContent)
  if (navigateBlock) displayContent = removeNavigateBlock(displayContent)
  if (inferenceConfig) displayContent = removeInferenceConfigBlock(displayContent)
  if (analysisConfig) displayContent = removeAnalysisConfigBlock(displayContent)
  if (metricConfig) displayContent = removeMetricConfigBlock(displayContent)
  if (chartConfig) displayContent = removeChartConfigBlock(displayContent)
  if (quickAnalysisConfig) displayContent = removeQuickAnalysisConfigBlock(displayContent)
  if (taskHistoryConfig) displayContent = removeTaskHistoryConfigBlock(displayContent)
  if (cancelTaskConfig) displayContent = removeCancelTaskBlock(displayContent)
  if (datasetRegistrationConfig) displayContent = removeDatasetRegistrationBlock(displayContent)
  if (metadataUploadConfig) displayContent = removeMetadataUploadBlock(displayContent)
  // Remove VOICE_CONTROL block - it's for internal use only
  displayContent = removeVoiceControlBlock(displayContent)
  // Remove SUBMIT_TASK block - it's for internal use only (voice command to trigger submit)
  displayContent = removeSubmitTaskBlock(displayContent)
  // Remove CANCEL_TASK_NOW block - it's for internal use only (voice command to trigger cancel)
  displayContent = removeCancelTaskNowBlock(displayContent)

  // Remove any incomplete blocks that are still streaming
  const { content: cleanedContent, incompleteTag } = getIncompleteBlock(displayContent)
  displayContent = cleanedContent


  return (
    <div className="w-full min-w-0">
      {/* Markdown content */}
      {displayContent.trim() && (
        <div className="prose prose-slate max-w-none prose-sm
          prose-p:my-2 prose-p:leading-relaxed
          prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
          prose-ul:my-2 prose-ul:list-disc prose-ul:pl-5
          prose-ol:my-2 prose-ol:list-decimal prose-ol:pl-5
          prose-li:my-1
          prose-code:bg-gray-100 prose-code:text-gray-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
          prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:p-4 prose-pre:my-3
          prose-strong:text-gray-900 prose-strong:font-semibold
          prose-a:text-primary-600 prose-a:no-underline hover:prose-a:underline
          prose-hr:border-gray-200 prose-hr:my-4
          prose-table:text-sm prose-th:bg-gray-50 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-td:border-gray-200">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {displayContent}
          </ReactMarkdown>
        </div>
      )}

      {/* Animated Components Section */}
      <AnimatePresence mode="wait">

        {/* Option buttons */}
        {options ? (
          <motion.div key="options-real" {...cardTransition}>
            <OptionButtons
              options={options}
              onSelect={onOptionSelect}
              disabled={isLoading}
            />
          </motion.div>
        ) : incompleteTag === 'OPTIONS' && (
          <motion.div key="options-skeleton" {...cardTransition}>
            <OptionButtonsSkeleton />
          </motion.div>
        )}

        {/* Task config card */}
        {taskConfig ? (
          <motion.div key="task-config-real" {...cardTransition}>
            <TaskConfigCard
              config={taskConfig}
              onSubmitSuccess={(taskId) => onTaskSubmitSuccess(taskId, messageId)}
              onSubmitError={onTaskSubmitError}
              messageId={messageId}
              onHelpfulnessFeedback={onHelpfulnessFeedback}
              savedHelpfulnessFeedback={savedHelpfulnessFeedback}
              submitTrigger={submitTaskTrigger}
            />
          </motion.div>
        ) : incompleteTag === 'TASK_CONFIG' && (
          <motion.div key="task-config-skeleton" {...cardTransition}>
            <TaskConfigSkeleton />
          </motion.div>
        )}

        {/* Inference config card */}
        {inferenceConfig ? (
          <motion.div key="inference-config-real" {...cardTransition}>
            <InferenceConfigCard
              config={inferenceConfig}
              onSubmitSuccess={(taskId) => onInferenceSubmitSuccess(taskId, messageId)}
              onSubmitError={onTaskSubmitError}
              messageId={messageId}
              onHelpfulnessFeedback={onHelpfulnessFeedback}
              savedHelpfulnessFeedback={savedHelpfulnessFeedback}
            />
          </motion.div>
        ) : incompleteTag === 'INFERENCE_CONFIG' && (
          <motion.div key="inference-config-skeleton" {...cardTransition}>
            <InferenceConfigSkeleton />
          </motion.div>
        )}

        {/* Analysis config card (internal or external) */}
        {analysisConfig ? (
          <motion.div key="analysis-config-real" {...cardTransition}>
            <AnalysisConfigCard
              config={analysisConfig}
              onSubmitSuccess={(taskId, analysisId) => onInternalAnalysisSubmitSuccess(taskId, analysisId, messageId)}
              onSubmitError={onTaskSubmitError}
              messageId={messageId}
              onHelpfulnessFeedback={onHelpfulnessFeedback}
              savedHelpfulnessFeedback={savedHelpfulnessFeedback}
            />
          </motion.div>
        ) : incompleteTag === 'ANALYSIS_CONFIG' && (
          <motion.div key="analysis-config-skeleton" {...cardTransition}>
            <AnalysisConfigSkeleton />
          </motion.div>
        )}

        {/* Quick analysis viewer - shows both metrics and charts */}
        {quickAnalysisConfig ? (
          <motion.div key="quick-analysis-real" {...cardTransition}>
            <QuickAnalysisViewer
              config={quickAnalysisConfig}
              onError={(error) => onToast({ type: 'error', message: error })}
              onDataLoaded={(data) => onQuickAnalysisDataLoaded(data, messageId)}
            />
          </motion.div>
        ) : incompleteTag === 'QUICK_ANALYSIS_CONFIG' && (
          <motion.div key="quick-analysis-skeleton" {...cardTransition}>
            <QuickAnalysisViewerSkeleton />
          </motion.div>
        )}

        {/* Metric card - shows specific metrics */}
        {metricConfig ? (
          <motion.div key="metric-real" {...cardTransition}>
            <MetricCard
              config={metricConfig}
              onError={(error) => onToast({ type: 'error', message: error })}
            />
          </motion.div>
        ) : incompleteTag === 'METRIC_CONFIG' && (
          <motion.div key="metric-skeleton" {...cardTransition}>
            <MetricSkeleton />
          </motion.div>
        )}

        {/* Chart card - shows specific charts */}
        {chartConfig ? (
          <motion.div key="chart-real" {...cardTransition}>
            <ChartCard
              config={chartConfig}
              onError={(error) => onToast({ type: 'error', message: error })}
            />
          </motion.div>
        ) : incompleteTag === 'CHART_CONFIG' && (
          <motion.div key="chart-skeleton" {...cardTransition}>
            <ChartSkeleton />
          </motion.div>
        )}

        {/* Image recommendation card */}
        {imageRecommendation ? (
          <motion.div key="image-rec-real" {...cardTransition}>
            <ImageRecommendationCard recommendation={imageRecommendation} />
          </motion.div>
        ) : incompleteTag === 'IMAGE_RECOMMENDATION' && (
          <motion.div key="image-rec-skeleton" {...cardTransition}>
            <ImageRecommendationSkeleton />
          </motion.div>
        )}

        {/* CSV action card */}
        {(csvAction && csvContent && csvFileName) ? (
          <motion.div key="csv-action-real" {...cardTransition}>
            <CSVActionCard
              config={csvAction}
              csvContent={csvContent}
              fileName={csvFileName}
              onSuccess={() => {
                onToast({ type: 'success', message: 'CSV uploaded successfully!' })
              }}
              onError={(error) => {
                onToast({ type: 'error', message: error })
              }}
            />
          </motion.div>
        ) : incompleteTag === 'CSV_ACTION' && (
          <motion.div key="csv-action-skeleton" {...cardTransition}>
            <CSVActionSkeleton />
          </motion.div>
        )}

        {/* Navigation card */}
        {navigateBlock ? (
          <motion.div key="navigate-real" {...cardTransition}>
            <NavigationCard
              config={navigateBlock}
              csvContent={csvContent}
              csvFileName={csvFileName}
            />
          </motion.div>
        ) : incompleteTag === 'NAVIGATE' && (
          <motion.div key="navigate-skeleton" {...cardTransition}>
            <NavigationCardSkeleton />
          </motion.div>
        )}

        {/* Task History card */}
        {taskHistoryConfig ? (
          <motion.div key="task-history-real" {...cardTransition}>
            <TaskHistoryCard
              config={taskHistoryConfig}
              onError={(error) => onToast({ type: 'error', message: error })}
              onDataLoaded={(data) => onTaskHistoryDataLoaded(data, messageId)}
            />
          </motion.div>
        ) : incompleteTag === 'TASK_HISTORY_CONFIG' && (
          <motion.div key="task-history-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Cancel Task card */}
        {cancelTaskConfig ? (
          <motion.div key="cancel-task-real" {...cardTransition}>
            <CancelTaskCard
              config={cancelTaskConfig}
              onSuccess={(taskId) => onToast({ type: 'success', message: `Task ${taskId} cancelled successfully` })}
              onError={(error) => onToast({ type: 'error', message: error })}
              cancelTrigger={cancelTaskTrigger}
            />
          </motion.div>
        ) : incompleteTag === 'CANCEL_TASK' && (
          <motion.div key="cancel-task-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Dataset Upload Card */}
        {datasetRegistrationConfig ? (
          <motion.div key="dataset-reg-real" {...cardTransition}>
            <DatasetRegistrationCard
              config={datasetRegistrationConfig}
              onUploadStarted={(taskId, fileCount, datasetName, mode) => onRegistrationSuccess(taskId, fileCount, datasetName, mode, messageId)}
              onError={(error) => onToast({ type: 'error', message: error })}
              messageId={messageId}
              onHelpfulnessFeedback={onHelpfulnessFeedback}
              savedHelpfulnessFeedback={savedHelpfulnessFeedback}
            />
          </motion.div>
        ) : incompleteTag === 'DATASET_REGISTRATION' && (
          <motion.div key="dataset-reg-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Metadata Upload Card */}
        {metadataUploadConfig ? (
          <motion.div key="metadata-upload-real" {...cardTransition}>
            <MetadataUploadCard
              config={metadataUploadConfig}
              onSuccess={(result, datasetId) => onMetadataUploadSuccess(result, datasetId, messageId)}
              onError={(error) => onToast({ type: 'error', message: error })}
            />
          </motion.div>
        ) : incompleteTag === 'METADATA_UPLOAD' && (
          <motion.div key="metadata-upload-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* CSV Preview (Generic Skeleton) */}
        {incompleteTag === 'CSV_PREVIEW' && (
          <motion.div key="csv-preview-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Fallback for other unfinished blocks */}
        {incompleteTag && ![
          'OPTIONS',
          'TASK_CONFIG',
          'INFERENCE_CONFIG',
          'ANALYSIS_CONFIG',
          'QUICK_ANALYSIS_CONFIG',
          'METRIC_CONFIG',
          'CHART_CONFIG',
          'IMAGE_RECOMMENDATION',
          'CSV_ACTION',
          'NAVIGATE',
          'CSV_PREVIEW',
          'TASK_HISTORY_CONFIG',
          'CANCEL_TASK',
          'DATASET_REGISTRATION',
          'METADATA_UPLOAD'
        ].includes(incompleteTag) && (
            <motion.div key="generic-skeleton" {...cardTransition}>
              <GenericCardSkeleton />
            </motion.div>
          )}
      </AnimatePresence>

    </div>
  )
})

export default function AIChatPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { conversationId: urlConversationId } = useParams<{ conversationId?: string }>()

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([])
  const [fileAttachments, setFileAttachments] = useState<FileAttachment[]>([])

  // Conversation management
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  // Initialize from localStorage, defaulting to true on desktop, false on mobile
  const [showHistory, setShowHistory] = useState(() => {
    const saved = localStorage.getItem('ai-chat-sidebar-open')
    if (saved !== null) {
      return saved === 'true'
    }
    return window.innerWidth >= 1024
  })

  // Persist sidebar state
  useEffect(() => {
    localStorage.setItem('ai-chat-sidebar-open', String(showHistory))
  }, [showHistory])

  const [isLoadingConversations, setIsLoadingConversations] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  // UI state
  const [showWelcomeHero, setShowWelcomeHero] = useState(true)
  const [toastMessage, setToastMessage] = useState<{ type: 'error' | 'success' | 'info'; message: string } | null>(null)

  // Feedback state: messageId -> feedback type
  const [feedbacks, setFeedbacks] = useState<Map<number, 'thumbs_up' | 'thumbs_down'>>(new Map())
  // Helpfulness feedback state: messageId -> helpfulness type (for task submission feedback)
  const [helpfulnessFeedbacks, setHelpfulnessFeedbacks] = useState<Map<number, 'helpful' | 'not_helpful'>>(new Map())

  // Voice command submit trigger: when this changes, trigger submit on TaskConfigCard
  const [submitTaskTrigger, setSubmitTaskTrigger] = useState<number>(0)
  // Voice command cancel trigger: when this changes, trigger cancel on CancelTaskCard
  const [cancelTaskTrigger, setCancelTaskTrigger] = useState<number>(0)

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initialMessageSent = useRef(false)
  const scrollRestoredRef = useRef(false)
  // Ref for aborting AI generation
  const abortControllerRef = useRef<AbortController | null>(null)
  // Ref to access latest messages in callbacks
  const messagesRef = useRef<Message[]>([])
  messagesRef.current = messages
  // Ref to skip loading conversation when we just created it (to avoid overwriting in-progress messages)
  const skipConversationLoadRef = useRef(false)
  // Ref to track current input value for voice transcript appending
  const inputRef = useRef('')
  inputRef.current = input

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Toast helper function (defined early for use in hook callbacks)
  const showToastRef = useRef<(type: 'error' | 'success' | 'info', message: string) => void>(() => { })

  // Voice session hook – single source of truth for all voice state
  const {
    voiceState,
    partialText: realtimePartialText,
    mediaStream: realtimeMediaStream,
    toggle: toggleVoiceSession,
    stop: stopVoiceSession,
    notifyResponseComplete: notifyVoiceResponseComplete,
  } = useVoiceSession({
    onTranscript: (transcript) => {
      // Get current input value from ref to support appending
      const currentInput = inputRef.current.trim()
      const newInput = currentInput
        ? `${currentInput} ${transcript}`
        : transcript

      // Set input state AND ref simultaneously to avoid race condition
      setInput(newInput)
      inputRef.current = newInput

      // Auto-submit: dispatch form submit after React has the new input
      setTimeout(() => {
        const form = document.getElementById('chat-form') as HTMLFormElement
        if (form) {
          form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
        }
      }, 50)
    },
    onError: (error) => {
      showToastRef.current('error', `Voice input error: ${error}`)
    },
    silenceDurationMs: 800,
    maxRecordingSeconds: 120,
  })

  // Derived booleans for UI convenience
  const voiceSessionActive = voiceState !== 'idle'
  const realtimeIsRecording = voiceState === 'recording'
  const realtimeIsConnecting = voiceState === 'connecting'

  // Pre-compute CSV content mapping: assistant message ID -> most recent CSV from any previous user message
  // Uses O(n) single pass: track the most recent CSV as we iterate forward
  const csvContentMap = useMemo(() => {
    const map = new Map<string, { content: string; fileName: string }>()
    let lastCSV: { content: string; fileName: string } | null = null

    for (const msg of messages) {
      if (msg.role === 'user' && msg.csvAttachments?.length) {
        // Update the most recent CSV
        const csv = msg.csvAttachments[0]
        lastCSV = { content: csv.content, fileName: csv.fileName }
      } else if (msg.role === 'assistant' && lastCSV) {
        // Associate this assistant message with the most recent CSV
        map.set(msg.id, lastCSV)
      }
    }
    return map
  }, [messages])

  useEffect(() => {
    // Don't scroll to bottom if we're restoring scroll position
    if (scrollRestoredRef.current) {
      scrollRestoredRef.current = false
      return
    }
    scrollToBottom()
  }, [messages])

  // Restore conversation from URL (supports page refresh)
  // Also supports legacy sessionStorage restore for backward compatibility
  useEffect(() => {
    // Priority 1: Load from URL if conversationId is present
    if (urlConversationId) {
      // Skip loading if we just created this conversation (to avoid overwriting in-progress messages)
      if (skipConversationLoadRef.current) {
        skipConversationLoadRef.current = false
        return
      }
      handleLoadConversation(urlConversationId)
      return
    }

    // Priority 2: Legacy - restore from sessionStorage (for back navigation from other pages)
    const savedConversationId = sessionStorage.getItem('ai-chat-conversation-id')
    if (savedConversationId) {
      handleLoadConversation(savedConversationId)
      sessionStorage.removeItem('ai-chat-conversation-id')
    }
  }, [urlConversationId])

  // Restore scroll position after messages are loaded (when returning from another page)
  useEffect(() => {
    const savedScrollPosition = sessionStorage.getItem('ai-chat-scroll-position')
    if (savedScrollPosition && messagesContainerRef.current && messages.length > 0) {
      // Use requestAnimationFrame to ensure DOM is ready after messages render
      requestAnimationFrame(() => {
        if (messagesContainerRef.current) {
          messagesContainerRef.current.scrollTop = parseInt(savedScrollPosition, 10)
          scrollRestoredRef.current = true
        }
      })
      sessionStorage.removeItem('ai-chat-scroll-position')
    }
  }, [messages])

  // Use useLayoutEffect for textarea resize to prevent visual jitter
  // This runs synchronously after DOM updates but before browser paint
  useLayoutEffect(() => {
    // Auto-resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [input])

  // Load conversations on mount
  useEffect(() => {
    loadConversations()
  }, [])

  // Handle initial message from navigation state
  useEffect(() => {
    const state = location.state as { initialMessage?: string; autoStartRecording?: boolean; fromDashboard?: boolean } | null

    if (state?.initialMessage && !initialMessageSent.current) {
      initialMessageSent.current = true
      setInput(state.initialMessage)
      // Auto-submit after a short delay
      setTimeout(() => {
        const form = document.querySelector('form')
        if (form) {
          form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
        }
      }, 100)
    }

    if (state?.autoStartRecording) {
      console.log('[VoiceSession] Auto-start recording triggered from navigation')

      // Clear the autoStartRecording flag immediately to prevent re-triggering
      navigate(location.pathname, { replace: true, state: { ...state, autoStartRecording: false } })

      // Start voice session after a short delay to ensure everything is ready
      setTimeout(() => {
        console.log('[VoiceSession] Starting auto-recording')
        toggleVoiceSession()
      }, 100)
    }
  }, [location, toggleVoiceSession, navigate])

  const loadConversations = async () => {
    try {
      setIsLoadingConversations(true)
      const convs = await getConversations()
      setConversations(convs)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setIsLoadingConversations(false)
    }
  }

  const handleNewChat = () => {
    setMessages([])
    setCurrentConversationId(null)
    setInput('')
    setImageAttachments([])
    setFileAttachments([])
    setShowHistory(false)
    setShowWelcomeHero(true)
    setFeedbacks(new Map())
    setHelpfulnessFeedbacks(new Map())
    // Update URL to base path (remove conversationId from URL)
    if (urlConversationId) {
      navigate('/ai-chat', { replace: true })
    }
  }

  const handleLoadConversation = async (conversationId: string) => {
    try {
      const conv = await getConversation(conversationId)
      const loadedMessages: Message[] = conv.messages.map(msg => ({
        id: String(msg.id),
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
        timestamp: new Date(msg.created_at)
      }))
      setMessages(loadedMessages)
      setCurrentConversationId(conversationId)
      setShowHistory(false)
      setShowWelcomeHero(false)

      // Update URL to reflect the current conversation (for page refresh support)
      if (urlConversationId !== conversationId) {
        navigate(`/ai-chat/${conversationId}`, { replace: true })
      }

      // Load feedbacks for this conversation
      try {
        const feedbackList = await getConversationFeedbacks(conversationId)
        const feedbackMap = new Map<number, 'thumbs_up' | 'thumbs_down'>()
        const helpfulnessMap = new Map<number, 'helpful' | 'not_helpful'>()
        for (const fb of feedbackList) {
          if (fb.feedback_type) {
            feedbackMap.set(fb.message_id, fb.feedback_type)
          }
          if (fb.task_helpfulness) {
            helpfulnessMap.set(fb.message_id, fb.task_helpfulness)
          }
        }
        setFeedbacks(feedbackMap)
        setHelpfulnessFeedbacks(helpfulnessMap)
      } catch (error) {
        console.error('Failed to load feedbacks:', error)
        setFeedbacks(new Map())
        setHelpfulnessFeedbacks(new Map())
      }
    } catch (error) {
      console.error('Failed to load conversation:', error)
      // If loading fails, navigate back to clean URL
      if (urlConversationId) {
        navigate('/ai-chat', { replace: true })
      }
    }
  }

  const handleDeleteAllHistory = () => {
    if (conversations.length === 0) return
    setDeleteConfirmId('all-conversations')
  }

  const handleDeleteConversation = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteConfirmId(conversationId)
  }

  const confirmDelete = async () => {
    if (!deleteConfirmId) return

    try {
      if (deleteConfirmId === 'all-conversations') {
        setIsLoadingConversations(true)
        try {
          await Promise.all(conversations.map(conv => deleteConversation(conv.conversation_id)))
          await loadConversations()
          handleNewChat()
        } catch (error) {
          console.error('Failed to delete all conversations:', error)
        } finally {
          setIsLoadingConversations(false)
        }
      } else {
        await deleteConversation(deleteConfirmId)
        await loadConversations()
        if (currentConversationId === deleteConfirmId) {
          handleNewChat()
        }
      }
    } catch (error) {
      console.error('Failed to delete:', error)
    } finally {
      setDeleteConfirmId(null)
    }
  }

  const cancelDelete = () => {
    setDeleteConfirmId(null)
  }

  // File upload handlers (images, CSV, XLSX)
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return

    const newImageAttachments: ImageAttachment[] = []
    const newFileAttachments: FileAttachment[] = []

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const fileName = file.name.toLowerCase()

      // Handle image files
      if (file.type.startsWith('image/')) {
        const base64 = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as string)
          reader.readAsDataURL(file)
        })

        newImageAttachments.push({
          id: `${Date.now()}-${i}`,
          file,
          preview: base64,
          base64
        })
      }
      // Handle CSV files
      else if (fileName.endsWith('.csv') || file.type === 'text/csv') {
        const content = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as string)
          reader.readAsText(file)
        })

        // Parse CSV to get preview (first 5 rows)
        const lines = content.split('\n').filter(line => line.trim())
        const preview = lines.slice(0, 6) // Header + 5 data rows

        newFileAttachments.push({
          id: `${Date.now()}-${i}`,
          file,
          name: file.name,
          type: 'csv',
          content,
          preview
        })
      }
      // Handle XLSX files - parse and convert to CSV
      else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls') ||
        file.type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
        file.type === 'application/vnd.ms-excel') {
        try {
          const arrayBuffer = await file.arrayBuffer()
          const workbook = XLSX.read(arrayBuffer, { type: 'array' })

          // Check for multiple sheets - if so, we'll note it for the agent to reject
          const sheetNames = workbook.SheetNames
          if (sheetNames.length > 1) {
            // Multiple sheets - let agent know to reject
            newFileAttachments.push({
              id: `${Date.now()}-${i}`,
              file,
              name: file.name,
              type: 'xlsx',
              content: `__MULTIPLE_SHEETS__:${sheetNames.join(',')}`,
              preview: [
                `Excel file has ${sheetNames.length} sheets:`,
                ...sheetNames.slice(0, 5).map(s => `  • ${s}`),
                sheetNames.length > 5 ? `  ... and ${sheetNames.length - 5} more` : ''
              ].filter(Boolean)
            })
          } else {
            // Single sheet - convert to CSV
            const worksheet = workbook.Sheets[sheetNames[0]]
            const csvContent = XLSX.utils.sheet_to_csv(worksheet)

            // Parse CSV to get preview (first 5 rows)
            const lines = csvContent.split('\n').filter(line => line.trim())
            const preview = lines.slice(0, 6) // Header + 5 data rows

            newFileAttachments.push({
              id: `${Date.now()}-${i}`,
              file,
              name: file.name,
              type: 'xlsx', // Keep as xlsx to indicate original format
              content: csvContent, // Store as CSV content
              preview
            })
          }
        } catch (error) {
          console.error('Failed to parse XLSX file:', error)
          newFileAttachments.push({
            id: `${Date.now()}-${i}`,
            file,
            name: file.name,
            type: 'xlsx',
            content: `__PARSE_ERROR__:${error instanceof Error ? error.message : 'Unknown error'}`,
            preview: [`Failed to parse Excel file: ${file.name}`]
          })
        }
      }
    }

    if (newImageAttachments.length > 0) {
      setImageAttachments(prev => [...prev, ...newImageAttachments])
    }
    if (newFileAttachments.length > 0) {
      setFileAttachments(prev => [...prev, ...newFileAttachments])
    }

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleImageRemove = (id: string) => {
    setImageAttachments(prev => prev.filter(img => img.id !== id))
  }

  const handleFileRemove = (id: string) => {
    setFileAttachments(prev => prev.filter(f => f.id !== id))
  }

  const handleScenarioCardClick = (card: typeof SCENARIO_CARDS[number]) => {
    setInput(card.prompt)
    setShowWelcomeHero(false)
    // Focus the textarea
    setTimeout(() => textareaRef.current?.focus(), 100)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // Use inputRef.current to get the latest value, avoiding stale closure issues
    // when form is submitted programmatically (e.g., from voice transcription)
    const currentInputValue = inputRef.current.trim()
    if ((!currentInputValue && imageAttachments.length === 0 && fileAttachments.length === 0) || isGenerating) return

    // Build user message content with optional file info
    let messageContent = currentInputValue

    // Append file attachment info to message content for AI to analyze
    if (fileAttachments.length > 0) {
      const fileInfos = fileAttachments.map(f => {
        // Check for special error/warning markers in XLSX content
        if (f.type === 'xlsx' && f.content.startsWith('__MULTIPLE_SHEETS__:')) {
          const sheets = f.content.replace('__MULTIPLE_SHEETS__:', '')
          return `\n\n📎 **Uploaded Excel: ${f.name}**\n **Warning: This file has multiple sheets (${sheets})**\nPlease save only the data sheet as a separate CSV file and re-upload.`
        } else if (f.type === 'xlsx' && f.content.startsWith('__PARSE_ERROR__:')) {
          const error = f.content.replace('__PARSE_ERROR__:', '')
          return `\n\n📎 **Uploaded Excel: ${f.name}**\n **Error: Failed to parse file** - ${error}`
        } else {
          // Both CSV and successfully parsed XLSX (converted to CSV)
          // Use [CSV_PREVIEW] block for beautiful rendering
          const totalRows = f.content.split('\n').filter(line => line.trim()).length
          const previewData = {
            fileName: f.name,
            fileType: f.type,
            preview: f.preview,
            totalRows: totalRows
          }
          return `\n\n[CSV_PREVIEW]${JSON.stringify(previewData)}[/CSV_PREVIEW]`
        }
      }).join('')
      messageContent += fileInfos
    }

    // Build user message with optional images and CSV attachments
    // Include both CSV files and successfully parsed XLSX files (which now contain CSV content)
    const currentImages = imageAttachments.map(img => img.base64)
    const csvAttachments = fileAttachments
      .filter(f => {
        // Include CSV files and XLSX files that were successfully converted (no error markers)
        if (f.type === 'csv') return true
        if (f.type === 'xlsx' && !f.content.startsWith('__MULTIPLE_SHEETS__:') && !f.content.startsWith('__PARSE_ERROR__:')) return true
        return false
      })
      .map(f => ({ fileName: f.name, content: f.content }))
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageContent,
      images: currentImages.length > 0 ? currentImages : undefined,
      csvAttachments: csvAttachments.length > 0 ? csvAttachments : undefined,
      timestamp: new Date()
    }

    setShowWelcomeHero(false)
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setImageAttachments([]) // Clear attachments after sending
    setFileAttachments([]) // Clear file attachments after sending

    // Create a new conversation if this is the first user message
    let conversationId = currentConversationId
    if (!conversationId && messages.length === 0) {
      try {
        // Generate title from first message (truncate if too long)
        const title = userMessage.content.length > 50
          ? userMessage.content.substring(0, 50) + '...'
          : userMessage.content || 'Image Analysis'
        const newConv = await createConversation(title)
        conversationId = newConv.conversation_id
        setCurrentConversationId(conversationId)
        // Skip the next conversation load triggered by URL change (to avoid overwriting in-progress messages)
        skipConversationLoadRef.current = true
        // Update URL with new conversation ID for page refresh support
        navigate(`/ai-chat/${conversationId}`, { replace: true })
        await loadConversations()
      } catch (error) {
        console.error('Failed to create conversation:', error)
      }
    }

    // Create a placeholder message for streaming
    const aiMessageId = (Date.now() + 1).toString()
    const aiMessage: Message = {
      id: aiMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, aiMessage])
    setIsLoading(true)
    setIsGenerating(true)

    // Create AbortController for this request
    const abortController = new AbortController()
    abortControllerRef.current = abortController

    try {
      // Build chat messages for API (with multimodal support)
      // Sanitize config blocks to strip persistence-only fields (e.g., submitted_task_id)
      // so the AI doesn't copy them into new responses
      const chatMessages: ChatMessage[] = messages
        .concat([userMessage])
        .map(m => {
          const sanitizedContent = sanitizeConfigBlocksForAI(m.content)
          // If message has images, use multimodal format
          if (m.images && m.images.length > 0) {
            const content: ChatMessageContent = [
              { type: 'text' as const, text: sanitizedContent },
              ...m.images.map(imgBase64 => ({
                type: 'image_url' as const,
                image_url: { url: imgBase64 }
              }))
            ]
            return { role: m.role, content }
          }
          // Text-only message
          return { role: m.role, content: sanitizedContent }
        })

      let hasReceivedContent = false
      await chatWithAI(chatMessages, (chunk) => {
        if (!hasReceivedContent) {
          hasReceivedContent = true
          setIsLoading(false) // Stop loading animation once we start receiving content
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content + chunk }
              : m
          )
        )
      }, conversationId || undefined, (messageId) => {
        // Update the AI message ID to the backend ID for proper persistence
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, id: String(messageId) }
              : m
          )
        )
      }, abortController.signal)
    } catch (error) {
      // If user aborted, keep partial content as-is (don't overwrite with error)
      if (error instanceof DOMException && error.name === 'AbortError') {
        console.log('AI generation stopped by user')
      } else {
        console.error('Failed to get AI response:', error)
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content || 'Sorry, I encountered an error. Please try again.' }
              : m
          )
        )
      }
      // On error, stop voice session
      stopVoiceSession()
    } finally {
      setIsLoading(false)
      setIsGenerating(false)
      abortControllerRef.current = null

      // Check for SUBMIT_TASK and CANCEL_TASK_NOW blocks in ALL cases (voice or text input)
      // Use a timeout to ensure messages state is updated
      setTimeout(() => {
        const latestMessages = messagesRef.current
        const lastMessage = latestMessages[latestMessages.length - 1]

        if (lastMessage?.role === 'assistant') {
          // Check for SUBMIT_TASK block - trigger submit on existing TaskConfigCard
          if (parseSubmitTask(lastMessage.content)) {
            setSubmitTaskTrigger(prev => prev + 1)
          }

          // Check for CANCEL_TASK_NOW block - trigger cancel on existing CancelTaskCard
          if (parseCancelTaskNow(lastMessage.content)) {
            setCancelTaskTrigger(prev => prev + 1)
          }
        }
      }, 100)

      // Notify voice session that LLM response is complete.
      // The hook will parse VOICE_CONTROL and decide whether to restart recording.
      setTimeout(() => {
        const latestMessages = messagesRef.current
        const lastMessage = latestMessages[latestMessages.length - 1]
        const aiContent = lastMessage?.role === 'assistant' ? lastMessage.content : ''
        notifyVoiceResponseComplete(aiContent)
      }, 150)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  // Toast helper function
  const showToast = useCallback((type: 'error' | 'success' | 'info', message: string) => {
    setToastMessage({ type, message })
    setTimeout(() => setToastMessage(null), 5000)
  }, [])

  // Update ref for use in hook callbacks
  showToastRef.current = showToast

  // Clean message content by removing special markup blocks
  const cleanMessageContent = (content: string): string => {
    let cleaned = content
    cleaned = removeOptionsBlock(cleaned)
    cleaned = removeTaskConfigBlock(cleaned)
    cleaned = removeImageRecommendationBlock(cleaned)
    cleaned = removeCSVActionBlock(cleaned)
    cleaned = removeNavigateBlock(cleaned)
    cleaned = removeInferenceConfigBlock(cleaned)
    cleaned = removeCSVPreviewBlock(cleaned)
    cleaned = removeMetricConfigBlock(cleaned)
    cleaned = removeChartConfigBlock(cleaned)
    cleaned = removeQuickAnalysisConfigBlock(cleaned)
    // Remove VOICE_CONTROL block - it's for internal use only
    cleaned = removeVoiceControlBlock(cleaned)
    return cleaned.trim()
  }

  // Copy message content to clipboard (cleaned of special markup)
  const handleCopy = async (content: string) => {
    try {
      const cleanedContent = cleanMessageContent(content)
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(cleanedContent)
      } else {
        // Fallback for Electron or non-secure contexts
        const textArea = document.createElement('textarea')
        textArea.value = cleanedContent
        textArea.style.position = 'fixed'
        textArea.style.opacity = '0'
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      showToast('success', 'Copied to clipboard')
    } catch (error) {
      console.error('Failed to copy:', error)
      showToast('error', 'Failed to copy to clipboard')
    }
  }

  // Handle thumbs up/down feedback for a message
  const handleFeedback = async (messageId: string, feedbackType: 'thumbs_up' | 'thumbs_down') => {
    const numericId = parseInt(messageId, 10)
    if (isNaN(numericId)) {
      showToast('error', 'Invalid message ID')
      return
    }

    const currentFeedback = feedbacks.get(numericId)

    // Get message content and context for preservation
    const messageIndex = messages.findIndex(m => m.id === messageId)
    let messageContent: string | null = null
    let contextMessages: { role: 'user' | 'assistant'; content: string }[] | null = null

    if (messageIndex >= 0) {
      const currentMessage = messages[messageIndex]
      messageContent = currentMessage.content

      // Get previous message for context (if exists)
      if (messageIndex > 0) {
        const prevMessage = messages[messageIndex - 1]
        contextMessages = [{
          role: prevMessage.role,
          content: prevMessage.content
        }]
      }
    }

    // Optimistic update: Update UI immediately
    if (currentFeedback === feedbackType) {
      // Toggle off - remove feedback
      setFeedbacks(prev => {
        const newMap = new Map(prev)
        newMap.delete(numericId)
        return newMap
      })
    } else {
      // Set new feedback
      setFeedbacks(prev => {
        const newMap = new Map(prev)
        newMap.set(numericId, feedbackType)
        return newMap
      })
    }

    // Then submit to backend in background
    try {
      if (currentFeedback === feedbackType) {
        await submitMessageFeedback(numericId, null)
      } else {
        await submitMessageFeedback(
          numericId,
          feedbackType,
          null, // taskHelpfulness
          null, // relatedTaskId
          null, // timeToActionSeconds
          messageContent,
          contextMessages
        )
      }
    } catch (error) {
      console.error('Failed to submit feedback:', error)
      // Rollback: Revert UI state on error
      if (currentFeedback === feedbackType) {
        // Was trying to toggle off, restore the feedback
        setFeedbacks(prev => {
          const newMap = new Map(prev)
          newMap.set(numericId, feedbackType)
          return newMap
        })
      } else {
        // Was trying to set new feedback, revert to previous state
        setFeedbacks(prev => {
          const newMap = new Map(prev)
          if (currentFeedback) {
            newMap.set(numericId, currentFeedback)
          } else {
            newMap.delete(numericId)
          }
          return newMap
        })
      }
      showToast('error', 'Failed to submit feedback')
    }
  }

  // Format timestamp for display
  const formatTimestamp = (date: Date): string => {
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`

    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  // Handle helpfulness feedback for task submission
  const handleHelpfulnessFeedback = async (
    messageId: string,
    helpfulness: 'helpful' | 'not_helpful',
    relatedTaskId: string,
    taskType?: 'training' | 'inference' | 'analysis' | 'registration',
    taskTitle?: string
  ) => {
    const numericId = parseInt(messageId, 10)
    if (isNaN(numericId)) {
      showToast('error', 'Invalid message ID')
      return
    }

    // Calculate time from FIRST message in conversation to current time (feedback submission)
    let timeToActionSeconds: number | null = null

    if (messages.length > 0) {
      const firstMessageTime = messages[0].timestamp.getTime()
      const now = Date.now()
      timeToActionSeconds = (now - firstMessageTime) / 1000
    }

    // Update local helpfulness feedbacks state for persistence display
    setHelpfulnessFeedbacks(prev => {
      const newMap = new Map(prev)
      newMap.set(numericId, helpfulness)
      return newMap
    })

    try {
      await submitMessageFeedback(
        numericId,
        null, // feedbackType
        helpfulness,
        relatedTaskId,
        timeToActionSeconds,
        null, // messageContent (not needed for task feedback)
        null, // contextMessages (not needed for task feedback)
        taskType || null,
        taskTitle || null
      )
    } catch (error) {
      console.error('Failed to submit helpfulness feedback:', error)
      // Rollback on error
      setHelpfulnessFeedbacks(prev => {
        const newMap = new Map(prev)
        newMap.delete(numericId)
        return newMap
      })
      showToast('error', 'Failed to submit feedback')
    }
  }

  // Delete a message and all subsequent messages (for branching)
  const handleDeleteMessage = async (messageIndex: number) => {
    if (isGenerating) return

    const targetMessage = messages[messageIndex]
    if (!targetMessage) return

    // If we have a conversation and a valid message ID, delete from backend
    if (currentConversationId) {
      const messageId = parseInt(targetMessage.id, 10)
      // Only call API if messageId is a valid number (from database)
      // New messages created during streaming have timestamp-based IDs that are not persisted yet
      if (!isNaN(messageId)) {
        try {
          await deleteMessagesFrom(currentConversationId, messageId)
        } catch (error) {
          console.error('Failed to delete messages from backend:', error)
          showToast('error', 'Failed to delete message')
          return
        }
      }
    }

    // Update local state
    const newMessages = messages.slice(0, messageIndex)
    setMessages(newMessages)
    showToast('info', 'Message deleted')
  }

  // Regenerate AI response for a specific message
  const handleRegenerate = async (messageIndex: number) => {
    if (isGenerating) return

    // Find the user message that prompted this response
    const userMessageIndex = messageIndex - 1
    if (userMessageIndex < 0 || messages[userMessageIndex].role !== 'user') {
      showToast('error', 'Cannot regenerate: no user message found')
      return
    }

    // Remove the current assistant message and keep messages up to (not including) it
    const newMessages = messages.slice(0, messageIndex)
    setMessages(newMessages)

    // Create a new placeholder for streaming
    const aiMessageId = (Date.now() + 1).toString()
    const aiMessage: Message = {
      id: aiMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, aiMessage])
    setIsLoading(true)
    setIsGenerating(true)

    // Create AbortController for this request
    const abortController = new AbortController()
    abortControllerRef.current = abortController

    try {
      // Build chat messages for API (with multimodal support)
      // Sanitize config blocks to strip persistence-only fields (same as handleSubmit)
      const chatMessages: ChatMessage[] = newMessages.map(m => {
        const sanitizedContent = sanitizeConfigBlocksForAI(m.content)
        if (m.images && m.images.length > 0) {
          const content: ChatMessageContent = [
            { type: 'text' as const, text: sanitizedContent },
            ...m.images.map(imgBase64 => ({
              type: 'image_url' as const,
              image_url: { url: imgBase64 }
            }))
          ]
          return { role: m.role, content }
        }
        return { role: m.role, content: sanitizedContent }
      })

      let hasReceivedContent = false
      await chatWithAI(chatMessages, (chunk) => {
        if (!hasReceivedContent) {
          hasReceivedContent = true
          setIsLoading(false)
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content + chunk }
              : m
          )
        )
      }, currentConversationId || undefined, (messageId) => {
        // Update the AI message ID to the backend ID for proper persistence
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, id: String(messageId) }
              : m
          )
        )
      }, abortController.signal)
    } catch (error) {
      // If user aborted, keep partial content as-is
      if (error instanceof DOMException && error.name === 'AbortError') {
        console.log('AI regeneration stopped by user')
      } else {
        console.error('Failed to regenerate response:', error)
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content || 'Sorry, I encountered an error. Please try again.' }
              : m
          )
        )
      }
    } finally {
      setIsLoading(false)
      setIsGenerating(false)
      abortControllerRef.current = null
    }
  }

  // Stop AI generation and voice recording
  const handleStopGeneration = useCallback(() => {
    abortControllerRef.current?.abort()
    stopVoiceSession()
  }, [stopVoiceSession])

  // Handle option button selection - auto-send message
  const handleOptionSelect = (text: string) => {
    setInput(text)
    // Auto-submit
    setTimeout(() => {
      const form = document.querySelector('form')
      if (form) {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      }
    }, 100)
  }

  // Handle task submission success
  const handleTaskSubmitSuccess = async (taskId: string, messageId: string) => {
    // Update the original message's TASK_CONFIG block to include submitted_task_id
    // This persists the submission status so it's preserved when reloading the conversation

    // Find the message in current state
    const messageIndex = messages.findIndex(m => m.id === messageId)
    // If message not found (shouldn't happen), return
    if (messageIndex === -1 && messages.length > 0) {
      console.warn(`Message ${messageId} not found for task update`)
    }

    // Use a function to update state to ensure we're working with latest, but we need the content for API call
    // We'll compute it based on the message passed or find it in current messages
    let updatedContent: string | null = null

    setMessages(prev => {
      return prev.map(m => {
        if (m.id === messageId) {
          const newContent = m.content.replace(
            /\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/,
            (_match, json) => {
              try {
                const config = JSON.parse(json.trim())
                config.submitted_task_id = taskId
                return `[TASK_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_CONFIG]`
              } catch {
                return _match // If parsing fails, keep original
              }
            }
          )
          updatedContent = newContent // Capture for API call
          return { ...m, content: newContent }
        }
        return m
      })
    })

    // We need to wait for the state update or just trust our calculation. 
    // Since we need to send the API request immediately, we'll re-calculate it safely
    // (or simpler: assume strict mode double-invocation won't hurt the regex replace)

    // Better approach: Calculate first, then update
    // But we need the ORIGINAL content. 
    const currentMessage = messages.find(m => m.id === messageId)
    if (currentMessage) {
      updatedContent = currentMessage.content.replace(
        /\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/,
        (_match, json) => {
          try {
            const config = JSON.parse(json.trim())
            config.submitted_task_id = taskId
            return `[TASK_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_CONFIG]`
          } catch {
            return _match
          }
        }
      )
    }

    // Try to persist the update to backend if we have a conversation ID
    // Message IDs from backend are small integers (auto-increment), while
    // frontend-generated IDs are timestamps (large numbers like 1706191234567)
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      // Backend message IDs are typically small integers (< 1000000000)
      // Timestamps are 13-digit numbers (> 1000000000000)
      // Check if it's a likely backend ID (safe integer and not a timestamp)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000

      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          // Silently fail - local state is already updated
          console.warn('Failed to persist message update to backend:', error)
          showToast('error', 'Failed to save task status to server')
        }
      } else {
        console.warn(`Skipping persistence for temporary message ID: ${messageId}`)
      }
    }

    // Add a success message with navigation card to the chat and persist to backend
    const navigateBlock = JSON.stringify({
      target: `/task/${taskId}`,
      buttonText: 'View Training Progress',
      description: 'Your training task has been submitted successfully! Click below to monitor the progress in real-time.',
      type: 'task',
      taskId: taskId
    }, null, 2)
    const successContent = `Training task created successfully!\n\n[NAVIGATE]\n${navigateBlock}\n[/NAVIGATE]`
    const successMessage: Message = {
      id: Date.now().toString(),
      role: 'assistant',
      content: successContent,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, successMessage])

    // Persist success message to backend
    if (currentConversationId) {
      try {
        const savedMessage = await addMessage(currentConversationId, 'assistant', successContent)
        // Update the message ID to the backend ID
        setMessages(prev => prev.map(m =>
          m.id === successMessage.id
            ? { ...m, id: String(savedMessage.id) }
            : m
        ))
      } catch (error) {
        console.warn('Failed to persist success message to backend:', error)
      }
    }
  }

  // Handle registration success (persist to message history)
  const handleRegistrationSuccess = async (
    taskId: string,
    fileCount: number,
    datasetName: string,
    mode: 'existing' | 'new',
    messageId?: string
  ) => {
    if (!messageId) return

    // Find the message in current state
    const messageIndex = messages.findIndex(m => m.id === messageId)
    if (messageIndex === -1 && messages.length > 0) {
      console.warn(`Message ${messageId} not found for registration update`)
    }

    // Capture updatedContent from the state update
    let updatedContent: string | null = null

    setMessages(prev => {
      return prev.map(m => {
        if (m.id === messageId) {
          const newContent = m.content.replace(
            /\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/,
            (_match, json) => {
              try {
                const config = JSON.parse(json.trim())
                config.submitted_task_id = taskId
                config.submitted_file_count = fileCount
                config.submitted_dataset_name = datasetName
                config.submitted_mode = mode
                return `[DATASET_REGISTRATION]\n${JSON.stringify(config, null, 2)}\n[/DATASET_REGISTRATION]`
              } catch {
                return _match
              }
            }
          )
          updatedContent = newContent
          return { ...m, content: newContent }
        }
        return m
      })
    })

    // Re-calculate for API call (same pattern as handleTaskSubmitSuccess)
    const currentMessage = messages.find(m => m.id === messageId)
    if (currentMessage) {
      updatedContent = currentMessage.content.replace(
        /\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/,
        (_match, json) => {
          try {
            const config = JSON.parse(json.trim())
            config.submitted_task_id = taskId
            config.submitted_file_count = fileCount
            config.submitted_dataset_name = datasetName
            config.submitted_mode = mode
            return `[DATASET_REGISTRATION]\n${JSON.stringify(config, null, 2)}\n[/DATASET_REGISTRATION]`
          } catch {
            return _match
          }
        }
      )
    }

    // Persist to backend
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000
      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist registration update:', error)
          showToast('error', 'Failed to save registration status to server')
        }
      } else {
        console.warn(`Skipping persistence for temporary message ID: ${messageId}`)
      }
    }

    showToast('info', 'Registration started in background')

    // Auto-send message to trigger AI's STEP 6 response (METADATA_UPLOAD card)
    const autoMessage = `Registration submitted. ${fileCount} Files are uploading in the background.`
    setInput(autoMessage)
    setTimeout(() => {
      const form = document.querySelector('form')
      if (form) {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      }
    }, 100)
  }

  // Handle metadata upload success (persist upload_result to message history)
  const handleMetadataUploadSuccess = async (
    result: import('../api').UploadSplitsResponse,
    datasetId: string,
    messageId?: string
  ) => {
    if (!messageId) return

    let updatedContent: string | null = null

    setMessages(prev => {
      return prev.map(m => {
        if (m.id === messageId) {
          const newContent = m.content.replace(
            /\[METADATA_UPLOAD\]([\s\S]*?)\[\/METADATA_UPLOAD\]/,
            (_match, json) => {
              try {
                const config = JSON.parse(json.trim())
                config.upload_result = {
                  updated_count: result.updated_count,
                  not_found_count: result.not_found_count,
                  auto_val_count: result.auto_val_count
                }
                return `[METADATA_UPLOAD]\n${JSON.stringify(config, null, 2)}\n[/METADATA_UPLOAD]`
              } catch {
                return _match
              }
            }
          )
          updatedContent = newContent
          return { ...m, content: newContent }
        }
        return m
      })
    })

    // Re-calculate for API call
    const currentMessage = messages.find(m => m.id === messageId)
    if (currentMessage) {
      updatedContent = currentMessage.content.replace(
        /\[METADATA_UPLOAD\]([\s\S]*?)\[\/METADATA_UPLOAD\]/,
        (_match, json) => {
          try {
            const config = JSON.parse(json.trim())
            config.upload_result = {
              updated_count: result.updated_count,
              not_found_count: result.not_found_count,
              auto_val_count: result.auto_val_count
            }
            return `[METADATA_UPLOAD]\n${JSON.stringify(config, null, 2)}\n[/METADATA_UPLOAD]`
          } catch {
            return _match
          }
        }
      )
    }

    // Persist to backend
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000
      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist metadata upload update:', error)
          showToast('error', 'Failed to save metadata upload status to server')
        }
      }
    }

    showToast('success', `Metadata uploaded: ${result.updated_count} files updated`)
  }

  // Handle task submission error
  const handleTaskSubmitError = (error: string) => {
    // Send error to agent for analysis
    const errorMessage = `The task submission failed with error: "${error}". Can you help me understand what went wrong and how to fix it?`
    setInput(errorMessage)
  }

  // Handle inference submission success
  const handleInferenceSubmitSuccess = async (taskId: string, messageId: string) => {
    // Update the original message's INFERENCE_CONFIG block to include submitted_task_id
    // This persists the submission status so it's preserved when reloading the conversation

    // First, compute the updated content
    let updatedContent: string | null = null

    const currentMessage = messages.find(m => m.id === messageId)
    if (currentMessage) {
      updatedContent = currentMessage.content.replace(
        /\[INFERENCE_CONFIG\]([\s\S]*?)\[\/INFERENCE_CONFIG\]/,
        (_match, json) => {
          try {
            const config = JSON.parse(json.trim())
            config.submitted_task_id = taskId
            return `[INFERENCE_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/INFERENCE_CONFIG]`
          } catch {
            return _match // If parsing fails, keep original
          }
        }
      )
    }

    setMessages(prev => prev.map(m => {
      if (m.id === messageId && updatedContent) {
        return { ...m, content: updatedContent }
      }
      return m
    }))

    // Try to persist the update to backend if we have a conversation ID
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000

      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist message update to backend:', error)
          showToast('error', 'Failed to save task status to server')
        }
      }
    }

    // Add a success message with navigation card to Results Viewer and persist to backend
    const successContent = `Inference task submitted successfully! Task ID: \`${taskId}\`\n\nOnce the inference is complete, you can view the analysis results in the Results Viewer.\n\n[NAVIGATE]\n${JSON.stringify({
      target: '/results',
      state: { selectedTaskId: taskId },
      buttonText: 'View Results',
      description: 'Click to open the Results Viewer and analyze the inference results.'
    }, null, 2)}\n[/NAVIGATE]`
    const successMessage: Message = {
      id: Date.now().toString(),
      role: 'assistant',
      content: successContent,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, successMessage])

    // Persist success message to backend
    if (currentConversationId) {
      try {
        const savedMessage = await addMessage(currentConversationId, 'assistant', successContent)
        // Update the message ID to the backend ID
        setMessages(prev => prev.map(m =>
          m.id === successMessage.id
            ? { ...m, id: String(savedMessage.id) }
            : m
        ))
      } catch (error) {
        console.warn('Failed to persist success message to backend:', error)
      }
    }
  }

  // Handle analysis submission success (internal or external)
  const handleInternalAnalysisSubmitSuccess = async (taskId: string, analysisId: string, messageId: string) => {
    // Determine if this is external validation (analysisId is empty for external)
    const isExternalValidation = !analysisId

    // Update the original message's ANALYSIS_CONFIG block to include submitted_analysis_id or external_validation_task_id
    let updatedContent: string | null = null

    const currentMessage = messages.find(m => m.id === messageId)
    if (currentMessage) {
      updatedContent = currentMessage.content.replace(
        /\[ANALYSIS_CONFIG\]([\s\S]*?)\[\/ANALYSIS_CONFIG\]/,
        (_match, json) => {
          try {
            const config = JSON.parse(json.trim())
            if (analysisId) {
              config.submitted_analysis_id = analysisId
            } else {
              // External validation - store the task_id
              config.external_validation_task_id = taskId
            }
            return `[ANALYSIS_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/ANALYSIS_CONFIG]`
          } catch {
            return _match
          }
        }
      )
    }

    setMessages(prev => prev.map(m => {
      if (m.id === messageId && updatedContent) {
        return { ...m, content: updatedContent }
      }
      return m
    }))

    // Persist the update to backend
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000

      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist message update to backend:', error)
          showToast('error', 'Failed to save analysis status to server')
        }
      }
    }

    // For external validation, build QUICK_ANALYSIS_CONFIG block for inline results display
    let quickAnalysisBlock = ''
    if (isExternalValidation && currentMessage) {
      const origAnalysisConfig = parseAnalysisConfig(currentMessage.content)
      if (origAnalysisConfig) {
        const quickConfig: Record<string, unknown> = {
          task_id: taskId,
          task_name: origAnalysisConfig.target_name || origAnalysisConfig.task_name || taskId,
          metrics: origAnalysisConfig.metrics || [],
          charts: origAnalysisConfig.charts || [],
          is_external_validation: true
        }
        if (origAnalysisConfig.compute_bootstrap_ci) {
          quickConfig.compute_bootstrap_ci = true
        }
        if (origAnalysisConfig.bootstrap_ci_metrics) {
          quickConfig.bootstrap_ci_metrics = origAnalysisConfig.bootstrap_ci_metrics
        }
        quickAnalysisBlock = `\n\n[QUICK_ANALYSIS_CONFIG]\n${JSON.stringify(quickConfig, null, 2)}\n[/QUICK_ANALYSIS_CONFIG]`
      }
    }

    // Add success message with navigation card to Results Viewer
    // Different message for external validation vs internal analysis
    const successContent = isExternalValidation
      ? `External validation started! Task ID: \`${taskId}\`\n\nThe model will run inference on the target dataset, then automatically analyze the results. You can track progress in the Background Tasks panel.${quickAnalysisBlock}\n\n[NAVIGATE]\n${JSON.stringify({
          target: '/results',
          state: { selectedTaskId: taskId },
          buttonText: 'View Results',
          description: 'Click to open the Results Viewer. Results will appear once validation completes.'
        }, null, 2)}\n[/NAVIGATE]`
      : `Analysis completed successfully!\n\nYou can view the detailed results including metrics and charts in the Results Viewer.\n\n[NAVIGATE]\n${JSON.stringify({
          target: '/results',
          state: { selectedTaskId: taskId },
          buttonText: 'View Analysis Results',
          description: 'Click to open the Results Viewer and see your analysis results.'
        }, null, 2)}\n[/NAVIGATE]`

    const successMessage: Message = {
      id: Date.now().toString(),
      role: 'assistant',
      content: successContent,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, successMessage])

    // Persist success message to backend
    if (currentConversationId) {
      try {
        const savedMessage = await addMessage(currentConversationId, 'assistant', successContent)
        setMessages(prev => prev.map(m =>
          m.id === successMessage.id
            ? { ...m, id: String(savedMessage.id) }
            : m
        ))
      } catch (error) {
        console.warn('Failed to persist success message to backend:', error)
      }
    }
  }

  // Handle task history data loaded - persist cached tasks to message content
  const handleTaskHistoryDataLoaded = async (data: CachedTaskData[], messageId: string) => {
    // Find the message and update TASK_HISTORY_CONFIG block with cached_tasks
    const currentMessage = messages.find(m => m.id === messageId)
    if (!currentMessage) return

    const updatedContent = currentMessage.content.replace(
      /\[TASK_HISTORY_CONFIG\]([\s\S]*?)\[\/TASK_HISTORY_CONFIG\]/,
      (_match, json) => {
        try {
          const config = JSON.parse(json.trim())
          config.cached_tasks = data
          config.cached_at = new Date().toISOString()
          return `[TASK_HISTORY_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_HISTORY_CONFIG]`
        } catch {
          return _match
        }
      }
    )

    // Update local state
    setMessages(prev => prev.map(m =>
      m.id === messageId ? { ...m, content: updatedContent } : m
    ))

    // Persist to backend if we have a valid backend message ID
    if (currentConversationId) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000

      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist task history cache to backend:', error)
        }
      }
    }
  }

  // Handle quick analysis data loaded - persist cached data to message content
  const handleQuickAnalysisDataLoaded = async (data: CachedAnalysisData, messageId: string) => {
    // Find the message and update QUICK_ANALYSIS_CONFIG block with cached_data
    const currentMessage = messages.find(m => m.id === messageId)
    if (!currentMessage) return

    const updatedContent = currentMessage.content.replace(
      /\[QUICK_ANALYSIS_CONFIG\]([\s\S]*?)\[\/QUICK_ANALYSIS_CONFIG\]/,
      (_match, json) => {
        try {
          const config = JSON.parse(json.trim())
          config.cached_data = data
          return `[QUICK_ANALYSIS_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/QUICK_ANALYSIS_CONFIG]`
        } catch {
          return _match
        }
      }
    )

    // Update local state
    setMessages(prev => prev.map(m =>
      m.id === messageId ? { ...m, content: updatedContent } : m
    ))

    // Persist to backend if we have a valid backend message ID
    if (currentConversationId) {
      const numericId = parseInt(messageId, 10)
      const isBackendId = !isNaN(numericId) && numericId < 1000000000

      if (isBackendId) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist quick analysis cache to backend:', error)
        }
      }
    }
  }

  return (
    <div className="flex h-full bg-gray-50 relative overflow-hidden">
      {/* Chat History Sidebar */}
      {showHistory && (
        <>
          <div
            className="fixed top-16 inset-x-0 bottom-0 bg-black/20 z-30 lg:hidden backdrop-blur-sm transition-opacity"
            onClick={() => setShowHistory(false)}
          />
          <div className="fixed top-16 bottom-0 left-0 w-80 bg-white border-r border-gray-200 z-40 flex flex-col shadow-2xl animate-in slide-in-from-left duration-300">
            <div className="p-4 border-b border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowHistory(false)}
                    className="p-2 -ml-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors"
                    title="Close history"
                  >
                    <PanelLeft className="w-5 h-5" />
                  </button>
                  <h2 className="text-lg font-semibold text-gray-900">History</h2>
                </div>
                {conversations.length > 0 && (
                  <button
                    onClick={handleDeleteAllHistory}
                    className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    title="Delete all history"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                )}
              </div>
              <button
                onClick={handleNewChat}
                className="w-full px-4 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-all shadow-sm flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                New Research Task
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {isLoadingConversations ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 text-primary-500 animate-spin mb-3" />
                  <p className="text-sm text-gray-500">Loading conversations...</p>
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-3">
                    <MessageSquare className="w-8 h-8 text-gray-300" />
                  </div>
                  <p className="text-sm font-medium text-gray-900 mb-1">No conversations yet</p>
                  <p className="text-xs text-gray-500">Start a new chat to begin</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {conversations.map((conv) => (
                    <div
                      key={conv.conversation_id}
                      onClick={() => handleLoadConversation(conv.conversation_id)}
                      className={`group relative p-3 rounded-xl cursor-pointer transition-all border ${currentConversationId === conv.conversation_id
                        ? 'bg-primary-50 border-primary-200 shadow-sm'
                        : 'hover:bg-gray-50 border-transparent hover:border-gray-100'
                        }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <h3 className={`text-sm font-medium truncate mb-1 ${currentConversationId === conv.conversation_id ? 'text-primary-900' : 'text-gray-900'
                            }`}>
                            {conv.title}
                          </h3>
                          <div className="flex items-center gap-1 text-xs text-gray-500">
                            <Clock className="w-3 h-3" />
                            {new Date(conv.updated_at).toLocaleDateString([], {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                          className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                          title="Delete conversation"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 h-full relative z-10 overflow-hidden">
        {/* Top Bar with History Toggle - Fixed at top of main area */}
        <div className="flex-shrink-0 z-20 bg-gray-50 border-b border-gray-200/50 px-4 py-3">
          <div className="max-w-4xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setShowHistory(!showHistory)}
                className={`p-2 -ml-2 rounded-full text-gray-500 hover:text-gray-900 hover:bg-white/50 transition-all ${showHistory ? 'bg-white/50 text-gray-900' : ''
                  }`}
                title={showHistory ? 'Close chat history' : 'Open chat history'}
              >
                <History className="w-5 h-5" />
              </button>
              <h1 className="text-base font-semibold text-gray-900 leading-tight">
                {currentConversationId
                  ? conversations.find(c => c.conversation_id === currentConversationId)?.title || 'Chat'
                  : 'New Research Task'
                }
              </h1>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                onClick={() => navigate('/dashboard')}
                className="gap-2 text-xs font-medium rounded-full border-gray-200 bg-white/50 hover:bg-white transition-all shadow-sm"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back
              </Button>
            </div>
          </div>
        </div>

        <div ref={messagesContainerRef} data-chat-messages-container data-current-conversation-id={currentConversationId || ''} className="flex-1 overflow-y-auto custom-scrollbar">
          <div className="px-4 pb-40">
          <div className="max-w-4xl mx-auto space-y-6">
            {/* Gemini-style Welcome Hero with Scenario Cards */}
            {messages.length === 0 && showWelcomeHero && (
              <div className="flex flex-col items-center justify-center pt-2 pb-12 text-center space-y-4">
                {/* Hero Title */}
                <div className="space-y-2">
                  <div className="flex items-center justify-center gap-2 mb-2">
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shadow-lg">
                      <Sparkles className="w-7 h-7 text-white" />
                    </div>
                  </div>
                  <h1 className="text-3xl font-bold bg-gradient-to-r from-gray-900 via-gray-700 to-gray-900 bg-clip-text text-transparent">
                    Hello, I'm PathLab Agent
                  </h1>
                  <p className="text-gray-500 max-w-lg mx-auto text-base">
                    Your AI assistant for pathology research. I can help you train models, run inference, and analyze whole slide images.
                  </p>
                </div>

                {/* Scenario Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-2xl mt-2">
                  {SCENARIO_CARDS.map((card) => {
                    const Icon = card.icon
                    return (
                      <button
                        key={card.id}
                        onClick={() => handleScenarioCardClick(card)}
                        className={`${card.bgColor} p-5 rounded-2xl text-left transition-all duration-200 hover:shadow-md hover:scale-[1.02] group border border-transparent hover:border-gray-200`}
                      >
                        <div className={`w-10 h-10 rounded-xl bg-white shadow-sm flex items-center justify-center mb-3 group-hover:shadow-md transition-shadow`}>
                          <Icon className={`w-5 h-5 ${card.iconColor}`} />
                        </div>
                        <h3 className="font-semibold text-gray-900 mb-1">{card.title}</h3>
                        <p className="text-sm text-gray-600">{card.description}</p>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            {/* Find the last message with a TaskConfigCard/CancelTaskCard to only pass triggers to it */}
            {(() => {
              // Find the index of the last message that contains a TaskConfigCard
              let lastTaskConfigIndex = -1
              let lastCancelTaskIndex = -1
              for (let i = messages.length - 1; i >= 0; i--) {
                const msg = messages[i]
                if (msg.role === 'assistant') {
                  if (lastTaskConfigIndex === -1 && parseTaskConfig(msg.content)) {
                    lastTaskConfigIndex = i
                  }
                  if (lastCancelTaskIndex === -1 && parseCancelTaskConfig(msg.content)) {
                    lastCancelTaskIndex = i
                  }
                  // Stop if both found
                  if (lastTaskConfigIndex !== -1 && lastCancelTaskIndex !== -1) {
                    break
                  }
                }
              }
              return messages.map((message, index) => (
              <div
                key={message.id}
                className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'} items-start`}
              >
                {/* Avatar */}
                <div className="flex-shrink-0 mt-1">
                  <div
                    className={`hidden w-8 h-8 rounded-full flex items-center justify-center border shadow-sm ${message.role === 'user'
                      ? 'bg-white border-gray-100'
                      : 'bg-white border-gray-100'
                      }`}
                  >
                    {message.role === 'user' ? (
                      <User className="w-5 h-5 text-gray-600" />
                    ) : (
                      <Bot className="w-5 h-5 text-primary-600" />
                    )}
                  </div>
                </div>

                {/* Message Content */}
                <div className={`flex-1 min-w-0 max-w-[80%] flex flex-col ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                  {/* User Images */}
                  {message.role === 'user' && message.images && message.images.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2 justify-end">
                      {message.images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img}
                          alt={`Attachment ${idx + 1}`}
                          className="max-w-[200px] max-h-[200px] rounded-xl object-cover border border-gray-200 shadow-sm"
                        />
                      ))}
                    </div>
                  )}

                  {/* Message Bubble */}
                  <div
                    className={`relative px-5 py-3.5 text-[15px] leading-7 shadow-sm w-full overflow-hidden ${message.role === 'user'
                      ? 'bg-gradient-to-br from-primary-500 to-primary-600 text-white rounded-[20px] rounded-tr-sm selection:bg-white/30'
                      : 'bg-white border border-gray-100 text-gray-900 rounded-[20px] rounded-tl-sm'
                      }`}
                  >
                    {message.role === 'user' ? (
                      (() => {
                        // Parse CSV preview from user message
                        const csvPreview = parseCSVPreview(message.content)
                        const displayContent = csvPreview ? removeCSVPreviewBlock(message.content) : message.content

                        return (
                          <div>
                            {displayContent.trim() && (
                              <div className="whitespace-pre-wrap break-words">
                                {displayContent}
                              </div>
                            )}
                            {csvPreview && (
                              <CSVPreviewCard {...csvPreview} />
                            )}
                          </div>
                        )
                      })()
                    ) : message.content === '' ? (
                      // ChatGPT-like Thinking Indicator
                      <div className="flex items-center gap-2 py-2">
                        <div className="w-2.5 h-2.5 bg-gray-400 rounded-full animate-pulse"></div>
                        <span className="text-sm font-medium text-gray-500 animate-pulse">Thinking...</span>
                      </div>
                    ) : (
                      <AssistantMessage
                        content={message.content}
                        messageId={message.id}
                        onOptionSelect={handleOptionSelect}
                        onTaskSubmitSuccess={handleTaskSubmitSuccess}
                        onInferenceSubmitSuccess={handleInferenceSubmitSuccess}
                        onInternalAnalysisSubmitSuccess={handleInternalAnalysisSubmitSuccess}
                        onTaskSubmitError={handleTaskSubmitError}
                        onTaskHistoryDataLoaded={handleTaskHistoryDataLoaded}
                        onQuickAnalysisDataLoaded={handleQuickAnalysisDataLoaded}
                        onHelpfulnessFeedback={handleHelpfulnessFeedback}
                        savedHelpfulnessFeedback={helpfulnessFeedbacks.get(parseInt(message.id, 10)) || null}
                        isStreaming={isLoading && index === messages.length - 1}
                        isLoading={isGenerating}
                        csvContent={csvContentMap.get(message.id)?.content}
                        csvFileName={csvContentMap.get(message.id)?.fileName}
                        onToast={setToastMessage}
                        onRegistrationSuccess={handleRegistrationSuccess}
                        onMetadataUploadSuccess={handleMetadataUploadSuccess}
                        submitTaskTrigger={index === lastTaskConfigIndex ? submitTaskTrigger : undefined}
                        cancelTaskTrigger={index === lastCancelTaskIndex ? cancelTaskTrigger : undefined}
                      />
                    )}
                  </div>

                  {/* Timestamp & Actions for Assistant Messages */}
                  {message.role === 'assistant' && message.content !== '' && (
                    <div className="flex items-center gap-3 mt-2 text-gray-400">
                      {/* Timestamp */}
                      <span className="text-xs text-gray-400" title={message.timestamp.toLocaleString()}>
                        {formatTimestamp(message.timestamp)}
                      </span>

                      <div className="w-px h-4 bg-gray-200" />

                      {/* Thumbs Up/Down Buttons */}
                      <button
                        onClick={() => handleFeedback(message.id, 'thumbs_up')}
                        className={`transition-colors ${feedbacks.get(parseInt(message.id, 10)) === 'thumbs_up'
                          ? 'text-green-500'
                          : 'hover:text-gray-600'
                          }`}
                        title="Good response"
                      >
                        <ThumbsUp className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleFeedback(message.id, 'thumbs_down')}
                        className={`transition-colors ${feedbacks.get(parseInt(message.id, 10)) === 'thumbs_down'
                          ? 'text-red-500'
                          : 'hover:text-gray-600'
                          }`}
                        title="Bad response"
                      >
                        <ThumbsDown className="w-4 h-4" />
                      </button>

                      <div className="w-px h-4 bg-gray-200" />

                      <button
                        onClick={() => handleCopy(message.content)}
                        className="hover:text-gray-600 transition-colors"
                        title="Copy"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                      </button>
                      <button
                        onClick={() => handleRegenerate(index)}
                        disabled={isGenerating}
                        className={`hover:text-gray-600 transition-colors ${isGenerating ? 'opacity-50 cursor-not-allowed' : ''}`}
                        title="Regenerate"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path><path d="M16 16h5v5"></path></svg>
                      </button>
                      <button
                        onClick={() => handleDeleteMessage(index)}
                        disabled={isGenerating}
                        className={`hover:text-red-500 transition-colors ${isGenerating ? 'opacity-50 cursor-not-allowed' : ''}`}
                        title="Delete this message and continue from here"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  )}

                  {/* Timestamp & Actions for User Messages */}
                  {message.role === 'user' && (
                    <div className="flex items-center gap-2 mt-1.5 mr-1 text-gray-400 justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                      {/* Timestamp */}
                      <span className="text-xs text-gray-400" title={message.timestamp.toLocaleString()}>
                        {formatTimestamp(message.timestamp)}
                      </span>

                      <div className="w-px h-4 bg-gray-200" />

                      <button
                        onClick={() => handleDeleteMessage(index)}
                        disabled={isGenerating}
                        className={`hover:text-red-500 transition-colors ${isGenerating ? 'opacity-50 cursor-not-allowed' : ''}`}
                        title="Delete this message and continue from here"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))
            })()}

            {/* Live Input Preview Bubble - shows text input or voice transcript in real-time */}
            {(realtimePartialText || input.trim()) && (
              <div className="flex gap-4 flex-row-reverse items-start animate-in fade-in slide-in-from-bottom-2 duration-200 mb-6">
                {/* Avatar */}
                <div className="flex-shrink-0">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center shadow-md ring-2 ring-white">
                    <User className="w-5 h-5 text-white" />
                  </div>
                </div>

                {/* Message Content */}
                <div className="flex-1 min-w-0 max-w-[80%] flex flex-col items-end">
                  {/* Message Bubble - slightly transparent for preview effect */}
                  <div className="relative px-5 py-3.5 text-[15px] leading-7 shadow-sm bg-gradient-to-br from-primary-400 to-primary-500 text-white rounded-[20px] rounded-tr-sm selection:bg-white/30 opacity-80 max-h-[120px] overflow-y-auto scrollbar-hide">
                    <div className="whitespace-pre-wrap break-words flex items-center gap-2">
                      <span>{realtimePartialText || input}</span>
                      {/* Show typing indicator only for voice input */}
                      {realtimePartialText && (
                        <span className="inline-flex gap-0.5">
                          <span className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                          <span className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                          <span className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>
        </div>


        {/* Input Area - Floating Island - Fixed to viewport bottom */}
        <div className="fixed bottom-6 left-0 right-0 px-4 z-30 pointer-events-none">
          <div className="max-w-4xl mx-auto pointer-events-auto">
            {/* Attachments Preview */}
            {(imageAttachments.length > 0 || fileAttachments.length > 0) && (
              <div className="mb-3 flex flex-wrap gap-2 p-3 bg-white/90 backdrop-blur-xl rounded-2xl border border-gray-200/50 shadow-lg animate-in slide-in-from-bottom-2 duration-300">
                {imageAttachments.map((attachment) => (
                  <div key={attachment.id} className="relative group">
                    <img
                      src={attachment.preview}
                      alt="Attachment"
                      className="w-14 h-14 object-cover rounded-xl border border-white/50 shadow-sm"
                    />
                    <button
                      type="button"
                      onClick={() => handleImageRemove(attachment.id)}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-900/80 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity backdrop-blur-sm"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
                {fileAttachments.map((attachment) => (
                  <div key={attachment.id} className="relative group flex items-start p-2 bg-gray-50/50 rounded-xl border border-gray-100">
                    <div className="flex-shrink-0 w-10 h-10 bg-white rounded-lg shadow-sm flex items-center justify-center mr-2">
                      <FileSpreadsheet className="w-5 h-5 text-green-600" />
                    </div>
                    <div className="max-w-[120px]">
                      <div className="text-xs font-medium text-gray-900 truncate">{attachment.name}</div>
                      <div className="text-[10px] text-gray-500 uppercase">{attachment.type}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleFileRemove(attachment.id)}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-900/80 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity backdrop-blur-sm"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <form id="chat-form" onSubmit={handleSubmit} className="relative group">
              <div className={`
                relative flex items-center 
                bg-white/80 backdrop-blur-xl 
                rounded-[28px] shadow-[0_8px_32px_rgba(0,0,0,0.12)] 
                border transition-all duration-300
                ${voiceSessionActive
                  ? 'border-primary-300 shadow-[0_0_0_4px_rgba(102,126,234,0.15)] bg-white/90'
                  : 'border-gray-200/50 hover:border-gray-300/80 hover:shadow-[0_8px_40px_rgba(0,0,0,0.15)]'
                }
                min-h-[56px] pl-4 pr-[104px] sm:pr-[120px] py-1.5
              `}>
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={voiceSessionActive ? "Listening..." : "Describe your research task..."}
                  className={`
                    w-full bg-transparent border-none focus:outline-none resize-none 
                    text-gray-900 placeholder-gray-400 transition-all 
                    text-[15px] leading-relaxed py-2.5 scrollbar-hide
                    ${(realtimeIsRecording || voiceSessionActive) ? 'opacity-0' : 'opacity-100'}
                  `}
                  rows={1}
                  style={{ maxHeight: '150px' }}
                  disabled={isGenerating}
                  autoFocus
                />

                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                />

                {/* Voice Visualizer Overlay with Realtime Transcript */}
                {(realtimeIsRecording || realtimeIsConnecting) && (
                  <div className="absolute left-4 right-[140px] top-0 bottom-0 flex items-center pointer-events-none">
                    {realtimePartialText ? (
                      // Show realtime transcript when available
                      <div className="w-full flex items-center gap-2 text-gray-700 text-[15px] leading-relaxed overflow-hidden">
                        <span className="truncate">{realtimePartialText}</span>
                        <span className="flex-shrink-0 inline-flex gap-0.5">
                          <span className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                          <span className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                          <span className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                        </span>
                      </div>
                    ) : (
                      // Show audio visualizer when no transcript yet
                      <AudioVisualizer stream={realtimeMediaStream} isActive={realtimeIsRecording} className="w-full h-12 opacity-80" />
                    )}
                  </div>
                )}

                {/* Voice Session Waiting State */}
                {voiceSessionActive && !realtimeIsRecording && isLoading && (
                  <div className="absolute left-4 right-[140px] top-0 bottom-0 flex items-center justify-center pointer-events-none">
                    <span className="flex items-center gap-2 text-sm text-primary-600 font-medium animate-pulse">
                      <div className="w-2 h-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-2 h-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-2 h-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                      Thinking
                    </span>
                  </div>
                )}


                <div className="absolute right-1.5 bottom-1.5 flex items-center gap-1 sm:gap-1.5">
                  {/* File Upload */}
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isGenerating || realtimeIsRecording || voiceSessionActive}
                    className="p-2 sm:p-2.5 rounded-full transition-all text-gray-400 hover:text-gray-600 hover:bg-gray-100 active:scale-95 disabled:opacity-50"
                  >
                    <Paperclip className="w-4 h-4 sm:w-5 sm:h-5" />
                  </button>

                  {/* Voice Button */}
                  <button
                    type="button"
                    onClick={toggleVoiceSession}
                    disabled={isGenerating && !voiceSessionActive}
                    className={`
                      p-2 sm:p-2.5 rounded-full transition-all duration-300 active:scale-95
                      ${realtimeIsRecording || realtimeIsConnecting
                        ? 'bg-red-500 text-white shadow-md animate-pulse'
                        : voiceSessionActive
                          ? 'bg-primary-500 text-white shadow-md'
                          : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                      }
                    `}
                  >
                    {realtimeIsConnecting ? (
                      <Loader2 className="w-4 h-4 sm:w-5 sm:h-5 animate-spin" />
                    ) : (realtimeIsRecording || voiceSessionActive) ? (
                      <MicOff className="w-4 h-4 sm:w-5 sm:h-5" />
                    ) : (
                      <Mic className="w-4 h-4 sm:w-5 sm:h-5" />
                    )}
                  </button>

                  {/* Send / Stop Button */}
                  {isGenerating ? (
                    <button
                      type="button"
                      onClick={handleStopGeneration}
                      className="p-2 sm:p-2.5 rounded-full transition-all duration-300 shadow-sm bg-gray-800 text-white hover:bg-gray-900 shadow-md active:scale-95"
                      title="Stop generating"
                    >
                      <Square className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" />
                    </button>
                  ) : (
                    <button
                      type="submit"
                      disabled={!input.trim() && imageAttachments.length === 0 && fileAttachments.length === 0}
                      className={`
                          p-2 sm:p-2.5 rounded-full transition-all duration-300 shadow-sm
                          ${!input.trim() && imageAttachments.length === 0 && fileAttachments.length === 0
                          ? 'bg-gray-100 text-gray-300 cursor-not-allowed'
                          : 'bg-primary-600 text-white hover:bg-primary-700 shadow-md active:scale-95'
                        }
                      `}
                    >
                      <Send className="w-4 h-4 sm:w-5 sm:h-5" />
                    </button>
                  )}
                </div>
              </div>
            </form>

            <div className="mt-2 text-center text-[8px] sm:text-xs text-gray-400/80 font-medium truncate px-4">
              PathLab Agent can make mistakes. Consider checking important information.
            </div>
          </div>
        </div>
      </div>



      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all scale-100">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {deleteConfirmId === 'all-conversations' ? 'Delete All History' : 'Delete Conversation'}
                </h3>
                <p className="text-sm text-gray-600 mb-6">
                  {deleteConfirmId === 'all-conversations'
                    ? 'Are you sure you want to delete all chat history? This action cannot be undone.'
                    : 'Are you sure you want to delete this conversation? This action cannot be undone.'}
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={cancelDelete}
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmDelete}
                    className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors shadow-sm"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast notification */}
      {toastMessage && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-in slide-in-from-top-2 duration-300 ${toastMessage.type === 'error' ? 'bg-red-500 text-white' :
          toastMessage.type === 'success' ? 'bg-green-500 text-white' : 'bg-blue-500 text-white'
          }`}>
          <span>{toastMessage.message}</span>
          <button
            onClick={() => setToastMessage(null)}
            className="ml-2 hover:opacity-80"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}


