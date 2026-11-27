import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowRight,
  BookOpen,
  FileText,
  Plus,
  Search,
  Sparkles,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Select } from '../components/ui/select'
import { useAuth } from '../contexts/AuthContext'
import {
  getWorkspaceSelection,
  WORKSPACE_CHANGED,
} from '../lib/workspaceSelection'
import { supportedLanguages, type SupportedLanguage } from '../i18n'
import {
  createReport,
  getReportSource,
  listReports,
  listReportSources,
  type ReportRecommendation,
  type ReportSource,
  type ReportSummary,
  type ReportTemplate,
} from '../api/reports'
import ArticleEditor from '../components/ArticleEditor'
import DeleteReportButton from '../components/DeleteReportButton'

export default function ReportGeneratorPage() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [workspace, setWorkspace] = useState(
    getWorkspaceSelection().workspaceId,
  )
  useEffect(() => {
    const changed = () => setWorkspace(getWorkspaceSelection().workspaceId)
    window.addEventListener(WORKSPACE_CHANGED, changed)
    return () => window.removeEventListener(WORKSPACE_CHANGED, changed)
  }, [])
  if (!user || !['admin', 'pathologist'].includes(user.role))
    return <div className="p-8 text-gray-600">{t('reports.restricted')}</div>
  return (
    <WritingStudio
      key={`${user.id}:${user.role}:${workspace}`}
      admin={user.role === 'admin'}
    />
  )
}

