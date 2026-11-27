/**
 * ReferenceCard — displays a reference card for PDF papers and academic sources.
 *
 * Parses [REFERENCE] blocks from AI responses and renders them as clickable cards.
 * Uses favicon extracted from the reference URL with emoji fallback.
 */
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion } from 'framer-motion'
import { ExternalLink, FileText, Globe } from 'lucide-react'

export interface ReferenceCardProps {
  icon: string
  title: string
  url: string
  sourceId?: string
  sourceIndex?: number
  source: string
  type: 'paper' | 'webpage'
}

/**
 * Parse [REFERENCE] block from content
 * Returns the parsed config or null if not found
 */
export function parseReferenceCard(content: string): ReferenceCardProps | null {
  const match = content.match(/\[REFERENCE\]([\s\S]*?)\[\/REFERENCE\]/)
  if (!match) return null
  
  try {
    const blockContent = match[1].trim()
    const lines = blockContent.split('\n')
    const config: Record<string, string> = {}
    
    for (const line of lines) {
      const colonIndex = line.indexOf(':')
      if (colonIndex > 0) {
        const key = line.substring(0, colonIndex).trim().toLowerCase()
        const value = line.substring(colonIndex + 1).trim()
        config[key] = value
      }
    }
    
    // Validate required fields
    if (!config.title || !config.url) return null

    return {
      icon: config.icon || '📄',
      title: config.title,
      url: config.url,
      sourceId: config.source_id || config.sourceid,
      sourceIndex: /^\d+$/.test(config.source_index || '') ? Number(config.source_index) : undefined,
      source: config.source || 'Unknown',
      type: (config.type === 'webpage' ? 'webpage' : 'paper') as 'paper' | 'webpage'
    }
  } catch {
    return null
  }
}

/**
 * Parse all [REFERENCE] blocks from content
 * Returns array of parsed configs
 */
export function parseAllReferenceCards(content: string): ReferenceCardProps[] {
  const results: ReferenceCardProps[] = []
  const regex = /\[REFERENCE\]([\s\S]*?)\[\/REFERENCE\]/g
  let match
  
  while ((match = regex.exec(content)) !== null) {
    const parsed = parseReferenceCard(match[0])
    if (parsed) {
      const existing = results.findIndex(card => (parsed.sourceId && card.sourceId === parsed.sourceId) || card.url === parsed.url)
      if (existing < 0) results.push(parsed)
      else if (parsed.sourceIndex) results[existing] = parsed
    }
  }
  
  return results
}

/**
 * Remove [REFERENCE] block from content
 */
export function removeReferenceBlock(content: string): string {
  return content.replace(/\[REFERENCE\][\s\S]*?\[\/REFERENCE\]/g, '').trim()
}

/**
 * Remove all [REFERENCE] blocks from content
 */
export function removeAllReferenceBlocks(content: string): string {
  return content.replace(/\[REFERENCE\][\s\S]*?\[\/REFERENCE\]/g, '').trim()
}

/**
 * Extract domain from URL for favicon
 */
function extractDomain(url: string): string | null {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname
  } catch {
    return null
  }
}

/**
 * Get favicon URL from domain using Google's favicon service
 */
