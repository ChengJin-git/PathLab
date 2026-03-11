/**
 * SearchingStatus — displays a searching indicator when AI is performing web search.
 *
 * Similar to the "Thinking..." indicator but for web search operations.
 * Also handles PDF parsing status display.
 */
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Globe, FileText, Download, ChevronDown, ExternalLink, AlertCircle } from 'lucide-react'

export interface SearchingStatusProps {
  query?: string
  reason?: string
}

/**
 * Parse [SEARCH_STATUS] block from content
 * Returns the parsed JSON config or null if not found
 */
export function parseSearchStatus(content: string): { query?: string; reason?: string } | null {
  const matches = Array.from(content.matchAll(/\[SEARCH_STATUS\]([\s\S]*?)\[\/SEARCH_STATUS\]/g))
  const match = matches.at(-1)
  if (!match) return null
  
  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    // If parsing fails, try to extract query from the content
    const queryMatch = content.match(/"query"\s*:\s*"([^"]+)"/)
    const reasonMatch = content.match(/"reason"\s*:\s*"([^"]+)"/)
    return {
      query: queryMatch?.[1],
      reason: reasonMatch?.[1]
    }
  }
}

/**
 * Remove [SEARCH_STATUS] block from content
 */
export function removeSearchStatusBlock(content: string): string {
  return content.replace(/\[SEARCH_STATUS\][\s\S]*?\[\/SEARCH_STATUS\]/g, '').trim()
}

/**
 * Parse [WEB_SEARCH_RESULT] block from content
 * Returns the parsed JSON result or null if not found
 */
export interface WebSearchResult {
  query: string
  results: Array<{
    title: string
    url: string
    snippet: string
  }>
}
 
export function parseWebSearchResult(content: string): WebSearchResult | null {
  const matches = Array.from(content.matchAll(/\[WEB_SEARCH_RESULT\]([\s\S]*?)\[\/WEB_SEARCH_RESULT\]/g))
  const match = matches.at(-1)
  if (!match) return null
  
  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [WEB_SEARCH_RESULT] block from content
 */
export function removeWebSearchResultBlock(content: string): string {
  return content.replace(/\[WEB_SEARCH_RESULT\][\s\S]*?\[\/WEB_SEARCH_RESULT\]/g, '').trim()
}

// Animated searching indicator component
const SearchingStatus = React.memo(function SearchingStatus({ query, reason }: SearchingStatusProps) {
  const { t } = useTranslation()
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl my-2"
    >
      {/* Animated search icon */}
      <div className="relative flex-shrink-0">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-4 sm:w-5 h-4 sm:h-5 border-2 border-blue-200 border-t-blue-500 rounded-full"
        />
        <Search className="w-4 sm:w-5 h-4 sm:h-5 text-blue-500 relative z-10" />
      </div>

      {/* Status text */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <div className="flex items-center gap-1 sm:gap-2 min-w-0">
          <span className="text-xs sm:text-sm font-medium text-blue-700 whitespace-nowrap flex-shrink-0">
            {t('settings.general.searching')}
          </span>
          {query && (
            <span className="text-[10px] sm:text-xs text-blue-500 truncate min-w-0">
              &quot;{query}&quot;
            </span>
          )}
        </div>
        {reason && (
          <p className="text-[10px] sm:text-xs text-blue-600/70 mt-0.5 truncate">
            {reason}
          </p>
          )}
      </div>

      {/* Animated dots */}
      <div className="flex gap-1 flex-shrink-0">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1 sm:w-1.5 h-1 sm:h-1.5 bg-blue-400 rounded-full"
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 0.6,
              repeat: Infinity,
              delay: i * 0.15,
            }}
          />
        ))}
      </div>
    </motion.div>
  )
})

/**
 * SearchCompletedCard Component
 *
 * Displays a completion card showing how many pages were searched,
 * with a collapsible list of all search results.
 */
