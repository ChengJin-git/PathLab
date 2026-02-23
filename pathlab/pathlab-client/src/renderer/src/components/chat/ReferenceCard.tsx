/**
 * ReferenceCard — displays a reference card for PDF papers and academic sources.
 *
 * Parses [REFERENCE] blocks from AI responses and renders them as clickable cards.
 * Supports journal logos from /images/journal-logos/{logo}.png with emoji fallback.
 */
import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { ExternalLink, FileText, BookOpen } from 'lucide-react'

export interface ReferenceCardProps {
  icon: string
  logo?: string // logo key matching /images/journal-logos/{logo}.png
  title: string
  url: string
  source: string
  type: 'paper' | 'article'
}

/**
 * Logo keys that have corresponding image files in /images/journal-logos/.
 * The frontend will attempt to render <img src="/images/journal-logos/{key}.png">
 * and fall back to the emoji icon if the image fails to load.
 *
 * Supported logos (place PNG files ~64x64 in /images/journal-logos/):
 *   arxiv.png, pubmed.png, nature.png, science.png, cell.png,
 *   lancet.png, nejm.png, jama.png, springer.png, ieee.png, acm.png, pdf.png
 */
const LOGO_SUPPORTED_KEYS = new Set([
  'arxiv', 'pubmed', 'nature', 'science', 'cell',
  'lancet', 'nejm', 'jama', 'springer', 'ieee', 'acm'
])

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
      logo: config.logo || undefined,
      title: config.title,
      url: config.url,
      source: config.source || 'Unknown',
      type: (config.type === 'article' ? 'article' : 'paper') as 'paper' | 'article'
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
      results.push(parsed)
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
 * JournalLogo — renders a journal logo image with emoji fallback.
 * Attempts to load /images/journal-logos/{logo}.png; falls back to emoji icon on error.
 */
const JournalLogo = React.memo(function JournalLogo({
  logo,
  icon
}: {
  logo?: string
  icon: string
}) {
  const [imgError, setImgError] = useState(false)
  const showLogo = logo && LOGO_SUPPORTED_KEYS.has(logo) && !imgError
  const baseUrl = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')

  if (showLogo) {
    return (
      <img
        src={`${baseUrl}/images/journal-logos/${logo}.png`}
        alt=""
        className="w-7 h-7 object-contain rounded"
        onError={() => setImgError(true)}
      />
    )
  }

  // Fallback: emoji icon
  return <span className="text-2xl leading-none">{icon}</span>
})

// Individual reference card component
const ReferenceCard = React.memo(function ReferenceCard({
  icon,
  logo,
  title,
  url,
  source,
  type
}: ReferenceCardProps) {
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
      className="group flex items-start gap-3 px-4 py-3 bg-gradient-to-r from-slate-50 to-gray-50 border border-gray-200 rounded-xl my-2 cursor-pointer hover:border-primary-300 hover:shadow-sm transition-all"
      onClick={handleClick}
    >
      {/* Logo / Icon */}
      <div className="flex-shrink-0 flex items-center justify-center w-8 h-8 overflow-hidden">
        <JournalLogo logo={logo} icon={icon} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Title */}
        <h4 className="text-sm font-medium text-gray-900 line-clamp-2 group-hover:text-primary-600 transition-colors">
          {title}
        </h4>

        {/* Source and type */}
        <div className="flex items-center gap-2 mt-1.5">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${getBadgeColor()}`}>
            {source}
          </span>
          <span className="text-xs text-gray-400">
            {type === 'paper' ? (
              <span className="flex items-center gap-1">
                <FileText className="w-3 h-3" />
                Paper
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <BookOpen className="w-3 h-3" />
                Article
              </span>
            )}
          </span>
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
  if (!cards || cards.length === 0) return null

  return (
    <div className="space-y-2 mt-3">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
        References
      </div>
      {cards.map((card, index) => (
        <ReferenceCard key={`${card.url}-${index}`} {...card} />
      ))}
    </div>
  )
})

export default ReferenceCard