function WritingStudio({ admin }: { admin: boolean }) {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams()
  const selected = params.get('report')
  const [showNew, setShowNew] = useState(Boolean(params.get('source_id')))
  const [items, setItems] = useState<ReportSummary[]>([])
  const [query, setQuery] = useState('')
  const [page, setPage] = useState<{
    query: string
    cursors: (string | undefined)[]
  }>({ query: '', cursors: [undefined] })
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [pageSize, setPageSize] = useState(20)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [visible, setVisible] = useState(!document.hidden)
  const searching = query.trim() !== page.query
  const cursor = page.cursors[page.cursors.length - 1]
  useEffect(() => {
    if (!searching) return
    const timer = window.setTimeout(
      () => setPage({ query: query.trim(), cursors: [undefined] }),
      300,
    )
    return () => window.clearTimeout(timer)
  }, [query, searching])
  useEffect(() => {
    const changed = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', changed)
    return () => document.removeEventListener('visibilitychange', changed)
  }, [])
  useEffect(() => {
    if (selected || searching) return
    const controller = new AbortController()
    setLoading(true)
    setError('')
    listReports(
      { query: page.query, ...(cursor ? { cursor } : {}) },
      controller.signal,
    )
      .then((data) => {
        if (!controller.signal.aborted) {
          setItems(data.items)
          setNextCursor(data.next_cursor)
          setPageSize(data.page_size)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(t('reports.error'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [page.query, cursor, refresh, selected, searching])
  useEffect(() => {
    if (
      selected ||
      loading ||
      searching ||
      !visible ||
      error ||
      !items.some((r) =>
        ['queued', 'running'].includes(r.generation?.status || ''),
      )
    )
      return
    const timer = window.setTimeout(() => setRefresh((v) => v + 1), 3000)
    return () => window.clearTimeout(timer)
  }, [items, selected, loading, searching, visible, error])
  if (selected)
    return (
      <ArticleEditor
        key={selected}
        reportId={selected}
        onBack={() => {
          setParams({})
          setRefresh((v) => v + 1)
        }}
      />
    )
  return (
    <main className="writing-studio mx-auto w-full max-w-7xl space-y-7 px-4 py-5 sm:px-6 sm:py-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.18em] text-blue-700">
            <BookOpen size={15} />
            {t('reports.studio')}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-950 sm:text-3xl">
            {t('reports.title')}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
            {t('reports.studioDescription')}
          </p>
        </div>
        <Button className="gap-2" onClick={() => setShowNew((v) => !v)}>
          <Plus size={16} />
          {t('reports.newArticle')}
        </Button>
      </header>
      {showNew && (
        <NewArticle
          onCreated={(id) => setParams({ report: id })}
          sourceType={params.get('source_type')}
          sourceId={params.get('source_id')}
        />
      )}
      <section
        aria-busy={loading || searching}
        className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-4 border-b p-4 sm:px-6 sm:py-5">
          <div>
            <h2 className="font-semibold text-gray-950">
              {t('reports.recent')}
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              {t(admin ? 'reports.adminVisibility' : 'reports.ownVisibility')}
            </p>
          </div>
          <div className="relative w-full sm:w-72">
            <Search size={16} className="absolute left-3 top-3 text-gray-400" />
            <input
              aria-label={t('reports.searchArticles')}
              placeholder={t('reports.searchArticles')}
              value={query}
              maxLength={200}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-lg border bg-gray-50 py-2.5 pl-9 pr-3 text-sm focus:border-blue-400 focus:outline-none"
            />
          </div>
        </div>
        {error && (
          <p role="alert" className="p-5 text-sm text-red-700">
            {error}
            <button
              className="ml-3 underline"
              onClick={() => setRefresh((v) => v + 1)}
            >
              {t('reports.retry')}
            </button>
          </p>
        )}
        {loading && !items.length ? (
          <div className="space-y-4 p-6" aria-label={t('reports.loading')}>
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-gray-100 motion-reduce:animate-none"
              />
            ))}
          </div>
        ) : !items.length ? (
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <div className="mb-4 rounded-2xl bg-blue-50 p-4 text-blue-600">
              <FileText size={28} />
            </div>
            <h3 className="font-medium text-gray-900">
              {t('reports.noArticles')}
            </h3>
            <p className="mt-2 max-w-full text-sm leading-6 text-gray-500 lg:whitespace-nowrap">
              {t('reports.noArticlesHint')}
            </p>
            <Button
              variant="outline"
              className="mt-5 gap-2"
              onClick={() => setShowNew(true)}
            >
              <Plus size={15} />
              {t('reports.newArticle')}
            </Button>
          </div>
        ) : (
          <div className="divide-y">
            {items.map((item) => {
              const status = item.generation?.status || item.status
              return (
                <div
                  key={item.report_id}
                  className="flex items-center pr-3 sm:pr-5"
                >
                  <button
                    onClick={() => setParams({ report: item.report_id })}
                    className="group flex min-w-0 flex-1 items-start gap-4 p-4 text-left transition-colors hover:bg-slate-50 focus-visible:outline-blue-500 sm:px-6 sm:py-5"
                  >
                    <div className="hidden h-16 w-12 shrink-0 flex-col gap-1.5 rounded border bg-white p-2.5 shadow-sm sm:flex">
                      <span className="h-1 w-5 bg-blue-300" />
                      <span className="h-0.5 w-full bg-gray-200" />
                      <span className="h-0.5 w-full bg-gray-200" />
                      <span className="h-0.5 w-4 bg-gray-200" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
                          {t(`reports.${item.template}`)}
                        </span>
                        <span
                          className={`rounded px-2 py-0.5 ${['running', 'queued'].includes(status) ? 'bg-blue-50 text-blue-700' : status === 'completed' || status === 'ready' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}
                        >
                          {t(`reports.state_${status}`)}
                        </span>
                      </div>
                      <h3 className="break-words text-sm font-semibold text-gray-900 group-hover:text-blue-700 sm:text-base">
                        {item.title}
                      </h3>
                      <p className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">
                        {item.generation?.current_section
                          ? `${t('reports.writingSection')} ${item.generation.current_section}`
                          : item.excerpt.replace(/[#*]/g, '')}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                        <span>{t(`reports.${item.source_type}`)}</span>
                        {admin && <span>{item.owner_name}</span>}
                        <time>
                          {new Date(item.updated_at).toLocaleString(
                            i18n.language,
                          )}
                        </time>
                      </div>
                    </div>
                    <ArrowRight
                      size={17}
                      className="mt-6 shrink-0 text-gray-400 group-hover:text-blue-600"
                    />
                  </button>
                  <DeleteReportButton
                    reportId={item.report_id}
                    title={item.title}
                    disabled={
                      loading ||
                      searching ||
                      ['queued', 'running'].includes(status)
                    }
                    onDeleted={() => {
                      setItems((current) =>
                        current.filter(
                          (report) => report.report_id !== item.report_id,
                        ),
                      )
                      if (items.length === 1 && page.cursors.length > 1)
                        setPage((current) => ({
                          ...current,
                          cursors: current.cursors.slice(0, -1),
                        }))
                      setRefresh((value) => value + 1)
                    }}
                  />
                </div>
              )
            })}
          </div>
        )}
        {(page.cursors.length > 1 || nextCursor) && (
          <nav
            aria-label={t('reports.pagination')}
            className="flex flex-wrap items-center justify-between gap-3 border-t p-4"
          >
            <span role="status" className="text-xs text-gray-500">
              {t('reports.pageInfo', {
                page: page.cursors.length,
                size: pageSize,
              })}
              {(loading || searching) && ` · ${t('reports.loading')}`}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page.cursors.length === 1 || loading || searching}
                onClick={() =>
                  setPage((current) => ({
                    ...current,
                    cursors: current.cursors.slice(0, -1),
                  }))
                }
              >
                {t('reports.previous')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!nextCursor || loading || searching || !!error}
                onClick={() => {
                  if (nextCursor)
                    setPage((current) => ({
                      ...current,
                      cursors: [...current.cursors, nextCursor],
                    }))
                }}
              >
                {t('reports.next')}
              </Button>
            </div>
          </nav>
        )}
      </section>
    </main>
  )
}

function NewArticle({
  onCreated,
  sourceType,
  sourceId,
}: {
  onCreated: (id: string) => void
  sourceType: string | null
  sourceId: string | null
}) {
  const { t } = useTranslation()
  const [sources, setSources] = useState<ReportSource[]>([])
  const [source, setSource] = useState(
    sourceId
      ? `${sourceType === 'research' ? 'research' : 'experiment'}:${sourceId}`
      : '',
  )
  const [recommendation, setRecommendation] = useState<ReportRecommendation>()
  const [template, setTemplate] = useState<ReportTemplate | 'auto'>('auto')
  const [language, setLanguage] = useState<SupportedLanguage>('en-US')
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    const c = new AbortController()
    listReportSources('', c.signal)
      .then((r) => {
        if (!c.signal.aborted) setSources(r.items)
      })
      .catch(() => {
        if (!c.signal.aborted) setError(t('reports.error'))
      })
    return () => c.abort()
  }, [])
  const key = () => ({
    source_type: source.split(':')[0] as 'research' | 'experiment',
    source_id: source.slice(source.indexOf(':') + 1),
  })
  useEffect(() => {
    setRecommendation(undefined)
    if (!source) return
    const c = new AbortController()
    getReportSource(key(), c.signal)
      .then((r) => {
        if (!c.signal.aborted) setRecommendation(r.recommendation)
      })
      .catch(() => {
        if (!c.signal.aborted) setError(t('reports.error'))
      })
    return () => c.abort()
  }, [source])
  const options = sources.map((s) => ({
    value: `${s.source_type}:${s.source_id}`,
    label: `${t(`reports.${s.source_type}`)} · ${s.title}`,
  }))
  if (source && !options.some((s) => s.value === source))
    options.unshift({ value: source, label: source })
  return (
    <section className="grid overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="space-y-5 p-5 sm:p-6">
        <h2 className="flex items-center gap-2 font-semibold text-gray-950">
          <Sparkles size={17} className="text-blue-600" />
          {t('reports.newArticle')}
        </h2>
        <div>
          <label className="mb-2 block text-xs font-medium text-gray-600">
            {t('reports.source')}
          </label>
          <Select
            ariaLabel={t('reports.source')}
            value={source}
            options={options}
            placeholder={t('reports.choose')}
            disabled={busy}
            onChange={setSource}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-xs font-medium text-gray-600">
              {t('reports.template')}
            </label>
            <Select
              ariaLabel={t('reports.template')}
              value={template}
              onChange={(v) => setTemplate(v as ReportTemplate | 'auto')}
              disabled={busy}
              options={['auto', 'conference', 'journal'].map((v) => ({
                value: v,
                label: t(`reports.${v}`),
              }))}
            />
          </div>
          <div>
            <label className="mb-2 block text-xs font-medium text-gray-600">
              {t('reports.language')}
            </label>
            <Select
              ariaLabel={t('reports.language')}
              value={language}
              onChange={(v) => setLanguage(v as SupportedLanguage)}
              disabled={busy}
              options={supportedLanguages.map((v) => ({
                value: v.code,
                label: v.nativeName,
              }))}
            />
          </div>
        </div>
        <label className="block text-xs font-medium text-gray-600">
          {t('reports.writingFocus')}
          <textarea
            rows={3}
            maxLength={8000}
            value={instruction}
            disabled={busy}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={t('reports.focusPlaceholder')}
            className="mt-2 w-full rounded-lg border p-3 text-sm font-normal leading-6 focus:border-blue-400 focus:outline-none"
          />
        </label>
        {recommendation && (
          <p className="text-xs text-gray-500">
            {t('reports.scale', {
              runs: recommendation.completed_runs,
              datasets: recommendation.dataset_count,
              template: t(`reports.${recommendation.template}`),
            })}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        <Button
          disabled={!recommendation || busy}
          className="gap-2"
          onClick={async () => {
            setBusy(true)
            setError('')
            try {
              const report = await createReport(
                key(),
                template,
                language,
                instruction,
              )
              if (alive.current) onCreated(report.report_id)
            } catch {
              if (alive.current) setError(t('reports.error'))
            } finally {
              if (alive.current) setBusy(false)
            }
          }}
        >
          <Sparkles size={16} />
          {t(busy ? 'reports.saving' : 'reports.generateArticle')}
        </Button>
      </div>
      <aside className="border-t bg-slate-50 p-6 lg:border-l lg:border-t-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {t('reports.writingProcess')}
        </p>
        <ol className="mt-5 space-y-5">
          {['evidence', 'literature', 'writing', 'review'].map((s, i) => (
            <li key={s} className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-white text-xs text-blue-700">
                {i + 1}
              </span>
              <span className="text-sm leading-6 text-gray-700">
                {t(`reports.stage_${s}`)}
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-xs leading-6 text-gray-500">
          {t('reports.verifiedHint')}
        </p>
      </aside>
    </section>
  )
}
