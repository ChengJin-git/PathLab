import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileCode2, Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperSections, type PaperSection } from '../../api/papers'
import { cn } from '../../lib/utils'
import { Card, CardContent } from '../ui/card'

interface SectionsTabProps {
  paperId: string
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

export function SectionsTab({ paperId }: SectionsTabProps) {
  const [selectedSection, setSelectedSection] = useState<string>('abstract')
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

  if (sectionsQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading sections...</div>
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
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{sectionsQuery.error instanceof Error ? sectionsQuery.error.message : String(sectionsQuery.error)}</div>
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
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
                  selectedRow ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600 hover:bg-white hover:text-slate-950'
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
          <pre className="max-h-[68vh] overflow-auto p-4 text-xs leading-6 text-slate-100 sm:text-sm"><code>{selected.text}</code></pre>
        ) : (
          <div className="p-8 text-center text-sm text-slate-400">This section is not present in drafts/sections yet.</div>
        )}
      </div>
    </div>
  )
}
