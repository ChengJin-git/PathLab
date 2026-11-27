import React, { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Plus, Copy, Check, Loader2 } from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkCjkFriendly from 'remark-cjk-friendly/parseOnly'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'
import { withAuthTokenQuery } from '../../api/client'
import { type MessageArtifacts } from '../../api'

import { OptionButtons, parseOptions, removeOptionsBlock } from './OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from './TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from './ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from './CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from './NavigationCard'
import { ReferenceCardList, parseAllReferenceCards, removeAllReferenceBlocks } from './ReferenceCard'
import InlineCitation from './InlineCitation'
import { createCitationRenderer, parseCitationContexts, prepareStreamingMarkdown } from './chatCitations'
export { findReferenceCardForCitation, parseCitationContexts } from './chatCitations'
export type { CitationContext } from './chatCitations'

import { AnalysisConfigCard, parseAnalysisConfig, removeAnalysisConfigBlock } from './AnalysisConfigCard'
import { MetricCard, parseMetricConfig, removeMetricConfigBlock } from './MetricCard'
import { ChartCard, parseChartConfig, removeChartConfigBlock } from './ChartCard'
import { QuickAnalysisViewer, parseQuickAnalysisConfig, removeQuickAnalysisConfigBlock, CachedAnalysisData } from './QuickAnalysisViewer'
import { TaskHistoryCard, parseTaskHistoryConfig, removeTaskHistoryConfigBlock, CachedTaskData } from './TaskHistoryCard'
import { CancelTaskCard, parseCancelTaskConfig, removeCancelTaskBlock } from './CancelTaskCard'
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from './DatasetRegistrationCard'
import { MetadataUploadCard, parseMetadataUploadConfig, removeMetadataUploadBlock } from './MetadataUploadCard'
import DatasetEditCard, { parseDatasetEdit } from './DatasetEditCard'
import { ModelListCard, parseModelListConfig, removeModelListBlock } from './ModelListCard'
import PatchInferenceCard, { parsePatchInferenceConfig, removePatchInferenceBlock } from './PatchInferenceCard'
import { BatchInferenceSummaryCard, parseBatchInferenceSummary, removeBatchInferenceSummaryBlock } from './BatchInferenceSummaryCard'
import { BatchInferenceConfigCard, parseBatchInferenceConfig, removeBatchInferenceConfigBlock } from './BatchInferenceConfigCard'
import { RenameTaskCard, parseRenameTaskConfig, removeRenameTaskBlock } from './RenameTaskCard'
import { removeVoiceControlBlock } from './VoiceControlBlock'
import SearchingStatus, {
  SearchResultsZone,
  SummarizingSearchStatus,
  SummarizingPdfStatus,
  PdfParsingStatus,
  PdfParsingCompletedCard
} from './SearchingStatus'
import {
  TaskConfigSkeleton,
  OptionButtonsSkeleton,
  AnalysisConfigSkeleton,
  ChartSkeleton,
  MetricSkeleton,
  ImageRecommendationSkeleton,
  CSVActionSkeleton,
  QuickAnalysisViewerSkeleton,
  GenericCardSkeleton,
  ModelListSkeleton,
  cardTransition
} from './CardSkeletons'
import { stripChatBlocks } from './chatBlockParsing'
import {Link} from 'react-router-dom'
import { FUNCTIONAL_CARD_INCOMPLETE_TAGS, SPECIAL_BLOCK_TAGS, getIncompleteBlock } from '../../lib/utils/chatBlockRegistry'
import FileDeliveryCard, { parseDeliveredFiles } from './FileDeliveryCard'
import ActivityStrip from './ActivityStrip'
import ResearchHandoffCard from './ResearchHandoffCard'
import { useWorkbenchText } from './workbenchText'
import type { AutoResearchSessionSummary } from '../../types/autoresearch'

