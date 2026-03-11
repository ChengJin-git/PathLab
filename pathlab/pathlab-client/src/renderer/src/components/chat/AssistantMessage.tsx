/**
 * AssistantMessage — renders a single AI assistant message with special block parsing.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */
import React, { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Plus, Copy, Check } from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { withAuthTokenQuery } from '../../api/client'

import { OptionButtons, parseOptions, removeOptionsBlock } from './OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from './TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from './ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from './CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from './NavigationCard'
import { ReferenceCardList, parseAllReferenceCards, removeAllReferenceBlocks } from './ReferenceCard'
import InlineCitation from './InlineCitation'

import { AnalysisConfigCard, parseAnalysisConfig, removeAnalysisConfigBlock } from './AnalysisConfigCard'
import { MetricCard, parseMetricConfig, removeMetricConfigBlock } from './MetricCard'
import { ChartCard, parseChartConfig, removeChartConfigBlock } from './ChartCard'
import { QuickAnalysisViewer, parseQuickAnalysisConfig, removeQuickAnalysisConfigBlock, CachedAnalysisData } from './QuickAnalysisViewer'
import { TaskHistoryCard, parseTaskHistoryConfig, removeTaskHistoryConfigBlock, CachedTaskData } from './TaskHistoryCard'
import { CancelTaskCard, parseCancelTaskConfig, removeCancelTaskBlock } from './CancelTaskCard'
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from './DatasetRegistrationCard'
import { MetadataUploadCard, parseMetadataUploadConfig, removeMetadataUploadBlock } from './MetadataUploadCard'
import { ModelListCard, parseModelListConfig, removeModelListBlock } from './ModelListCard'
import PatchInferenceCard, { parsePatchInferenceConfig, removePatchInferenceBlock } from './PatchInferenceCard'
import { RenameTaskCard, parseRenameTaskConfig, removeRenameTaskBlock } from './RenameTaskCard'
import { removeVoiceControlBlock } from './VoiceControlBlock'
import SearchingStatus, {
  parseSearchStatus,
  removeSearchStatusBlock,
  SearchCompletedCard,
  SummarizingSearchStatus,
  SummarizingPdfStatus,
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
}

