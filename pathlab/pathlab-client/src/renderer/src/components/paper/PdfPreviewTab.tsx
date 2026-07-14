import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BookOpen, ChevronDown, Download, FileArchive, FileText, Loader2, Maximize2, MousePointer2, RefreshCw, ZoomIn, ZoomOut } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  downloadPaperExport,
  downloadPaperFile,
  getPaperFileBlob,
  getPaperFileUrl,
  getPaperSections,
  postPaperRenderExport,
  type PaperRunArtifact,
  type PaperSectionListResponse,
  type PaperRunDetail,
} from '../../api/papers'
import { normalizeForMatch, pdfMatchSection } from '../../lib/pdfSectionMatch'
import { expandPdfSelectionToSourceSentences } from '../../lib/sentenceBoundary'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { RegenerateSelectionPanel, type SelectionInfo } from './RegenerateSelectionPanel'
import { labelForSection, sectionBodyView } from './SectionsTab'
import { paperStageLabel, paperTaskRoleLabel, paperTemplateTitle } from '../../lib/paperI18n'

const PdfViewer = lazy(() => import('./PdfViewer').then((module) => ({ default: module.PdfViewer })))

interface PdfPreviewTabProps {
  paperId: string
  run: PaperRunDetail
  pdfRefreshKey: number
  onPdfRefreshNeeded: () => void
}

