/**
 * SearchingStatus — displays a searching indicator when AI is performing web search.
 *
 * Similar to the "Thinking..." indicator but for web search operations.
 * Also handles PDF parsing status display.
 */
import React from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import { Search, Globe, FileText } from 'lucide-react'

export interface SearchingStatusProps {
  query?: string
  reason?: string
}

/**
 * Parse [SEARCH_STATUS] block from content
 * Returns the parsed JSON config or null if not found
 */
export function parseSearchStatus(content: string): { query?: string; reason?: string } | null {
  const match = content.match(/\[SEARCH_STATUS\]([\s\S]*?)\[\/SEARCH_STATUS\]/)
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
  const match = content.match(/\[WEB_SEARCH_RESULT\]([\s\S]*?)\[\/WEB_SEARCH_RESULT\]/)
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
      className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl my-2"
    >
      {/* Animated search icon */}
      <div className="relative">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-5 h-5 border-2 border-blue-200 border-t-blue-500 rounded-full"
        />
        <Search className="w-5 h-5 text-blue-500 relative z-10" />
      </div>
      
      {/* Status text */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-blue-700">
            {t('settings.general.searching')}
          </span>
          {query && (
            <span className="text-xs text-blue-500 truncate">
              "{query}"
            </span>
          )}
        </div>
        {reason && (
          <p className="text-xs text-blue-600/70 mt-0.5 truncate">
            {reason}
          </p>
          )}
      </div>
      
      {/* Animated dots */}
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1.5 h-1.5 bg-blue-400 rounded-full"
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
 * Displays a completion card showing how many pages were searched
 */
export const SearchCompletedCard = React.memo(function SearchCompletedCard({
  query,
  resultCount
}: {
  query: string
  resultCount: number
}) {
  const { t } = useTranslation()

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-100 rounded-xl my-2"
    >
      {/* Check icon */}
      <div className="flex-shrink-0">
        <div className="w-5 h-5 bg-green-500 rounded-full flex items-center justify-center">
          <svg
            className="w-3 h-3 text-white"
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
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-green-700">
            {t('settings.general.searchedPages', { count: resultCount })}
          </span>
        </div>
        <p className="text-xs text-green-600/70 mt-0.5 truncate">"{query}"</p>
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
  status: string // "parsing" | "completed" | "download_failed" | "parse_failed" | error strings
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
  const parsingItems = items.filter(i => i.status === 'parsing')
  const currentTitle = parsingItems[0]?.title || ''

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-100 rounded-xl my-2"
    >
      {/* Animated file icon */}
      <div className="relative">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          className="absolute inset-0 w-5 h-5 border-2 border-amber-200 border-t-amber-500 rounded-full"
        />
        <FileText className="w-5 h-5 text-amber-500 relative z-10" />
      </div>

      {/* Status text */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-amber-700">
            {t('settings.general.parsingPdf')}
          </span>
        </div>
        {currentTitle && (
          <p className="text-xs text-amber-600/70 mt-0.5 truncate">{currentTitle}</p>
        )}
      </div>

      {/* Animated dots */}
      <div className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1.5 h-1.5 bg-amber-400 rounded-full"
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
 */
export const PdfParsingCompletedCard = React.memo(function PdfParsingCompletedCard({
  items
}: {
  items: PdfParseStatusItem[]
}) {
  const { t } = useTranslation()
  const completedCount = items.filter(i => i.status === 'completed').length

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-100 rounded-xl my-2"
    >
      {/* Check icon */}
      <div className="flex-shrink-0">
        <div className="w-5 h-5 bg-green-500 rounded-full flex items-center justify-center">
          <svg
            className="w-3 h-3 text-white"
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
        <span className="text-sm font-medium text-green-700">
          {t('settings.general.pdfParsedCount', { count: completedCount })}
        </span>
      </div>
    </motion.div>
  )
})

export default SearchingStatus
