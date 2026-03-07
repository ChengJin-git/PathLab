/**
 * InlineCitation — Gemini-style inline citation badge with hover tooltip.
 *
 * Renders a small numbered badge (e.g. [1] or [2, p.3]) that shows a tooltip
 * on hover with title, source, and snippet excerpt. Clicking opens the URL.
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import { ExternalLink } from 'lucide-react'

export interface InlineCitationProps {
  index: number
  title?: string
  source?: string
  snippet?: string
  pageInfo?: string
  url?: string
  variant?: 'badge' | 'text'
}

const InlineCitation = React.memo(function InlineCitation({
  index,
  title,
  source,
  snippet,
  pageInfo,
  url,
  variant = 'badge'
}: InlineCitationProps) {
  const [showTooltip, setShowTooltip] = useState(false)
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({})
  const badgeRef = useRef<HTMLSpanElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  // Build label text — badge shows only the number; page info is in the tooltip
  const label = `${index}`

  // Truncate snippet — article citations (with pageInfo) get more space (~200 chars)
  // than web search snippets (~100 chars)
  const maxSnippetLen = pageInfo ? 200 : 100
  const truncatedSnippet = snippet
    ? snippet.length > maxSnippetLen
      ? snippet.slice(0, maxSnippetLen) + '…'
      : snippet
    : undefined

  // Calculate tooltip position to stay within viewport
  const updateTooltipPosition = useCallback(() => {
    if (!badgeRef.current || !tooltipRef.current) return
    const badgeRect = badgeRef.current.getBoundingClientRect()
    const tooltipEl = tooltipRef.current
    const tooltipWidth = tooltipEl.offsetWidth
    const viewportWidth = window.innerWidth

    const style: React.CSSProperties = {}

    // Horizontal: center on badge, but clamp within viewport
    let left = badgeRect.left + badgeRect.width / 2 - tooltipWidth / 2
    if (left < 8) left = 8
    if (left + tooltipWidth > viewportWidth - 8) left = viewportWidth - 8 - tooltipWidth
    style.left = left
    style.position = 'fixed'

    // Vertical: prefer above the badge, fall back to below
    const tooltipHeight = tooltipEl.offsetHeight
    if (badgeRect.top - tooltipHeight - 6 > 0) {
      style.top = badgeRect.top - tooltipHeight - 6
    } else {
      style.top = badgeRect.bottom + 6
    }

    setTooltipStyle(style)
  }, [])

  useEffect(() => {
    if (showTooltip) updateTooltipPosition()
  }, [showTooltip, updateTooltipPosition])

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }

  const labelContent = variant === 'text' ? `[${label}]` : label

  return (
    <>
      <span
        ref={badgeRef}
        className={variant === 'text'
          ? "mx-[0.08rem] inline text-[0.95em] font-medium leading-none text-primary-600/90 cursor-pointer select-none align-[0.02em] hover:text-primary-700"
          : "inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 mx-0.5 text-[11px] font-medium leading-none rounded-md cursor-pointer select-none bg-primary-50 text-primary-600 border border-primary-200 hover:bg-primary-100 hover:border-primary-300 hover:shadow-sm transition-all duration-150 align-baseline"
        }
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        aria-label={title || `Citation ${index}`}
      >
        {labelContent}
      </span>

      {/* Tooltip rendered via portal-like fixed positioning */}
      {showTooltip && (title || truncatedSnippet || pageInfo) && (
        <div
          ref={tooltipRef}
          style={tooltipStyle}
          className="fixed z-[9999] w-72 max-w-[calc(100vw-16px)] p-3 rounded-xl
            bg-white border border-gray-200 shadow-lg
            pointer-events-none animate-in fade-in duration-150"
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
        >
          {pageInfo ? (
            /* ── Article citation layout: page + snippet prominent, title/URL compact ── */
            <>
              {/* Page header with optional external link */}
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-gray-700">
                  📄 Page {pageInfo.replace(/p\./g, '').replace(/,\s*/g, ', ')}
                </span>
                {source && (
                  <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
                    <ExternalLink className="w-2.5 h-2.5" />
                    {source}
                  </span>
                )}
              </div>
              {/* Snippet — primary content */}
              {truncatedSnippet && (
                <p className="text-xs text-gray-600 leading-relaxed line-clamp-4 mb-1">
                  "{truncatedSnippet}"
                </p>
              )}
              {/* Title — de-emphasized */}
              {title && (
                <p className="text-[10px] text-gray-400 line-clamp-1 mt-1">{title}</p>
              )}
            </>
          ) : (
            /* ── Web search citation layout: title + source prominent ── */
            <>
              {/* Title */}
              {title && (
                <p className="text-sm font-medium text-gray-900 line-clamp-2 mb-1">{title}</p>
              )}
              {/* Source */}
              {source && (
                <p className="text-xs text-gray-500 mb-1.5 flex items-center gap-1">
                  <ExternalLink className="w-3 h-3 flex-shrink-0" />
                  {source}
                </p>
              )}
              {/* Snippet */}
              {truncatedSnippet && (
                <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">
                  "{truncatedSnippet}"
                </p>
              )}
            </>
          )}
        </div>
      )}
    </>
  )
})

export default InlineCitation

