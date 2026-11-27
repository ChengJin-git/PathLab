import type { CitationSource, WebSearchResultEvent } from '../../api/chat'
import type { ReferenceCardProps } from './ReferenceCard'
import remend, { isWithinCodeBlock, isWithinMathBlock } from 'remend'

export interface CitationContext {
  page: number
  context: string
  sourceId?: string
}

export function parseCitationContexts(content: string): Record<string, CitationContext> | null {
  const match = content.match(/\[CITATION_CONTEXTS\]([\s\S]*?)\[\/CITATION_CONTEXTS\]/)
  if (!match) return null
  try {
    const parsed = JSON.parse(match[1])
    if (!parsed || typeof parsed !== 'object') return null
    return Object.fromEntries(Object.entries(parsed).flatMap(([key, value]) => {
      if (!value || typeof value !== 'object') return []
      const raw = value as Record<string, unknown>
      return [[normalizeCitationKey(key), {
        page: Number(raw.page) || 0,
        context: typeof raw.context === 'string' ? raw.context : '',
        sourceId: typeof raw.source_id === 'string' ? raw.source_id : typeof raw.sourceId === 'string' ? raw.sourceId : undefined,
      }]]
    }))
  } catch {
    return null
  }
}

export function findReferenceCardForCitation(cards: ReferenceCardProps[] | null, key: string, sourceId?: string) {
  if (sourceId) return cards?.find(card => card.sourceId === sourceId)
  return cards?.find(card => card.sourceIndex === Number(key.split('-')[0]))
}

function normalizeCitationKey(key: string) {
  return key.replace(/\s/g, '').replace(/[–—−]/g, '-').toLowerCase()
}

interface CitationData {
  title: string
  url: string
  snippet: string
  source: string
  sourceId?: string
  sourceIndex: number
  pageInfo?: string
}

interface MarkdownNode {
  type: string
  value?: string
  url?: string
  children?: MarkdownNode[]
  position?: { start: { offset?: number }; end: { offset?: number } }
}

const citationPattern = /\[(\d{1,3})(?:,\s*(p\.\s*\d+(?:\s*[-–—−]\s*\d+)?(?:\s*,\s*p\.\s*\d+(?:\s*[-–—−]\s*\d+)?)*)|((?:\s*,\s*\d{1,3})+))?\]/gi

/** One sequential display index per unique source/page target, in document order.
 * Source IDs/indices remain separate and are never changed by display numbering.
 */
export function createCitationRenderer({ references, contexts, sources, searchResults, streaming }: {
  references: ReferenceCardProps[]
  contexts: Record<string, CitationContext> | null
  sources: CitationSource[]
  searchResults: WebSearchResultEvent[]
  streaming: boolean
}) {
  const map = new Map<number, CitationData>()

  function resolve(sourceIndex: number, pagePart?: string): CitationData | undefined {
    const key = normalizeCitationKey(`${sourceIndex}-${pagePart || 'bare'}`)
    const ctx = contexts?.[key]
    const source = sources.find(item => item.source_index === sourceIndex && (!ctx?.sourceId || ctx.sourceId === item.source_id))
    const reference = findReferenceCardForCitation(references, key, ctx?.sourceId)
    const search = !pagePart ? searchResults.flatMap(result => result.results).find((item, index) => (item.source_index || index + 1) === sourceIndex) : undefined
    if (!source && !reference && !search) return undefined
    let snippet = ctx?.context || search?.snippet || ''
    if (pagePart && !ctx) {
      const pages: number[] = []
      for (const match of pagePart.matchAll(/(\d+)(?:\s*[-–—−]\s*(\d+))?/g)) {
        const start = Number(match[1]), end = Number(match[2] || match[1])
        if (start < 1 || end < start || end - start > 300) return undefined
        for (let page = start; page <= end; page++) pages.push(page)
      }
      // Never promote a hallucinated page into a verified citation badge.
      if (!pages.length || !source || pages.some(page => !Object.hasOwn(source.pages, String(page)))) return undefined
      snippet = source.pages[String(pages[0])] || ''
    }
    const url = reference?.url || source?.url || search?.url || ''
    let host = ''
    try { host = new URL(url).hostname.replace(/^www\./, '') } catch { /* invalid reference */ }
    return {
      title: reference?.title || source?.title || search?.title || '', url, snippet,
      source: host, sourceIndex, sourceId: ctx?.sourceId || reference?.sourceId || source?.source_id || search?.source_id,
      pageInfo: pagePart ? normalizeCitationKey(pagePart) : undefined,
    }
  }

  function remarkCitations() {
    return (tree: MarkdownNode) => {
      map.clear()
      const indices = new Map<string, number>()
      function walk(node: MarkdownNode) {
        // Transform prose text only: code, math, URLs and link labels are literal.
        if (['link', 'linkReference', 'image', 'imageReference', 'code', 'inlineCode', 'math', 'inlineMath', 'html'].includes(node.type)) return
        if (!node.children) return
        node.children = node.children.flatMap(child => {
          if (child.type !== 'text') { walk(child); return [child] }
          const value = child.value || ''
          const output: MarkdownNode[] = []
          let cursor = 0
          for (const match of value.matchAll(citationPattern)) {
            const targets = match[3] ? [match[1], ...match[3].split(',').filter(Boolean)].map(Number) : [Number(match[1])]
            const entries = targets.map(index => resolve(index, match[2]))
            if (entries.some(entry => !entry)) continue
            if (match.index > cursor) output.push({ type: 'text', value: value.slice(cursor, match.index) })
            entries.forEach((entry, i) => {
              const key = normalizeCitationKey(`${targets[i]}-${match[2] || 'bare'}`)
              const index = indices.get(key) || indices.size + 1
              indices.set(key, index)
              map.set(index, entry!)
              output.push({ type: 'link', url: `#cite-${index}`, children: [{ type: 'text', value: String(index) }] })
            })
            cursor = match.index + match[0].length
          }
          let tail = value.slice(cursor)
          if (streaming) tail = tail.replace(/\[(?:\d{0,3}(?:,\s*(?:p\.?[\d\s,–—−.-]*)?)?)?$/, '')
          output.push({ type: 'text', value: tail })
          return output
        })
      }
      walk(tree)
    }
  }
  return { map, remarkCitations }
}

export function prepareStreamingMarkdown(content: string, streaming: boolean): string {
  if (!streaming) return content
  if (/^[*_]{1,3}$/.test(content.trim())) return ''
  const partialCitation = /\[(?:\d{0,3}(?:,\s*(?:p\.?[\d\s,–—−.-]*)?)?)?$/.exec(content)
  let openCode = 0
  if (partialCitation) {
    for (const ticks of content.slice(0, partialCitation.index).matchAll(/`+/g)) {
      if (isWithinCodeBlock(content, ticks.index)) continue
      if (!openCode) openCode = ticks[0].length
      else if (openCode === ticks[0].length) openCode = 0
    }
  }
  if (partialCitation && !openCode && !isWithinCodeBlock(content, partialCitation.index) && !isWithinMathBlock(content, partialCitation.index)) {
    content = content.slice(0, partialCitation.index)
  }
  return remend(content, { linkMode: 'text-only', katex: false })
}
