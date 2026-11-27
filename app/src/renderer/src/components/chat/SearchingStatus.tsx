/**
 * SearchingStatus — displays a searching indicator when AI is performing web search.
 *
 * Similar to the "Thinking..." indicator but for web search operations.
 * Also handles PDF parsing status display.
 */
import React, { useState, useEffect } from 'react'
import { useWorkbenchText } from './workbenchText'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Globe, FileText, Download, ChevronDown, ExternalLink, AlertCircle } from 'lucide-react'

export interface SearchingStatusProps {
  query?: string
  reason?: string
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
  results?: SearchResultItem[]
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
                      {result.source_index || idx + 1}
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

type SearchResultItem = { title: string; url: string; snippet: string; source_index?: number }
type WebSearchResult = { query: string; results?: SearchResultItem[] }

export const SearchResultsZone = React.memo(function SearchResultsZone({
  results,
  isStreaming,
}: {
  results: WebSearchResult[]
  isStreaming: boolean
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!isStreaming) setExpanded(false)
  }, [isStreaming])

  const totalSources = results.reduce((sum, r) => sum + (r.results?.length ?? 0), 0)

  if (isStreaming || expanded) {
    return (
      <div>
        {results.map((result, index) => (
          <SearchCompletedCard
            key={`${result.query}-${index}`}
            query={result.query}
            resultCount={result.results?.length ?? 0}
            results={result.results}
          />
        ))}
        {!isStreaming && (
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="flex items-center gap-1 px-2 py-0.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ChevronDown className="w-3 h-3 rotate-180" />
          </button>
        )}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => setExpanded(true)}
      className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 bg-green-50 hover:bg-green-100 border border-green-200 rounded-lg transition-colors w-full mb-2"
    >
      <Globe className="w-3 h-3 text-green-500 flex-shrink-0" />
      <span className="flex-1 text-left text-green-700">
        {t('settings.general.searchedPages', { count: totalSources })}
      </span>
      <ChevronDown className="w-3 h-3 text-green-400" />
    </button>
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
  action?: 'read' | 'download' | 'read_download'
  elapsed_ms?: number
  bytes_received?: number
  total_bytes?: number | null
  pages_done?: number
  total_pages?: number
  phase?: 'ocr'
  error_code?: string
  message?: string
  recovery_hint?: string
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
  const text = useWorkbenchText()
  // Show "downloading" or "parsing" depending on the most recent in-progress item
  const inProgressItems = items.filter(i => ['downloading','fetching','parsing','cached','waiting'].includes(i.status))
  const currentItem = inProgressItems.at(-1)
  const currentTitle = currentItem?.title || ''
  const isDownloading = currentItem?.status === 'downloading'
  const statusText = currentItem?.status === 'fetching' ? text('articleFetching') : currentItem?.status === 'cached' ? text('articleCached') : currentItem?.status === 'waiting' ? text('articleWaiting') : currentItem?.phase === 'ocr' ? text('articleOcr') : isDownloading
    ? t('settings.general.downloadingPdf')
    : t('settings.general.parsingPdf')
  const elapsed = Math.floor((currentItem?.elapsed_ms || 0) / 1000)
  const total = isDownloading ? currentItem?.total_bytes : currentItem?.total_pages
  const done = (isDownloading ? currentItem?.bytes_received : currentItem?.pages_done) || 0
  const progress = total && total > 0 ? Math.min(100, done / total * 100) : undefined
  const megabytes = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`
  const detail = isDownloading && done > 0
    ? `${megabytes(done)}${total ? ` / ${megabytes(total)}` : ''}`
    : currentItem?.total_pages
      ? text('articlePages').replace('{done}', String(done)).replace('{total}', String(total))
      : ''
  const hint = currentItem?.status === 'waiting' ? text('articleQueueHint')
    : elapsed >= 8 || (currentItem?.total_pages || 0) >= 40 || (currentItem?.total_bytes || 0) >= 8 * 1024 * 1024
      ? text(isDownloading || currentItem?.status === 'fetching' ? 'articleLongDownload' : 'articleLongRead') : ''

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 sm:py-3 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-100 rounded-xl my-2"
      role="status"
      aria-live="polite"
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
        <span className="text-xs sm:text-sm font-medium text-amber-700">
          {statusText}
        </span>
        {currentTitle && (
          <p className="text-[10px] sm:text-xs text-amber-600/70 mt-0.5 truncate">{currentTitle}</p>
        )}
        {(detail || elapsed > 0) && <p className="mt-1 text-xs text-amber-800 tabular-nums">
          {[detail, elapsed > 0 ? text('articleElapsed').replace('{seconds}', String(elapsed)) : ''].filter(Boolean).join(' · ')}
        </p>}
        {progress !== undefined && <div role="progressbar" aria-label={statusText} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)} className="mt-2 h-1 overflow-hidden rounded-full bg-amber-100">
          <div className="h-full rounded-full bg-amber-500 transition-[width] motion-reduce:transition-none" style={{ width: `${progress}%` }} />
        </div>}
        {hint && <p className="mt-1.5 text-xs leading-relaxed text-amber-700">{hint}</p>}
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
  const text = useWorkbenchText()
  const completedItems = items.filter(i => i.status === 'completed')
  const completedCount = completedItems.length
  const failedItems = items.filter(i => ['download_failed','parse_failed'].includes(i.status))
  const busyItems = items.filter(i => i.status === 'parse_busy')

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
              {completedItems.every(item => item.action === 'download') ? text('articleDownloaded') : t('settings.general.pdfParsedCount', { count: completedCount })}
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
              {failedItems.length === 1 && failedItems[0].message ? failedItems[0].message : failedItems.length === 1
                ? (failedItems[0].error_code === 'parse_timeout' ? text('articleParseTimeout') : failedItems[0].status === 'download_failed'
                  ? t('settings.general.pdfDownloadFailed')
                  : t('settings.general.pdfParseFailed'))
                : t('settings.general.pdfFailedCount', { count: failedItems.length })}
            </span>
            {failedItems.length === 1 && failedItems[0].title && (
              <p className="text-[10px] sm:text-xs text-red-600/70 mt-0.5 truncate">{failedItems[0].title}</p>
            )}
            {failedItems.map(item => item.recovery_hint && <p key={item.url} className="mt-1 text-xs leading-5 text-red-700">{failedItems.length > 1 ? `${item.title}: ${item.message} ` : ''}{item.recovery_hint}</p>)}
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
              {busyItems[0].message || t('settings.general.pdfParseBusy')}
            </span>
            {busyItems.length === 1 && busyItems[0].title && (
              <p className="text-[10px] sm:text-xs text-amber-600/70 mt-0.5 truncate">{busyItems[0].title}</p>
            )}
            {busyItems[0].recovery_hint && <p className="mt-1 text-xs leading-5 text-amber-700">{busyItems[0].recovery_hint}</p>}
          </div>
        </motion.div>
      )}
    </>
  )
})

export default SearchingStatus
