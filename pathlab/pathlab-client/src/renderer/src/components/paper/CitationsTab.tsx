import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Library, Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperFileJson, getPaperFileText, type OutlineDocument } from '../../api/papers'
import { Badge } from '../ui/badge'
import { Card, CardContent } from '../ui/card'

interface CitationsTabProps {
  paperId: string
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (typeof item === 'string') return item
      if (typeof item === 'object' && item !== null && 'paperId' in item) return String((item as { paperId?: unknown }).paperId ?? '')
      if (typeof item === 'object' && item !== null && 'paper_id' in item) return String((item as { paper_id?: unknown }).paper_id ?? '')
      if (typeof item === 'object' && item !== null && 'id' in item) return String((item as { id?: unknown }).id ?? '')
      return ''
    })
    .filter(Boolean)
}

function collectRequiredCites(outline: OutlineDocument | undefined): string[] {
  if (!outline) return []
  const found = new Set<string>()
  for (const key of stringArray((outline as Record<string, unknown>).required_cites)) found.add(key)
  for (const key of stringArray((outline.pathlab_extensions as Record<string, unknown>).required_cites)) found.add(key)
  for (const section of outline.section_plan ?? []) {
    const sectionRecord = section as Record<string, unknown>
    for (const key of stringArray(sectionRecord.required_cites)) found.add(key)
    for (const key of stringArray(sectionRecord.citations)) found.add(key)
  }
  return [...found].sort((a, b) => a.localeCompare(b))
}

function parseBibKeys(refsBib: string | undefined): string[] {
  if (!refsBib) return []
  const keys = new Set<string>()
  const regex = /@\w+\s*\{\s*([^,\s]+)\s*,/g
  let match = regex.exec(refsBib)
  while (match) {
    keys.add(match[1])
    match = regex.exec(refsBib)
  }
  return [...keys].sort((a, b) => a.localeCompare(b))
}

function missingIsNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.isNotFound()
}

export function CitationsTab({ paperId }: CitationsTabProps) {
  const refsQuery = useQuery({
    queryKey: ['paper-file', paperId, 'citations/refs.bib'],
    queryFn: () => getPaperFileText(paperId, 'citations/refs.bib'),
    retry: false,
  })
  const outlineQuery = useQuery({
    queryKey: ['paper-file', paperId, 'drafts/outline.json', 'citations'],
    queryFn: () => getPaperFileJson<OutlineDocument>(paperId, 'drafts/outline.json'),
    retry: false,
  })

  const bibKeys = useMemo(() => parseBibKeys(refsQuery.data), [refsQuery.data])
  const requiredCites = useMemo(() => collectRequiredCites(outlineQuery.data), [outlineQuery.data])
  const bibKeySet = useMemo(() => new Set(bibKeys), [bibKeys])
  const loading = refsQuery.isLoading || outlineQuery.isLoading
  const refsMissing = missingIsNotFound(refsQuery.error)
  const outlineMissing = missingIsNotFound(outlineQuery.error)

  if (loading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading citations...</div>
  }

  if ((refsMissing || refsQuery.data === undefined) && (outlineMissing || outlineQuery.data === undefined)) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Library className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Citations not generated yet</div>
          <p className="mt-1 text-sm text-slate-500">Literature review will write refs.bib and required citation metadata.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-950">refs.bib</h2>
              <p className="text-sm text-slate-500">Selected bibliography keys.</p>
            </div>
            <Badge variant={bibKeys.length ? 'secondary' : 'outline'}>{bibKeys.length} keys</Badge>
          </div>
        </div>
        <div className="max-h-[62vh] overflow-auto p-4">
          {refsQuery.error && !refsMissing ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{refsQuery.error instanceof Error ? refsQuery.error.message : String(refsQuery.error)}</div>
          ) : bibKeys.length ? (
            <div className="space-y-2">
              {bibKeys.map((key) => <div key={key} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700">{key}</div>)}
            </div>
          ) : (
            <div className="text-sm text-slate-500">refs.bib is empty or missing.</div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-950">Required cites</h2>
              <p className="text-sm text-slate-500">From outline.required_cites and section extras.</p>
            </div>
            <Badge variant="outline">A2 contract</Badge>
          </div>
        </div>
        <div className="max-h-[62vh] overflow-auto p-4">
          {outlineQuery.error && !outlineMissing ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{outlineQuery.error instanceof Error ? outlineQuery.error.message : String(outlineQuery.error)}</div>
          ) : requiredCites.length ? (
            <div className="space-y-2">
              {requiredCites.map((key) => {
                const present = bibKeySet.has(key)
                return (
                  <div key={key} className={present ? 'rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 font-mono text-sm text-emerald-800' : 'rounded-xl border border-red-200 bg-red-50 px-3 py-2 font-mono text-sm text-red-700'}>
                    {key}
                    <span className="float-right font-sans text-xs font-semibold uppercase tracking-[0.14em]">{present ? 'present' : 'missing'}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-sm text-slate-500">No required citations declared in the outline.</div>
          )}
        </div>
      </section>
    </div>
  )
}
