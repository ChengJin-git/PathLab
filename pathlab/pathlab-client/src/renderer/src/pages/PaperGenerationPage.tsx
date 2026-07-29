import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ChevronLeft, ChevronRight, FileText, Loader2, Plus, RefreshCw, Search, X } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { Input } from '../components/ui/input'
import { PageHeader } from '../components/PageHeader'
import { listPaperRuns, type PaperRunSummary } from '../api/papers'
import { formatDateTime } from '../lib/utils'
import { paperStageLabel, paperStatusLabel, paperTemplateTitle } from '../lib/paperI18n'

const ACTIVE_STATUSES = new Set(['pending', 'running'])
const RUNS_PER_PAGE = 5
const FILTERED_RUNS_PER_PAGE = 10

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'secondary'
  if (status === 'failed' || status === 'cancelled') return 'destructive'
  if (status === 'running') return 'default'
  return 'outline'
}

function RunRow({ run, onOpen }: { run: PaperRunSummary; onOpen: () => void }) {
  const { t } = useTranslation()

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group w-full rounded-2xl border border-slate-200 bg-white px-5 py-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg hover:shadow-slate-200/70 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-sky-500/15"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3 font-semibold text-slate-950">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-50 text-slate-400 ring-1 ring-slate-200 transition group-hover:bg-slate-100 group-hover:text-slate-700">
              <FileText className="h-4 w-4" />
            </span>
            <span className="line-clamp-2 text-base leading-snug tracking-[-0.015em] sm:text-lg">{run.title || t('paperAgent.detail.fallbackTitle')}</span>
          </div>
        </div>
        <Badge variant={statusVariant(run.status)} className="mt-1 h-8 px-3 tracking-[0.16em] shadow-sm">{paperStatusLabel(t, run.status)}</Badge>
      </div>
      <div className="mt-5 grid gap-3 text-sm text-slate-700 sm:grid-cols-3">
        <div className="rounded-xl bg-slate-50/80 px-4 py-3 ring-1 ring-slate-100"><span className="text-xs font-medium text-slate-400">{t('paperAgent.runRow.stage')}</span><br /><span className="font-medium">{paperStageLabel(t, run.current_stage)}</span></div>
        <div className="rounded-xl bg-slate-50/80 px-4 py-3 ring-1 ring-slate-100"><span className="text-xs font-medium text-slate-400">{t('paperAgent.runRow.template')}</span><br /><span className="font-medium">{run.selected_templates.map((template) => paperTemplateTitle(t, template)).join(', ') || '-'}</span></div>
        <div className="rounded-xl bg-slate-50/80 px-4 py-3 ring-1 ring-slate-100"><span className="text-xs font-medium text-slate-400">{t('paperAgent.runRow.created')}</span><br /><span className="font-medium">{formatDateTime(run.created_at)}</span></div>
      </div>
    </button>
  )
}