export interface AssistantMessageProps {
  content: string
  messageId: string
  onOptionSelect: (text: string) => void
  onTaskSubmitSuccess: (taskId: string, messageId: string) => void
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
  onNewChat?: () => void  // Callback to start a new conversation (context limit card)
  conversationId?: string
  referenceImages?: string[]
  onMessageContentReplace?: (messageId: string, updatedContent: string, errorToastKey?: string) => void | Promise<void>
  searchArtifacts?: MessageArtifacts | null
  researchSessions?: AutoResearchSessionSummary[]
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

// Parse [CONTEXT_LIMIT] block — signals a true upstream context-window overflow
export function parseContextLimit(content: string): boolean {
  return /\[CONTEXT_LIMIT\][\s\S]*?\[\/CONTEXT_LIMIT\]/i.test(content)
}

// Remove [CONTEXT_LIMIT] block from content
export function removeContextLimitBlock(content: string): string {
  return content.replace(/\[CONTEXT_LIMIT\][\s\S]*?\[\/CONTEXT_LIMIT\]/gi, '').trim()
}

// Parse [RESPONSE_TRUNCATED] block — signals the answer hit an output-length limit
export function parseResponseTruncated(content: string): boolean {
  return /\[RESPONSE_TRUNCATED\][\s\S]*?\[\/RESPONSE_TRUNCATED\]/i.test(content)
}

// Remove [RESPONSE_TRUNCATED] block from content
export function removeResponseTruncatedBlock(content: string): string {
  return content.replace(/\[RESPONSE_TRUNCATED\][\s\S]*?\[\/RESPONSE_TRUNCATED\]/gi, '').trim()
}

// ── Citation Contexts (article reading) ─────────────────────────────────────

/** Remove [CITATION_CONTEXTS] block from display content. */
export function removeCitationContextsBlock(content: string): string {
  return content.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '').trim()
}

/**
 * Check if an assistant message contains only internal-use blocks (no user-facing content).
 * Such messages should not be rendered as visible bubbles.
 * This handles pure internal control / tool blocks such as [VOICE_CONTROL],
 * [SUBMIT_TASK], [CANCEL_TASK_NOW], [WEB_SEARCH], or [READ_ARTICLE].
 */
export function isInternalOnlyMessage(content: string): boolean {
  if (!content) return false // empty content shows "Thinking..." indicator
  let stripped = content
  stripped = removeVoiceControlBlock(stripped)
  stripped = removeSubmitTaskBlock(stripped)
  stripped = removeCancelTaskNowBlock(stripped)
  stripped = stripChatBlocks(stripped, ['WEB_SEARCH', 'READ_ARTICLE', 'LOAD_CAPABILITY', 'CITATION_CONTEXTS'])
  stripped = removeEmptyFencedCodeBlocks(stripped)
  stripped = removeDanglingFenceArtifacts(stripped)
  return stripped.trim() === ''
}

function normalizeCodeLanguage(className?: string): string {
  const raw = className?.match(/language-([\w-]+)/)?.[1]?.toLowerCase() || ''
  if (!raw) return 'text'
  if (raw === 'plaintext' || raw === 'plain') return 'text'
  if (raw === 'shell' || raw === 'bash' || raw === 'zsh') return 'bash'
  if (raw === 'bib' || raw === 'bibtex') return 'bibtex'
  if (raw === 'tsx' || raw === 'jsx' || raw === 'typescript' || raw === 'javascript') return raw
  if (raw === 'monofont') return 'text'
  return raw
}

