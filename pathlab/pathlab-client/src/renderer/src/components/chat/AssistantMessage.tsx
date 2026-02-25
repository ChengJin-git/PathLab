/**
 * AssistantMessage — renders a single AI assistant message with special block parsing.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */
import React, { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAuthToken } from '../../api/client'

import { OptionButtons, parseOptions, removeOptionsBlock } from './OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from './TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from './ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from './CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from './NavigationCard'
import { ReferenceCardList, parseAllReferenceCards, removeAllReferenceBlocks } from './ReferenceCard'
import InlineCitation from './InlineCitation'

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
  SummarizingSearchStatus,
  parseWebSearchResult,
  removeWebSearchResultBlock,
  parseAllPdfParseStatus,
  removePdfParseStatusBlock,
  PdfParsingStatus,
  PdfParsingCompletedCard
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
  'MODEL_LIST',
  'REFERENCE',
  'PDF_PARSE_STATUS',
  'SEARCH_STATUS',
  'WEB_SEARCH_RESULT',
  'WEB_SEARCH',
  'CITATION_CONTEXTS'
]

/**
 * Identify any incomplete/streaming special blocks in content.
 * Returns the cleaned content (without the incomplete block) and the tag of the incomplete block.
 *
 * When isStreaming is true, also detects partial tag prefixes at the end of the content.
 * For example, if the AI is streaming "[OPTIO" (not yet complete "[OPTIONS]"),
 * this function will detect it as an incomplete OPTIONS block and show the skeleton.
 */
