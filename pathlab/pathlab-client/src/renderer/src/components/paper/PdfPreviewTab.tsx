import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BookOpen, Download, FileCode2, Loader2, Maximize2, MousePointer2, RefreshCw, ZoomIn, ZoomOut } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  downloadPaperExport,
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
import { SECTION_ORDER, labelForSection, sectionBodyView } from './SectionsTab'
import { paperStageLabel, paperTemplateTitle } from '../../lib/paperI18n'

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

export function PdfPreviewTab({ paperId, run, pdfRefreshKey, onPdfRefreshNeeded }: PdfPreviewTabProps) {
  const { t } = useTranslation()
  const [, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [sourceSection, setSourceSection] = useState<string>('abstract')
  const [selectionMessage, setSelectionMessage] = useState<{
    tone: 'info' | 'warning' | 'success'
    text: string
  } | null>(null)
  const [pdfSelection, setPdfSelection] = useState<{
    sectionName: string
    selection: SelectionInfo
  } | null>(null)
  const [pdfScale, setPdfScale] = useState<number>(1)
  const template = run.selected_templates[0] ?? 'miccai'
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

  const sectionsCacheQuery = useQuery({
    queryKey: ['paper-sections', paperId],
    queryFn: () => getPaperSections(paperId),
    enabled: false,
    initialData: () => queryClient.getQueryData<PaperSectionListResponse>(['paper-sections', paperId]),
  })

  const generatedSectionNames = useMemo(
    () => new Set((sectionsCacheQuery.data?.sections ?? []).map((section) => section.section_name)),
    [sectionsCacheQuery.data?.sections],
  )
  const firstGeneratedSection = useMemo(
    () => SECTION_ORDER.find((section) => generatedSectionNames.has(section)) ?? 'abstract',
    [generatedSectionNames],
  )
  const sectionOptions = useMemo(
    () =>
      SECTION_ORDER.map((section) => ({
        value: section,
        label: labelForSection(section, t),
        generated: generatedSectionNames.has(section),
      })),
    [generatedSectionNames, t],
  )

  const pdfQuery = useQuery({
    queryKey: ['paper-file', paperId, pdfPath, 'exists', pdfRefreshKey],
    queryFn: () => getPaperFileBlob(paperId, pdfPath),
    enabled: isPdfPublished,
    retry: false,
  })

  const downloadMutation = useMutation({
    mutationFn: () => downloadPaperExport(paperId, template),
  })
  const renderExportMutation = useMutation({
    mutationFn: () => postPaperRenderExport(paperId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      await queryClient.invalidateQueries({ queryKey: ['paper-file', paperId] })
      onPdfRefreshNeeded()
    },
  })

  const isMissing = !isPdfPublished || artifactUnavailable(pdfQuery.error)

  useEffect(() => {
    setSourceSection((current) =>
      generatedSectionNames.size > 0 && !generatedSectionNames.has(current) ? firstGeneratedSection : current,
    )
  }, [firstGeneratedSection, generatedSectionNames])

  const handleEditInSource = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', 'sections')
      next.set('section', sourceSection)
      return next
    })
  }

  const handlePdfSelection = async (text: string) => {
    const normalized = normalizeForMatch(text)
    if (normalized.length < 20) {
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
        setSelectionMessage({
          tone: 'warning',
          text: t('paperAgent.pdf.matchFailed'),
        })
        return
      }
      if (match.ambiguous) {
        setSelectionMessage({
          tone: 'warning',
          text: t('paperAgent.pdf.matchAmbiguous'),
        })
        return
      }

      setSourceSection(match.section_name)
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
              disabled={pipelineBlocksRender || renderExportMutation.isPending}
            >
              {renderExportMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {pipelineBlocksRender ? t('paperAgent.pdf.pipelineBlocked', { stage: paperStageLabel(t, run.current_stage) }) : t('paperAgent.pdf.renderExport')}
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
          <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
            <span>{t('paperAgent.pdf.editInSource')}</span>
            <select
              value={sourceSection}
              onChange={(event) => setSourceSection(event.target.value)}
              className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm transition focus:border-sky-300 focus:outline-none focus:ring-4 focus:ring-sky-500/20"
              aria-label={t('paperAgent.pdf.sectionSelectAria')}
            >
              {sectionOptions.map((section) => (
                <option key={section.value} value={section.value}>
                  {section.label}
                  {section.generated ? '' : ` (${t('paperAgent.pdf.notGeneratedOption')})`}
                </option>
              ))}
            </select>
          </label>
          <Button variant="secondary" size="sm" className="gap-2" onClick={handleEditInSource}>
            <FileCode2 className="h-4 w-4" />
            {t('paperAgent.pdf.editInSource')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending}
          >
            {downloadMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {t('paperAgent.pdf.downloadBundle')}
          </Button>
        </div>
      </div>
      {downloadMutation.error ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {downloadMutation.error instanceof Error ? downloadMutation.error.message : String(downloadMutation.error)} (
          {bundlePath})
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
            disabled={pipelineBlocksRender || renderExportMutation.isPending}
          >
            {renderExportMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {pipelineBlocksRender ? t('paperAgent.pdf.pipelineBlocked', { stage: paperStageLabel(t, run.current_stage) }) : t('paperAgent.pdf.rerenderExport')}
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
            sectionName={pdfSelection?.sectionName ?? sourceSection}
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