function getFaviconUrl(url: string): string | null {
  const domain = extractDomain(url)
  if (!domain) return null
  // Use Google's favicon service as a reliable fallback
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`
}

/**
 * JournalLogo — renders a favicon from the reference URL with emoji fallback.
 */
const JournalLogo = React.memo(function JournalLogo({
  icon,
  url
}: {
  icon: string
  url: string
}) {
  const [faviconError, setFaviconError] = useState(false)

  // Try to extract favicon from URL
  if (!faviconError) {
    const faviconUrl = getFaviconUrl(url)
    if (faviconUrl) {
      return (
        <img
          src={faviconUrl}
          alt=""
          className="w-7 h-7 object-contain rounded"
          onError={() => setFaviconError(true)}
        />
      )
    }
  }

  // Fallback: emoji icon
  return <span className="text-2xl leading-none">{icon}</span>
})

// Individual reference card component
const ReferenceCard = React.memo(function ReferenceCard({
  icon,
  title,
  url,
  source,
  type
}: ReferenceCardProps) {
  const { t } = useTranslation()
  const displayDomain = extractDomain(url)?.replace(/^www\./, '')

  const handleClick = () => {
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  // Determine badge color based on source type
  const getBadgeColor = () => {
    const sourceLower = source.toLowerCase()
    if (sourceLower.includes('arxiv')) return 'bg-orange-100 text-orange-700 border-orange-200'
    if (sourceLower.includes('pubmed') || sourceLower.includes('ncbi')) return 'bg-blue-100 text-blue-700 border-blue-200'
    if (sourceLower.includes('nature')) return 'bg-green-100 text-green-700 border-green-200'
    if (sourceLower.includes('science')) return 'bg-purple-100 text-purple-700 border-purple-200'
    if (sourceLower.includes('cell')) return 'bg-teal-100 text-teal-700 border-teal-200'
    if (sourceLower.includes('lancet')) return 'bg-red-100 text-red-700 border-red-200'
    if (sourceLower.includes('nejm') || sourceLower.includes('jama')) return 'bg-indigo-100 text-indigo-700 border-indigo-200'
    if (sourceLower.includes('springer')) return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    if (sourceLower.includes('ieee') || sourceLower.includes('acm')) return 'bg-cyan-100 text-cyan-700 border-cyan-200'
    return 'bg-gray-100 text-gray-700 border-gray-200'
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="group flex items-start gap-2 sm:gap-3 px-3 sm:px-4 py-2.5 sm:py-3 bg-gradient-to-r from-slate-50 to-gray-50 border border-gray-200 rounded-xl my-2 cursor-pointer hover:border-primary-300 hover:shadow-sm transition-all"
      onClick={handleClick}
    >
      {/* Logo / Icon */}
      <div className="flex-shrink-0 flex items-center justify-center w-8 h-8 overflow-hidden">
        <JournalLogo icon={icon} url={url} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Title */}
        <h4 className="text-sm font-medium text-gray-900 line-clamp-2 group-hover:text-primary-600 transition-colors">
          {title}
        </h4>

        {/* Source and type */}
        <div className="flex items-center gap-1.5 sm:gap-2 mt-1 sm:mt-1.5 flex-wrap">
          <span className={`text-xs px-1.5 sm:px-2 py-0.5 rounded-full border ${getBadgeColor()} truncate max-w-[140px] sm:max-w-none`}>
            {source}
          </span>
          <span className="text-xs text-gray-400">
            {type === 'paper' ? (
              <span className="flex items-center gap-1">
                <FileText className="w-3 h-3" />
                {t('chatComponents.referenceCard.paper')}
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <Globe className="w-3 h-3" />
                {t('chatComponents.referenceCard.webpage')}
              </span>
            )}
          </span>
          {displayDomain && (
            <span className="text-xs text-gray-400 truncate max-w-[180px]" title={displayDomain}>
              {displayDomain}
            </span>
          )}
        </div>
      </div>

      {/* External link indicator */}
      <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <ExternalLink className="w-4 h-4 text-primary-500" />
      </div>
    </motion.div>
  )
})

/**
 * ReferenceCardList — renders multiple reference cards
 */
export const ReferenceCardList = React.memo(function ReferenceCardList({
  cards
}: {
  cards: ReferenceCardProps[]
}) {
  const { t } = useTranslation()

  if (!cards || cards.length === 0) return null

  return (
    <div className="space-y-2 mt-3">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
        {t('chatComponents.referenceCard.references')}
      </div>
      {cards.map((card, index) => (
        <ReferenceCard key={`${card.sourceId || card.url}-${index}`} {...card} />
      ))}
    </div>
  )
})

export default ReferenceCard