function removeEmptyFencedCodeBlocks(content: string): string {
  return content.replace(
    /(^|\n)```[^\n`]*\r?\n(?:[ \t]*\r?\n)*```[ \t]*(?=\n|$)/g,
    '$1'
  )
}

function removeDanglingFenceArtifacts(content: string): string {
  let cleaned = content

  cleaned = cleaned.replace(/(^|\n)```[^\n`]*\r?\n(?:[ \t]*\r?\n?)*$/g, '$1')

  const meaningfulLines = cleaned
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)

  if (meaningfulLines.length > 0 && meaningfulLines.every(line => /^```[^`]*$/.test(line))) {
    return ''
  }

  return cleaned
}

const CODE_FONT_STACK = 'JetBrains Mono, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace'

function extractNodeText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node)
  }
  if (Array.isArray(node)) {
    return node.map(extractNodeText).join('')
  }
  if (React.isValidElement(node)) {
    const props = node.props as { children?: React.ReactNode }
    return extractNodeText(props.children)
  }
  return ''
}

function MarkdownCodeBlock({
  language,
  codeText,
  children,
  copyLabel,
  copiedLabel,
  copyAriaLabel,
}: {
  language: string
  codeText: string
  children: React.ReactNode
  copyLabel: string
  copiedLabel: string
  copyAriaLabel: string
}) {
  const [copied, setCopied] = useState(false)

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(codeText)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="my-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-950 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-700/80 bg-slate-900/85 px-3 py-2">
        <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300">
          {language}
        </span>
        <button
          type="button"
          onClick={copyCode}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-200 transition-colors hover:bg-slate-700"
          aria-label={copyAriaLabel}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-300" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? copiedLabel : copyLabel}
        </button>
      </div>
      <pre className="max-h-[420px] overflow-x-auto overflow-y-auto px-4 py-3 text-[12px] leading-6 text-slate-100">
        <code style={{ fontFamily: CODE_FONT_STACK }}>{children}</code>
      </pre>
    </div>
  )
}


// Assistant message component with special markup parsing
// Defined outside of AIChatPage to prevent re-creation on every render
const AssistantMessage = React.memo(function AssistantMessage({
  content,
  messageId,
  onOptionSelect,
  onTaskSubmitSuccess,
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
  cancelTaskTrigger,
  onNewChat,
  conversationId,
  referenceImages,
  onMessageContentReplace,
  searchArtifacts,
  researchSessions = [],
}: AssistantMessageProps) {
  const { t } = useTranslation()
  const workbenchText = useWorkbenchText()
  const codeCopyLabel = t('aiChat.copy')
  const deliveredFiles = useMemo(() => parseDeliveredFiles(content), [content]);
  const codeCopiedLabel = t('aiChat.copied')
  const codeCopyAriaLabel = t('aiChat.copyCodeBlockAria')

  const {
    contextLimitReached,
    responseTruncated,
    options,
    taskConfig,
    imageRecommendation,
    csvAction,
    navigateBlock,
    analysisConfig,
    metricConfig,
    chartConfig,
    quickAnalysisConfig,
    taskHistoryConfig,
    cancelTaskConfig,
    renameTaskConfig,
    datasetRegistrationConfig,
    metadataUploadConfig,
    modelListConfig,
    patchInferenceConfig,
    batchInferenceSummaryConfig,
    batchInferenceConfig,
    referenceCards,
    citationContexts,
  } = useMemo(() => {
    return {
      contextLimitReached: parseContextLimit(content),
      responseTruncated: parseResponseTruncated(content),
      options: parseOptions(content),
      taskConfig: parseTaskConfig(content),
      imageRecommendation: parseImageRecommendation(content),
      csvAction: parseCSVAction(content),
      navigateBlock: parseNavigateBlock(content),
      analysisConfig: parseAnalysisConfig(content),
      metricConfig: parseMetricConfig(content),
      chartConfig: parseChartConfig(content),
      quickAnalysisConfig: parseQuickAnalysisConfig(content),
      taskHistoryConfig: parseTaskHistoryConfig(content),
      cancelTaskConfig: parseCancelTaskConfig(content),
      renameTaskConfig: parseRenameTaskConfig(content),
      datasetRegistrationConfig: parseDatasetRegistrationConfig(content),
      metadataUploadConfig: parseMetadataUploadConfig(content),
      modelListConfig: parseModelListConfig(content),
      patchInferenceConfig: parsePatchInferenceConfig(content),
      batchInferenceSummaryConfig: parseBatchInferenceSummary(content),
      batchInferenceConfig: parseBatchInferenceConfig(content),
      referenceCards: parseAllReferenceCards(content),
      citationContexts: parseCitationContexts(content),
    }
  }, [content])

  const citationRenderer = useMemo(() => createCitationRenderer({
    references: referenceCards,
    contexts: citationContexts,
    sources: searchArtifacts?.citationSources || [],
    searchResults: searchArtifacts?.search?.webSearchResults || [],
    streaming: isStreaming,
  }), [referenceCards, citationContexts, searchArtifacts?.citationSources, searchArtifacts?.search?.webSearchResults, isStreaming])
  const citationMap = citationRenderer.map

  // Custom ReactMarkdown components:
  // - img: inject auth token for /pdf-images/ URLs so <img> tags can load authenticated images
  // - hr: render a visually refined separator instead of the default ugly <hr>
  // - a: render InlineCitation for cite:// protocol links, visual external link indicator for URLs
  // - table: wrap in scrollable container for mobile responsive design
  const markdownComponents = useMemo<Components>(() => ({
    img: ({ src, alt, ...rest }) => {
      let finalSrc = src || ''
      if (finalSrc.includes('/pdf-images/')) {
        finalSrc = withAuthTokenQuery(finalSrc)
      }
      // Safety net: prevent 404 flood from hallucinated image URLs.
      // On error, clear src so the browser stops retrying broken PDF images.
      const isPdfImage = (src || '').includes('/pdf-images/')
      return (
        <img
          src={finalSrc}
          alt={alt || ''}
          loading="lazy"
          onError={(e) => {
            const img = e.target as HTMLImageElement
            img.removeAttribute('src')          // stop browser retry loop
            if (isPdfImage) {
              img.style.display = 'none'        // hide broken pdf figure
            } else {
              img.style.display = 'none'
            }
          }}
          {...rest}
        />
      )
    },
    hr: () => (
      <div className="my-6 flex items-center gap-3">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
        <div className="w-1 h-1 rounded-full bg-gray-300" />
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent" />
      </div>
    ),
    // Wrap tables in a horizontally scrollable container for mobile
    table: ({ children }) => (
      <div className="overflow-x-auto my-3 rounded-lg border border-gray-200 shadow-sm">
        <table className="min-w-full">{children}</table>
      </div>
    ),
    pre: ({ children }) => {
      const codeElement = React.isValidElement(children)
        ? children as React.ReactElement<{ className?: string; children?: React.ReactNode }>
        : null

      const className = codeElement?.props?.className || ''
      const language = normalizeCodeLanguage(className)
      const codeText = extractNodeText(codeElement?.props?.children).replace(/\n$/, '')

      if (!codeText.trim()) return null

      return (
        <MarkdownCodeBlock
          language={language}
          codeText={codeText}
          copyLabel={codeCopyLabel}
          copiedLabel={codeCopiedLabel}
          copyAriaLabel={codeCopyAriaLabel}
        >
          {children}
        </MarkdownCodeBlock>
      )
    },
    code: ({ className, children, ...props }) => {
      const isInline = !className || (!className.includes('language-') && !className.includes('hljs'))
      if (isInline) {
        return (
          <code
            className="rounded-md border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-[0.82em] text-slate-800"
            style={{ fontFamily: CODE_FONT_STACK }}
            {...props}
          >
            {children}
          </code>
        )
      }
      return <code className={className} style={{ fontFamily: CODE_FONT_STACK }} {...props}>{children}</code>
    },
    a: ({ href, children, ...rest }) => {
      if(href?.startsWith('/files?'))return <Link to={href} className="underline decoration-primary-300 underline-offset-2">{children}</Link>
      // Detect #cite-N hash links and render InlineCitation component
      const citationMatch = href?.match(/^#cite-(\d+)$/)
      if (citationMatch) {
        const index = parseInt(citationMatch[1])
        const data = citationMap.get(index)
        const pageInfo = data?.pageInfo
        return (
          <InlineCitation
            index={index}
            sourceIndex={data?.sourceIndex}
            sourceId={data?.sourceId}
            title={data?.title}
            source={data?.source}
            snippet={data?.snippet}
            pageInfo={pageInfo}
            url={data?.url}
          />
        )
      }
      // Fallback: render links to /pdf-images/ as inline images.
      // The AI sometimes uses [text](url) link syntax instead of ![text](url) image syntax
      // for PDF figure references, causing them to appear as clickable links instead of images.
      if (href && href.includes('/pdf-images/')) {
        const finalSrc = withAuthTokenQuery(href)
        const altText = typeof children === 'string' ? children
          : Array.isArray(children) ? children.map(c => typeof c === 'string' ? c : '').join('')
          : ''
        return (
          <img
            src={finalSrc}
            alt={altText || 'Figure'}
            loading="lazy"
            onError={(e) => {
              const img = e.target as HTMLImageElement
              img.removeAttribute('src')
              img.style.display = 'none'
            }}
          />
        )
      }
      // External links: show underline + arrow indicator so users know it's clickable
      const isExternal = href?.startsWith('http')
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
          {isExternal && <span className="inline-block ml-0.5 opacity-70 text-[0.7em] no-underline">↗</span>}
        </a>
      )
    },
  }), [citationMap, codeCopyAriaLabel, codeCopiedLabel, codeCopyLabel])

  // Remove special blocks from display content
  // Keep the text content but strip out the special markup blocks
  let displayContent = content
  const datasetEdit = parseDatasetEdit(content)
  displayContent = displayContent.replace(/\[DATASET_EDIT\][\s\S]*?\[\/DATASET_EDIT\]/g, '')
  displayContent = stripChatBlocks(displayContent, ['DELIVER_FILE', 'FILE_DELIVERY', 'RESEARCH_RUN', 'LOAD_CONNECTOR', 'CONNECTOR_TOOL', 'LOAD_SKILL', 'SEARCH_FILES']);
  if (options) displayContent = removeOptionsBlock(displayContent)
  if (taskConfig) displayContent = removeTaskConfigBlock(displayContent)
  if (imageRecommendation) displayContent = removeImageRecommendationBlock(displayContent)
  if (csvAction) displayContent = removeCSVActionBlock(displayContent)
  if (navigateBlock) displayContent = removeNavigateBlock(displayContent)
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
  if (patchInferenceConfig) displayContent = removePatchInferenceBlock(displayContent)
  if (batchInferenceSummaryConfig) displayContent = removeBatchInferenceSummaryBlock(displayContent)
  if (batchInferenceConfig) displayContent = removeBatchInferenceConfigBlock(displayContent)
  // Remove WEB_SEARCH request block - AI's internal search request
  displayContent = displayContent.replace(/\[WEB_SEARCH\][\s\S]*?\[\/WEB_SEARCH\]/g, '').trim()
  // Remove READ_ARTICLE request block - AI's internal article reading request
  displayContent = displayContent.replace(/\[READ_ARTICLE\][\s\S]*?\[\/READ_ARTICLE\]/g, '').trim()
  // Remove CONTEXT_LIMIT block - rendered as a card
  if (contextLimitReached) displayContent = removeContextLimitBlock(displayContent)
  // Remove RESPONSE_TRUNCATED block - rendered as a card
  if (responseTruncated) displayContent = removeResponseTruncatedBlock(displayContent)
  // Remove VOICE_CONTROL block - it's for internal use only
  displayContent = removeVoiceControlBlock(displayContent)
  displayContent = displayContent.replace(/\[LOAD_CAPABILITY\][\s\S]*?\[\/LOAD_CAPABILITY\]/g, '')
  // Remove SUBMIT_TASK block - it's for internal use only (voice command to trigger submit)
  displayContent = removeSubmitTaskBlock(displayContent)
  // Remove CANCEL_TASK_NOW block - it's for internal use only (voice command to trigger cancel)
  displayContent = removeCancelTaskNowBlock(displayContent)
  // Remove REFERENCE blocks - rendered as cards
  displayContent = removeAllReferenceBlocks(displayContent)
  // Remove CITATION_CONTEXTS block - data consumed by citationMap, not for display
  // Always strip (even if parsing failed) to prevent raw JSON from showing
  displayContent = removeCitationContextsBlock(displayContent)
  // Some internal control blocks may be wrapped in ```text fences by the model.
  // After stripping the inner blocks above, that can leave behind an empty code block.
  displayContent = removeEmptyFencedCodeBlocks(displayContent)
  displayContent = removeDanglingFenceArtifacts(displayContent)

  // Convert pdf-image links to images: [text](…/pdf-images/…) → ![text](…/pdf-images/…)
  // The AI sometimes uses markdown link syntax instead of image syntax for figure references,
  // causing them to render as clickable links instead of inline images.
  // Only converts when NOT already preceded by '!' (i.e. not already an image).
  displayContent = displayContent.replace(
    /(^|[^!])\[([^\]]*)\]\((https?:\/\/[^)]*\/pdf-images\/[^)]+)\)/gm,
    '$1![$2]($3)'
  )

  // Remove any incomplete blocks that are still streaming
  const { content: cleanedContent, incompleteTag } = getIncompleteBlock(displayContent, isStreaming)
  displayContent = prepareStreamingMarkdown(cleanedContent, isStreaming)

  const searchArt = searchArtifacts?.search ?? null
  const effectivePdfStatuses = searchArt?.pdfStatuses
    ? Array.from(new Map(searchArt.pdfStatuses.map(item => [item.url, item])).values())
    : null
  const effectiveWebSearchResults = searchArt?.webSearchResults?.length ? searchArt.webSearchResults : null
  const effectivePdfParseResults = searchArt?.pdfParseResults?.length ? searchArt.pdfParseResults : null

  const webSearchResultCount = effectiveWebSearchResults?.length ?? 0

  const activeSearchStatus = searchArt?.statuses.at(-1)

  const showSearchingStatus = searchArt?.phase === 'searching' && isStreaming

  const hasPdfParsingInProgress = effectivePdfStatuses?.some(i => ['parsing', 'downloading', 'fetching', 'waiting', 'cached'].includes(i.status)) ?? false
  const showPdfParsingStatus = !!effectivePdfStatuses && hasPdfParsingInProgress && isStreaming

  const hasFunctionalCard = !!(
    taskConfig || analysisConfig || imageRecommendation || patchInferenceConfig ||
    quickAnalysisConfig || metricConfig || chartConfig || options || datasetEdit || datasetRegistrationConfig
  ) || FUNCTIONAL_CARD_INCOMPLETE_TAGS.has(incompleteTag ?? '')

  const showSummarizingSearch = searchArt
    ? searchArt.phase === 'summarizing' && isStreaming && !displayContent.trim() && !incompleteTag && !hasFunctionalCard
    : false

  const showPdfParsingCompleted = !!effectivePdfParseResults?.length && !hasPdfParsingInProgress

  const hasCompletedPdf = (effectivePdfParseResults ?? effectivePdfStatuses)?.some(i => i.status === 'completed') ?? false
  const showSummarizingPdf = !hasPdfParsingInProgress && hasCompletedPdf
    && isStreaming && !displayContent.trim() && !incompleteTag && !hasFunctionalCard && !showSummarizingSearch

  const showSearchZone = showSearchingStatus || !!effectiveWebSearchResults?.length
    || showSummarizingSearch || showPdfParsingStatus || showPdfParsingCompleted || showSummarizingPdf

  return (
    <div className="w-full min-w-0">
      {!!searchArtifacts?.activity?.length && <ActivityStrip items={searchArtifacts.activity} running={isStreaming} />}
      {showSearchZone && (
        <div className="search-zone mb-2">
          {showSearchingStatus && !searchArtifacts?.activity?.length && (
            <SearchingStatus query={activeSearchStatus?.query} reason={activeSearchStatus?.reason} />
          )}

          {effectiveWebSearchResults && (
            <SearchResultsZone
              results={effectiveWebSearchResults}
              isStreaming={isStreaming}
            />
          )}

          {showSummarizingSearch && !searchArtifacts?.activity?.length && <SummarizingSearchStatus />}

          {showPdfParsingStatus && effectivePdfStatuses && (
            <PdfParsingStatus items={effectivePdfStatuses} />
          )}

          {showPdfParsingCompleted && effectivePdfParseResults && (
            <PdfParsingCompletedCard items={effectivePdfParseResults} />
          )}

          {showSummarizingPdf && !searchArtifacts?.activity?.length && <SummarizingPdfStatus />}
        </div>
      )}

      {/* Thinking indicator — shown inside AssistantMessage when streaming but no text content yet
          and no search/PDF status cards are visible. This covers the gap between when the message
          bubble is rendered and when actual PDF status events or text chunks arrive. */}
      {isStreaming && !displayContent.trim() && !showSearchZone && !incompleteTag && !hasFunctionalCard && !searchArtifacts?.activity?.length && (
        <div className="flex items-center gap-2.5 py-2" aria-busy="true">
          <div className="flex items-center gap-1" aria-hidden="true">
            <div
              className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
              style={{ animationDelay: '0ms', animationDuration: '1.2s' }}
            />
            <div
              className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
              style={{ animationDelay: '200ms', animationDuration: '1.2s' }}
            />
            <div
              className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
              style={{ animationDelay: '400ms', animationDuration: '1.2s' }}
            />
          </div>
          <span className="text-sm font-medium text-gray-400">
            {t('aiChat.thinking')}
          </span>
        </div>
      )}

      {/* Markdown content — no skeleton; stream starts directly */}
      {deliveredFiles.length > 0 && <FileDeliveryCard files={deliveredFiles} />}
      {displayContent.trim() && (
        <div className="prose prose-slate max-w-none prose-sm
          prose-p:my-2 prose-p:leading-relaxed
          prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
          prose-ul:my-3 prose-ul:list-disc prose-ul:pl-6
          prose-ol:my-3 prose-ol:list-decimal prose-ol:pl-6
          prose-li:my-1.5 prose-li:leading-relaxed
          prose-code:before:content-none prose-code:after:content-none
          prose-pre:bg-transparent prose-pre:p-0 prose-pre:my-0
          prose-strong:text-gray-900 prose-strong:font-semibold
          prose-a:text-blue-600 prose-a:underline prose-a:decoration-blue-300 prose-a:underline-offset-2 hover:prose-a:text-blue-700 hover:prose-a:decoration-blue-500
          prose-hr:border-gray-200 prose-hr:my-4
          prose-table:text-sm
          prose-img:rounded-lg prose-img:shadow-md prose-img:my-3 prose-img:max-w-full prose-img:h-auto prose-img:border prose-img:border-gray-200">
          <ReactMarkdown
            remarkPlugins={isStreaming
              ? [remarkGfm, remarkCjkFriendly, citationRenderer.remarkCitations]
              : [remarkGfm, remarkCjkFriendly, remarkMath, citationRenderer.remarkCitations]}
            rehypePlugins={isStreaming ? [] : [
              rehypeKatex,
              [rehypeHighlight, { ignoreMissing: true, detect: true }],
            ]}
            components={markdownComponents}
          >
            {displayContent}
          </ReactMarkdown>
        </div>
      )}

      {searchArtifacts?.researchHandoff && <ResearchHandoffCard
        handoff={searchArtifacts.researchHandoff}
        streaming={isStreaming}
        session={researchSessions.find(session => session.session_id === searchArtifacts.researchHandoff?.session_id)}
      />}

      {/* Animated Components Section */}
      <AnimatePresence mode="wait">
        {datasetEdit && <DatasetEditCard config={datasetEdit} disabled={isStreaming || isLoading} />}

        {/* Option buttons */}
        {options ? (
          <motion.div key="options-real" {...cardTransition}>
            <OptionButtons
              options={options}
              onSelect={onOptionSelect}
              disabled={isStreaming || isLoading}
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
              onConfigChange={(updatedConfig) => {
                const nextBlock = `[TASK_CONFIG]\n${JSON.stringify(updatedConfig, null, 2)}\n[/TASK_CONFIG]`
                void onMessageContentReplace?.(messageId, content.replace(/\[TASK_CONFIG\][\s\S]*?\[\/TASK_CONFIG\]/, nextBlock))
              }}
            />
          </motion.div>
        ) : incompleteTag === 'TASK_CONFIG' && (
          <motion.div key="task-config-skeleton" {...cardTransition}>
            <TaskConfigSkeleton />
          </motion.div>
        )}

        {/* Analysis config card (internal or external) */}
        {analysisConfig ? (
          <motion.div key="analysis-config-real" {...cardTransition}>
            <AnalysisConfigCard
              config={analysisConfig}
              submitTrigger={submitTaskTrigger}
              onSubmitSuccess={(taskId, analysisId) => onInternalAnalysisSubmitSuccess(taskId, analysisId, messageId)}
              onSubmitError={onTaskSubmitError}
              messageId={messageId}
              onHelpfulnessFeedback={onHelpfulnessFeedback}
              savedHelpfulnessFeedback={savedHelpfulnessFeedback}
              onConfigChange={(updatedConfig) => {
                const nextBlock = `[ANALYSIS_CONFIG]\n${JSON.stringify(updatedConfig, null, 2)}\n[/ANALYSIS_CONFIG]`
                void onMessageContentReplace?.(messageId, content.replace(/\[ANALYSIS_CONFIG\][\s\S]*?\[\/ANALYSIS_CONFIG\]/, nextBlock))
              }}
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
              conversationId={conversationId}
              csvContent={csvContent}
              csvFileName={csvFileName}
            />
          </motion.div>
        ) : incompleteTag === 'NAVIGATE' && (
          <motion.div key="navigate-pending" {...cardTransition}>
            <div role="status" className="my-3 flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
              <Loader2 size={16} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
              {workbenchText('navigationPreparing')}
            </div>
          </motion.div>
        )}

        {/* Context limit warning card */}
        {contextLimitReached && !isStreaming && (
          <motion.div key="context-limit" {...cardTransition}>
            <div className="my-4 p-4 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-xl shadow-sm">
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 w-8 h-8 bg-amber-100 rounded-full flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-amber-800">
                    {t('aiChat.contextLimit.title')}
                  </p>
                  <p className="text-xs text-amber-600 mt-1">
                    {t('aiChat.contextLimit.description')}
                  </p>
                </div>
              </div>
              {onNewChat && (
                <button
                  onClick={onNewChat}
                  className="mt-3 w-full px-4 py-2.5 bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium rounded-lg flex items-center justify-center gap-2 shadow-sm hover:shadow-md transition-all"
                >
                  <Plus className="w-4 h-4" />
                  {t('aiChat.contextLimit.newResearch')}
                </button>
              )}
            </div>
          </motion.div>
        )}

        {/* Response truncated warning card */}
        {responseTruncated && !isStreaming && (
          <motion.div key="response-truncated" {...cardTransition}>
            <div className="my-4 p-4 bg-gradient-to-r from-amber-50 to-yellow-50 border border-amber-200 rounded-xl shadow-sm">
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 w-8 h-8 bg-amber-100 rounded-full flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-amber-800">
                    {t('aiChat.responseTruncated.title')}
                  </p>
                  <p className="text-xs text-amber-600 mt-1">
                    {t('aiChat.responseTruncated.description')}
                  </p>
                </div>
              </div>
            </div>
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
              onSuccess={(_taskId, newName) => onToast({ type: 'success', message: t('chatComponents.assistantMessage.taskRenamedSuccess', { newName }) })}
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
              disabled={isStreaming || isLoading}
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
            <ModelListCard config={modelListConfig} onToast={onToast} />
          </motion.div>
        ) : incompleteTag === 'MODEL_LIST' && (
          <motion.div key="model-list-skeleton" {...cardTransition}>
            <ModelListSkeleton />
          </motion.div>
        )}

        {/* Patch inference card */}
        {patchInferenceConfig ? (
          <motion.div key="patch-inference-real" {...cardTransition}>
            <PatchInferenceCard
              config={patchInferenceConfig}
              conversationId={conversationId}
              messageId={messageId}
              referenceImages={referenceImages}
              onToast={onToast}
              onPersistConfig={(nextConfig) => {
                if (!onMessageContentReplace) return
                const nextBlock = `[PATCH_INFERENCE]\n${JSON.stringify(nextConfig, null, 2)}\n[/PATCH_INFERENCE]`
                const updatedContent = content.replace(/\[PATCH_INFERENCE\][\s\S]*?\[\/PATCH_INFERENCE\]/, nextBlock)
                return onMessageContentReplace(messageId, updatedContent, 'aiChat.failedToSavePatchInferenceStatus')
              }}
            />
          </motion.div>
        ) : incompleteTag === 'PATCH_INFERENCE' && (
          <motion.div key="patch-inference-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Batch Inference Config Card */}
        {batchInferenceConfig ? (
          <motion.div key="batch-inference-config-real" {...cardTransition}>
            <BatchInferenceConfigCard
              config={batchInferenceConfig}
              submitTrigger={submitTaskTrigger}
              onSubmitSuccess={() => onToast({ type: 'success', message: t('chatComponents.batchInferenceConfig.submitted') })}
              onSubmitError={onTaskSubmitError}
              messageId={messageId}
              onConfigChange={(updatedConfig) => {
                if (onMessageContentReplace) {
                  const nextBlock = `[BATCH_INFERENCE_CONFIG]\n${JSON.stringify(updatedConfig, null, 2)}\n[/BATCH_INFERENCE_CONFIG]`
                  const updatedContent = content.replace(/\[BATCH_INFERENCE_CONFIG\][\s\S]*?\[\/BATCH_INFERENCE_CONFIG\]/, nextBlock)
                  void onMessageContentReplace(messageId, updatedContent)
                }
              }}
            />
          </motion.div>
        ) : incompleteTag === 'BATCH_INFERENCE_CONFIG' && (
          <motion.div key="batch-inference-config-skeleton" {...cardTransition}>
            <GenericCardSkeleton />
          </motion.div>
        )}

        {/* Batch Inference Summary Card */}
        {batchInferenceSummaryConfig && (
          <motion.div key="batch-inference-summary-real" {...cardTransition}>
            <BatchInferenceSummaryCard config={batchInferenceSummaryConfig} />
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
          'PATCH_INFERENCE',
          'BATCH_INFERENCE_CONFIG',
          'BATCH_INFERENCE_SUMMARY',
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

      {referenceCards && referenceCards.length > 0 && (
        <ReferenceCardList cards={referenceCards} />
      )}
    </div>
  )
})

export default AssistantMessage
