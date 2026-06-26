import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Image, Loader2, Maximize2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperFileJson, getPaperFileUrl, type FigureManifest, type FigureManifestItem } from '../../api/papers'
import { Badge } from '../ui/badge'
import { Card, CardContent } from '../ui/card'
import { ModalShell } from '../ui/modal-shell'
import { paperArtifactStatusLabel } from '../../lib/paperI18n'

interface FiguresTabProps {
  paperId: string
}

function isImagePath(path: string | null | undefined): boolean {
  return !!path && /\.(png|jpe?g|webp|gif|svg)$/i.test(path)
}

function isPdfPath(path: string | null | undefined): boolean {
  return !!path && /\.pdf$/i.test(path)
}

function badgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'ready' || status === 'user_provided') return 'secondary'
  if (status === 'missing' || status === 'failed' || status === 'requires_user_revision') return 'destructive'
  return 'outline'
}

function FigurePreview({ paperId, figure }: { paperId: string; figure: FigureManifestItem }) {
  const { t } = useTranslation()
  if (figure.path && isImagePath(figure.path)) {
    return <img src={getPaperFileUrl(paperId, figure.path)} alt={figure.figure_id} className="h-40 w-full rounded-xl object-cover" />
  }
  if (figure.path && isPdfPath(figure.path)) {
    return (
      <div className="flex h-40 w-full items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-semibold text-slate-500">
        {t('paperAgent.figures.pdfFigure')}
      </div>
    )
  }
  return (
    <div className="flex h-40 w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-400">
      {t('paperAgent.figures.noArtifact')}
    </div>
  )
}

export function FiguresTab({ paperId }: FiguresTabProps) {
  const { t } = useTranslation()
  const [selectedFigure, setSelectedFigure] = useState<FigureManifestItem | null>(null)
  const figuresQuery = useQuery({
    queryKey: ['paper-file', paperId, 'figures/manifest.json'],
    queryFn: () => getPaperFileJson<FigureManifest>(paperId, 'figures/manifest.json'),
    retry: false,
  })

  const isMissing = figuresQuery.error instanceof ApiError && figuresQuery.error.isNotFound()
  const figures = figuresQuery.data?.figures ?? []

  if (figuresQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.figures.loading')}</div>
  }

  if (isMissing || figures.length === 0) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Image className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.figures.emptyTitle')}</div>
          <p className="mt-1 text-sm text-slate-500">{t('paperAgent.figures.emptyDescription')}</p>
        </CardContent>
      </Card>
    )
  }

  if (figuresQuery.error) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{figuresQuery.error instanceof Error ? figuresQuery.error.message : String(figuresQuery.error)}</div>
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">{t('paperAgent.figures.title')}</h2>
        <p className="text-sm text-slate-500">{t('paperAgent.figures.description')}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        {figures.map((figure) => (
          <button
            key={figure.figure_id}
            type="button"
            onClick={() => setSelectedFigure(figure)}
            className="group rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
          >
            <FigurePreview paperId={paperId} figure={figure} />
            <div className="mt-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-950">{figure.figure_id}</div>
                <div className="mt-1 line-clamp-2 text-sm leading-5 text-slate-500">{figure.caption || figure.path || t('paperAgent.figures.noCaptionYet')}</div>
              </div>
              <Maximize2 className="mt-1 h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-slate-500" />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant={badgeVariant(figure.status)}>{paperArtifactStatusLabel(t, figure.status)}</Badge>
              {figure.kind ? <Badge variant="outline">{figure.kind}</Badge> : null}
            </div>
          </button>
        ))}
      </div>

      <ModalShell isOpen={!!selectedFigure} onClose={() => setSelectedFigure(null)} maxWidth="6xl" title={selectedFigure?.figure_id ?? t('paperAgent.figures.figureFallback')}>
        {selectedFigure ? (
          <div className="space-y-4 p-4 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-2xl font-semibold tracking-[-0.04em] text-slate-950">{selectedFigure.figure_id}</h3>
                <p className="mt-1 text-sm text-slate-500">{selectedFigure.path ?? t('paperAgent.figures.noGeneratedFile')}</p>
              </div>
              <Badge variant={badgeVariant(selectedFigure.status)}>{paperArtifactStatusLabel(t, selectedFigure.status)}</Badge>
            </div>
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
              {selectedFigure.path && isImagePath(selectedFigure.path) ? (
                <img src={getPaperFileUrl(paperId, selectedFigure.path)} alt={selectedFigure.figure_id} className="max-h-[70vh] w-full object-contain" />
              ) : selectedFigure.path && isPdfPath(selectedFigure.path) ? (
                <iframe title={selectedFigure.figure_id} src={getPaperFileUrl(paperId, selectedFigure.path)} className="h-[70vh] w-full bg-white" />
              ) : (
                <div className="p-10 text-center text-sm text-slate-500">{t('paperAgent.figures.noPreview')}</div>
              )}
            </div>
            <p className="text-sm leading-6 text-slate-700">{selectedFigure.caption || t('paperAgent.figures.noCaptionAvailable')}</p>
          </div>
        ) : null}
      </ModalShell>
    </div>
  )
}
