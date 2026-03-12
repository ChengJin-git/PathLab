import { parse as parseBestEffortJson } from 'best-effort-json-parser'

export interface ChatBlockMatch {
  tag: string
  body: string
  raw: string
  isClosed: boolean
  start: number
  end: number
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function buildBlockRegex(tag: string): RegExp {
  const escapedTag = escapeRegExp(tag)
  return new RegExp(`\\[${escapedTag}\\]([\\s\\S]*?)\\[\\/${escapedTag}\\]`, 'g')
}

export function extractAllChatBlocks(
  content: string,
  tag: string,
  options?: { allowIncompleteLast?: boolean }
): ChatBlockMatch[] {
  const source = content || ''
  const regex = buildBlockRegex(tag)
  const matches: ChatBlockMatch[] = []
  let match: RegExpExecArray | null

  while ((match = regex.exec(source)) !== null) {
    matches.push({
      tag,
      body: match[1],
      raw: match[0],
      isClosed: true,
      start: match.index,
      end: match.index + match[0].length,
    })
  }

  if (options?.allowIncompleteLast) {
    const openTag = `[${tag}]`
    const closeTag = `[/${tag}]`
    const lastOpenIndex = source.lastIndexOf(openTag)
    if (lastOpenIndex !== -1 && !matches.some(item => item.start === lastOpenIndex)) {
      const closeAfterOpen = source.indexOf(closeTag, lastOpenIndex + openTag.length)
      if (closeAfterOpen === -1) {
        const bodyStart = lastOpenIndex + openTag.length
        matches.push({
          tag,
          body: source.slice(bodyStart),
          raw: source.slice(lastOpenIndex),
          isClosed: false,
          start: lastOpenIndex,
          end: source.length,
        })
      }
    }
  }

  return matches
}

export function extractLastChatBlock(
  content: string,
  tag: string,
  options?: { allowIncompleteLast?: boolean }
): ChatBlockMatch | null {
  return extractAllChatBlocks(content, tag, options).at(-1) ?? null
}

export function stripChatBlocks(content: string, tags: string | string[]): string {
  let result = content || ''

  for (const tag of Array.isArray(tags) ? tags : [tags]) {
    result = result.replace(buildBlockRegex(tag), '')

    const openTag = `[${tag}]`
    const closeTag = `[/${tag}]`
    const lastOpenIndex = result.lastIndexOf(openTag)
    if (lastOpenIndex !== -1) {
      const closeAfterOpen = result.indexOf(closeTag, lastOpenIndex + openTag.length)
      if (closeAfterOpen === -1) {
        result = result.slice(0, lastOpenIndex)
      }
    }
  }

  return result
}

function parseJsonBody<T>(body: string): T | null {
  const jsonText = body.trim()
  if (!jsonText) return null

  try {
    return JSON.parse(jsonText) as T
  } catch {
    try {
      return parseBestEffortJson(jsonText) as T
    } catch {
      return null
    }
  }
}

export function parseLastChatBlockJson<T>(
  content: string,
  tag: string,
  options?: { allowIncompleteLast?: boolean }
): T | null {
  const match = extractLastChatBlock(content, tag, options)
  if (!match) return null
  return parseJsonBody<T>(match.body)
}

export function parseAllChatBlockJson<T>(
  content: string,
  tag: string,
  options?: { allowIncompleteLast?: boolean }
): T[] | null {
  const parsed = extractAllChatBlocks(content, tag, options)
    .map(match => parseJsonBody<T>(match.body))
    .filter((item): item is T => item !== null)

  return parsed.length > 0 ? parsed : null
}