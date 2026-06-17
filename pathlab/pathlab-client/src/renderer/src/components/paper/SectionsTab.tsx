import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, FileCode2, Loader2, PencilLine, Save, X } from 'lucide-react'
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

export function labelForSection(section: string): string {
  return section
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
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
  if (!text) return null

  return (
    <div
      className={cn(
        'select-none bg-white/[0.035] px-4 py-2 font-mono text-xs leading-6 text-slate-500 sm:text-sm',
        edge === 'top' ? 'border-b border-white/10' : 'border-t border-white/10',
      )}
      aria-label="Locked LaTeX wrapper"
    >
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">
        Locked LaTeX
      </div>
      <pre className="whitespace-pre-wrap break-words">
        <code>{text}</code>
      </pre>
    </div>
  )
}

type DraftSegment = {
  id: string
  kind: 'editable' | 'locked'
  text: string
}

const LOCKED_LATEX_SEGMENT_RE = new RegExp(
  String.raw`\\begin\{(figure\*?|table\*?|tabularx?|equation\*?|align\*?)\}[\s\S]*?\\end\{\1\}|\\(?:input|include|includegraphics|cite[a-zA-Z*]*|ref|eqref|autoref|cref|Cref|label|caption|bibliographystyle|bibliography)(?:\[[^\]]*\])*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}`,
  'g',
)

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
      segments.push({
        id: `editable-${index++}`,
        kind: 'editable',
        text: bodyText.slice(cursor, start),
      })
    }
    segments.push({ id: `locked-${index++}`, kind: 'locked', text: token })
    cursor = start + token.length
  }

  if (cursor < bodyText.length) {
    segments.push({
      id: `editable-${index++}`,
      kind: 'editable',
      text: bodyText.slice(cursor),
    })
  }
  return segments.length ? segments : [{ id: 'editable-0', kind: 'editable', text: bodyText }]
}

function textareaRows(text: string): number {
  const lineCount = Math.max(1, text.split('\n').length)
  const wrappedLineEstimate = Math.ceil(text.length / 96)
  return Math.max(2, Math.min(18, Math.max(lineCount, wrappedLineEstimate)))
}