export default function PaperGenerationPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const { t } = useTranslation()
  const sourceTaskId = searchParams.get('source_task_id')?.trim() || ''
  const routeState = location.state as { sourceTaskId?: string; sourceTaskName?: string } | null
  const sourceTaskName = sourceTaskId && routeState?.sourceTaskId === sourceTaskId ? routeState.sourceTaskName : ''
  const isSourceTaskView = Boolean(sourceTaskId)
  const [titleSearch, setTitleSearch] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const runsPerPage = isSourceTaskView ? FILTERED_RUNS_PER_PAGE : RUNS_PER_PAGE
  const queryOffset = isSourceTaskView ? (currentPage - 1) * runsPerPage : 0
  const runsQuery = useQuery({
    queryKey: ['paper-runs', sourceTaskId, isSourceTaskView ? currentPage : 'all'],
    queryFn: () => listPaperRuns({
      limit: isSourceTaskView ? runsPerPage : 50,
      offset: queryOffset,
      source_task_id: sourceTaskId || undefined,
    }),
    refetchInterval: (query) => {
      const hasActive = query.state.data?.items?.some((run) => ACTIVE_STATUSES.has(run.status))
      return hasActive ? 2000 : false
    },
  })
  const normalizedTitleSearch = titleSearch.trim().toLocaleLowerCase()
  const visibleRuns = useMemo(() => {
    const runs = runsQuery.data?.items ?? []
    if (!normalizedTitleSearch) return runs
    return runs.filter((run) => (run.title || '').toLocaleLowerCase().includes(normalizedTitleSearch))
  }, [normalizedTitleSearch, runsQuery.data?.items])
  const hasRuns = Boolean(runsQuery.data?.items.length)
  const hasSearch = Boolean(normalizedTitleSearch)
  const sourceTotal = runsQuery.data?.total ?? 0
  const totalPages = isSourceTaskView
    ? Math.max(1, Math.ceil(sourceTotal / runsPerPage) || 1)
    : Math.max(1, Math.ceil(visibleRuns.length / runsPerPage) || 1)
  const paginationStart = isSourceTaskView
    ? (sourceTotal === 0 ? 0 : queryOffset + 1)
    : (visibleRuns.length === 0 ? 0 : (currentPage - 1) * runsPerPage + 1)
  const paginationEnd = isSourceTaskView
    ? Math.min(queryOffset + visibleRuns.length, sourceTotal)
    : Math.min(currentPage * runsPerPage, visibleRuns.length)
  const paginationTotal = isSourceTaskView ? sourceTotal : visibleRuns.length
  const paginatedRuns = isSourceTaskView
    ? visibleRuns
    : visibleRuns.slice((currentPage - 1) * runsPerPage, currentPage * runsPerPage)

  useEffect(() => {
    setCurrentPage(1)
  }, [normalizedTitleSearch])

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages))
  }, [totalPages])

  useEffect(() => {
    setCurrentPage(1)
  }, [sourceTaskId])

  const clearSourceTaskFilter = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('source_task_id')
    setSearchParams(next)
    setCurrentPage(1)
  }

  return (
    <div className="w-full px-4 py-5 sm:px-6 sm:py-9">
      <div className="mx-auto flex max-w-7xl flex-col gap-7">
        <PageHeader
          title={t('paperAgent.runs.title')}
          description={t('paperAgent.runs.description')}
          className="mb-3 items-start gap-5 pb-6 lg:flex-row"
          titleClassName="text-[2.1rem] leading-[1.05] tracking-[-0.03em] sm:text-[2.75rem] lg:text-[3.2rem]"
          actionsClassName="w-full justify-start gap-2 sm:w-auto sm:justify-end lg:pt-2"
        >
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <Button variant="outline" size="sm" onClick={() => navigate('/tools')} className="h-10 gap-2 px-3.5 text-sm shadow-sm">
              <ArrowLeft className="h-4 w-4" />
              {t('common.back')}
            </Button>
            {isSourceTaskView ? (
              <Button variant="outline" size="sm" onClick={clearSourceTaskFilter} className="h-10 px-3.5 text-sm shadow-sm">
                {t('paperAgent.runs.clearSourceTaskFilter')}
              </Button>
            ) : null}
            <Button variant="outline" size="sm" onClick={() => runsQuery.refetch()} className="h-10 gap-2 px-3.5 text-sm shadow-sm">
              <RefreshCw className="h-4 w-4" />
              {t('paperAgent.common.refresh')}
            </Button>
            <Button size="sm" onClick={() => navigate('/papers/new')} className="h-10 gap-2 px-4 text-sm shadow-lg shadow-slate-300/40">
              <Plus className="h-4 w-4" />
              {t('paperAgent.common.newPaper')}
            </Button>
          </div>
        </PageHeader>

        <Card className="overflow-hidden border-slate-200 bg-white shadow-sm">
          <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0 px-6 pb-4 pt-6 sm:px-7 sm:pt-7">
            <div className="min-w-0">
              <CardTitle className="text-[1.65rem] tracking-[-0.025em] sm:text-[1.9rem]">{isSourceTaskView ? t('paperAgent.runs.sourceTaskTitle') : t('paperAgent.runs.workspaceIndex')}</CardTitle>
              <CardDescription className="mt-1 text-base text-slate-500">
                {isSourceTaskView
                  ? t('paperAgent.runs.sourceTaskDescription', { taskName: sourceTaskName || t('paperAgent.runs.sourceTaskFilter') })
                  : t('paperAgent.runs.pollingDescription')}
              </CardDescription>
            </div>
            <Badge variant="outline" className="mt-1 h-8 px-3 tracking-[0.18em] shadow-sm">{t('paperAgent.runs.total', { count: runsQuery.data?.total ?? 0 })}</Badge>
          </CardHeader>
          <CardContent className="space-y-5 px-6 pb-6 sm:px-7 sm:pb-7">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative w-full sm:max-w-xl">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                <Input
                  value={titleSearch}
                  onChange={(event) => setTitleSearch(event.target.value)}
                  placeholder={t('paperAgent.runs.searchTitlePlaceholder')}
                  aria-label={t('paperAgent.runs.searchTitleAria')}
                  className="h-12 rounded-2xl border-slate-200 bg-white pl-12 pr-11 text-base shadow-sm shadow-slate-100/80 placeholder:text-slate-400 focus-visible:ring-4 focus-visible:ring-sky-500/15"
                />
                {titleSearch ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => setTitleSearch('')}
                    aria-label={t('paperAgent.runs.clearSearch')}
                    className="absolute right-2 top-1/2 h-8 w-8 -translate-y-1/2 rounded-xl text-slate-400 hover:text-slate-700"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
              {hasSearch && hasRuns ? (
                <div className="text-sm font-medium text-slate-500">
                  {t('paperAgent.runs.searchResults', { count: visibleRuns.length })}
                </div>
              ) : null}
            </div>
            {runsQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.runs.loading')}
              </div>
            ) : runsQuery.error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {runsQuery.error instanceof Error ? runsQuery.error.message : String(runsQuery.error)}
              </div>
            ) : visibleRuns.length ? (
              <div className="space-y-3">
                {paginatedRuns.map((run) => <RunRow key={run.paper_id} run={run} onOpen={() => navigate(`/papers/${run.paper_id}`)} />)}
                {paginationTotal > runsPerPage ? (
                  <div className="flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-sm font-medium text-slate-500">
                      {t('paperAgent.runs.paginationRange', {
                        start: paginationStart,
                        end: paginationEnd,
                        total: paginationTotal,
                      })}
                    </div>
                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                        disabled={currentPage <= 1}
                        className="gap-1"
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />
                        {t('paperAgent.runs.previousPage')}
                      </Button>
                      <span className="text-sm font-medium text-slate-500">
                        {t('paperAgent.runs.pageInfo', {
                          current: Math.min(currentPage, totalPages),
                          total: totalPages,
                        })}
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                        disabled={currentPage >= totalPages}
                        className="gap-1"
                      >
                        {t('paperAgent.runs.nextPage')}
                        <ChevronRight className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : hasSearch && hasRuns ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-10 text-center">
                <Search className="mx-auto h-9 w-9 text-slate-300" />
                <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.runs.noSearchResultsTitle')}</div>
                <p className="mt-1 text-sm text-slate-500">{t('paperAgent.runs.noSearchResultsDescription')}</p>
                <Button variant="outline" className="mt-4 gap-2" onClick={() => setTitleSearch('')}>
                  <X className="h-4 w-4" /> {t('paperAgent.runs.clearSearch')}
                </Button>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-10 text-center">
                <FileText className="mx-auto h-9 w-9 text-slate-300" />
                <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.runs.emptyTitle')}</div>
                <p className="mt-1 text-sm text-slate-500">{t('paperAgent.runs.emptyDescription')}</p>
                <Button className="mt-4 gap-2" onClick={() => navigate('/papers/new')}>
                  <Plus className="h-4 w-4" /> {t('paperAgent.common.newPaper')}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
