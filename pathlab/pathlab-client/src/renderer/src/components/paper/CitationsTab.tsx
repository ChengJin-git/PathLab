import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Library,
  Loader2,
  Plus,
  Trash2,
  Users,
  XCircle,
} from 'lucide-react'
import {
  deleteCitation,
  getCitations,
  type CitationReference,
  type CitationsView,
  type VerifiedPoolSummary,
} from '../../api/papers'
import { cn } from '../../lib/utils'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Tooltip } from '../ui/tooltip'
import { AddCitationModal } from './AddCitationModal'

interface CitationsTabProps {
  paperId: string
}

export function CitationsTab({ paperId }: CitationsTabProps) {
  const qc = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [highlightKey, setHighlightKey] = useState<string | null>(null)
  const citationsQuery = useQuery({
    queryKey: ['paper-citations', paperId],
    queryFn: () => getCitations(paperId),
    retry: false,
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) => deleteCitation(paperId, key),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['paper-citations', paperId] })
      await qc.invalidateQueries({ queryKey: ['paper-run', paperId] })
    },
  })

  const view = citationsQuery.data
  const selectedRefs = view?.selected_refs ?? []
  const requiredKeys = view?.required_keys ?? []
  const refsByKey = useMemo(() => new Map(selectedRefs.map((ref) => [ref.key, ref])), [selectedRefs])
  const selectedKeySet = useMemo(() => new Set(selectedRefs.map((ref) => ref.key)), [selectedRefs])

  const focusCitation = (key: string) => {
    setHighlightKey(key)
    window.setTimeout(() => {
      document.getElementById(citationDomId(key))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
    window.setTimeout(() => setHighlightKey((current) => (current === key ? null : current)), 2500)
  }

  if (citationsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading citations...
      </div>
    )
  }

  if (citationsQuery.error) {
    return (
      <Card className="border-red-200 bg-red-50/80">
        <CardContent className="py-6">
          <div className="flex items-start gap-2 text-sm text-red-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>{citationsQuery.error instanceof Error ? citationsQuery.error.message : String(citationsQuery.error)}</div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!view || (!selectedRefs.length && !requiredKeys.length && !view.verified_pool_summary)) {
    return (
      <>
        <Card className="border-dashed border-slate-200 bg-slate-50/70">
          <CardContent className="py-10 text-center">
            <Library className="mx-auto h-8 w-8 text-slate-300" />
            <div className="mt-3 font-semibold text-slate-800">Citations not generated yet</div>
            <p className="mt-1 text-sm text-slate-500">Literature review will write selected refs and citation coverage metadata.</p>
            <Button className="mt-4 gap-2" size="sm" onClick={() => setModalOpen(true)}>
              <Plus className="h-4 w-4" />
              Add citation
            </Button>
          </CardContent>
        </Card>
        <AddCitationModal
          paperId={paperId}
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          onDuplicate={focusCitation}
          onAdded={focusCitation}
        />
      </>
    )
  }

  return (
    <div className="space-y-4">
      <CoverageStrip view={view} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 bg-gradient-to-r from-slate-950 to-slate-800 px-4 py-4 text-white">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold tracking-[-0.03em]">Selected references</h2>
                <p className="text-sm text-slate-300">Structured metadata that regenerates refs.bib.</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="border-teal-200 bg-teal-50 text-teal-800">
                  {selectedRefs.length} refs
                </Badge>
                <Button size="sm" variant="secondary" className="gap-2 bg-white text-slate-900 hover:bg-teal-50" onClick={() => setModalOpen(true)}>
                  <Plus className="h-4 w-4" />
                  Add citation
                </Button>
              </div>
            </div>
          </div>
          <div className="max-h-[72vh] space-y-3 overflow-auto bg-slate-50/60 p-4">
            {deleteMutation.error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {deleteMutation.error instanceof Error ? deleteMutation.error.message : String(deleteMutation.error)}
              </div>
            ) : null}
            {selectedRefs.length ? (
              selectedRefs.map((ref) => (
                <CitationCard
                  key={ref.key}
                  refData={ref}
                  highlighted={highlightKey === ref.key}
                  deleting={deleteMutation.isPending && deleteMutation.variables === ref.key}
                  onDelete={(key) => deleteMutation.mutate(key)}
                />
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
                No selected references yet.
              </div>
            )}
          </div>
        </section>

        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-slate-950">Required cites</h2>
                <p className="text-sm text-slate-500">A2 citation contract from the outline.</p>
              </div>
              <Badge variant="outline">{requiredKeys.length} keys</Badge>
            </div>
          </div>
          <div className="max-h-[72vh] space-y-2 overflow-auto p-4">
            {requiredKeys.length ? (
              requiredKeys.map((key) => {
                const present = selectedKeySet.has(key)
                const ref = refsByKey.get(key)
                const row = (
                  <button
                    key={key}
                    type="button"
                    onClick={() => ref && focusCitation(key)}
                    className={cn(
                      'w-full rounded-2xl border px-3 py-2 text-left font-mono text-sm transition',
                      present
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-900 hover:border-emerald-300'
                        : 'border-red-200 bg-red-50 text-red-700',
                    )}
                  >
                    <span>{key}</span>
                    <span className="float-right font-sans text-xs font-semibold uppercase tracking-[0.14em]">
                      {present ? 'present' : 'missing'}
                    </span>
                  </button>
                )
                return ref ? (
                  <Tooltip key={key} content={<CitationTooltip refData={ref} />} side="left" contentClassName="max-w-[280px] text-left">
                    {row}
                  </Tooltip>
                ) : (
                  row
                )
              })
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
                No required citations declared in the outline.
              </div>
            )}
          </div>
        </section>
      </div>

      <VerifiedPoolPanel summary={view.verified_pool_summary ?? null} />

      <AddCitationModal
        paperId={paperId}
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onDuplicate={focusCitation}
        onAdded={focusCitation}
      />
    </div>
  )
}

function CitationCard({
  refData,
  highlighted,
  deleting,
  onDelete,
}: {
  refData: CitationReference
  highlighted: boolean
  deleting: boolean
  onDelete: (key: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const type = citationType(refData)
  const Icon = type === 'article' ? BookOpen : type === 'inproceedings' ? Users : FileText
  return (
    <article
      id={citationDomId(refData.key)}
      className={cn(
        'rounded-3xl border bg-white shadow-sm transition-all duration-300',
        highlighted ? 'border-teal-400 shadow-[0_0_0_4px_rgba(45,212,191,0.18)]' : 'border-slate-200',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-start gap-3 p-4 text-left"
      >
        <span className="mt-0.5 rounded-2xl border border-slate-200 bg-slate-50 p-2 text-slate-600">
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <TypeBadge type={type} />
            <span className="font-mono text-xs font-semibold text-slate-500">{refData.key}</span>
            {refData.added_by === 'user' ? <Badge variant="outline" className="bg-amber-50 text-amber-800">manual</Badge> : null}
          </span>
          <span className="mt-1 line-clamp-2 block font-semibold leading-6 tracking-[-0.02em] text-slate-950">{refData.title}</span>
        </span>
        <span className="mt-1 text-slate-400">{expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</span>
      </button>

      {expanded ? (
        <div className="border-t border-slate-100 px-4 pb-4 pt-3">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <Meta label="Authors" value={(refData.authors ?? []).join(', ')} />
            <Meta label="Venue" value={refData.venue ?? refData.journal ?? refData.booktitle ?? undefined} />
            <Meta label="Year" value={refData.year ? String(refData.year) : undefined} />
            <Meta label="DOI" value={refData.doi ?? undefined} />
            <Meta label="Source" value={refData.source} />
            <Meta label="Cluster" value={refData.cluster ?? undefined} />
          </dl>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
            <ExternalLinks refData={refData} />
            {refData.added_by === 'user' ? (
              <Button
                size="sm"
                variant="destructive"
                className="gap-2"
                onClick={() => onDelete(refData.key)}
                disabled={deleting}
              >
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                Delete
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </article>
  )
}

function CoverageStrip({ view }: { view: CitationsView }) {
  const coverage = view.coverage
  if (!coverage) return null
  const color =
    coverage.status === 'passed'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : coverage.status === 'warning'
        ? 'border-amber-200 bg-amber-50 text-amber-800'
        : 'border-red-200 bg-red-50 text-red-700'
  const Icon = coverage.status === 'passed' ? CheckCircle2 : coverage.status === 'warning' ? AlertCircle : XCircle
  return (
    <div className={cn('flex flex-wrap items-center gap-2 rounded-2xl border px-4 py-2 text-sm', color)}>
      <Icon className="h-4 w-4" />
      <span className="font-semibold">Coverage:</span>
      <span>
        {coverage.cited_count}/{coverage.selected_count} ({Math.round(coverage.coverage_ratio * 100)}%) · {coverage.status}
      </span>
    </div>
  )
}

function VerifiedPoolPanel({ summary }: { summary: VerifiedPoolSummary | null }) {
  const [open, setOpen] = useState(false)
  if (!summary) return null
  const breakdown = Object.entries(summary.rejection_breakdown ?? {})
  return (
    <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left"
      >
        <div>
          <h2 className="font-semibold text-slate-950">Verified pool</h2>
          <p className="text-sm text-slate-500">
            {summary.discovery_total} considered · {summary.verified_total} verified · {summary.selected_total} selected
          </p>
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
      </button>
      <div className="border-t border-slate-100 px-4 py-3">
        <div className="flex flex-wrap gap-2">
          {breakdown.length ? (
            breakdown.map(([reason, count]) => (
              <span key={reason} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
                {reason}: {count}
              </span>
            ))
          ) : (
            <span className="text-sm text-slate-500">No rejected candidates recorded.</span>
          )}
        </div>
        {open ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {(summary.sample_rejections ?? []).map((item, index) => (
              <div key={`${item.title}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <div className="font-medium text-slate-900">{item.title || 'Untitled candidate'}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {[item.source, item.year].filter(Boolean).join(' · ') || 'unknown source'}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(item.reasons ?? []).map((reason) => (
                    <Badge key={reason} variant="outline" className="bg-white text-slate-700">
                      {reason}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  )
}

function CitationTooltip({ refData }: { refData: CitationReference }) {
  return (
    <div className="space-y-1 text-left">
      <div className="font-semibold">{refData.title}</div>
      <div>{(refData.authors ?? []).slice(0, 3).join(', ') || 'No authors recorded'}</div>
      <div>{[refData.venue ?? refData.journal ?? refData.booktitle, refData.year].filter(Boolean).join(' · ')}</div>
    </div>
  )
}

function ExternalLinks({ refData }: { refData: CitationReference }) {
  const links = [
    refData.doi ? { label: 'doi.org', href: `https://doi.org/${refData.doi}` } : null,
    refData.arxiv_id ? { label: 'arxiv.org', href: `https://arxiv.org/abs/${refData.arxiv_id}` } : null,
    refData.pmid ? { label: 'PubMed', href: `https://pubmed.ncbi.nlm.nih.gov/${refData.pmid}/` } : null,
    refData.openalex_id ? { label: 'OpenAlex', href: openAlexUrl(refData.openalex_id) } : null,
  ].filter((item): item is { label: string; href: string } => Boolean(item))
  if (!links.length) return <span className="text-sm text-slate-400">No external identifiers</span>
  return (
    <div className="flex flex-wrap gap-2">
      {links.map((link) => (
        <a
          key={link.label}
          href={link.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800"
        >
          {link.label}
          <ExternalLink className="h-3 w-3" />
        </a>
      ))}
    </div>
  )
}

function TypeBadge({ type }: { type: 'article' | 'inproceedings' | 'misc' }) {
  const label = type === 'inproceedings' ? 'inproceedings' : type
  const variant = type === 'article' ? 'secondary' : type === 'inproceedings' ? 'default' : 'outline'
  return <Badge variant={variant}>{label}</Badge>
}

function Meta({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-slate-900">{value || '—'}</dd>
    </div>
  )
}

function citationType(refData: CitationReference): 'article' | 'inproceedings' | 'misc' {
  const explicit = refData.entry_type
  if (explicit === 'article' || explicit === 'inproceedings' || explicit === 'misc') return explicit
  if (refData.arxiv_id) return 'misc'
  if (refData.booktitle) return 'inproceedings'
  return 'article'
}

function openAlexUrl(openalexId: string): string {
  return openalexId.startsWith('http') ? openalexId : `https://openalex.org/${openalexId}`
}

function citationDomId(key: string): string {
  return `citation-${key.replace(/[^A-Za-z0-9_-]/g, '_')}`
}
