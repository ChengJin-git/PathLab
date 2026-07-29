export interface SectionMatchResult {
  section_name: string
  confidence: number
  second_best?: { section_name: string; confidence: number }
  ambiguous: boolean
}

const MIN_SELECTION_CHARS = 20
const FOUND_THRESHOLD = 0.6
const AMBIGUOUS_DELTA = 0.08
const MAX_SELECTED_CHARS = 2400

const TEXT_COMMANDS = ['textbf', 'emph', 'underline', 'textit', 'texttt', 'textsc']

function stripLatexComments(text: string): string {
  return text
    .split('\n')
    .map((line) => {
      const match = line.match(/(^|[^\\])%/)
      if (!match || match.index === undefined) return line
      return line.slice(0, match.index + (match[1] ? 1 : 0))
    })
    .join('\n')
}

function replaceCommandWithToken(text: string, commands: string[], token: string): string {
  const commandGroup = commands.join('|')
  const pattern = new RegExp(String.raw`\\(?:${commandGroup})\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})+`, 'gi')
  return text.replace(pattern, ` ${token} `)
}

function unwrapTextCommands(text: string): string {
  let next = text
  for (let pass = 0; pass < 6; pass += 1) {
    const previous = next
    for (const command of TEXT_COMMANDS) {
      next = next.replace(new RegExp(String.raw`\\${command}\*?\{([^{}]*)\}`, 'gi'), '$1')
    }
    if (next === previous) break
  }
  return next
}

function replaceMath(text: string): string {
  return text
    .replace(/\\\[[\s\S]*?\\\]/g, ' [MATH] ')
    .replace(/\\\([\s\S]*?\\\)/g, ' [MATH] ')
    .replace(/\$\$[\s\S]*?\$\$/g, ' [MATH] ')
    .replace(/\$[^$\n]*\$/g, ' [MATH] ')
}

function normalizePdfCitations(text: string): string {
  return text
    .replace(/\[(?:\s*\d+\s*(?:[-,;]\s*\d+\s*)*)\]/g, ' [CITE] ')
    .replace(/\((?:[A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s+\d{4}[a-z]?(?:;\s*)?)+\)/g, ' [CITE] ')
}

function normalizePdfRefs(text: string): string {
  return text.replace(/\b(?:fig(?:ure)?|table|sec(?:tion)?)\.?\s*\d+[a-z]?\b/gi, ' [REF] ')
}

function normalizeUnicodeAndWhitespace(text: string): string {
  return text
    .normalize('NFKC')
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function mergeWrappedHyphenation(text: string): string {
  return text.replace(/([A-Za-z])-\s+([A-Za-z])/g, '$1$2')
}

export function normalizeForMatch(text: string): string {
  let normalized = text
  normalized = stripLatexComments(normalized)
  normalized = mergeWrappedHyphenation(normalized)
  normalized = replaceMath(normalized)
  normalized = replaceCommandWithToken(normalized, ['cite', 'parencite', 'citep', 'citet'], '[CITE]')
  normalized = replaceCommandWithToken(normalized, ['ref', 'autoref', 'cref', 'Cref'], '[REF]')
  normalized = unwrapTextCommands(normalized)
  normalized = normalizePdfCitations(normalized)
  normalized = normalizePdfRefs(normalized)
  normalized = normalized.replace(/[{}]/g, ' ')
  normalized = normalized.replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?/g, ' ')
  return normalizeUnicodeAndWhitespace(normalized)
}

function compactForMatch(text: string): string {
  return text.replace(/[^a-z0-9]+/g, '')
}

function longestCommonSubstringLength(needle: string, haystack: string): number {
  if (!needle || !haystack) return 0
  const previous = new Uint16Array(haystack.length + 1)
  const current = new Uint16Array(haystack.length + 1)
  let best = 0

  for (let i = 1; i <= needle.length; i += 1) {
    for (let j = 1; j <= haystack.length; j += 1) {
      if (needle.charCodeAt(i - 1) === haystack.charCodeAt(j - 1)) {
        const value = previous[j - 1] + 1
        current[j] = value
        if (value > best) best = value
      } else {
        current[j] = 0
      }
    }
    previous.set(current)
    current.fill(0)
  }

  return best
}

export function pdfMatchSection(
  selectedText: string,
  sections: Array<{ section_name: string; text: string }>,
): SectionMatchResult | null {
  const normalizedSelection = normalizeForMatch(selectedText)
  if (normalizedSelection.length < MIN_SELECTION_CHARS) return null

  // PDF.js text extraction varies slightly across browser/font stacks. Keep a
  // bounded needle so matching remains responsive while preserving enough text
  // for robust section-level disambiguation.
  const needle = normalizedSelection.slice(0, MAX_SELECTED_CHARS)
  const compactNeedle = compactForMatch(needle)
  const ranked = sections
    .map((section) => {
      const haystack = normalizeForMatch(section.text)
      const spacedConfidence = longestCommonSubstringLength(needle, haystack) / needle.length
      const compactHaystack = compactForMatch(haystack)
      const compactConfidence =
        compactNeedle.length >= MIN_SELECTION_CHARS
          ? longestCommonSubstringLength(compactNeedle, compactHaystack) / compactNeedle.length
          : 0
      const confidence = Math.max(spacedConfidence, compactConfidence)
      return { section_name: section.section_name, confidence }
    })
    .sort((left, right) => right.confidence - left.confidence)

  const best = ranked[0]
  if (!best || best.confidence < FOUND_THRESHOLD) return null

  const second = ranked[1]
  const secondBest = second ? { section_name: second.section_name, confidence: second.confidence } : undefined
  const ambiguous = Boolean(second && best.confidence - second.confidence < AMBIGUOUS_DELTA)

  return {
    section_name: best.section_name,
    confidence: best.confidence,
    second_best: secondBest,
    ambiguous,
  }
}
