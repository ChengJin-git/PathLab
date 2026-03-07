/**
 * InlineCitation — Gemini-style inline citation badge with hover tooltip.
 *
 * Renders a small numbered badge (e.g. [1] or [2, p.3]) that shows a tooltip
 * on hover with title, source, and snippet excerpt. Clicking opens the URL.
 */
import React from 'react'
import { ExternalLink } from 'lucide-react'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '../ui/hover-card'

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

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLSpanElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  const labelContent = variant === 'text' ? `[${label}]` : label
  const hasTooltipContent = Boolean(title || truncatedSnippet || pageInfo || source)

  const trigger = (
    <span
      className={variant === 'text'
        ? "mx-[0.08rem] inline text-[0.95em] font-medium leading-none text-primary-600/90 cursor-pointer select-none align-[0.02em] hover:text-primary-700"
        : "inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 mx-0.5 text-[11px] font-medium leading-none rounded-md cursor-pointer select-none bg-primary-50 text-primary-600 border border-primary-200 hover:bg-primary-100 hover:border-primary-300 hover:shadow-sm transition-all duration-150 align-baseline"
      }
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={title || `Citation ${index}`}
    >
      {labelContent}
    </span>
  )

  if (!hasTooltipContent) {
    return trigger
  }

  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>{trigger}</HoverCardTrigger>
      <HoverCardContent
        className="z-[9999] w-72 max-w-[calc(100vw-16px)] rounded-xl border border-gray-200 bg-white p-3 shadow-lg"
        side="top"
        align="center"
        sideOffset={8}
        collisionPadding={8}
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
      </HoverCardContent>
    </HoverCard>
  )
})

export default InlineCitation