function cacheBustedUrl(url: string, key: number): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}v=${key}`
}

function artifactUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  if (error.isNotFound()) return true
  const detail = error.details || error.message
  return error.status === 403 && detail.includes('Artifact is not registered public')
}

function sanitizeDownloadNamePart(value: string | null | undefined, fallback: string): string {
  const cleaned = (value || '')
    .normalize('NFKC')
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned || fallback
}

export function PdfPreviewTab({ paperId, run, pdfRefreshKey, onPdfRefreshNeeded }: PdfPreviewTabProps) {
  const { t } = useTranslation()
  const [, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [selectionMessage, setSelectionMessage] = useState<{
    tone: 'info' | 'warning' | 'success'
    text: string
  } | null>(null)
  const [pdfSelection, setPdfSelection] = useState<{
    sectionName: string
    selection: SelectionInfo
  } | null>(null)
  const [pdfScale, setPdfScale] = useState<number>(1)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const [awaitingRenderExport, setAwaitingRenderExport] = useState(false)
  const [renderExportRequestedAt, setRenderExportRequestedAt] = useState<number | null>(null)
  const downloadMenuRef = useRef<HTMLDivElement | null>(null)
  const template = run.selected_templates[0] ?? 'miccai'
  const primarySourceTask = run.source_tasks?.[0]
  const sourceTaskId = primarySourceTask?.task_id ?? run.source_task_ids[0] ?? paperId
  const sourceTaskLabel = primarySourceTask?.label
  const sourceRole = primarySourceTask?.role ?? 'main'
  const paperTitlePart = sanitizeDownloadNamePart(run.title, paperId)
  const sourceRolePart = sanitizeDownloadNamePart(paperTaskRoleLabel(t, sourceRole), sourceRole)
  const sourceTaskIdPart = sanitizeDownloadNamePart(sourceTaskId, 'source-task')
  const sourceTaskLabelPart = sanitizeDownloadNamePart(sourceTaskLabel, '')
  const sourceTaskPart =
    sourceTaskLabelPart && sourceTaskLabelPart !== sourceTaskIdPart
      ? `${sourceTaskIdPart}-${sourceTaskLabelPart}`
      : sourceTaskIdPart
  const paperDownloadBaseName = `${paperTitlePart}（${sourceRolePart}）-${sourceTaskPart}`
  const pdfPath = `final/${template}/main.pdf`
  const bundlePath = `exports/${template}_bundle.zip`
  const pdfArtifact = (run.artifacts ?? []).find((artifact) => artifact.path === pdfPath)
  const pdfArtifactMeta = pdfArtifact as (PaperRunArtifact & { stale?: boolean }) | undefined
  const pdfArtifactStale = Boolean(pdfArtifactMeta?.stale)
  const pipelineBlocksRender =
    run.status === 'pending' || run.status === 'running' || run.status === 'awaiting_outline_approval'
  const isPdfPublished = Boolean(
    pdfArtifact &&
      pdfArtifact.visibility === 'public' &&
      pdfArtifact.downloadable &&
      ['ready', 'generated', 'completed'].includes(pdfArtifact.status),
  )
  const pdfUrl = cacheBustedUrl(getPaperFileUrl(paperId, pdfPath), pdfRefreshKey)
  const renderExportStageActive =
    run.status === 'running' &&
    (run.current_stage === 'rendering' || run.current_stage === 'exporting')

  const pdfQuery = useQuery({
    queryKey: ['paper-file', paperId, pdfPath, 'exists', pdfRefreshKey],
    queryFn: () => getPaperFileBlob(paperId, pdfPath, { cache: 'no-store' }),
    enabled: isPdfPublished,
    retry: false,
  })

  const downloadPdfMutation = useMutation({
    mutationFn: () => downloadPaperFile(paperId, pdfPath, `${paperDownloadBaseName}.pdf`),
    onSuccess: () => setDownloadMenuOpen(false),
  })
  const downloadBundleMutation = useMutation({
    mutationFn: () => downloadPaperExport(paperId, template, `${paperDownloadBaseName}.zip`),
    onSuccess: () => setDownloadMenuOpen(false),
  })
  const renderExportMutation = useMutation({
    mutationFn: () => postPaperRenderExport(paperId),
    onSuccess: async () => {
      setAwaitingRenderExport(true)
      setRenderExportRequestedAt(Date.now())
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
    },
  })
  const renderExportInFlight = renderExportMutation.isPending || awaitingRenderExport

  useEffect(() => {
    if (!awaitingRenderExport) return
    if (renderExportMutation.isPending || renderExportStageActive) return
    if (run.status !== 'completed' && run.status !== 'failed' && run.status !== 'cancelled') return

    const elapsedMs = renderExportRequestedAt ? Date.now() - renderExportRequestedAt : 0
    if (elapsedMs < 1200 && run.status === 'completed') {
      const timer = window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      }, 1200 - elapsedMs)
      return () => window.clearTimeout(timer)
    }

    setAwaitingRenderExport(false)
    setRenderExportRequestedAt(null)
    if (run.status !== 'completed' || pdfArtifactStale) return

    void queryClient.invalidateQueries({ queryKey: ['paper-file', paperId, pdfPath] })
    onPdfRefreshNeeded()
  }, [
    awaitingRenderExport,
    renderExportMutation.isPending,
    renderExportStageActive,
    renderExportRequestedAt,
    run.status,
    pdfArtifactStale,
    queryClient,
    paperId,
    pdfPath,
    onPdfRefreshNeeded,
  ])

  const isMissing = !isPdfPublished || artifactUnavailable(pdfQuery.error)
  const isDownloading = downloadPdfMutation.isPending || downloadBundleMutation.isPending
  const downloadError = downloadPdfMutation.error ?? downloadBundleMutation.error
  const downloadErrorPath = downloadPdfMutation.error ? pdfPath : bundlePath

  useEffect(() => {
    if (!downloadMenuOpen) return

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target
      if (target instanceof Node && downloadMenuRef.current?.contains(target)) return
      setDownloadMenuOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDownloadMenuOpen(false)
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [downloadMenuOpen])

  const handleReturnToSections = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', 'sections')
      if (pdfSelection?.sectionName) {
        next.set('section', pdfSelection.sectionName)
      } else {
        next.delete('section')
      }
      return next
    })
  }

  const handlePdfSelection = async (text: string) => {
    const normalized = normalizeForMatch(text)
    if (normalized.length < 20) {
      setPdfSelection(null)
      setSelectionMessage({ tone: 'warning', text: t('paperAgent.pdf.selectShort') })
      return
    }

    try {
      const cached = queryClient.getQueryData<PaperSectionListResponse>(['paper-sections', paperId])
      const sectionsResponse = cached ?? (await getPaperSections(paperId))
      if (!cached) {
        queryClient.setQueryData(['paper-sections', paperId], sectionsResponse)
      }
      const sections = sectionsResponse.sections ?? []
      const match = pdfMatchSection(text, sections)

      if (!match) {
        setPdfSelection(null)
        setSelectionMessage({
          tone: 'warning',
          text: t('paperAgent.pdf.matchFailed'),
        })
        return
      }
      if (match.ambiguous) {
        setPdfSelection(null)
        setSelectionMessage({
          tone: 'warning',
          text: t('paperAgent.pdf.matchAmbiguous'),
        })
        return
      }

      // Expand the PDF selection to whole source sentences. If the user only
      // grabbed half a sentence, walk into the matched section's LaTeX source
      // and round outwards to sentence boundaries there. Strip the section /
      // abstract wrapper first so the expansion can never absorb commands
      // like `\begin{abstract}` or `\section{Methods}` into the selection.
      const matchedSection = sections.find((s) => s.section_name === match.section_name)
      const matchedBodyView = matchedSection
        ? sectionBodyView(matchedSection.text, match.section_name)
        : null
      const sourceText = matchedBodyView?.bodyText ?? matchedSection?.text ?? ''
      const expansion = expandPdfSelectionToSourceSentences(text, sourceText)
      const snappedText = expansion?.text ?? text
      const expanded = expansion?.expanded ?? false
      const expansionNote = expanded
        ? t('paperAgent.pdf.expanded')
        : expansion === null
          ? t('paperAgent.pdf.rawSelection')
          : ''
      setSelectionMessage({
        tone: 'success',
        text: t('paperAgent.pdf.matched', {
          section: labelForSection(match.section_name, t),
          confidence: Math.round(match.confidence * 100),
          note: expansionNote,
        }),
      })
      setPdfSelection({
        sectionName: match.section_name,
        selection: {
          text: snappedText,
          paragraphIndex: 0, // backend selection_locator resolves precise paragraph from selected_text
          charStart: -1,     // negative ⇒ "from PDF, no precise char hint"
          charEnd: -1,
        },
      })
    } catch (error) {
      setPdfSelection(null)
      setSelectionMessage({
        tone: 'warning',
        text: error instanceof Error ? error.message : String(error),
      })
    }
  }

  if (pdfQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.pdf.checking')}
      </div>
    )
  }

  if (isMissing) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-12 text-center">
          <BookOpen className="mx-auto h-9 w-9 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.pdf.compilePending')}</div>
          <p className="mt-1 text-sm text-slate-500">
            {t('paperAgent.pdf.missingDescription', { path: pdfPath })}
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <Button
              type="button"
              size="sm"
              className="gap-2"
              onClick={() => renderExportMutation.mutate()}
              disabled={pipelineBlocksRender || renderExportInFlight}
            >
              {renderExportInFlight ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {renderExportInFlight
                ? t('paperAgent.pdf.renderQueued')
                : pipelineBlocksRender
                  ? t('paperAgent.pdf.pipelineBlocked', { stage: paperStageLabel(t, run.current_stage) })
                  : t('paperAgent.pdf.renderExport')}
            </Button>
          </div>
          {renderExportMutation.error ? (
            <p className="mt-3 text-sm text-red-600">
              {renderExportMutation.error instanceof Error
                ? renderExportMutation.error.message
                : String(renderExportMutation.error)}
            </p>
          ) : null}
        </CardContent>
      </Card>
    )
  }

  if (pdfQuery.error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {pdfQuery.error instanceof Error ? pdfQuery.error.message : String(pdfQuery.error)}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">{t('paperAgent.pdf.title')}</h2>
          <p className="text-sm text-slate-500">
            {t('paperAgent.pdf.sourceLine', { template: paperTemplateTitle(t, template), path: pdfPath })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" className="gap-2" onClick={handleReturnToSections}>
            <FileText className="h-4 w-4" />
            {t('paperAgent.pdf.returnToSections')}
          </Button>
          <div ref={downloadMenuRef} className="relative">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => setDownloadMenuOpen((open) => !open)}
              disabled={isDownloading}
              aria-haspopup="menu"
              aria-expanded={downloadMenuOpen}
            >
              {isDownloading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {t('paperAgent.pdf.download')}
              <ChevronDown className="h-4 w-4" />
            </Button>
            {downloadMenuOpen ? (
              <div
                role="menu"
                className="absolute right-0 z-30 mt-2 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-xl"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => downloadPdfMutation.mutate()}
                  disabled={isDownloading}
                >
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
                  <span>
                    <span className="block font-semibold text-slate-900">{t('paperAgent.pdf.downloadPdf')}</span>
                    <span className="block text-xs text-slate-500">{t('paperAgent.pdf.downloadPdfDescription')}</span>
                  </span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  onClick={() => downloadBundleMutation.mutate()}
                  disabled={isDownloading}
                >
                  <FileArchive className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600" />
                  <span>
                    <span className="block font-semibold text-slate-900">{t('paperAgent.pdf.downloadBundle')}</span>
                    <span className="block text-xs text-slate-500">{t('paperAgent.pdf.downloadBundleDescription')}</span>
                  </span>
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
      {downloadError ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {downloadError instanceof Error ? downloadError.message : String(downloadError)} (
          {downloadErrorPath})
        </div>
      ) : null}
      {pdfArtifactStale ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <div>
            <div className="font-semibold">{t('paperAgent.pdf.staleTitle')}</div>
            <div className="mt-0.5 text-amber-800">
              {t('paperAgent.pdf.staleDescription')}
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            className="gap-2 bg-amber-900 text-white hover:bg-amber-950"
            onClick={() => renderExportMutation.mutate()}
            disabled={pipelineBlocksRender || renderExportInFlight}
          >
            {renderExportInFlight ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {renderExportInFlight
              ? t('paperAgent.pdf.renderQueued')
              : pipelineBlocksRender
                ? t('paperAgent.pdf.pipelineBlocked', { stage: paperStageLabel(t, run.current_stage) })
                : t('paperAgent.pdf.rerenderExport')}
          </Button>
        </div>
      ) : null}
      {renderExportMutation.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {renderExportMutation.error instanceof Error
            ? renderExportMutation.error.message
            : String(renderExportMutation.error)}
        </div>
      ) : null}
      <div
        className={[
          'flex items-start gap-2 rounded-2xl border p-3 text-sm',
          selectionMessage?.tone === 'warning'
            ? 'border-amber-200 bg-amber-50 text-amber-800'
            : selectionMessage?.tone === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-sky-100 bg-sky-50 text-sky-800',
        ].join(' ')}
      >
        <MousePointer2 className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          {selectionMessage?.text ??
            t('paperAgent.pdf.selectionHint')}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-inner">
          <div className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-xl border border-slate-200 bg-white/95 p-1 shadow-md backdrop-blur">
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('paperAgent.pdf.zoomOut')}
              className="h-7 w-7"
              onClick={() => setPdfScale((s) => Math.max(0.5, +(s - 0.1).toFixed(2)))}
              disabled={pdfScale <= 0.5}
            >
              <ZoomOut className="h-4 w-4" />
            </Button>
            <button
              type="button"
              className="min-w-[3.25rem] rounded-md px-2 py-1 text-xs font-semibold tabular-nums text-slate-700 hover:bg-slate-100"
              title={t('paperAgent.pdf.resetZoom')}
              onClick={() => setPdfScale(1)}
            >
              {Math.round(pdfScale * 100)}%
            </button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('paperAgent.pdf.zoomIn')}
              className="h-7 w-7"
              onClick={() => setPdfScale((s) => Math.min(2.5, +(s + 0.1).toFixed(2)))}
              disabled={pdfScale >= 2.5}
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t('paperAgent.pdf.fitWidth')}
              className="h-7 w-7"
              title={t('paperAgent.pdf.fitWidthTitle')}
              onClick={() => setPdfScale(1.5)}
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
          <Suspense
            fallback={
              <div className="flex h-[72vh] items-center justify-center bg-white text-sm text-slate-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t('paperAgent.pdf.loadingTextLayer')}
              </div>
            }
          >
            <PdfViewer pdfUrl={pdfUrl} refreshKey={pdfRefreshKey} scale={pdfScale} onSelectionChange={handlePdfSelection} />
          </Suspense>
        </div>
        <div className="xl:sticky xl:top-4 xl:self-start">
          <RegenerateSelectionPanel
            paperId={paperId}
            sectionName={pdfSelection?.sectionName ?? null}
            templateId={template}
            selection={pdfSelection?.selection ?? null}
            onPdfRefreshNeeded={onPdfRefreshNeeded}
            onClear={() => {
              setPdfSelection(null)
              setSelectionMessage(null)
              window.getSelection()?.removeAllRanges()
            }}
          />
        </div>
      </div>
    </div>
  )
}
