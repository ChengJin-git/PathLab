import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { AlertTriangle, CheckCircle2, FileCode2, Loader2, PencilLine, Redo2, Save, Undo2, X } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  getPaperSections,
  putPaperSection,
  type PaperSection,
  type PaperSectionListResponse,
  type TemplateId,
} from '../../api/papers'
import { cn } from '../../lib/utils'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { RegenerateSelectionPanel, type SelectionInfo } from './RegenerateSelectionPanel'
import { expandToSentence } from '../../lib/sentenceBoundary'

interface SectionsTabProps {
  paperId: string
  templateId?: TemplateId
  onPdfRefreshNeeded: () => void
}

export const SECTION_ORDER = [
  'abstract',
  'introduction',
  'related_work',
  'methods',
  'experiments',
  'results',
  'discussion',
  'conclusion',
] as const

export function labelForSection(section: string, t?: TFunction): string {
  const fallback = section
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
  return t ? t(`paperAgent.sections.labels.${section}`, { defaultValue: fallback }) : fallback
}

function paragraphIndexAt(text: string, offset: number): number {
  // Match the backend's paragraph splitter (regenerate.py:_paragraph_spans):
  // paragraphs are separated by blank lines.
  const before = text.slice(0, offset)
  const matches = before.match(/\n[ \t]*\n/g)
  return matches ? matches.length : 0
}

function textOffsetWithin(root: HTMLElement, target: Node, nodeOffset: number): number | null {
  let offset = 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    if (node === target) {
      return offset + nodeOffset
    }
    offset += node.length
  }
  return null
}

function sourceOffsetWithinReadable(root: HTMLElement, target: Node, nodeOffset: number): number | null {
  const targetElement = target.nodeType === Node.TEXT_NODE ? target.parentElement : target instanceof HTMLElement ? target : null
  let element = targetElement

  while (element && element !== root) {
    const start = element.dataset.sourceStart
    const end = element.dataset.sourceEnd
    if (start !== undefined && end !== undefined) {
      const sourceStart = Number(start)
      const sourceEnd = Number(end)
      if (element.dataset.sourceKind === 'locked') {
        if (target.nodeType === Node.TEXT_NODE) {
          const textLength = Math.max(1, (target as Text).length)
          return sourceStart + (nodeOffset >= textLength / 2 ? sourceEnd - sourceStart : 0)
        }
        return sourceStart
      }

      const localOffset = textOffsetWithin(element, target, nodeOffset) ?? 0
      return Math.min(sourceEnd, sourceStart + localOffset)
    }
    element = element.parentElement
  }

  return null
}

function locateNodeAtOffset(root: HTMLElement, charOffset: number): { node: Text; offset: number } | null {
  // Inverse of textOffsetWithin: walk text nodes pre-order and find the one
  // that contains `charOffset` (in body-local coordinates).
  let consumed = 0
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let lastNode: Text | null = null
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    lastNode = node
    if (charOffset <= consumed + node.length) {
      return { node, offset: charOffset - consumed }
    }
    consumed += node.length
  }
  // Offset is past the end — clamp to the end of the last text node.
  if (lastNode) return { node: lastNode, offset: lastNode.length }
  return null
}

function locateReadableNodeAtSourceOffset(root: HTMLElement, charOffset: number): { node: Text; offset: number } | null {
  const elements = Array.from(root.querySelectorAll<HTMLElement>('[data-source-start][data-source-end]'))
  let previousEditable: HTMLElement | null = null

  for (const element of elements) {
    const sourceStart = Number(element.dataset.sourceStart)
    const sourceEnd = Number(element.dataset.sourceEnd)
    const isEditable = element.dataset.sourceKind === 'editable'

    if (isEditable && charOffset >= sourceStart && charOffset <= sourceEnd) {
      return locateNodeAtOffset(element, charOffset - sourceStart)
    }

    if (charOffset < sourceStart) {
      if (isEditable) return locateNodeAtOffset(element, 0)
      break
    }

    if (isEditable) previousEditable = element
  }

  if (previousEditable) return locateNodeAtOffset(previousEditable, previousEditable.textContent?.length ?? 0)
  return null
}

