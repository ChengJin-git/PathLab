// Snap a selection (start, end) outwards to whole-sentence boundaries.
// Goal: stop users from selecting half a sentence and feeding it to the
// regenerate flow. The model rewrites whatever span you hand it, and a
// half-sentence rewrite stitched back to the rest reads awful.

const ABBREVIATIONS = [
  'e.g.',
  'i.e.',
  'cf.',
  'vs.',
  'etc.',
  'et al.',
  'Dr.',
  'Mr.',
  'Mrs.',
  'Ms.',
  'Prof.',
  'St.',
  'Fig.',
  'Eq.',
  'No.',
  'Vol.',
  'Ref.',
  'p.',
  'pp.',
  'U.S.',
  'U.K.',
  'A.D.',
  'B.C.',
]

const SENTENCE_TERMINATORS = new Set(['.', '!', '?'])

function endsWithAbbreviation(text: string, indexInclusive: number): boolean {
  // indexInclusive points at the terminator char in `text`.
  for (const abbr of ABBREVIATIONS) {
    const sliceStart = indexInclusive - (abbr.length - 1)
    if (sliceStart < 0) continue
    if (text.slice(sliceStart, indexInclusive + 1) === abbr) return true
  }
  return false
}

function isSentenceEndAt(text: string, terminatorIndex: number): boolean {
  // True iff text[terminatorIndex] is . / ! / ? AND it actually closes a
  // sentence (followed by whitespace + capital/digit/quote/end-of-text,
  // and not preceded by a common abbreviation).
  const ch = text[terminatorIndex]
  if (!ch || !SENTENCE_TERMINATORS.has(ch)) return false

  if (endsWithAbbreviation(text, terminatorIndex)) return false

  // End of text counts as a sentence end.
  if (terminatorIndex >= text.length - 1) return true

  // Need at least one whitespace after the terminator.
  const after = text.slice(terminatorIndex + 1)
  if (!/^\s/.test(after)) return false

  // Next non-whitespace character. If it's a capital letter, digit, or
  // common opening punctuation, treat the terminator as a true sentence end.
  const afterTrimmed = after.replace(/^\s+/, '')
  if (!afterTrimmed) return true
  return /^[A-Z0-9"“'`(\\]/.test(afterTrimmed)
}

function isParagraphBoundary(text: string, index: number): boolean {
  // A run of \n\n (optionally with horizontal whitespace) starting at index.
  return /^\n[\s\t ]*\n/.test(text.slice(index))
}

export interface ExpandResult {
  start: number
  end: number
  expanded: boolean
}

export function expandToSentence(text: string, start: number, end: number): ExpandResult {
  if (start < 0 || end > text.length || start >= end) {
    return { start, end, expanded: false }
  }

  // ---- walk backwards from `start` to the nearest sentence start. ----
  let newStart = start
  while (newStart > 0) {
    const prev = newStart - 1
    if (isParagraphBoundary(text, prev)) break
    if (SENTENCE_TERMINATORS.has(text[prev]) && isSentenceEndAt(text, prev)) {
      // newStart now points at the whitespace after the terminator; skip it.
      break
    }
    newStart--
  }
  while (newStart < text.length && /\s/.test(text[newStart])) newStart++

  // ---- walk forwards from `end` to the nearest sentence terminator. ----
  let newEnd = end
  // If the selection already happens to end exactly on a terminator we still
  // want to include any trailing closing quote/bracket, so let the loop run.
  while (newEnd < text.length) {
    if (isParagraphBoundary(text, newEnd)) break
    const ch = text[newEnd]
    if (SENTENCE_TERMINATORS.has(ch) && isSentenceEndAt(text, newEnd)) {
      // Include the terminator itself and any trailing closing quote / bracket.
      newEnd += 1
      while (newEnd < text.length && /["”')\]]/.test(text[newEnd])) newEnd += 1
      break
    }
    newEnd++
  }

  // Trim any trailing whitespace we accidentally absorbed.
  while (newEnd > newStart && /\s/.test(text[newEnd - 1])) newEnd--

  if (newStart >= newEnd) return { start, end, expanded: false }
  return { start: newStart, end: newEnd, expanded: newStart !== start || newEnd !== end }
}


// Trim a free-standing chunk of text (e.g. PDF selection where source offsets
// are unknown) to the complete sentences fully contained inside it. Returns
// null if no complete sentence can be carved out.
export function trimToContainedSentences(text: string): { text: string; trimmed: boolean } | null {
  const trimmed = text.trim()
  if (!trimmed) return null

  // For free-standing PDF chunks we assume the user-selected leading text
  // is the start of their span; the model can handle prose that begins mid-
  // word from a previous sentence as long as the *contained* span ends on a
  // terminator. So we don't aggressively skip leading lowercase here — only
  // skip leading non-word junk (whitespace was already stripped).
  let start = 0
  while (start < trimmed.length && !/[A-Za-z0-9"“'`(\\]/.test(trimmed[start])) start++
  if (start >= trimmed.length) return null

  // Walk backwards to the last position that is a sentence terminator. Allow
  // trailing closing quotes/brackets after the terminator.
  let end = trimmed.length
  while (end > start) {
    const i = end - 1
    if (/["”')\]]/.test(trimmed[i])) {
      end--
      continue
    }
    if (SENTENCE_TERMINATORS.has(trimmed[i]) && isSentenceEndAt(trimmed, i)) {
      // Re-include any closing punctuation we just stripped.
      while (end < trimmed.length && /["”')\]]/.test(trimmed[end])) end++
      break
    }
    end--
  }

  if (end <= start) return null
  const result = trimmed.slice(start, end)
  if (!result.trim()) return null
  return { text: result, trimmed: result !== text }
}


// Segment text into sentence-bounded spans with their original positions.
// Paragraph breaks act as hard splits (a paragraph never bridges sentences).
export interface SentenceSpan {
  start: number
  end: number
  text: string
}

export function segmentSentences(text: string): SentenceSpan[] {
  const out: SentenceSpan[] = []
  let cursor = 0
  while (cursor < text.length) {
    let s = cursor
    while (s < text.length && /\s/.test(text[s])) s++
    if (s >= text.length) break

    let e = s
    while (e < text.length) {
      if (isParagraphBoundary(text, e)) break
      const ch = text[e]
      if (SENTENCE_TERMINATORS.has(ch) && isSentenceEndAt(text, e)) {
        e += 1
        while (e < text.length && /["”')\]]/.test(text[e])) e += 1
        break
      }
      e++
    }
    if (e > s) out.push({ start: s, end: e, text: text.slice(s, e) })
    cursor = Math.max(e, s + 1)
  }
  return out
}


// Given a free-standing PDF selection and the matched section's LaTeX source,
// expand the selection outward to the full sentence(s) it overlaps in source.
// Returns null when no source sentence can be reasonably matched.

function normalizeForOverlap(text: string): string {
  return text
    .replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?/g, ' ') // strip LaTeX commands
    .replace(/\$[^$]*\$/g, ' ')
    .replace(/[{}]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function longestCommonSubstringLen(a: string, b: string): number {
  if (!a || !b) return 0
  const prev = new Uint16Array(b.length + 1)
  const curr = new Uint16Array(b.length + 1)
  let best = 0
  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      if (a.charCodeAt(i - 1) === b.charCodeAt(j - 1)) {
        const v = prev[j - 1] + 1
        curr[j] = v
        if (v > best) best = v
      } else {
        curr[j] = 0
      }
    }
    prev.set(curr)
    curr.fill(0)
  }
  return best
}

export interface ExpandToSourceResult {
  text: string         // full-sentence text from source
  expanded: boolean    // true if the selection was widened
}

export function expandPdfSelectionToSourceSentences(
  selectedText: string,
  sectionSource: string,
  { minOverlap = 0.25 }: { minOverlap?: number } = {},
): ExpandToSourceResult | null {
  if (!selectedText.trim() || !sectionSource.trim()) return null

  const needleNorm = normalizeForOverlap(selectedText)
  if (needleNorm.length < 10) return null

  const sentences = segmentSentences(sectionSource)
  if (sentences.length === 0) return null

  // Score every source sentence by how much of the user's selection it covers.
  const scored = sentences.map((sentence) => {
    const haystackNorm = normalizeForOverlap(sentence.text)
    const lcs = longestCommonSubstringLen(needleNorm, haystackNorm)
    return { sentence, score: needleNorm.length === 0 ? 0 : lcs / needleNorm.length }
  })

  // Keep sentences with non-trivial overlap; if none, give up.
  const matched = scored.filter((entry) => entry.score >= minOverlap)
  if (matched.length === 0) return null

  // Take the source range from the first matched sentence to the last.
  matched.sort((a, b) => a.sentence.start - b.sentence.start)
  const first = matched[0].sentence
  const last = matched[matched.length - 1].sentence
  const text = sectionSource.slice(first.start, last.end)
  if (!text.trim()) return null

  // Did we expand beyond what the user actually selected?
  const expandedText = text.trim()
  const expanded = normalizeForOverlap(expandedText) !== needleNorm
  return { text: expandedText, expanded }
}
