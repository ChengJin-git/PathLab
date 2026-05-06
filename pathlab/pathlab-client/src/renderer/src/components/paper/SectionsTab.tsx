import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileCode2, Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperSections, type PaperSection, type TemplateId } from '../../api/papers'
import { cn } from '../../lib/utils'
import { Card, CardContent } from '../ui/card'
import { RegenerateSelectionPanel, type SelectionInfo } from './RegenerateSelectionPanel'

interface SectionsTabProps {
  paperId: string
  templateId?: TemplateId
  onPdfRefreshNeeded: () => void
}

const SECTION_ORDER = [
  'abstract',
  'introduction',
  'related_work',
  'methods',
  'experiments',
  'results',
  'discussion',
  'conclusion',
] as const

function labelForSection(section: string): string {
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

export function SectionsTab({ paperId, templateId, onPdfRefreshNeeded }: SectionsTabProps) {
  const [selectedSection, setSelectedSection] = useState<string>('abstract')
  const [selection, setSelection] = useState<SelectionInfo | null>(null)
  const sourceRef = useRef<HTMLPreElement>(null)

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

  // Clear pending selection when user switches section.
  useEffect(() => {
    setSelection(null)
  }, [selectedSection])

  const handleMouseUp = () => {
    if (!selected || !sourceRef.current) return
    const win = window.getSelection()
    if (!win || win.rangeCount === 0 || win.isCollapsed) return
    const range = win.getRangeAt(0)
    if (!sourceRef.current.contains(range.commonAncestorContainer)) return
    const text = win.toString()
    if (!text || !text.trim()) return

    // Compute character offsets within the section text by
    // walking pre-order through the pre's text nodes.
    const charStart = textOffsetWithin(sourceRef.current, range.startContainer, range.startOffset) ?? 0
    const charEnd = textOffsetWithin(sourceRef.current, range.endContainer, range.endOffset) ?? charStart + text.length
    setSelection({
      text,
      paragraphIndex: paragraphIndexAt(selected.text, charStart),
      charStart,
      charEnd,
    })
  }

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
                onClick={() => setSelectedSection(section)}
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
          <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-300">
            {selected?.path ?? 'not generated'}
          </span>
        </div>
        {selected ? (
          <pre
            ref={sourceRef}
            onMouseUp={handleMouseUp}
            className="max-h-[68vh] overflow-auto p-4 text-xs leading-6 text-slate-100 selection:bg-violet-400/40 selection:text-white sm:text-sm"
          >
            <code>{selected.text}</code>
          </pre>
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
