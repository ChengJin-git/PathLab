import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Braces, CheckCircle2, Loader2, PlayCircle } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getPaperFileJson, putPaperOutline, type OutlineDocument, type PaperRunDetail } from '../../api/papers'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { paperStageLabel } from '../../lib/paperI18n'

interface OutlineTabProps {
  paperId: string
  run: PaperRunDetail
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateOutlineDocument(value: unknown): value is OutlineDocument {
  if (!isRecord(value)) return false
  return (
    Array.isArray(value.plotting_plan) &&
    Array.isArray(value.macro_lit_search) &&
    Array.isArray(value.micro_lit_clusters) &&
    Array.isArray(value.section_plan) &&
    isRecord(value.pathlab_extensions)
  )
}

function artifactUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  if (error.isNotFound()) return true
  const detail = error.details || error.message
  return error.status === 403 && detail.includes('Artifact is not registered public')
}

function JsonNode({
  name,
  value,
  depth = 0,
  emptyLabel,
  nullLabel,
}: {
  name?: string
  value: unknown
  depth?: number
  emptyLabel: string
  nullLabel: string
}) {
  const paddingLeft = `${depth * 14}px`

  if (Array.isArray(value)) {
    return (
      <div style={{ paddingLeft }} className="py-1">
        <div className="font-mono text-xs text-slate-500">
          {name ? <span className="font-semibold text-slate-700">{name}: </span> : null}[{value.length}]
        </div>
        <div className="mt-1 border-l border-slate-200">
          {value.length ? value.map((item, index) => <JsonNode key={index} name={String(index)} value={item} depth={depth + 1} emptyLabel={emptyLabel} nullLabel={nullLabel} />) : <div className="pl-4 text-xs text-slate-400">{emptyLabel}</div>}
        </div>
      </div>
    )
  }

  if (isRecord(value)) {
    const entries = Object.entries(value)
    return (
      <div style={{ paddingLeft }} className="py-1">
        <div className="font-mono text-xs text-slate-500">
          {name ? <span className="font-semibold text-slate-700">{name}: </span> : null}{'{'}{entries.length}{'}'}
        </div>
        <div className="mt-1 border-l border-slate-200">
          {entries.map(([key, item]) => <JsonNode key={key} name={key} value={item} depth={depth + 1} emptyLabel={emptyLabel} nullLabel={nullLabel} />)}
        </div>
      </div>
    )
  }

  return (
    <div style={{ paddingLeft }} className="grid grid-cols-[minmax(80px,180px)_1fr] gap-3 py-1 font-mono text-xs">
      <span className="truncate font-semibold text-slate-600">{name}</span>
      <span className="break-words text-slate-900">{value === null ? nullLabel : JSON.stringify(value)}</span>
    </div>
  )
}

const POST_OUTLINE_STAGES = new Set([
  'plotting',
  'literature_review',
  'section_writing',
  'validating',
  'refining',
  'rendering',
  'exporting',
])

export function OutlineTab({ paperId, run }: OutlineTabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const outlineQuery = useQuery({
    queryKey: ['paper-file', paperId, 'drafts/outline.json'],
    queryFn: () => getPaperFileJson<OutlineDocument>(paperId, 'drafts/outline.json'),
    retry: false,
  })
  const approveMutation = useMutation({
    mutationFn: () => {
      if (!outlineQuery.data) throw new Error(t('paperAgent.outline.notLoadedError'))
      return putPaperOutline(paperId, { outline: outlineQuery.data, approve: true })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      await queryClient.invalidateQueries({ queryKey: ['paper-file', paperId, 'drafts/outline.json'] })
    },
  })

  const validation = useMemo(() => validateOutlineDocument(outlineQuery.data), [outlineQuery.data])
  const isMissing = artifactUnavailable(outlineQuery.error)
  const awaitingApproval = run.status === 'awaiting_outline_approval'
  const continuingAfterOutline = run.status === 'running' && POST_OUTLINE_STAGES.has(run.current_stage)

  if (outlineQuery.isLoading) {
    return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {t('paperAgent.outline.loading')}</div>
  }

  if (isMissing) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <Braces className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">{t('paperAgent.outline.emptyTitle')}</div>
          <p className="mt-1 text-sm text-slate-500">{t('paperAgent.outline.emptyDescription')}</p>
        </CardContent>
      </Card>
    )
  }

  if (outlineQuery.error) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{outlineQuery.error instanceof Error ? outlineQuery.error.message : String(outlineQuery.error)}</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">{t('paperAgent.outline.title')}</h2>
          <p className="text-sm text-slate-500">{t('paperAgent.outline.description')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {awaitingApproval ? <Badge variant="secondary">{t('paperAgent.outline.awaitingApproval')}</Badge> : null}
          {continuingAfterOutline ? <Badge variant="secondary">{t('paperAgent.outline.continuing', { stage: paperStageLabel(t, run.current_stage) })}</Badge> : null}
          {validation ? <Badge variant="secondary">OutlineDocument</Badge> : <Badge variant="destructive">{t('paperAgent.outline.schemaMismatch')}</Badge>}
        </div>
      </div>

      {awaitingApproval ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="flex min-w-0 items-start gap-2">
            <PlayCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">{t('paperAgent.outline.readyTitle')}</div>
              <div className="mt-0.5 text-amber-800">
                {t('paperAgent.outline.readyDescription')}
              </div>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            className="gap-2 bg-amber-900 text-white hover:bg-amber-950"
            onClick={() => approveMutation.mutate()}
            disabled={!validation || approveMutation.isPending}
          >
            {approveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {t('paperAgent.outline.approve')}
          </Button>
        </div>
      ) : null}

      {continuingAfterOutline ? (
        <div className="flex items-start gap-2 rounded-2xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
          {t('paperAgent.outline.postOutlineRunning')}
        </div>
      ) : null}

      {approveMutation.error ? (
        <div className="flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {approveMutation.error instanceof Error ? approveMutation.error.message : String(approveMutation.error)}
        </div>
      ) : null}

      {!validation ? (
        <div className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {t('paperAgent.outline.invalidSchema')}
        </div>
      ) : null}

      <div className="max-h-[68vh] overflow-auto rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
        <JsonNode value={outlineQuery.data} emptyLabel={t('paperAgent.common.empty')} nullLabel={t('paperAgent.common.null')} />
      </div>
    </div>
  )
}
