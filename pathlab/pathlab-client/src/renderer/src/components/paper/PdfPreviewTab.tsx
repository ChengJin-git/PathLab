import { useMutation, useQuery } from '@tanstack/react-query'
import { BookOpen, Download, Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { downloadPaperExport, getPaperFileBlob, getPaperFileUrl, type PaperRunDetail } from '../../api/papers'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'

interface PdfPreviewTabProps {
  paperId: string
  run: PaperRunDetail
}

export function PdfPreviewTab({ paperId, run }: PdfPreviewTabProps) {
  const template = run.selected_templates[0] ?? 'miccai'
  const pdfPath = `final/${template}/main.pdf`
  const bundlePath = `exports/${template}_bundle.zip`

  const pdfQuery = useQuery({
    queryKey: ['paper-file', paperId, pdfPath, 'exists'],
    queryFn: () => getPaperFileBlob(paperId, pdfPath),
    retry: false,
  })

  const downloadMutation = useMutation({
    mutationFn: () => downloadPaperExport(paperId, template),
  })

  const isMissing = pdfQuery.error instanceof ApiError && pdfQuery.error.isNotFound()

  if (pdfQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Checking PDF...</div>
  }

  if (isMissing) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-12 text-center">
          <BookOpen className="mx-auto h-9 w-9 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Compile pending</div>
          <p className="mt-1 text-sm text-slate-500">{pdfPath} is not available yet. Rendering/exporting will publish the PDF.</p>
        </CardContent>
      </Card>
    )
  }

  if (pdfQuery.error) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{pdfQuery.error instanceof Error ? pdfQuery.error.message : String(pdfQuery.error)}</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">PDF preview</h2>
          <p className="text-sm text-slate-500">Template: {template}. Source: {pdfPath}</p>
        </div>
        <Button variant="outline" size="sm" className="gap-2" onClick={() => downloadMutation.mutate()} disabled={downloadMutation.isPending}>
          {downloadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Download bundle
        </Button>
      </div>
      {downloadMutation.error ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {downloadMutation.error instanceof Error ? downloadMutation.error.message : String(downloadMutation.error)} ({bundlePath})
        </div>
      ) : null}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-inner">
        <iframe title="Paper PDF preview" src={getPaperFileUrl(paperId, pdfPath)} className="h-[72vh] w-full bg-white" />
      </div>
    </div>
  )
}