function getIncompleteBlock(content: string, isStreaming: boolean = false): { content: string; incompleteTag: string | null } {
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

  // During streaming, detect partial tag prefixes at the end of content.
  // e.g. content ending with "[OPTIO" should be recognised as an incomplete OPTIONS block.
  if (isStreaming && !incompleteTag) {
    const lastBracket = result.lastIndexOf('[')
    if (lastBracket !== -1) {
      const trailing = result.substring(lastBracket)
      // Only consider if the bracket is unclosed (no ']' after it)
      if (!trailing.includes(']')) {
        const partialTag = trailing.substring(1) // text after '['
        if (partialTag.length > 0) {
          for (const tag of SPECIAL_BLOCK_TAGS) {
            if (tag.startsWith(partialTag)) {
              result = result.substring(0, lastBracket).trim()
              incompleteTag = tag
              break
            }
          }
        }
      }
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

// ── Citation Contexts (article reading) ─────────────────────────────────────

/** Parsed citation context for a single [N, p.Y] reference. */
export interface CitationContext {
  page: number
  context: string
}

/**
 * Parse [CITATION_CONTEXTS] block from content.
 * Returns a map keyed by "N-pY" → { page, context }, or null if absent.
 */
export function parseCitationContexts(
  content: string
): Record<string, CitationContext> | null {
  const match = content.match(/\[CITATION_CONTEXTS\]([\s\S]*?)\[\/CITATION_CONTEXTS\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch {
    return null
  }
}

/** Remove [CITATION_CONTEXTS] block from display content. */
export function removeCitationContextsBlock(content: string): string {
  return content.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '').trim()
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
  const referenceCards = parseAllReferenceCards(content)
  const pdfParseStatusItems = parseAllPdfParseStatus(content)
  const citationContexts = parseCitationContexts(content)

  // For article citations, build a sequential renumbering map.
  // AI uses [N, p.Y] where N is always the same paper number (e.g. 1).
  // We renumber each unique "N-pY" by order of first appearance → 1, 2, 3, ...
  // This map is used by both citationMap and the regex replacement below.
  const articleCitationRenumber = useMemo(() => {
    // General pattern: [N, p.ANY_PAGE_DESCRIPTION] — matches p.2, p.2-3, p.2, p.4, etc.
    // Works independently of citationContexts so renumbering is correct during streaming.
    const renumber = new Map<string, number>() // "N-p.X" → sequential index
    const pattern = /\[(\d{1,2}),\s*(p\.[^\]]+)\]/g
    let m: RegExpExecArray | null
    let seq = 1
    while ((m = pattern.exec(content)) !== null) {
      // Normalize key: remove whitespace for consistent lookup
      const key = `${m[1]}-${m[2].replace(/\s/g, '')}`
      if (!renumber.has(key)) {
        renumber.set(key, seq++)
      }
    }
    return renumber.size > 0 ? renumber : null
  }, [content])

  // Build citation lookup map from web search results + article citation contexts.
  // Maps citation display index (1-based) to { title, url, snippet, source, pageInfo? }
  const citationMap = useMemo(() => {
    const map = new Map<number, { title: string; url: string; snippet: string; source: string; pageInfo?: string }>()
    // 1) Web search results — index is 1-based ordinal
    if (webSearchResult?.results) {
      webSearchResult.results.forEach((r, i) => {
        let source = 'Unknown'
        try { source = new URL(r.url).hostname.replace(/^www\./, '') } catch { /* ignore */ }
        map.set(i + 1, { title: r.title, url: r.url, snippet: r.snippet, source })
      })
    }
    // 2) Article citation contexts — keyed "N-p.X" (normalized), renumbered sequentially
    if (citationContexts && articleCitationRenumber) {
      const refCard = referenceCards?.[0]
      const refSource = refCard?.url ? (() => { try { return new URL(refCard.url).hostname.replace(/^www\./, '') } catch { return '' } })() : ''
      for (const [key, ctx] of Object.entries(citationContexts)) {
        const seqIdx = articleCitationRenumber.get(key)
        if (!seqIdx) continue
        // Extract page info from key (e.g. "1-p.2" → "p.2", "1-p.2-3" → "p.2-3", "1-p.2,p.4" → "p.2,p.4")
        const pageFromKey = key.replace(/^\d+-/, '')
        map.set(seqIdx, {
          title: refCard?.title || '',
          url: refCard?.url || '',
          snippet: ctx.context,
          source: refSource,
          pageInfo: pageFromKey,
        })
      }
    }
    return map
  }, [webSearchResult, citationContexts, articleCitationRenumber, referenceCards])

  // Custom ReactMarkdown components:
  // - img: inject auth token for /pdf-images/ URLs so <img> tags can load authenticated images
  // - hr: render a visually refined separator instead of the default ugly <hr>
  // - a: render InlineCitation for cite:// protocol links
  const markdownComponents = useMemo<Components>(() => ({
    img: ({ src, alt, ...rest }) => {
      let finalSrc = src || ''
      if (finalSrc.includes('/pdf-images/')) {
        const token = getAuthToken()
        if (token) {
          const sep = finalSrc.includes('?') ? '&' : '?'
          finalSrc = `${finalSrc}${sep}token=${encodeURIComponent(token)}`
        }
      }
      return <img src={finalSrc} alt={alt || ''} loading="lazy" {...rest} />
    },
    hr: () => (
      <div className="my-6 flex items-center gap-3">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
        <div className="w-1 h-1 rounded-full bg-gray-300" />
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
      </div>
    ),
    a: ({ href, children, ...rest }) => {
      // Detect #cite-N hash links and render InlineCitation component
      const citationMatch = href?.match(/^#cite-(\d+)$/)
      if (citationMatch) {
        const index = parseInt(citationMatch[1])
        const data = citationMap.get(index)
        const pageInfo = data?.pageInfo
        return (
          <InlineCitation
            index={index}
            title={data?.title}
            source={data?.source}
            snippet={data?.snippet}
            pageInfo={pageInfo}
            url={data?.url}
          />
        )
      }
      return <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>
    },
  }), [citationMap])

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
  // Remove PDF_PARSE_STATUS blocks - handled separately
  if (pdfParseStatusItems) displayContent = removePdfParseStatusBlock(displayContent)
  // Remove WEB_SEARCH request block - AI's internal search request
  displayContent = displayContent.replace(/\[WEB_SEARCH\][\s\S]*?\[\/WEB_SEARCH\]/g, '').trim()
  // Remove READ_ARTICLE request block - AI's internal article reading request
  displayContent = displayContent.replace(/\[READ_ARTICLE\][\s\S]*?\[\/READ_ARTICLE\]/g, '').trim()
  // Remove VOICE_CONTROL block - it's for internal use only
  displayContent = removeVoiceControlBlock(displayContent)
  // Remove SUBMIT_TASK block - it's for internal use only (voice command to trigger submit)
  displayContent = removeSubmitTaskBlock(displayContent)
  // Remove CANCEL_TASK_NOW block - it's for internal use only (voice command to trigger cancel)
  displayContent = removeCancelTaskNowBlock(displayContent)
  // Remove REFERENCE blocks - rendered as cards
  displayContent = removeAllReferenceBlocks(displayContent)
  // Remove CITATION_CONTEXTS block - data consumed by citationMap, not for display
  // Always strip (even if parsing failed) to prevent raw JSON from showing
  displayContent = removeCitationContextsBlock(displayContent)

  // Convert inline citation patterns to markdown links with #cite- hash
  // Hash links are not sanitized by ReactMarkdown (unlike custom protocols like cite://)
  // Badge text shows only the sequential index number; page info is in the tooltip via citationMap.
  // Handle more specific patterns first to avoid partial matches
  // 1. [Paper N, p.Y / Page Y / any page desc] (legacy backend format)
  if (articleCitationRenumber) {
    displayContent = displayContent.replace(
      /\[Paper\s+(\d{1,2}),\s*(p\.[^\]]+|Page\s*[^\]]+)\](?!\()/g,
      (_match, n, pagesPart) => {
        const key = `${n}-${pagesPart.replace(/\s/g, '').replace(/^Page/, 'p.')}`
        const seq = articleCitationRenumber.get(key) || n
        return `[${seq}](#cite-${seq})`
      }
    )
  } else {
    displayContent = displayContent.replace(
      /\[Paper\s+(\d{1,2}),\s*(?:p\.[^\]]+|Page\s*[^\]]+)\](?!\()/g,
      '[$1](#cite-$1)'
    )
  }
  // 2. [Paper N] (legacy backend format, fallback)
  displayContent = displayContent.replace(
    /\[Paper\s+(\d{1,2})\](?!\()/g,
    '[$1](#cite-$1)'
  )
  // 3. [N, p.ANY_PAGE_DESC] (current general format) — matches p.2, p.2-3, p.2, p.4, etc.
  if (articleCitationRenumber) {
    displayContent = displayContent.replace(
      /\[(\d{1,2}),\s*(p\.[^\]]+)\](?!\()/g,
      (_match, n, pagesPart) => {
        const key = `${n}-${pagesPart.replace(/\s/g, '')}`
        const seq = articleCitationRenumber.get(key) || n
        return `[${seq}](#cite-${seq})`
      }
    )
  } else {
    displayContent = displayContent.replace(
      /\[(\d{1,2}),\s*(p\.[^\]]+)\](?!\()/g,
      '[$1](#cite-$1)'
    )
  }
  // 4. [N, M, ...] (comma-separated multi-citation) — e.g. [1, 8] or [1,2,3]
  //    Split into individual citation links: [1](#cite-1)[8](#cite-8)
  if (citationMap.size > 0) {
    displayContent = displayContent.replace(
      /\[(\d{1,2}(?:\s*,\s*\d{1,2})+)\](?!\()/g,
      (_match, inner: string) => {
        return inner.split(',').map(s => {
          const n = s.trim()
          return `[${n}](#cite-${n})`
        }).join('')
      }
    )
  }
  // 5. [N] (simple citation) — only match when citationMap has data to avoid
  //    false positives with markdown footnotes/list references
  if (citationMap.size > 0) {
    displayContent = displayContent.replace(
      /\[(\d{1,2})\](?!\()/g,
      '[$1](#cite-$1)'
    )
  }

  // Remove any incomplete blocks that are still streaming
  const { content: cleanedContent, incompleteTag } = getIncompleteBlock(displayContent, isStreaming)
  displayContent = cleanedContent

	  // Show searching indicator only while streaming and before results arrive
	  const showSearchingStatus = !!searchStatus && !webSearchResult && isStreaming

    // PDF parsing status: show animated indicator while any PDF is still "parsing"
    const hasPdfParsingInProgress = pdfParseStatusItems?.some(i => i.status === 'parsing') ?? false
    const showPdfParsingStatus = !!pdfParseStatusItems && hasPdfParsingInProgress && isStreaming
    // Show completed card when all PDFs are done (not streaming OR all statuses are final)
    const showPdfParsingCompleted = !!pdfParseStatusItems && !hasPdfParsingInProgress

    // Show "summarizing search results" indicator after search completes but before
    // the AI starts streaming actual summary text. This fills the visual gap between
    // the search-completed card and the streamed markdown content.
    const showSummarizingSearch = !!webSearchResult && isStreaming && !displayContent.trim()

	  return (
    <div className="w-full min-w-0">
      {/* Searching Status indicator */}
	      {showSearchingStatus && (
	        <SearchingStatus query={searchStatus?.query} reason={searchStatus?.reason} />
      )}

      {/* Search Completed Card */}
      {webSearchResult && (
        <SearchCompletedCard
          query={webSearchResult.query}
          resultCount={webSearchResult.results?.length || 0}
          results={webSearchResult.results}
        />
      )}

      {/* Summarizing Search Results indicator */}
      {showSummarizingSearch && (
        <SummarizingSearchStatus />
      )}

      {/* PDF Parsing Status indicator */}
      {showPdfParsingStatus && pdfParseStatusItems && (
        <PdfParsingStatus items={pdfParseStatusItems} />
      )}

      {/* PDF Parsing Completed Card */}
      {showPdfParsingCompleted && pdfParseStatusItems && (
        <PdfParsingCompletedCard items={pdfParseStatusItems} />
      )}

	      {/* Markdown content — no skeleton; stream starts directly */}
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
	          prose-table:text-sm prose-th:bg-gray-50 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-td:border-gray-200
          prose-img:rounded-lg prose-img:shadow-md prose-img:my-3 prose-img:max-w-full prose-img:h-auto prose-img:border prose-img:border-gray-200">
	          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
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
          'RENAME_TASK',
          'DATASET_REGISTRATION',
          'METADATA_UPLOAD',
          'MODEL_LIST',
          'CITATION_CONTEXTS',
          'REFERENCE',
          'WEB_SEARCH_RESULT',
          'SEARCH_STATUS',
          'PDF_PARSE_STATUS',
          'WEB_SEARCH',
          'READ_ARTICLE',
          'VOICE_CONTROL',
          'SUBMIT_TASK',
          'CANCEL_TASK_NOW'
        ].includes(incompleteTag) && (
            <motion.div key="generic-skeleton" {...cardTransition}>
              <GenericCardSkeleton />
            </motion.div>
          )}
      </AnimatePresence>

      {/* Reference Cards */}
      {referenceCards && referenceCards.length > 0 && (
        <ReferenceCardList cards={referenceCards} />
      )}
    </div>
  )
})

export default AssistantMessage