export interface SectionBodyView {
  prefixText: string
  bodyText: string
  bodyOffset: number
  suffixText: string
  toSource: (bodyText: string) => string
}

export function sectionBodyView(source: string, sectionName: string): SectionBodyView {
  if (sectionName === 'abstract') {
    const match = source.match(/^(\s*\\begin\{abstract\}\s*\n?)([\s\S]*?)(\n?\\end\{abstract\}\s*)$/)
    if (match) {
      const [, prefix, body, suffix] = match
      return {
        prefixText: prefix,
        bodyText: body,
        bodyOffset: prefix.length,
        suffixText: suffix,
        toSource: (nextBody) => `${prefix}${nextBody}${suffix}`,
      }
    }
  }

  const sectionMatch = source.match(/^(\s*\\section\*?\{[^}]*\}\s*\n?)([\s\S]*)$/)
  if (sectionMatch) {
    const [, prefix, body] = sectionMatch
    return {
      prefixText: prefix,
      bodyText: body,
      bodyOffset: prefix.length,
      suffixText: '',
      toSource: (nextBody) => `${prefix}${nextBody}`,
    }
  }

  return {
    prefixText: '',
    bodyText: source,
    bodyOffset: 0,
    suffixText: '',
    toSource: (nextBody) => nextBody,
  }
}

function LockedLatexBlock({ text, edge }: { text: string; edge: 'top' | 'bottom' }) {
  const { t } = useTranslation()
  if (!text) return null

  return (
    <div
      className={cn(
        'select-none bg-slate-50 px-5 py-3 text-xs leading-5 text-slate-500',
        edge === 'top' ? 'border-b border-slate-200' : 'border-t border-slate-200',
      )}
      aria-label={t('paperAgent.sections.lockedLatexWrapper')}
    >
      <div className="font-semibold text-slate-700">
        {edge === 'top'
          ? t('paperAgent.sections.lockedStructureTop')
          : t('paperAgent.sections.lockedStructureBottom')}
      </div>
      <div className="mt-0.5">
        {t('paperAgent.sections.lockedStructureDescription')}
      </div>
    </div>
  )
}

type DraftSegment = {
  id: string
  kind: 'editable' | 'locked' | 'heading'
  text: string
  originalText: string
  sourceStart: number
  sourceEnd: number
}

const LOCKED_LATEX_SEGMENT_RE = new RegExp(
  String.raw`\\(?:paragraph|subparagraph)\*?\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$[^$\n]+\$|\\begin\{(figure\*?|table\*?|tabularx?|equation\*?|align\*?)\}[\s\S]*?\\end\{\1\}|\\(?:input|include|includegraphics|cite[a-zA-Z*]*|ref|eqref|autoref|cref|Cref|label|caption|bibliographystyle|bibliography)(?:\[[^\]]*\])*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}`,
  'g',
)

function parseLatexHeadingToken(text: string): { level: 'paragraph' | 'subparagraph'; title: string } | null {
  const match = text.match(/^\\(paragraph|subparagraph)\*?\{([\s\S]*)\}$/)
  if (!match) return null
  return {
    level: match[1] as 'paragraph' | 'subparagraph',
    title: match[2].trim(),
  }
}

function latexDraftSegments(bodyText: string): DraftSegment[] {
  const segments: DraftSegment[] = []
  let cursor = 0
  let index = 0
  LOCKED_LATEX_SEGMENT_RE.lastIndex = 0

  for (const match of bodyText.matchAll(LOCKED_LATEX_SEGMENT_RE)) {
    const start = match.index ?? 0
    const token = match[0]
    if (!token) continue
    if (start > cursor) {
      const text = bodyText.slice(cursor, start)
      segments.push({
        id: `editable-${index++}`,
        kind: 'editable',
        text,
        originalText: text,
        sourceStart: cursor,
        sourceEnd: start,
      })
    }
    const heading = parseLatexHeadingToken(token)
    segments.push({
      id: `locked-${index++}`,
      kind: heading ? 'heading' : 'locked',
      text: token,
      originalText: token,
      sourceStart: start,
      sourceEnd: start + token.length,
    })
    cursor = start + token.length
  }

  if (cursor < bodyText.length) {
    const text = bodyText.slice(cursor)
    segments.push({
      id: `editable-${index++}`,
      kind: 'editable',
      text,
      originalText: text,
      sourceStart: cursor,
      sourceEnd: bodyText.length,
    })
  }
  return segments.length
    ? segments
    : [
        {
          id: 'editable-0',
          kind: 'editable',
          text: bodyText,
          originalText: bodyText,
          sourceStart: 0,
          sourceEnd: bodyText.length,
        },
      ]
}

