import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, Download, FileCode2, Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  downloadPaperExport,
  getPaperFileBlob,
  getPaperFileUrl,
  getPaperSections,
  type PaperSectionListResponse,
  type PaperRunDetail,
} from '../../api/papers'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { SECTION_ORDER, labelForSection } from './SectionsTab'

interface PdfPreviewTabProps {
  paperId: string
  run: PaperRunDetail
  pdfRefreshKey: number
}

function cacheBustedUrl(url: string, key: number): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}v=${key}`
}

export function PdfPreviewTab({ paperId, run, pdfRefreshKey }: PdfPreviewTabProps) {
  const [, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [sourceSection, setSourceSection] = useState<string>('abstract')
  const template = run.selected_templates[0] ?? 'miccai'
  const pdfPath = `final/${template}/main.pdf`
  const bundlePath = `exports/${template}_bundle.zip`

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
        label: labelForSection(section),
        generated: generatedSectionNames.has(section),
      })),
    [generatedSectionNames],
  )

  const pdfQuery = useQuery({
    queryKey: ['paper-file', paperId, pdfPath, 'exists', pdfRefreshKey],
    queryFn: () => getPaperFileBlob(paperId, pdfPath),
    retry: false,
  })

  const downloadMutation = useMutation({
    mutationFn: () => downloadPaperExport(paperId, template),
  })

  const isMissing = pdfQuery.error instanceof ApiError && pdfQuery.error.isNotFound()

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

  if (pdfQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Checking PDF...
      </div>
    )
  }

  if (isMissing) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-12 text-center">
          <BookOpen className="mx-auto h-9 w-9 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Compile pending</div>
          <p className="mt-1 text-sm text-slate-500">
            {pdfPath} is not available yet. Rendering/exporting will publish the PDF.
          </p>
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
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">PDF preview</h2>
          <p className="text-sm text-slate-500">
            Template: {template}. Source: {pdfPath}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
            <span>Edit in source:</span>
            <select
              value={sourceSection}
              onChange={(event) => setSourceSection(event.target.value)}
              className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm transition focus:border-sky-300 focus:outline-none focus:ring-4 focus:ring-sky-500/20"
              aria-label="Section to edit in source"
            >
              {sectionOptions.map((section) => (
                <option key={section.value} value={section.value}>
                  {section.label}
                  {section.generated ? '' : ' (not generated)'}
                </option>
              ))}
            </select>
          </label>
          <Button variant="secondary" size="sm" className="gap-2" onClick={handleEditInSource}>
            <FileCode2 className="h-4 w-4" />
            Edit in source
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending}
          >
            {downloadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Download bundle
          </Button>
        </div>
      </div>
      {downloadMutation.error ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {downloadMutation.error instanceof Error ? downloadMutation.error.message : String(downloadMutation.error)} (
          {bundlePath})
        </div>
      ) : null}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-inner">
        <iframe
          key={pdfRefreshKey}
          title="Paper PDF preview"
          src={cacheBustedUrl(getPaperFileUrl(paperId, pdfPath), pdfRefreshKey)}
          className="h-[72vh] w-full bg-white"
        />
      </div>
    </div>
  )
}