export const SearchCompletedCard = React.memo(function SearchCompletedCard({
  query,
  resultCount,
  results
}: {
  query: string
  resultCount: number
  results?: Array<{ title: string; url: string; snippet: string }>
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="bg-gradient-to-r from-green-50 to-emerald-50 border border-green-100 rounded-xl my-2 overflow-hidden"
    >
      {/* Header row — clickable to toggle results list */}
      <button
        type="button"
        onClick={() => results && results.length > 0 && setExpanded(!expanded)}
        className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 w-full text-left hover:bg-green-50/50 transition-colors"
      >
        {/* Check icon */}
        <div className="flex-shrink-0">
          <div className="w-4 sm:w-5 h-4 sm:h-5 bg-green-500 rounded-full flex items-center justify-center">
            <svg
              className="w-2.5 sm:w-3 h-2.5 sm:h-3 text-white"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={3}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
        </div>

        {/* Search completion info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 sm:gap-2">
            <span className="text-xs sm:text-sm font-medium text-green-700">
              {t('settings.general.searchedPages', { count: resultCount })}
            </span>
          </div>
          <p className="text-[10px] sm:text-xs text-green-600/70 mt-0.5 truncate">&quot;{query}&quot;</p>
        </div>

        {/* Expand/collapse chevron */}
        {results && results.length > 0 && (
          <ChevronDown
            className={`w-3.5 sm:w-4 h-3.5 sm:h-4 text-green-500 flex-shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {/* Collapsible results list */}
      <AnimatePresence>
        {expanded && results && results.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 sm:px-4 pb-2 sm:pb-3 space-y-1 sm:space-y-1.5 border-t border-green-100/60 pt-2">
              {results.map((result, idx) => {
                let source = ''
                try { source = new URL(result.url).hostname.replace(/^www\./, '') } catch { /* ignore */ }
                return (
                  <a
                    key={idx}
                    href={result.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-1.5 sm:gap-2 px-2 sm:px-2.5 py-1 sm:py-1.5 rounded-lg hover:bg-green-100/50 transition-colors group"
                  >
                    <span className="text-[10px] sm:text-xs font-medium text-green-600 mt-0.5 flex-shrink-0 w-4 text-right">
                      {idx + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] sm:text-xs font-medium text-gray-800 truncate group-hover:text-green-700">
                        {result.title || source || result.url}
                      </p>
                      {result.title && (
                        <p className="text-[9px] sm:text-[10px] text-gray-400 truncate">{source}</p>
                      )}
                    </div>
                    <ExternalLink className="w-2.5 sm:w-3 h-2.5 sm:h-3 text-gray-300 group-hover:text-green-500 flex-shrink-0 mt-0.5" />
                  </a>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
})

// ============================================================================
// Summarizing Search Results Status
// ============================================================================

/**
 * SummarizingSearchStatus — animated indicator while AI is summarizing web search results.
 *
 * Shown after search completes (SearchCompletedCard visible) but before
 * the AI starts streaming the actual summary text.
 */
export const SummarizingSearchStatus = React.memo(function SummarizingSearchStatus() {
  const { t } = useTranslation()

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl my-2"
    >
      {/* Animated globe icon */}
      <div className="relative">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-4 sm:w-5 h-4 sm:h-5 border-2 border-blue-200 border-t-blue-500 rounded-full"
        />
        <Globe className="w-4 sm:w-5 h-4 sm:h-5 text-blue-500 relative z-10" />
      </div>

      {/* Status text */}
      <div className="flex-1 min-w-0">
        <span className="text-xs sm:text-sm font-medium text-blue-700">
          {t('settings.general.summarizingSearch')}
        </span>
      </div>

      {/* Animated dots */}
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1 sm:w-1.5 h-1 sm:h-1.5 bg-blue-400 rounded-full"
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 0.6,
              repeat: Infinity,
              delay: i * 0.15,
            }}
          />
        ))}
      </div>
    </motion.div>
  )
})

// ============================================================================
// Summarizing PDF Status
// ============================================================================

/**
 * SummarizingPdfStatus — animated indicator while AI is generating the PDF summary.
 *
 * Shown after PDF parsing completes (PdfParsingCompletedCard visible) but before
 * the AI starts streaming the actual summary text.
 */
export const SummarizingPdfStatus = React.memo(function SummarizingPdfStatus() {
  const { t } = useTranslation()

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-100 rounded-xl my-2"
    >
      {/* Animated FileText icon */}
      <div className="relative">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-4 sm:w-5 h-4 sm:h-5 border-2 border-emerald-200 border-t-emerald-500 rounded-full"
        />
        <FileText className="w-4 sm:w-5 h-4 sm:h-5 text-emerald-500 relative z-10" />
      </div>

      {/* Status text */}
      <div className="flex-1 min-w-0">
        <span className="text-xs sm:text-sm font-medium text-emerald-700">
          {t('settings.general.summarizingPdf')}
        </span>
      </div>

      {/* Animated dots */}
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1 sm:w-1.5 h-1 sm:h-1.5 bg-emerald-400 rounded-full"
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 0.6,
              repeat: Infinity,
              delay: i * 0.15,
            }}
          />
        ))}
      </div>
    </motion.div>
  )
})

// ============================================================================
// PDF Parse Status
// ============================================================================

export interface PdfParseStatusItem {
  url: string
  title: string
  status: string // "parsing" | "completed" | "download_failed" | "parse_failed" | "parse_busy" | error strings
  from_cache?: boolean
}

/**
 * Parse all [PDF_PARSE_STATUS] blocks from content.
 * Deduplicates by URL, keeping the latest status.
 * Returns null if no blocks found.
 */
export function parseAllPdfParseStatus(content: string): PdfParseStatusItem[] | null {
  const regex = /\[PDF_PARSE_STATUS\]([\s\S]*?)\[\/PDF_PARSE_STATUS\]/g
  const items = new Map<string, PdfParseStatusItem>()
  let match: RegExpExecArray | null

  while ((match = regex.exec(content)) !== null) {
    try {
      const parsed = JSON.parse(match[1].trim()) as PdfParseStatusItem
      if (parsed.url) {
        items.set(parsed.url, parsed)
      }
    } catch {
      // Skip invalid JSON
    }
  }

  if (items.size === 0) return null
  return Array.from(items.values())
}

/**
 * Remove all [PDF_PARSE_STATUS] blocks from content
 */
export function removePdfParseStatusBlock(content: string): string {
  return content.replace(/\[PDF_PARSE_STATUS\][\s\S]*?\[\/PDF_PARSE_STATUS\]/g, '').trim()
}

/**
 * PdfParsingStatus — animated indicator while PDFs are being parsed.
 */
export const PdfParsingStatus = React.memo(function PdfParsingStatus({
  items
}: {
  items: PdfParseStatusItem[]
}) {
  const { t } = useTranslation()
  // Show "downloading" or "parsing" depending on the most recent in-progress item
  const inProgressItems = items.filter(i => i.status === 'downloading' || i.status === 'parsing')
  const currentItem = inProgressItems[0]
  const currentTitle = currentItem?.title || ''
  const isDownloading = currentItem?.status === 'downloading'
  const statusText = isDownloading
    ? t('settings.general.downloadingPdf')
    : t('settings.general.parsingPdf')

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-100 rounded-xl my-2"
    >
      {/* Animated icon — Download for downloading, FileText for parsing */}
      <div className="relative flex-shrink-0">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-4 sm:w-5 h-4 sm:h-5 border-2 border-amber-200 border-t-amber-500 rounded-full"
        />
        {isDownloading
          ? <Download className="w-4 sm:w-5 h-4 sm:h-5 text-amber-500 relative z-10" />
          : <FileText className="w-4 sm:w-5 h-4 sm:h-5 text-amber-500 relative z-10" />
        }
      </div>

      {/* Status text */}
      <div className="flex-1 min-w-0 overflow-hidden">
        <span className="text-xs sm:text-sm font-medium text-amber-700 whitespace-nowrap">
          {statusText}
        </span>
        {currentTitle && (
          <p className="text-[10px] sm:text-xs text-amber-600/70 mt-0.5 truncate">{currentTitle}</p>
        )}
      </div>

      {/* Animated dots */}
      <div className="flex gap-1 flex-shrink-0">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1 sm:w-1.5 h-1 sm:h-1.5 bg-amber-400 rounded-full"
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 0.6,
              repeat: Infinity,
              delay: i * 0.15,
            }}
          />
        ))}
      </div>
    </motion.div>
  )
})

/**
 * PdfParsingCompletedCard — shows summary after PDF parsing is done.
 * Displays success card if any PDFs were parsed, and/or failure card
 * if any PDFs failed to download or parse.
 */
export const PdfParsingCompletedCard = React.memo(function PdfParsingCompletedCard({
  items
}: {
  items: PdfParseStatusItem[]
}) {
  const { t } = useTranslation()
  const completedItems = items.filter(i => i.status === 'completed')
  const completedCount = completedItems.length
  const failedItems = items.filter(i => i.status === 'download_failed' || i.status === 'parse_failed')
  const busyItems = items.filter(i => i.status === 'parse_busy' || i.status === 'busy')

  // Don't show if nothing completed, failed, or was rejected due to load
  if (completedCount === 0 && failedItems.length === 0 && busyItems.length === 0) return null

  return (
    <>
      {/* Success card */}
      {completedCount > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-100 rounded-xl my-2"
        >
          {/* Check icon */}
          <div className="flex-shrink-0">
            <div className="w-4 sm:w-5 h-4 sm:h-5 bg-green-500 rounded-full flex items-center justify-center">
              <svg
                className="w-2.5 sm:w-3 h-2.5 sm:h-3 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={3}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
          </div>

          {/* Completion info */}
          <div className="flex-1 min-w-0">
            <span className="text-xs sm:text-sm font-medium text-green-700">
              {t('settings.general.pdfParsedCount', { count: completedCount })}
            </span>
          </div>
        </motion.div>
      )}

      {/* Failure card */}
      {failedItems.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-red-50 to-rose-50 border border-red-100 rounded-xl my-2"
        >
          {/* Error icon */}
          <div className="flex-shrink-0">
            <AlertCircle className="w-4 sm:w-5 h-4 sm:h-5 text-red-500" />
          </div>

          {/* Failure info */}
          <div className="flex-1 min-w-0">
            <span className="text-xs sm:text-sm font-medium text-red-700">
              {failedItems.length === 1
                ? (failedItems[0].status === 'download_failed'
                  ? t('settings.general.pdfDownloadFailed')
                  : t('settings.general.pdfParseFailed'))
                : t('settings.general.pdfFailedCount', { count: failedItems.length })}
            </span>
            {failedItems.length === 1 && failedItems[0].title && (
              <p className="text-[10px] sm:text-xs text-red-600/70 mt-0.5 truncate">{failedItems[0].title}</p>
            )}
          </div>
        </motion.div>
      )}

      {/* Busy card */}
      {busyItems.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-100 rounded-xl my-2"
        >
          <div className="flex-shrink-0">
            <AlertCircle className="w-4 sm:w-5 h-4 sm:h-5 text-amber-500" />
          </div>

          <div className="flex-1 min-w-0">
            <span className="text-xs sm:text-sm font-medium text-amber-700">
              {t('settings.general.pdfParseBusy')}
            </span>
            {busyItems.length === 1 && busyItems[0].title && (
              <p className="text-[10px] sm:text-xs text-amber-600/70 mt-0.5 truncate">{busyItems[0].title}</p>
            )}
          </div>
        </motion.div>
      )}
    </>
  )
})

export default SearchingStatus
