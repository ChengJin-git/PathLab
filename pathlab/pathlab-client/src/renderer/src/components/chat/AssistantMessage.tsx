/**
 * AssistantMessage — renders a single AI assistant message with special block parsing.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */
import React from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { OptionButtons, parseOptions, removeOptionsBlock } from './OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from './TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from './ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from './CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from './NavigationCard'

import { InferenceConfigCard, parseInferenceConfig, removeInferenceConfigBlock } from './InferenceConfigCard'
import { AnalysisConfigCard, parseAnalysisConfig, removeAnalysisConfigBlock } from './AnalysisConfigCard'
import { MetricCard, parseMetricConfig, removeMetricConfigBlock } from './MetricCard'
import { ChartCard, parseChartConfig, removeChartConfigBlock } from './ChartCard'
import { QuickAnalysisViewer, parseQuickAnalysisConfig, removeQuickAnalysisConfigBlock, CachedAnalysisData } from './QuickAnalysisViewer'
import { TaskHistoryCard, parseTaskHistoryConfig, removeTaskHistoryConfigBlock, CachedTaskData } from './TaskHistoryCard'
import { CancelTaskCard, parseCancelTaskConfig, removeCancelTaskBlock } from './CancelTaskCard'
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from './DatasetRegistrationCard'
import { MetadataUploadCard, parseMetadataUploadConfig, removeMetadataUploadBlock } from './MetadataUploadCard'
import { ModelListCard, parseModelListConfig, removeModelListBlock } from './ModelListCard'
import { RenameTaskCard, parseRenameTaskConfig, removeRenameTaskBlock } from './RenameTaskCard'
import { removeVoiceControlBlock } from './VoiceControlBlock'
import SearchingStatus, {
  parseSearchStatus,
  removeSearchStatusBlock,
  SearchCompletedCard,
  parseWebSearchResult,
  removeWebSearchResultBlock
} from './SearchingStatus'
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
  ModelListSkeleton,
  cardTransition
} from './CardSkeletons'

// Props interface for AssistantMessage component
export interface AssistantMessageProps {
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
  onMetadataUploadSuccess: (result: import('../../api').UploadSplitsResponse, datasetId: string, messageId: string) => void
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
  'RENAME_TASK',
  'TASK_HISTORY_CONFIG',
  'VOICE_CONTROL',
  'SUBMIT_TASK',  // Voice command to trigger submit on existing TaskConfigCard
  'CANCEL_TASK_NOW',  // Voice command to trigger cancel on existing CancelTaskCard
  'DATASET_UPLOAD',
  'METADATA_UPLOAD',
  'MODEL_LIST'
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
export function parseSubmitTask(content: string): boolean {
  const match = content.match(/\[SUBMIT_TASK\]([\s\S]*?)\[\/SUBMIT_TASK\]/)
  return !!match
}

// Remove [SUBMIT_TASK] block from content
export function removeSubmitTaskBlock(content: string): string {
  return content.replace(/\[SUBMIT_TASK\][\s\S]*?\[\/SUBMIT_TASK\]/g, '').trim()
}

// Parse [CANCEL_TASK_NOW] block - triggers cancel on existing CancelTaskCard
export function parseCancelTaskNow(content: string): boolean {
  const match = content.match(/\[CANCEL_TASK_NOW\]([\s\S]*?)\[\/CANCEL_TASK_NOW\]/)
  return !!match
}

// Remove [CANCEL_TASK_NOW] block from content
export function removeCancelTaskNowBlock(content: string): string {
  return content.replace(/\[CANCEL_TASK_NOW\][\s\S]*?\[\/CANCEL_TASK_NOW\]/g, '').trim()
}

/**
 * Check if an assistant message contains only internal-use blocks (no user-facing content).
 * Such messages should not be rendered as visible bubbles.
 * This handles the case where AI responds with only [VOICE_CONTROL], [SUBMIT_TASK], or [CANCEL_TASK_NOW].
 */
export function isInternalOnlyMessage(content: string): boolean {
  if (!content) return false // empty content shows "Thinking..." indicator
  let stripped = content
  stripped = removeVoiceControlBlock(stripped)
  stripped = removeSubmitTaskBlock(stripped)
  stripped = removeCancelTaskNowBlock(stripped)
  return stripped.trim() === ''
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
  const { t } = useTranslation()
  // Parse special blocks
  const searchStatus = parseSearchStatus(content)
  const webSearchResult = parseWebSearchResult(content)
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
  const renameTaskConfig = parseRenameTaskConfig(content)
  const datasetRegistrationConfig = parseDatasetRegistrationConfig(content)
  const metadataUploadConfig = parseMetadataUploadConfig(content)
  const modelListConfig = parseModelListConfig(content)

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
  if (renameTaskConfig) displayContent = removeRenameTaskBlock(displayContent)
  if (datasetRegistrationConfig) displayContent = removeDatasetRegistrationBlock(displayContent)
  if (metadataUploadConfig) displayContent = removeMetadataUploadBlock(displayContent)
  if (modelListConfig) displayContent = removeModelListBlock(displayContent)
  // Remove SEARCH_STATUS block - it handled separately
  if (searchStatus) displayContent = removeSearchStatusBlock(displayContent)
  // Remove WEB_SEARCH_RESULT block - it handled separately
  if (webSearchResult) displayContent = removeWebSearchResultBlock(displayContent)
  // Remove WEB_SEARCH request block - AI's internal search request
  displayContent = displayContent.replace(/\[WEB_SEARCH\][\s\S]*?\[\/WEB_SEARCH\]/g, '').trim()
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
      {/* Searching Status indicator */}
      {searchStatus && (
        <SearchingStatus query={searchStatus.query} reason={searchStatus.reason} />
      )}

      {/* Search Completed Card */}
      {webSearchResult && (
        <SearchCompletedCard
          query={webSearchResult.query}
          resultCount={webSearchResult.results?.length || 0}
        />
      )}

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
                onToast({ type: 'success', message: t('chatComponents.assistantMessage.csvUploadedSuccess') })
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
              onSuccess={(taskId) => onToast({ type: 'success', message: t('chatComponents.assistantMessage.taskCancelledSuccess', { taskId }) })}
              onError={(error) => onToast({ type: 'error', message: error })}
              cancelTrigger={cancelTaskTrigger}
            />
          </motion.div>
        ) : incompleteTag === 'CANCEL_TASK' && (
          <motion.div key="cancel-task-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Rename Task card */}
        {renameTaskConfig ? (
          <motion.div key="rename-task-real" {...cardTransition}>
            <RenameTaskCard
              config={renameTaskConfig}
              onSuccess={(taskId, newName) => onToast({ type: 'success', message: t('chatComponents.assistantMessage.taskRenamedSuccess', { newName }) })}
              onError={(error) => onToast({ type: 'error', message: error })}
            />
          </motion.div>
        ) : incompleteTag === 'RENAME_TASK' && (
          <motion.div key="rename-task-skeleton" {...cardTransition}>
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

        {/* Model List Card */}
        {modelListConfig ? (
          <motion.div key="model-list-real" {...cardTransition}>
            <ModelListCard config={modelListConfig} />
          </motion.div>
        ) : incompleteTag === 'MODEL_LIST' && (
          <motion.div key="model-list-skeleton" {...cardTransition}>
            <ModelListSkeleton />
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
          'METADATA_UPLOAD',
          'MODEL_LIST'
        ].includes(incompleteTag) && (
            <motion.div key="generic-skeleton" {...cardTransition}>
              <GenericCardSkeleton />
            </motion.div>
          )}
      </AnimatePresence>

    </div>
  )
})

export default AssistantMessage