function lockedTokenLabel(text: string, t: TFunction): string {
  if (/^\\cite/.test(text)) return t('paperAgent.sections.lockedTokenTypes.citation')
  if (/^\\(?:ref|eqref|autoref|cref|Cref)/.test(text)) return t('paperAgent.sections.lockedTokenTypes.reference')
  if (/^\\label/.test(text)) return t('paperAgent.sections.lockedTokenTypes.label')
  if (/^\\caption/.test(text)) return t('paperAgent.sections.lockedTokenTypes.caption')
  if (/^\\includegraphics/.test(text)) return t('paperAgent.sections.lockedTokenTypes.image')
  if (/^\\(?:input|include)/.test(text)) return t('paperAgent.sections.lockedTokenTypes.input')
  if (/^\\begin\{figure/.test(text)) return t('paperAgent.sections.lockedTokenTypes.figure')
  if (/^\\begin\{table|^\\begin\{tabular/.test(text)) return t('paperAgent.sections.lockedTokenTypes.table')
  if (/^\\\(|^\\\[|^\$/.test(text)) return t('paperAgent.sections.lockedTokenTypes.equation')
  if (/^\\begin\{equation|^\\begin\{align/.test(text)) return t('paperAgent.sections.lockedTokenTypes.equation')
  if (/^\\bibliography|^\\bibliographystyle/.test(text)) return t('paperAgent.sections.lockedTokenTypes.bibliography')
  return t('paperAgent.sections.lockedToken')
}

function lockedTokenReadableValue(text: string): string {
  const braced = text.match(/\{([^{}]+)\}\s*$/)
  if (!braced) return ''
  const value = braced[1].trim()
  return value.split('/').pop() || value
}

function lockedImportName(value: string, t: TFunction): string {
  const fileName = value.split('/').pop() || value
  const importNameByFile: Record<string, string> = {
    'dataset_block.tex': t('paperAgent.sections.lockedImportNames.datasetBlock'),
    'method_block.tex': t('paperAgent.sections.lockedImportNames.methodBlock'),
    'results_block.tex': t('paperAgent.sections.lockedImportNames.resultsBlock'),
    'evidence_gaps.tex': t('paperAgent.sections.lockedImportNames.evidenceGaps'),
    'metrics_macros.tex': t('paperAgent.sections.lockedImportNames.metricsMacros'),
    'table_2_main_results.tex': t('paperAgent.sections.lockedImportNames.mainResultsTable'),
    'table_3_per_class.tex': t('paperAgent.sections.lockedImportNames.perClassTable'),
    'table_4_ablation.tex': t('paperAgent.sections.lockedImportNames.ablationTable'),
    'table_5_external_validation.tex': t('paperAgent.sections.lockedImportNames.externalValidationTable'),
  }
  return importNameByFile[fileName] ?? t('paperAgent.sections.lockedImportNames.generic')
}

function LockedLatexToken({ text }: { text: string }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const isBlock = text.includes('\n') || /^\\begin\{/.test(text)
  const isImport = /^\\(?:input|include)/.test(text)
  const label = lockedTokenLabel(text, t)
  const readableValue = lockedTokenReadableValue(text)
  const importName = isImport ? lockedImportName(readableValue, t) : ''

  if (isImport) {
    return (
      <span className="my-3 block max-w-full px-5 align-middle">
        <button
          type="button"
          className="flex w-full select-none items-start gap-3 rounded-xl border border-sky-100 bg-sky-50/80 px-4 py-3 text-left shadow-sm transition hover:border-sky-200 hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-200"
          aria-label={t('paperAgent.sections.lockedTokenAria')}
          title={t('paperAgent.sections.lockedTokenTitle')}
          onClick={() => setExpanded((open) => !open)}
        >
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-sky-700 shadow-sm">
            <FileCode2 className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="block text-xs font-semibold text-sky-700">
              {t('paperAgent.sections.lockedImportBadge')}
            </span>
            <span className="mt-0.5 block text-sm font-semibold text-slate-900">
              {importName}
            </span>
            <span className="mt-1 block text-xs leading-5 text-slate-600">
              {t('paperAgent.sections.lockedImportDescription')}
            </span>
            {expanded ? (
              <span className="mt-2 block rounded-lg border border-sky-100 bg-white px-3 py-2 text-xs leading-5 text-slate-600">
                {readableValue
                  ? t('paperAgent.sections.lockedImportPreservedWithValue', { value: readableValue })
                  : t('paperAgent.sections.lockedTokenPreserved')}
              </span>
            ) : null}
          </span>
        </button>
      </span>
    )
  }

  const button = (
    <button
      type="button"
      className="inline-flex w-fit select-none items-center rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-700 transition hover:border-sky-300 hover:bg-sky-100 focus:outline-none focus:ring-2 focus:ring-sky-200"
      aria-label={t('paperAgent.sections.lockedTokenAria')}
      title={t('paperAgent.sections.lockedTokenTitle')}
      onClick={() => setExpanded((open) => !open)}
    >
      {label}
    </button>
  )

  const details = expanded ? (
    <span className="mt-2 inline-flex max-w-full rounded-xl border border-sky-100 bg-sky-50/70 px-3 py-2 text-left text-xs leading-5 text-slate-600">
      <span>
        <span className="block font-semibold text-slate-800">{label}</span>
        <span className="block">
          {readableValue
            ? t('paperAgent.sections.lockedTokenPreservedWithValue', { value: readableValue })
            : t('paperAgent.sections.lockedTokenPreserved')}
        </span>
      </span>
    </span>
  ) : null

  if (isBlock || expanded) {
    return (
      <span className={cn('my-2 inline-flex max-w-full flex-col align-middle', isBlock ? 'w-full' : 'mx-1')}>
        {button}
        {details}
      </span>
    )
  }

  return (
    <span className="mx-1 inline-flex align-baseline">
      {button}
    </span>
  )
}

function LatexHeadingToken({ text }: { text: string }) {
  const { t } = useTranslation()
  const heading = parseLatexHeadingToken(text)
  if (!heading) return <LockedLatexToken text={text} />

  return (
    <div
      className={cn(
        'select-none px-5 pb-1 font-serif text-slate-950',
        heading.level === 'paragraph' ? 'pt-5 text-xl font-semibold' : 'pt-3 text-lg font-semibold',
      )}
      title={t('paperAgent.sections.lockedHeadingTitle')}
    >
      {heading.title}
    </div>
  )
}

type HighlightToken = {
  text: string
  changed: boolean
}

function tokenizeForHighlight(text: string): string[] {
  return (
    text.match(/\s+|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\sA-Za-z0-9\u3400-\u9fff]+/g) ?? []
  )
}

function comparableToken(token: string): boolean {
  return !/^\s+$/.test(token)
}

function changedWordTokens(originalText: string, currentText: string): HighlightToken[] {
  const originalTokens = tokenizeForHighlight(originalText)
  const currentTokens = tokenizeForHighlight(currentText)
  const originalWords = originalTokens.filter(comparableToken)
  const currentWords = currentTokens
    .map((token, tokenIndex) => ({ token, tokenIndex }))
    .filter(({ token }) => comparableToken(token))

  if (originalWords.length === 0) {
    return currentTokens.map((text) => ({ text, changed: comparableToken(text) }))
  }

  if (originalWords.length * currentWords.length > 180_000) {
    let wordIndex = 0
    return currentTokens.map((text) => {
      if (!comparableToken(text)) return { text, changed: false }
      const changed = originalWords[wordIndex] !== text
      wordIndex += 1
      return { text, changed }
    })
  }

  const dp = Array.from({ length: originalWords.length + 1 }, () => Array(currentWords.length + 1).fill(0))
  for (let i = originalWords.length - 1; i >= 0; i -= 1) {
    for (let j = currentWords.length - 1; j >= 0; j -= 1) {
      dp[i][j] =
        originalWords[i] === currentWords[j].token
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const unchangedCurrentTokenIndexes = new Set<number>()
  let i = 0
  let j = 0
  while (i < originalWords.length && j < currentWords.length) {
    if (originalWords[i] === currentWords[j].token) {
      unchangedCurrentTokenIndexes.add(currentWords[j].tokenIndex)
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i += 1
    } else {
      j += 1
    }
  }

  return currentTokens.map((text, tokenIndex) => ({
    text,
    changed: comparableToken(text) && !unchangedCurrentTokenIndexes.has(tokenIndex),
  }))
}

function textareaRows(text: string): number {
  const lineCount = Math.max(1, text.split('\n').length)
  const wrappedLineEstimate = Math.ceil(text.length / 92)
  return Math.max(4, Math.min(40, Math.max(lineCount, wrappedLineEstimate)))
}

function EditableProseSegment({
  segment,
  onChange,
  ariaLabel,
}: {
  segment: DraftSegment
  onChange: (text: string) => void
  ariaLabel: string
}) {
  const [scrollTop, setScrollTop] = useState(0)
  const tokens = useMemo(() => changedWordTokens(segment.originalText, segment.text), [segment.originalText, segment.text])
  const visibleRows = Math.min(10, textareaRows(segment.text))
  const editorHeight = `${visibleRows * 2 + 2}rem`

  if (!segment.text.trim()) return null

  return (
    <div className="px-5 py-2">
      <div
        className="relative overflow-hidden rounded-xl border border-slate-200 bg-white focus-within:border-sky-200 focus-within:ring-4 focus-within:ring-sky-100"
        style={{ height: editorHeight }}
      >
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
          <div
            className="whitespace-pre-wrap break-words p-4 pr-8 font-serif text-base leading-8 text-slate-800"
            style={{ transform: `translateY(-${scrollTop}px)` }}
          >
            {tokens.length > 0
              ? tokens.map((token, index) =>
                  token.changed ? (
                    <span key={`${index}-${token.text}`} className="text-orange-600">
                      {token.text}
                    </span>
                  ) : (
                    <span key={`${index}-${token.text}`}>{token.text}</span>
                  ),
                )
              : '\u00a0'}
          </div>
        </div>
        <textarea
          value={segment.text}
          onChange={(event) => onChange(event.target.value)}
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
          wrap="soft"
          spellCheck={false}
          aria-label={ariaLabel}
          className="relative z-10 block h-full w-full resize-none overflow-y-auto whitespace-pre-wrap break-words border-0 bg-transparent p-4 pr-8 font-serif text-base leading-8 text-transparent caret-slate-950 outline-none selection:bg-orange-200/70 selection:text-transparent"
          style={{ scrollbarGutter: 'stable' }}
        />
      </div>
    </div>
  )
}

export function SectionsTab({ paperId, templateId, onPdfRefreshNeeded }: SectionsTabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedSection, setSelectedSection] = useState<string>('abstract')
  const [selection, setSelection] = useState<SelectionInfo | null>(null)
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [draftSegments, setDraftSegments] = useState<DraftSegment[]>([])
  const [draftHistory, setDraftHistory] = useState<DraftSegment[][]>([])
  const [draftFuture, setDraftFuture] = useState<DraftSegment[][]>([])
  const [saveNotice, setSaveNotice] = useState<string | null>(null)
  const sourceRef = useRef<HTMLDivElement>(null)
  const sectionParam = searchParams.get('section')

  const sectionsQuery = useQuery({
    queryKey: ['paper-sections', paperId],
    queryFn: () => getPaperSections(paperId),
    retry: false,
  })

  const sectionsByName = useMemo(() => {
    const map = new Map<string, PaperSection>()
    for (const section of sectionsQuery.data?.sections ?? []) {
      map.set(section.section_name, section)
    }
    return map
  }, [sectionsQuery.data?.sections])

  const selected = sectionsByName.get(selectedSection)
  const isMissing = sectionsQuery.error instanceof ApiError && sectionsQuery.error.isNotFound()
  const selectedBodyView = useMemo(
    () => sectionBodyView(selected?.text ?? '', selectedSection),
    [selected?.text, selectedSection],
  )
  const readableSegments = useMemo(() => latexDraftSegments(selectedBodyView.bodyText), [selectedBodyView.bodyText])
  const isEditing = editingSection === selectedSection
  const draftBodyText = useMemo(() => draftSegments.map((segment) => segment.text).join(''), [draftSegments])
  const isDirty = isEditing && selected ? draftBodyText !== selectedBodyView.bodyText : false

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error(t('paperAgent.sections.sourceUnavailable', { section: labelForSection(selectedSection, t) }))
      return putPaperSection(paperId, selectedSection, {
        text: selectedBodyView.toSource(draftBodyText),
        source_hash: selected.content_hash,
      })
    },
    onSuccess: async (response) => {
      queryClient.setQueryData<PaperSectionListResponse>(['paper-sections', paperId], (current) => {
        const sections = current?.sections ?? []
        return {
          sections: sections.length
            ? sections.map((section) =>
                section.section_name === response.section.section_name ? response.section : section,
              )
            : [response.section],
        }
      })
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      setEditingSection(null)
      setDraftSegments(latexDraftSegments(sectionBodyView(response.section.text, response.section.section_name).bodyText))
      setDraftHistory([])
      setDraftFuture([])
      setSelection(null)
      setSaveNotice(
        response.downstream_stale
          ? t('paperAgent.sections.savedStale')
          : t('paperAgent.sections.saved'),
      )
      onPdfRefreshNeeded()
    },
  })

  useEffect(() => {
    if (
      sectionParam &&
      sectionParam !== selectedSection &&
      (SECTION_ORDER as readonly string[]).includes(sectionParam)
    ) {
      setSelectedSection(sectionParam)
      setSelection(null)
      setEditingSection(null)
      setSaveNotice(null)
    }
  }, [sectionParam, selectedSection])

  const handleSelectSection = (section: string) => {
    setSelectedSection(section)
    setSelection(null)
    setEditingSection(null)
    setDraftHistory([])
    setDraftFuture([])
    setSaveNotice(null)
    saveMutation.reset()
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('section', section)
      return next
    })
  }

  const handleMouseUp = () => {
    if (isEditing || !selected || !sourceRef.current) return
    const win = window.getSelection()
    if (!win || win.rangeCount === 0 || win.isCollapsed) return
    const range = win.getRangeAt(0)
    if (!sourceRef.current.contains(range.commonAncestorContainer)) return
    const text = win.toString()
    if (!text || !text.trim()) return

    const bodyCharStart = sourceOffsetWithinReadable(sourceRef.current, range.startContainer, range.startOffset) ?? 0
    const bodyCharEnd =
      sourceOffsetWithinReadable(sourceRef.current, range.endContainer, range.endOffset) ?? bodyCharStart + text.length

    // Snap to whole-sentence boundaries so the LLM never rewrites a half
    // sentence. expandToSentence operates on body-local offsets (it doesn't
    // need the section wrapper).
    const expansion = expandToSentence(selectedBodyView.bodyText, bodyCharStart, bodyCharEnd)
    const expandedBodyText = selectedBodyView.bodyText.slice(expansion.start, expansion.end)

    // Update the browser selection so the user sees the snapped range.
    if (expansion.expanded) {
      try {
        const snappedRange = document.createRange()
        const startPos = locateReadableNodeAtSourceOffset(sourceRef.current, expansion.start)
        const endPos = locateReadableNodeAtSourceOffset(sourceRef.current, expansion.end)
        if (startPos && endPos) {
          snappedRange.setStart(startPos.node, startPos.offset)
          snappedRange.setEnd(endPos.node, endPos.offset)
          win.removeAllRanges()
          win.addRange(snappedRange)
        }
      } catch {
        // best-effort visual sync; selection state is authoritative regardless
      }
    }

    const charStart = expansion.start + selectedBodyView.bodyOffset
    const charEnd = expansion.end + selectedBodyView.bodyOffset
    setSelection({
      text: expandedBodyText,
      source: 'source',
      paragraphIndex: paragraphIndexAt(selected.text, charStart),
      charStart,
      charEnd,
    })
  }

  const startEditing = () => {
    if (!selected) return
    setDraftSegments(latexDraftSegments(selectedBodyView.bodyText))
    setDraftHistory([])
    setDraftFuture([])
    setEditingSection(selected.section_name)
    setSelection(null)
    setSaveNotice(null)
    saveMutation.reset()
    window.getSelection()?.removeAllRanges()
  }

  const cancelEditing = () => {
    setDraftSegments(latexDraftSegments(selectedBodyView.bodyText))
    setDraftHistory([])
    setDraftFuture([])
    setEditingSection(null)
    saveMutation.reset()
  }

  const updateDraftSegment = (segmentId: string, text: string) => {
    setDraftSegments((current) => {
      const next = current.map((segment) => (segment.id === segmentId ? { ...segment, text } : segment))
      if (next.map((segment) => segment.text).join('') === current.map((segment) => segment.text).join('')) {
        return current
      }
      setDraftHistory((history) => [...history.slice(-49), current])
      setDraftFuture([])
      return next
    })
  }

  const undoDraft = () => {
    setDraftHistory((history) => {
      const previous = history[history.length - 1]
      if (!previous) return history
      setDraftFuture((future) => [draftSegments, ...future].slice(0, 50))
      setDraftSegments(previous)
      return history.slice(0, -1)
    })
  }

  const redoDraft = () => {
    setDraftFuture((future) => {
      const next = future[0]
      if (!next) return future
      setDraftHistory((history) => [...history.slice(-49), draftSegments])
      setDraftSegments(next)
      return future.slice(1)
    })
  }

  const saveError = saveMutation.error

  if (sectionsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.sections.loading')}
      </div>
    )
  }

  if (isMissing || sectionsQuery.data?.sections?.length === 0) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <FileCode2 className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.sections.emptyTitle')}</div>
          <p className="mt-1 text-sm text-slate-500">{t('paperAgent.sections.emptyDescription')}</p>
        </CardContent>
      </Card>
    )
  }

  if (sectionsQuery.error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {sectionsQuery.error instanceof Error ? sectionsQuery.error.message : String(sectionsQuery.error)}
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[200px_minmax(0,1fr)_320px] lg:grid-cols-[200px_minmax(0,1fr)]">
      <nav className="rounded-2xl border border-slate-200 bg-slate-50/70 p-2">
        <div className="px-2 pb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{t('paperAgent.sections.sectionCount', { count: SECTION_ORDER.length })}</div>
        <div className="space-y-1">
          {SECTION_ORDER.map((section) => {
            const available = sectionsByName.has(section)
            const selectedRow = selectedSection === section
            return (
              <button
                key={section}
                type="button"
                onClick={() => handleSelectSection(section)}
                className={cn(
                  'flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition',
                  selectedRow
                    ? 'bg-slate-950 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-white hover:text-slate-950',
                )}
              >
                <span>{labelForSection(section, t)}</span>
                <span className={cn('h-2 w-2 rounded-full', available ? 'bg-emerald-400' : 'bg-slate-300')} />
              </button>
            )
          })}
        </div>
      </nav>

      <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/80 px-4 py-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
              {t('paperAgent.sections.latexSource')}
            </div>
            <div className="font-semibold text-slate-950">{labelForSection(selectedSection, t)}</div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-500">
              {selected?.path ? t('paperAgent.sections.pathLocked', { path: selected.path }) : t('paperAgent.common.notGenerated')}
            </span>
            {selected && !isEditing ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8 gap-2 bg-slate-950 text-white hover:bg-slate-800"
                onClick={startEditing}
              >
                <PencilLine className="h-4 w-4" />
                {t('paperAgent.common.edit')}
              </Button>
            ) : null}
            {selected && isEditing ? (
              <>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 border border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
                  onClick={undoDraft}
                  disabled={draftHistory.length === 0 || saveMutation.isPending}
                  aria-label={t('paperAgent.sections.undo')}
                  title={t('paperAgent.sections.undo')}
                >
                  <Undo2 className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 border border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
                  onClick={redoDraft}
                  disabled={draftFuture.length === 0 || saveMutation.isPending}
                  aria-label={t('paperAgent.sections.redo')}
                  title={t('paperAgent.sections.redo')}
                >
                  <Redo2 className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-8 gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
                  onClick={() => saveMutation.mutate()}
                  disabled={!isDirty || saveMutation.isPending}
                >
                  {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {t('paperAgent.common.save')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 gap-2 border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 hover:text-slate-950"
                  onClick={cancelEditing}
                  disabled={saveMutation.isPending}
                >
                  <X className="h-4 w-4" />
                  {t('paperAgent.common.cancel')}
                </Button>
              </>
            ) : null}
          </div>
        </div>
        {saveNotice ? (
          <div className="border-b border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
            <span className="inline-flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              {saveNotice}
            </span>
          </div>
        ) : null}
        {saveError ? (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
            <span className="inline-flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {saveError instanceof Error ? saveError.message : String(saveError)}
            </span>
          </div>
        ) : null}
        {selected ? (
          isEditing ? (
            <div className="bg-white">
              <div className="max-h-[68vh] overflow-auto">
                <LockedLatexBlock text={selectedBodyView.prefixText} edge="top" />
                {draftSegments.map((segment) =>
                  segment.kind === 'locked' ? (
                    <LockedLatexToken key={segment.id} text={segment.text} />
                  ) : segment.kind === 'heading' ? (
                    <LatexHeadingToken key={segment.id} text={segment.text} />
                  ) : (
                    <EditableProseSegment
                      key={segment.id}
                      segment={segment}
                      onChange={(text) => updateDraftSegment(segment.id, text)}
                      ariaLabel={t('paperAgent.sections.editSegmentAria', { section: labelForSection(selectedSection, t) })}
                    />
                  ),
                )}
                <LockedLatexBlock text={selectedBodyView.suffixText} edge="bottom" />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-slate-50/80 px-4 py-2 text-xs text-slate-500">
                <span>
                  {t('paperAgent.sections.editableGuidance')}
                </span>
                <span className={isDirty ? 'font-semibold text-orange-700' : undefined}>
                  {isDirty ? t('paperAgent.sections.unsavedChanges') : t('paperAgent.sections.noChanges')}
                </span>
              </div>
            </div>
          ) : (
            <div className="max-h-[68vh] overflow-auto">
              <LockedLatexBlock text={selectedBodyView.prefixText} edge="top" />
              <div
                ref={sourceRef}
                onMouseUp={handleMouseUp}
                className="px-5 py-5 font-serif text-base leading-8 text-slate-800 selection:bg-violet-200 selection:text-violet-950"
              >
                {readableSegments.map((segment) =>
                  segment.kind === 'locked' ? (
                    <span
                      key={segment.id}
                      data-source-start={segment.sourceStart}
                      data-source-end={segment.sourceEnd}
                      data-source-kind="locked"
                    >
                      <LockedLatexToken text={segment.text} />
                    </span>
                  ) : segment.kind === 'heading' ? (
                    <div
                      key={segment.id}
                      data-source-start={segment.sourceStart}
                      data-source-end={segment.sourceEnd}
                      data-source-kind="locked"
                    >
                      <LatexHeadingToken text={segment.text} />
                    </div>
                  ) : (
                    <span
                      key={segment.id}
                      data-source-start={segment.sourceStart}
                      data-source-end={segment.sourceEnd}
                      data-source-kind="editable"
                      className="whitespace-pre-wrap break-words"
                    >
                      {segment.text}
                    </span>
                  ),
                )}
              </div>
              <LockedLatexBlock text={selectedBodyView.suffixText} edge="bottom" />
            </div>
          )
        ) : (
          <div className="p-8 text-center text-sm text-slate-500">
            {t('paperAgent.sections.missingSection')}
          </div>
        )}
      </div>

      <div className="lg:col-span-2 xl:col-span-1">
        <RegenerateSelectionPanel
          paperId={paperId}
          sectionName={selectedSection}
          templateId={templateId}
          selection={selection}
          onPdfRefreshNeeded={onPdfRefreshNeeded}
          onClear={() => {
            setSelection(null)
            window.getSelection()?.removeAllRanges()
          }}
        />
      </div>
    </div>
  )
}