// All special block tag names used in the chat
const SPECIAL_BLOCK_TAGS = [
  'OPTIONS',
  'TASK_CONFIG',
  'IMAGE_RECOMMENDATION',
  'CSV_ACTION',
  'NAVIGATE',
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
  'PATCH_INFERENCE',
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

  // When streaming has ended, don't report incomplete tags – this prevents
  // skeleton loading UI from rendering forever when the AI finishes without
  // completing a block (e.g. [OPTIONS] without [/OPTIONS]).
  // The content cleanup above still applies so broken markup is stripped.
  if (!isStreaming) {
    incompleteTag = null
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

/** Parsed citation context for a single [N, p.Y] reference. */
export interface CitationContext {
  page: number
  context: string
  sourceId?: string
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
    const parsed = JSON.parse(match[1].trim())
    if (!parsed || typeof parsed !== 'object') return null

    const normalized: Record<string, CitationContext> = {}
    Object.entries(parsed).forEach(([key, value]) => {
      if (!value || typeof value !== 'object') return
      const raw = value as Record<string, unknown>
      const rawPage = raw.page
      const page = typeof rawPage === 'number'
        ? rawPage
        : parseInt(String(rawPage ?? '0'), 10) || 0
      normalized[key] = {
        page,
        context: typeof raw.context === 'string' ? raw.context : '',
        sourceId: typeof raw.source_id === 'string'
          ? raw.source_id
          : typeof raw.sourceId === 'string'
            ? raw.sourceId
            : undefined
      }
    })
    return normalized
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

function getHostnameFromUrl(url?: string): string {
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

function findReferenceCardForCitation(
  referenceCards: ReturnType<typeof parseAllReferenceCards> | null,
  key: string,
  sourceId?: string
) {
  if (!referenceCards?.length) return undefined
  if (sourceId) {
    const matchBySourceId = referenceCards.find(card => card.sourceId === sourceId)
    if (matchBySourceId) return matchBySourceId
  }
  const paperIdxMatch = key.match(/^(\d+)-/)
  const paperIdx = paperIdxMatch ? parseInt(paperIdxMatch[1]) : 1
  return referenceCards[paperIdx - 1] ?? referenceCards[0]
}

function normalizeCodeLanguage(className?: string): string {
  const raw = className?.match(/language-([\w-]+)/)?.[1]?.toLowerCase() || ''
  if (!raw) return 'text'
  if (raw === 'plaintext' || raw === 'plain') return 'text'
  if (raw === 'shell' || raw === 'bash' || raw === 'zsh') return 'bash'
  if (raw === 'tsx' || raw === 'jsx' || raw === 'typescript' || raw === 'javascript') return raw
  if (raw === 'monofont') return 'text'
  return raw
}

const CODE_FONT_STACK = 'JetBrains Mono, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace'

type CodeTokenType = 'plain' | 'keyword' | 'string' | 'number' | 'comment' | 'operator' | 'constant' | 'function'

interface CodeToken {
  text: string
  type: CodeTokenType
}

const KEYWORDS_BY_LANGUAGE: Record<string, Set<string>> = {
  js: new Set(['const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'finally', 'throw', 'new', 'class', 'extends', 'import', 'from', 'export', 'default', 'async', 'await', 'typeof', 'instanceof', 'in', 'of']),
  jsx: new Set(['const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'finally', 'throw', 'new', 'class', 'extends', 'import', 'from', 'export', 'default', 'async', 'await']),
  ts: new Set(['const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'finally', 'throw', 'new', 'class', 'extends', 'import', 'from', 'export', 'default', 'async', 'await', 'interface', 'type', 'enum', 'implements', 'public', 'private', 'protected', 'readonly']),
  tsx: new Set(['const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'switch', 'case', 'break', 'continue', 'try', 'catch', 'finally', 'throw', 'new', 'class', 'extends', 'import', 'from', 'export', 'default', 'async', 'await', 'interface', 'type', 'enum', 'implements']),
  python: new Set(['def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while', 'in', 'is', 'not', 'and', 'or', 'try', 'except', 'finally', 'raise', 'import', 'from', 'as', 'with', 'lambda', 'pass', 'break', 'continue', 'global', 'nonlocal', 'yield', 'async', 'await']),
  bash: new Set(['if', 'then', 'else', 'fi', 'for', 'in', 'do', 'done', 'while', 'case', 'esac', 'function', 'return', 'local', 'export']),
  sql: new Set(['select', 'from', 'where', 'group', 'by', 'order', 'having', 'join', 'left', 'right', 'inner', 'outer', 'on', 'insert', 'into', 'values', 'update', 'set', 'delete', 'create', 'table', 'alter', 'drop', 'limit', 'offset', 'as', 'and', 'or', 'not', 'null']),
  json: new Set([]),
}

const OPERATOR_PATTERN = /^(===|!==|==|!=|<=|>=|=>|\+\+|--|&&|\|\||[=+\-*/%<>!&|^~?:.,;{}()[\]])$/
const TOKEN_PATTERN = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b(?:true|false|null|undefined|None|True|False)\b|[A-Za-z_][A-Za-z0-9_]*|===|!==|==|!=|<=|>=|=>|\+\+|--|&&|\|\||[=+\-*/%<>!&|^~?:.,;{}()[\]])/g

function getLanguageKeywordSet(language: string): Set<string> | null {
  if (language === 'javascript') return KEYWORDS_BY_LANGUAGE.js
  if (language === 'typescript') return KEYWORDS_BY_LANGUAGE.ts
  return KEYWORDS_BY_LANGUAGE[language] || null
}

function tokenizeCodeLine(line: string, language: string): CodeToken[] {
  if (!line) return [{ text: '', type: 'plain' }]

  if (language === 'python' || language === 'bash') {
    const commentIndex = line.indexOf('#')
    if (commentIndex !== -1) {
      const before = line.slice(0, commentIndex)
      const comment = line.slice(commentIndex)
      return [...tokenizeCodeLine(before, language).filter(t => t.text.length > 0), { text: comment, type: 'comment' }]
    }
  }

  if (language === 'sql') {
    const commentIndex = line.indexOf('--')
    if (commentIndex !== -1) {
      const before = line.slice(0, commentIndex)
      const comment = line.slice(commentIndex)
      return [...tokenizeCodeLine(before, language).filter(t => t.text.length > 0), { text: comment, type: 'comment' }]
    }
  }

  const keywordSet = getLanguageKeywordSet(language)
  const tokens: CodeToken[] = []
  let cursor = 0

  for (const match of line.matchAll(TOKEN_PATTERN)) {
    const token = match[0]
    const index = match.index ?? 0

    if (index > cursor) {
      tokens.push({ text: line.slice(cursor, index), type: 'plain' })
    }

    let type: CodeTokenType = 'plain'
    const lower = token.toLowerCase()

    if (token.startsWith('"') || token.startsWith("'") || token.startsWith('`')) {
      type = 'string'
    } else if (/^\d+(?:\.\d+)?$/.test(token)) {
      type = 'number'
    } else if (['true', 'false', 'null', 'undefined', 'none'].includes(lower)) {
      type = 'constant'
    } else if (keywordSet && keywordSet.has(lower)) {
      type = 'keyword'
    } else if (OPERATOR_PATTERN.test(token)) {
      type = 'operator'
    } else if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(token)) {
      const rest = line.slice(index + token.length)
      if (/^\s*\(/.test(rest)) {
        type = 'function'
      }
    }

    tokens.push({ text: token, type })
    cursor = index + token.length
  }

  if (cursor < line.length) {
    tokens.push({ text: line.slice(cursor), type: 'plain' })
  }

  return tokens
}

function tokenClassName(type: CodeTokenType): string {
  switch (type) {
    case 'keyword':
      return 'text-sky-300'
    case 'string':
      return 'text-emerald-300'
    case 'number':
      return 'text-amber-300'
    case 'comment':
      return 'text-slate-400 italic'
    case 'operator':
      return 'text-fuchsia-300'
    case 'constant':
      return 'text-orange-300'
    case 'function':
      return 'text-cyan-300'
    default:
      return 'text-slate-100'
  }
}

function renderHighlightedCode(codeText: string, language: string): React.ReactNode {
  const lines = codeText.split('\n')
  return lines.map((line, lineIdx) => {
    const tokens = tokenizeCodeLine(line, language)
    return (
      <div key={`line-${lineIdx}`} className="group grid grid-cols-[auto_1fr] gap-3">
        <span className="select-none text-right text-[11px] text-slate-500 pr-1 min-w-[2ch]">
          {lineIdx + 1}
        </span>
        <span className="whitespace-pre">
          {tokens.map((token, tokenIdx) => (
            <span key={`line-${lineIdx}-token-${tokenIdx}`} className={tokenClassName(token.type)}>{token.text}</span>
          ))}
        </span>
      </div>
    )
  })
}

function MarkdownCodeBlock({
  className,
  children,
  copyLabel,
  copiedLabel,
  copyAriaLabel,
}: {
  className?: string
  children: React.ReactNode
  copyLabel: string
  copiedLabel: string
  copyAriaLabel: string
}) {
  const [copied, setCopied] = useState(false)
  const language = normalizeCodeLanguage(className)
  const codeText = String(children ?? '').replace(/\n$/, '')
  const shouldHighlight = ['js', 'jsx', 'ts', 'tsx', 'javascript', 'typescript', 'python', 'bash', 'sql', 'json'].includes(language)

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
      <pre className="max-h-[420px] overflow-x-auto overflow-y-auto px-4 py-3 text-[12px] leading-6">
        <code style={{ fontFamily: CODE_FONT_STACK }}>
          {shouldHighlight ? renderHighlightedCode(codeText, language) : codeText}
        </code>
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
  onMessageContentReplace
}: AssistantMessageProps) {
  const { t } = useTranslation()
  const codeCopyLabel = t('aiChat.copy')
  const codeCopiedLabel = t('aiChat.copied')
  const codeCopyAriaLabel = t('aiChat.copyCodeBlockAria')

  // Parse special blocks
  const contextLimitReached = parseContextLimit(content)
  const responseTruncated = parseResponseTruncated(content)
  const searchStatus = parseSearchStatus(content)
  const webSearchResult = parseWebSearchResult(content)
  const options = parseOptions(content)
  const taskConfig = parseTaskConfig(content)
  const imageRecommendation = parseImageRecommendation(content)
  const csvAction = parseCSVAction(content)
  const navigateBlock = parseNavigateBlock(content)
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
  const patchInferenceConfig = parsePatchInferenceConfig(content)
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
    const renumber = new Map<string, number>() // "N-p.X" or "N-bare" → sequential index
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
    // Also match standalone [p.X] (no paper number prefix) — treat as paper 1
    const standalonePattern = /\[(p\.\d[^\]]*)\](?!\()/g
    while ((m = standalonePattern.exec(content)) !== null) {
      const key = `1-${m[1].replace(/\s/g, '')}`
      if (!renumber.has(key)) {
        renumber.set(key, seq++)
      }
    }
    // Also scan for bare [N] citations when in a paper context (referenceCards
    // exist or we already found page-level citations).  Bare citations are
    // keyed "N-bare" so they get sequential indices that don't collide with
    // page-level renumbered indices — critical for multi-paper conversations
    // where [1, p.5] (paper 1) might get seq 2 and bare [2] (paper 2) would
    // collide if we used the raw number.
    if (renumber.size > 0 || referenceCards?.length) {
      const barePattern = /\[(\d{1,2})\](?!\()/g
      while ((m = barePattern.exec(content)) !== null) {
        const key = `${m[1]}-bare`
        if (!renumber.has(key)) {
          renumber.set(key, seq++)
        }
      }
    }
    return renumber.size > 0 ? renumber : null
  }, [content, referenceCards])

  // Build citation lookup map from web search results + article citation contexts.
  // Maps citation display index (1-based) to { title, url, snippet, source, pageInfo? }
  const citationMap = useMemo(() => {
    const map = new Map<number, { title: string; url: string; snippet: string; source: string; pageInfo?: string }>()
    // 1) Web search results — index is 1-based ordinal
    if (webSearchResult?.results) {
      webSearchResult.results.forEach((r, i) => {
        const source = getHostnameFromUrl(r.url) || 'Unknown'
        map.set(i + 1, { title: r.title, url: r.url, snippet: r.snippet, source })
      })
    }
    // 2) Article citation contexts — keyed "N-p.X" (normalized), renumbered sequentially
    //    Prefer backend-provided stable sourceId over transient paper numbering,
    //    then fall back to paper index for backward compatibility.
    if (citationContexts && articleCitationRenumber) {
      for (const [key, ctx] of Object.entries(citationContexts)) {
        const seqIdx = articleCitationRenumber.get(key)
        if (!seqIdx) continue
        const refCard = findReferenceCardForCitation(referenceCards, key, ctx.sourceId)
        const refSource = getHostnameFromUrl(refCard?.url)
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
    // 3) Fill in any articleCitationRenumber entries that still lack citationMap data.
    //    This covers standalone [p.X] patterns and [N, p.X] patterns where the backend
    //    didn't send CITATION_CONTEXTS. Uses referenceCards for title/url and the page
    //    info from the renumber key.
    if (articleCitationRenumber && referenceCards?.length) {
      for (const [key, seqIdx] of articleCitationRenumber.entries()) {
        if (map.has(seqIdx)) continue
        const refCard = findReferenceCardForCitation(referenceCards, key)
        const refSource = getHostnameFromUrl(refCard?.url)
        const pageFromKey = key.replace(/^\d+-/, '')
        map.set(seqIdx, {
          title: refCard?.title || '',
          url: refCard?.url || '',
          snippet: '',
          source: refSource,
          pageInfo: pageFromKey,
        })
      }
    }
    // 4) Fallback for bare [N] article citations with no CITATION_CONTEXTS data
    //    and no articleCitationRenumber (e.g., cache miss or AI only uses bare [N]).
    //    Scan content for all bare [N] and map each to referenceCards[N-1].
    if (referenceCards?.length && map.size === 0) {
      const barePattern = /\[(\d{1,2})\](?!\()/g
      let bm: RegExpExecArray | null
      const seenBare = new Set<number>()
      while ((bm = barePattern.exec(content)) !== null) {
        const idx = parseInt(bm[1])
        if (seenBare.has(idx)) continue
        seenBare.add(idx)
        const refCard = referenceCards[idx - 1] ?? referenceCards[0]
        if (!refCard) continue
        const refSource = getHostnameFromUrl(refCard.url)
        map.set(idx, {
          title: refCard.title,
          url: refCard.url,
          snippet: '',
          source: refSource,
        })
      }
    }
    return map
  }, [webSearchResult, citationContexts, articleCitationRenumber, referenceCards])

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
    code: ({ className, children, ...props }) => {
      const isInline = !className?.includes('language-')
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
      return (
        <MarkdownCodeBlock
          className={className}
          copyLabel={codeCopyLabel}
          copiedLabel={codeCopiedLabel}
          copyAriaLabel={codeCopyAriaLabel}
        >
          {children}
        </MarkdownCodeBlock>
      )
    },
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
  // Remove CONTEXT_LIMIT block - rendered as a card
  if (contextLimitReached) displayContent = removeContextLimitBlock(displayContent)
  // Remove RESPONSE_TRUNCATED block - rendered as a card
  if (responseTruncated) displayContent = removeResponseTruncatedBlock(displayContent)
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

  // Convert pdf-image links to images: [text](…/pdf-images/…) → ![text](…/pdf-images/…)
  // The AI sometimes uses markdown link syntax instead of image syntax for figure references,
  // causing them to render as clickable links instead of inline images.
  // Only converts when NOT already preceded by '!' (i.e. not already an image).
  displayContent = displayContent.replace(
    /(^|[^!])\[([^\]]*)\]\((https?:\/\/[^)]*\/pdf-images\/[^)]+)\)/gm,
    '$1![$2]($3)'
  )

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
  // 3.5. [p.X] (standalone page reference, no paper number) — treat as paper 1
  if (articleCitationRenumber) {
    displayContent = displayContent.replace(
      /\[(p\.\d[^\]]*)\](?!\()/g,
      (_match, pagesPart) => {
        const key = `1-${pagesPart.replace(/\s/g, '')}`
        const seq = articleCitationRenumber.get(key)
        if (seq) return `[${seq}](#cite-${seq})`
        return _match // no renumber entry, leave as-is
      }
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
  // 5. [N] (simple citation) — when articleCitationRenumber exists (paper context),
  //    use renumbered seq index to avoid citationMap key mismatch; otherwise use raw N.
  if (citationMap.size > 0) {
    if (articleCitationRenumber) {
      displayContent = displayContent.replace(
        /\[(\d{1,2})\](?!\()/g,
        (_match, n: string) => {
          const key = `${n}-bare`
          const seq = articleCitationRenumber.get(key)
          if (seq) return `[${seq}](#cite-${seq})`
          // Not in renumber map — leave as-is to avoid false positives
          return _match
        }
      )
    } else {
      displayContent = displayContent.replace(
        /\[(\d{1,2})\](?!\()/g,
        '[$1](#cite-$1)'
      )
    }
  }

  // Remove any incomplete blocks that are still streaming
  const { content: cleanedContent, incompleteTag } = getIncompleteBlock(displayContent, isStreaming)
  displayContent = cleanedContent

	  // Show searching indicator only while streaming and before results arrive
	  const showSearchingStatus = !!searchStatus && !webSearchResult && isStreaming

    // PDF parsing status: show animated indicator while any PDF is still "parsing" or "downloading".
    // Hide entirely during web-search streaming — the AI may autonomously trigger
    // [READ_ARTICLE] and cached PDFs finish before the summary text appears, which
    // looks confusing alongside "Summarizing search results…".
    const hasPdfParsingInProgress = pdfParseStatusItems?.some(i => i.status === 'parsing' || i.status === 'downloading') ?? false
    const isWebSearchStreaming = isStreaming && !!webSearchResult
    const showPdfParsingStatus = !!pdfParseStatusItems && hasPdfParsingInProgress && isStreaming && !isWebSearchStreaming

    // Show "summarizing search results" indicator after search completes but before
    // the AI starts streaming actual summary text. This fills the visual gap between
    // the search-completed card and the streamed markdown content.
    const showSummarizingSearch = !!webSearchResult && isStreaming && !displayContent.trim()

    // Show completed card when all PDFs are done (not streaming OR all statuses are final).
    // Hide during web-search streaming to avoid "Parsed N PDFs" card appearing before
    // or alongside "Summarizing search results…" (jarring when PDF is cached).
    const showPdfParsingCompleted = !!pdfParseStatusItems && !hasPdfParsingInProgress && !isWebSearchStreaming

    // Show "summarizing PDF" indicator after PDF parsing completes but before
    // the AI starts streaming the actual summary. Fills the visual gap between
    // the "已解析 N 篇 PDF 论文" card and the streamed markdown content.
    const hasCompletedPdf = pdfParseStatusItems?.some(i => i.status === 'completed') ?? false
    const showSummarizingPdf = showPdfParsingCompleted && hasCompletedPdf && isStreaming && !displayContent.trim()

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

      {/* Summarizing PDF indicator */}
      {showSummarizingPdf && (
        <SummarizingPdfStatus />
      )}

	      {/* Markdown content — no skeleton; stream starts directly */}
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
	          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>
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

