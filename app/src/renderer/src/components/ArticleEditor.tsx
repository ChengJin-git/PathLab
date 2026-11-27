import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowLeft,
  BookOpen,
  Download,
  FileText,
  Image,
  List,
  Pencil,
  Save,
} from 'lucide-react'
import { Button } from './ui/button'
import ArticleProgress from './ArticleProgress'
import ReportPolishPanel from './ReportPolishPanel'
import DeleteReportButton from './DeleteReportButton'
import {
  downloadReport,
  getReport,
  getReportFigure,
  polishReport,
  resumeReport,
  saveReport,
  type Manuscript,
} from '../api/reports'

function ReportImage({
  reportId,
  filename,
  alt,
}: {
  reportId: string
  filename: string
  alt: string
}) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    getReportFigure(reportId, filename, controller.signal)
      .then((blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob)
          setUrl(objectUrl)
        }
      })
      .catch(() => {})
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [reportId, filename])
  return url ? (
    <img
      src={url}
      alt={alt}
      className="mx-auto max-h-[480px] max-w-full object-contain"
    />
  ) : (
    <span className="block rounded-lg bg-gray-100 p-5 text-xs text-gray-500">
      {alt}
    </span>
  )
}

export default function ArticleEditor({
  reportId,
  onBack,
}: {
  reportId: string
  onBack: () => void
}) {
  const { t, i18n } = useTranslation()
  const [report, setReport] = useState<Manuscript>()
  const [tab, setTab] = useState<'preview' | 'editor'>('preview')
  const [side, setSide] = useState<'polish' | 'references' | 'figures'>(
    'polish',
  )
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [instruction, setInstruction] = useState('')
  const [selection, setSelection] = useState<[number, number]>([0, 0])
  const [suggestion, setSuggestion] = useState<{
    text: string
    before: string
    range: [number, number]
  }>()
  const [undo, setUndo] = useState<{ before: string; after: string }>()
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    getReport(reportId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setReport(result)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(t('reports.error'))
      })
    return () => controller.abort()
  }, [reportId, refresh])
  const generating = ['queued', 'running'].includes(
    report?.generation?.status || '',
  )
  useEffect(() => {
    if (!generating) return
    const timer = window.setTimeout(() => setRefresh((v) => v + 1), 2500)
    return () => window.clearTimeout(timer)
  }, [generating, report])
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])
  async function action(operation: () => Promise<void>) {
    setBusy(true)
    setError('')
    try {
      await operation()
    } catch (e) {
      if (alive.current)
        setError(e instanceof Error ? e.message : t('reports.error'))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const accept = (saved: Manuscript) => {
    if (alive.current) {
      setReport(saved)
      setDirty(false)
      setSuggestion(undefined)
    }
  }
  const update = (patch: Partial<Manuscript>) => {
    setReport((r) => (r ? { ...r, ...patch } : r))
    setDirty(true)
    setSuggestion(undefined)
  }
  async function persist() {
    if (!report) return
    const saved = dirty ? await saveReport(report) : report
    accept(saved)
    return saved
  }
  if (!report)
    return (
      <div className="p-8">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} />
          {t('reports.recent')}
        </Button>
        <p
          role={error ? 'alert' : 'status'}
          className="mt-5 text-sm text-gray-600"
        >
          {error || t('reports.loading')}
        </p>
      </div>
    )
  const headings = [...report.content.matchAll(/^## (.+)$/gm)].map((m) => m[1])
  const locked = busy || generating
  const failed = ['failed', 'paused'].includes(report.generation?.status || '')
  return (
    <main className="writing-studio mx-auto w-full max-w-[1600px] space-y-5 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <Button
          variant="ghost"
          className="gap-2 pl-0"
          onClick={() => (dirty ? setError(t('reports.leave')) : onBack())}
        >
          <ArrowLeft size={16} />
          {t('reports.recent')}
        </Button>
        <div className="flex flex-wrap gap-2">
          <DeleteReportButton
            reportId={reportId}
            title={report.title}
            disabled={locked}
            onDeleted={onBack}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={locked || !dirty}
            onClick={() =>
              void action(async () => {
                await persist()
              })
            }
          >
            <Save size={14} className="mr-2" />
            {t('reports.save')}
          </Button>
          {(['docx', 'latex'] as const).map((format) => (
            <Button
              size="sm"
              key={format}
              variant="outline"
              disabled={locked || !report.content}
              onClick={() =>
                void action(async () => {
                  const saved = await persist()
                  if (saved && alive.current)
                    await downloadReport(saved, format)
                })
              }
            >
              <Download size={14} className="mr-2" />
              {format === 'docx' ? 'Word' : 'LaTeX'}
            </Button>
          ))}
        </div>
      </header>
      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      )}
      {report.generation && <ArticleProgress generation={report.generation} />}
      {failed && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {report.generation?.autonomous ? (
            <Link
              className="rounded-lg border bg-white px-4 py-2 text-blue-700"
              to={`/autoresearch/sessions/${encodeURIComponent(report.source_id)}`}
            >
              {t('reports.resumeStudy')}
            </Link>
          ) : (
            <Button
              variant="outline"
              disabled={busy || dirty}
              onClick={() =>
                void action(async () => accept(await resumeReport(reportId)))
              }
            >
              {t('reports.resumeWriting')}
            </Button>
          )}
          <span className="text-xs text-gray-500">
            {t('reports.savedSections')}
          </span>
        </div>
      )}
      <div className="grid items-start gap-5 xl:grid-cols-[180px_minmax(0,1fr)_300px]">
        <aside className="hidden space-y-4 xl:block">
          <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
            <List size={14} />
            {t('reports.outline')}
          </h2>
          <nav className="space-y-1">
            {headings.map((heading, i) => (
              <a
                key={`${heading}-${i}`}
                href={`#article-section-${i}`}
                onClick={() => setTab('preview')}
                className="block rounded-lg px-3 py-2 text-xs leading-5 text-gray-600 hover:bg-white hover:text-blue-700"
              >
                {heading}
              </a>
            ))}
          </nav>
          <div className="border-t pt-4 text-xs leading-6 text-gray-500">
            <span className="block font-semibold text-gray-700">
              {t(`reports.${report.template}`)}
            </span>
            {new Date(report.updated_at).toLocaleString(i18n.language)}
            <br />
            {report.content.split(/\s+/).filter(Boolean).length}{' '}
            {t('reports.words')}
          </div>
        </aside>
        <section className="min-w-0 overflow-hidden rounded-xl border bg-white shadow-sm">
          <div className="flex items-center justify-between border-b bg-gray-50/50 px-4 py-2">
            <div role="tablist" className="flex gap-1">
              {(['preview', 'editor'] as const).map((value) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={tab === value}
                  onClick={() => setTab(value)}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium ${tab === value ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-500 hover:text-gray-900'}`}
                >
                  {value === 'preview' ? (
                    <BookOpen size={14} />
                  ) : (
                    <Pencil size={14} />
                  )}
                  {t(`reports.${value}`)}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-gray-500">
              {t(dirty ? 'reports.unsaved' : 'reports.saved')}
            </span>
          </div>
          <div className="p-5 sm:p-8 lg:p-10">
            {tab === 'editor' ? (
              <>
                <label
                  className="text-xs font-medium text-gray-500"
                  htmlFor="article-title"
                >
                  {t('reports.reportTitle')}
                </label>
                <input
                  id="article-title"
                  value={report.title}
                  disabled={locked}
                  maxLength={500}
                  onChange={(e) => update({ title: e.target.value })}
                  className="mb-6 mt-2 w-full border-b pb-3 text-xl font-semibold outline-none focus:border-blue-500"
                />
                <label
                  className="mb-2 block text-xs font-medium text-gray-500"
                  htmlFor="article-content"
                >
                  {t('reports.editor')}
                </label>
                <textarea
                  id="article-content"
                  value={report.content}
                  disabled={locked}
                  onChange={(e) => update({ content: e.target.value })}
                  onSelect={(e) =>
                    setSelection([
                      e.currentTarget.selectionStart,
                      e.currentTarget.selectionEnd,
                    ])
                  }
                  maxLength={200000}
                  className="min-h-[65vh] w-full resize-y rounded-lg border p-4 font-mono text-sm leading-7 focus:border-blue-400 focus:outline-none"
                />
              </>
            ) : (
              <article className="article-prose max-w-none break-words">
                <p className="not-prose mb-4 text-[10px] font-semibold uppercase tracking-[.18em] text-gray-400">
                  {t('reports.manuscript')}
                </p>
                <h1 className="!mt-0 !text-2xl !leading-snug">
                  {report.title}
                </h1>
                {report.content ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      h2: ({ children }) => (
                        <h2
                          id={`article-section-${headings.indexOf(String(children))}`}
                          className="scroll-mt-8"
                        >
                          {children}
                        </h2>
                      ),
                      img: ({ src, alt }) => {
                        const filename = src?.replace(/^figures\//, '') || ''
                        return report.figures?.some(
                          (f) => f.filename === filename,
                        ) ? (
                          <ReportImage
                            reportId={reportId}
                            filename={filename}
                            alt={alt || ''}
                          />
                        ) : (
                          <span>{alt}</span>
                        )
                      },
                    }}
                  >
                    {report.content}
                  </ReactMarkdown>
                ) : (
                  <div className="not-prose space-y-4 py-8">
                    <p className="text-sm text-gray-500">
                      {t('reports.waitingForArticle')}
                    </p>
                    {[100, 95, 85, 100, 75].map((width, i) => (
                      <div
                        key={i}
                        style={{ width: `${width}%` }}
                        className="h-2.5 animate-pulse rounded bg-gray-100 motion-reduce:animate-none"
                      />
                    ))}
                  </div>
                )}
              </article>
            )}
          </div>
        </section>
        <aside className="min-w-0 space-y-4">
          <div role="tablist" className="flex rounded-lg border bg-white p-1">
            {(['polish', 'references', 'figures'] as const).map((value) => (
              <button
                key={value}
                role="tab"
                aria-selected={side === value}
                onClick={() => setSide(value)}
                className={`flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-md px-2 text-xs ${side === value ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-500'}`}
              >
                {value === 'polish' ? (
                  <Pencil size={13} />
                ) : value === 'figures' ? (
                  <Image size={13} />
                ) : (
                  <BookOpen size={13} />
                )}
                {t(`reports.${value}`)}
              </button>
            ))}
          </div>
          {side === 'polish' && (
            <ReportPolishPanel
              instruction={instruction}
              onInstruction={setInstruction}
              selected={selection[1] > selection[0]}
              busy={locked || !report.content}
              suggestion={suggestion?.text || ''}
              onRequest={() =>
                void action(async () => {
                  const saved = await persist()
                  if (!saved || !alive.current) return
                  const range: [number, number] =
                    saved.content === report.content ? selection : [0, 0]
                  const result = await polishReport(saved, instruction, range)
                  if (alive.current)
                    setSuggestion({
                      text: result.suggestion,
                      before: saved.content,
                      range,
                    })
                })
              }
              onDiscard={() => setSuggestion(undefined)}
              onApply={() => {
                if (!suggestion || suggestion.before !== report.content) return
                const [start, end] = suggestion.range
                const after =
                  end > start
                    ? report.content.slice(0, start) +
                      suggestion.text +
                      report.content.slice(end)
                    : suggestion.text
                setUndo({ before: report.content, after })
                update({ content: after })
                setSelection([0, 0])
              }}
              onUndo={
                undo && undo.after === report.content
                  ? () => {
                      update({ content: undo.before })
                      setUndo(undefined)
                    }
                  : undefined
              }
            />
          )}
          {side === 'references' && (
            <div className="space-y-3">
              {!report.references?.length && (
                <p className="p-4 text-xs text-gray-500">
                  {t('reports.noReferencesYet')}
                </p>
              )}
              {report.references?.map((ref) => (
                <article
                  key={ref.number}
                  className="rounded-lg border bg-white p-4"
                >
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-blue-600">
                    [{ref.number}] · {ref.source}
                  </span>
                  <a
                    href={ref.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 block text-xs font-semibold leading-5 text-gray-900 hover:underline"
                  >
                    {ref.title}
                  </a>
                  <p className="mt-2 text-[11px] leading-5 text-gray-500">
                    {ref.venue} · {ref.year}
                  </p>
                  {ref.doi && (
                    <p className="mt-1 break-all text-[10px] text-gray-500">
                      DOI: {ref.doi}
                    </p>
                  )}
                  <span className="mt-2 block text-[10px] text-emerald-700">
                    {t('reports.verifiedReference')}
                  </span>
                </article>
              ))}
            </div>
          )}
          {side === 'figures' && (
            <div className="space-y-3">
              <p className="text-xs leading-5 text-gray-500">
                {t('reports.figureStyle')}
              </p>
              {report.figures?.map((figure) => (
                <div
                  key={figure.filename}
                  className="rounded-lg border bg-white p-3"
                >
                  <ReportImage
                    reportId={reportId}
                    filename={figure.filename}
                    alt={figure.caption}
                  />
                  <p className="mt-2 text-xs leading-5 text-gray-600">
                    Figure {figure.number}. {figure.caption}
                  </p>
                </div>
              ))}
            </div>
          )}
          <details className="rounded-lg border bg-white p-4 text-xs">
            <summary className="cursor-pointer font-medium text-gray-600">
              {t('reports.evidence')}
            </summary>
            <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all text-[10px]">
              {JSON.stringify(report.evidence, null, 2)}
            </pre>
          </details>
        </aside>
      </div>
    </main>
  )
}