function LockedLatexToken({ text }: { text: string }) {
  const isBlock = text.includes('\n') || /^\\begin\{/.test(text)
  return (
    <div
      className={cn(
        'select-none border-y border-sky-300/15 bg-sky-300/10 px-4 py-2 font-mono text-xs leading-6 text-sky-100 sm:text-sm',
        isBlock ? 'my-1' : 'my-0',
      )}
      aria-label="Locked LaTeX token"
    >
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-sky-300/80">
        Locked token
      </div>
      <pre className="whitespace-pre-wrap break-words">
        <code>{text}</code>
      </pre>
    </div>
  )
}

export function SectionsTab({ paperId, templateId, onPdfRefreshNeeded }: SectionsTabProps) {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedSection, setSelectedSection] = useState<string>('abstract')
  const [selection, setSelection] = useState<SelectionInfo | null>(null)
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [draftSegments, setDraftSegments] = useState<DraftSegment[]>([])
  const [saveNotice, setSaveNotice] = useState<string | null>(null)
  const sourceRef = useRef<HTMLPreElement>(null)
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
  const isEditing = editingSection === selectedSection
  const draftBodyText = useMemo(() => draftSegments.map((segment) => segment.text).join(''), [draftSegments])
  const isDirty = isEditing && selected ? draftBodyText !== selectedBodyView.bodyText : false

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error(`Section source is not available: ${selectedSection}`)
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
      setSelection(null)
      setSaveNotice(
        response.downstream_stale
          ? 'Saved section source. PDF, export, and validation may be stale until the next render/validate pass.'
          : 'Saved section source.',
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

    // Compute character offsets within the section text by
    // walking pre-order through the pre's text nodes.
    const bodyCharStart = textOffsetWithin(sourceRef.current, range.startContainer, range.startOffset) ?? 0
    const bodyCharEnd = textOffsetWithin(sourceRef.current, range.endContainer, range.endOffset) ?? bodyCharStart + text.length

    // Snap to whole-sentence boundaries so the LLM never rewrites a half
    // sentence. expandToSentence operates on body-local offsets (it doesn't
    // need the section wrapper).
    const expansion = expandToSentence(selectedBodyView.bodyText, bodyCharStart, bodyCharEnd)
    const expandedBodyText = selectedBodyView.bodyText.slice(expansion.start, expansion.end)

    // Update the browser selection so the user sees the snapped range.
    if (expansion.expanded) {
      try {
        const snappedRange = document.createRange()
        const startPos = locateNodeAtOffset(sourceRef.current, expansion.start)
        const endPos = locateNodeAtOffset(sourceRef.current, expansion.end)
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
    setEditingSection(selected.section_name)
    setSelection(null)
    setSaveNotice(null)
    saveMutation.reset()
    window.getSelection()?.removeAllRanges()
  }

  const cancelEditing = () => {
    setDraftSegments(latexDraftSegments(selectedBodyView.bodyText))
    setEditingSection(null)
    saveMutation.reset()
  }

  const updateDraftSegment = (segmentId: string, text: string) => {
    setDraftSegments((current) =>
      current.map((segment) => (segment.id === segmentId ? { ...segment, text } : segment)),
    )
  }

  const saveError = saveMutation.error

  if (sectionsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading sections...
      </div>
    )
  }

  if (isMissing || sectionsQuery.data?.sections?.length === 0) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <FileCode2 className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Sections not generated yet</div>
          <p className="mt-1 text-sm text-slate-500">The section_writing stage will publish LaTeX source here.</p>
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
        <div className="px-2 pb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">8 sections</div>
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
                <span>{labelForSection(section)}</span>
                <span className={cn('h-2 w-2 rounded-full', available ? 'bg-emerald-400' : 'bg-slate-300')} />
              </button>
            )
          })}
        </div>
      </nav>

      <div className="min-w-0 rounded-2xl border border-slate-200 bg-slate-950 text-slate-100 shadow-inner">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">LaTeX source</div>
            <div className="font-semibold text-white">{labelForSection(selectedSection)}</div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-300">
              {selected?.path ? `${selected.path} · locked LaTeX` : 'not generated'}
            </span>
            {selected && !isEditing ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8 gap-2 bg-white text-slate-950 hover:bg-sky-50"
                onClick={startEditing}
              >
                <PencilLine className="h-4 w-4" />
                Edit
              </Button>
            ) : null}
            {selected && isEditing ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-8 gap-2 bg-emerald-400 text-emerald-950 hover:bg-emerald-300"
                  onClick={() => saveMutation.mutate()}
                  disabled={!isDirty || saveMutation.isPending}
                >
                  {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 gap-2 border border-white/10 text-slate-200 hover:bg-white/10 hover:text-white"
                  onClick={cancelEditing}
                  disabled={saveMutation.isPending}
                >
                  <X className="h-4 w-4" />
                  Cancel
                </Button>
              </>
            ) : null}
          </div>
        </div>
        {saveNotice ? (
          <div className="border-b border-emerald-400/20 bg-emerald-400/10 px-4 py-2 text-sm text-emerald-100">
            <span className="inline-flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              {saveNotice}
            </span>
          </div>
        ) : null}
        {saveError ? (
          <div className="border-b border-amber-400/20 bg-amber-400/10 px-4 py-2 text-sm text-amber-100">
            <span className="inline-flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {saveError instanceof Error ? saveError.message : String(saveError)}
            </span>
          </div>
        ) : null}
        {selected ? (
          isEditing ? (
            <div className="bg-slate-950">
              <div className="max-h-[68vh] overflow-auto">
                <LockedLatexBlock text={selectedBodyView.prefixText} edge="top" />
                {draftSegments.map((segment) =>
                  segment.kind === 'locked' ? (
                    <LockedLatexToken key={segment.id} text={segment.text} />
                  ) : (
                    <textarea
                      key={segment.id}
                      value={segment.text}
                      onChange={(event) => updateDraftSegment(segment.id, event.target.value)}
                      rows={textareaRows(segment.text)}
                      wrap="soft"
                      spellCheck={false}
                      className="w-full resize-y whitespace-pre-wrap break-words border-0 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100 outline-none selection:bg-emerald-400/30 selection:text-white sm:text-sm"
                      aria-label={`Edit ${labelForSection(selectedSection)} prose segment`}
                    />
                  ),
                )}
                <LockedLatexBlock text={selectedBodyView.suffixText} edge="bottom" />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 px-4 py-2 text-xs text-slate-400">
                <span>
                  Prose segments are editable. Section wrappers, citations, inputs, figures, labels, and captions are locked.
                </span>
                <span>{isDirty ? 'Unsaved changes' : 'No changes'}</span>
              </div>
            </div>
          ) : (
            <div className="max-h-[68vh] overflow-auto">
              <LockedLatexBlock text={selectedBodyView.prefixText} edge="top" />
              <pre
                ref={sourceRef}
                onMouseUp={handleMouseUp}
                className="whitespace-pre-wrap break-words p-4 text-xs leading-6 text-slate-100 selection:bg-violet-400/40 selection:text-white sm:text-sm"
              >
                <code>{selectedBodyView.bodyText}</code>
              </pre>
              <LockedLatexBlock text={selectedBodyView.suffixText} edge="bottom" />
            </div>
          )
        ) : (
          <div className="p-8 text-center text-sm text-slate-400">
            This section is not present in drafts/sections yet.
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
