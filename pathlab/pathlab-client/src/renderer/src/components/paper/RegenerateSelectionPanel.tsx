import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { AlertTriangle, Loader2, RotateCcw, Sparkles, X } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  getPaperSections,
  getRegenerateJob,
  postRegenerateCancel,
  postRegenerateReject,
  postSectionRegenerate,
  type PaperSectionListResponse,
  type RegenerateJobEntry,
  type TemplateId,
} from '../../api/papers'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { DiffPreview } from './DiffPreview'
import { RegenerateProgressBar } from './RegenerateProgressBar'
import { labelForSection } from './SectionsTab'
import { paperRegenerateStatusLabel } from '../../lib/paperI18n'

export interface SelectionInfo {
  text: string
  source?: 'source' | 'pdf'
  paragraphIndex?: number
  charStart?: number
  charEnd?: number
}

interface RegenerateSelectionPanelProps {
  paperId: string
  sectionName: string
  templateId?: TemplateId
  selection: SelectionInfo | null
  onClear: () => void
  onPdfRefreshNeeded: () => void
}

const POLLING_STATUSES = new Set<RegenerateJobEntry['status']>(['queued', 'running', 'cancelling'])

const FRIENDLY_ERROR_CODES = new Set([
  'stale_selection',
  'stale_reject',
  'selection_not_found',
  'ambiguous_selection',
  'selection_too_short',
])

function extractBackendCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  if (FRIENDLY_ERROR_CODES.has(error.code)) return error.code

  const rawDetails = (error as ApiError & { details?: unknown }).details
  if (!rawDetails) return null
  if (typeof rawDetails === 'object' && rawDetails !== null && 'code' in rawDetails) {
    const code = (rawDetails as { code?: unknown }).code
    return typeof code === 'string' ? code : null
  }
  if (typeof rawDetails !== 'string') return null

  try {
    const parsed = JSON.parse(rawDetails) as { code?: unknown }
    return typeof parsed.code === 'string' ? parsed.code : null
  } catch {
    return null
  }
}

function errorMessage(error: unknown, t: TFunction): string {
  const code = extractBackendCode(error)
  if (code && FRIENDLY_ERROR_CODES.has(code)) return t(`paperAgent.regenerate.errors.${code}`)
  return error instanceof Error ? error.message : String(error)
}

function jobErrorMessage(job: RegenerateJobEntry, t: TFunction): string {
  const code = job.error_code ?? ''
  if (FRIENDLY_ERROR_CODES.has(code)) return t(`paperAgent.regenerate.errors.${code}`)
  return job.error_message || t('paperAgent.regenerate.fallbackJobError')
}

function previewSelection(text: string): string {
  return text.length > 280 ? `${text.slice(0, 280)}...` : text
}

export function RegenerateSelectionPanel({
  paperId,
  sectionName,
  templateId,
  selection,
  onClear,
  onPdfRefreshNeeded,
}: RegenerateSelectionPanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')
  const [regenId, setRegenId] = useState<string | null>(null)
  const [rejectError, setRejectError] = useState<unknown>(null)
  const selectionSignature = selection
    ? `${sectionName}:${selection.source ?? 'source'}:${selection.charStart ?? 'pdf'}:${selection.charEnd ?? 'pdf'}:${selection.text.length}:${selection.text.slice(0, 120)}`
    : 'none'
  const isPdfSelection =
    selection?.source === 'pdf' || selection?.charStart === undefined || selection?.charEnd === undefined

  const jobQuery = useQuery({
    queryKey: ['paper-regenerate-job', paperId, regenId],
    queryFn: () => getRegenerateJob(paperId, regenId || ''),
    enabled: Boolean(regenId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && POLLING_STATUSES.has(status) ? 1500 : false
    },
  })

  const job = jobQuery.data
  const isPolling = Boolean(job?.status && POLLING_STATUSES.has(job.status))
  const isSubmittingOrPolling = isPolling || jobQuery.isLoading

  const startMutation = useMutation({
    mutationFn: async () => {
      if (!selection) throw new Error(t('paperAgent.regenerate.errors.selectFirst'))
      const cached = queryClient.getQueryData<PaperSectionListResponse>(['paper-sections', paperId])
      const sections = cached ?? (await getPaperSections(paperId))
      const section = sections.sections?.find((item) => item.section_name === sectionName)
      if (!section) throw new Error(t('paperAgent.regenerate.errors.sectionUnavailable', { section: labelForSection(sectionName, t) }))

      // For PDF-sourced selections we don't have precise char offsets; the
      // panel uses negative sentinels (-1) to signal "no hint, let backend
      // selection_locator do fuzzy match". Backend Pydantic schema requires
      // `ge=0` on char_start/char_end, so we must omit them instead of
      // sending the sentinel.
      const charStart = selection.charStart
      const charEnd = selection.charEnd
      const hasCharRange =
        typeof charStart === 'number' && typeof charEnd === 'number' && charStart >= 0 && charEnd >= 0
      return postSectionRegenerate(paperId, sectionName, {
        mode: 'selection',
        target_section: sectionName,
        target_paragraph: hasCharRange ? selection.paragraphIndex : undefined,
        selected_text: selection.text,
        source_hash: section.content_hash,
        char_start: hasCharRange ? charStart : undefined,
        char_end: hasCharRange ? charEnd : undefined,
        user_note: note.trim() || undefined,
        template_id: templateId,
      })
    },
    onMutate: () => {
      setRejectError(null)
      setRegenId(null)
    },
    onSuccess: (response) => {
      setRegenId(response.regen_id)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!regenId) throw new Error(t('paperAgent.regenerate.errors.noJobCancel'))
      return postRegenerateCancel(paperId, regenId)
    },
    onSuccess: () => {
      void jobQuery.refetch()
    },
  })

  const rejectMutation = useMutation({
    mutationFn: () => {
      if (!regenId) throw new Error(t('paperAgent.regenerate.errors.noJobReject'))
      return postRegenerateReject(paperId, regenId, 'Rejected from the Paper Agent workspace.', templateId)
    },
    onMutate: () => {
      setRejectError(null)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['paper-sections', paperId],
      })
      void queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
      onPdfRefreshNeeded()
      setNote('')
      setRegenId(null)
      setRejectError(null)
      startMutation.reset()
      cancelMutation.reset()
      onClear()
    },
    onError: (error) => {
      setRejectError(error)
      void queryClient.invalidateQueries({
        queryKey: ['paper-sections', paperId],
      })
    },
  })

  const currentError = rejectError ?? startMutation.error ?? cancelMutation.error ?? jobQuery.error

  const completedJob = job?.status === 'completed' ? job : null
  const failedJob = job?.status === 'failed' ? job : null
  const terminalState = job && ['rejected', 'cancelled'].includes(job.status) ? job.status : null
  const canSubmit = Boolean(selection) && !startMutation.isPending && !isSubmittingOrPolling && !completedJob

  const helperCopy = useMemo(() => {
    if (!selection) return t('paperAgent.regenerate.helperNoSelection')
    if (completedJob)
      return t('paperAgent.regenerate.helperCompleted')
    if (failedJob) return jobErrorMessage(failedJob, t)
    if (terminalState === 'cancelled') return t('paperAgent.regenerate.helperCancelled')
    if (terminalState === 'rejected') return t('paperAgent.regenerate.helperRejected')
    if (isSubmittingOrPolling)
      return t('paperAgent.regenerate.helperRunning')
    return t('paperAgent.regenerate.helperReady')
  }, [completedJob, failedJob, isSubmittingOrPolling, selection, t, terminalState])

  useEffect(() => {
    setRegenId(null)
    setRejectError(null)
    startMutation.reset()
    cancelMutation.reset()
    rejectMutation.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionSignature])

  const handleClear = () => {
    setNote('')
    setRegenId(null)
    setRejectError(null)
    startMutation.reset()
    cancelMutation.reset()
    rejectMutation.reset()
    onClear()
  }

  const handleRestart = () => {
    setRegenId(null)
    setRejectError(null)
    startMutation.reset()
    cancelMutation.reset()
    rejectMutation.reset()
  }

  const handleAccept = () => {
    void queryClient.invalidateQueries({
      queryKey: ['paper-sections', paperId],
    })
    void queryClient.invalidateQueries({ queryKey: ['paper-run', paperId] })
    onPdfRefreshNeeded()
    handleClear()
  }

  return (
    <Card className="border-slate-200 bg-white/95 shadow-sm xl:sticky xl:top-4">
      <CardHeader className="border-b border-slate-100 pb-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{t('paperAgent.regenerate.title')}</div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-4 w-4 text-sky-500" />
              {labelForSection(sectionName, t)}
            </CardTitle>
          </div>
          {selection ? (
            <Button variant="ghost" size="icon" aria-label={t('paperAgent.regenerate.clearSelection')} onClick={handleClear}>
              <X className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 py-4">
        {selection ? (
          <>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {isPdfSelection ? (
                  <Badge variant="outline" className="bg-amber-50 text-amber-700">
                    {t('paperAgent.regenerate.fromPdf')}
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-sky-50 text-sky-700">
                    {t('paperAgent.regenerate.paragraph', { index: selection.paragraphIndex })}
                  </Badge>
                )}
                <span className="text-slate-400">{t('paperAgent.regenerate.chars', { count: selection.text.length })}</span>
                {!isPdfSelection ? (
                  <span className="text-slate-300">
                    {selection.charStart}-{selection.charEnd}
                  </span>
                ) : null}
              </div>
              <div className="max-h-32 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 p-3 text-xs italic leading-5 text-slate-600">
                "{previewSelection(selection.text)}"
              </div>
              {isPdfSelection ? (
                <div className="rounded-xl border border-amber-100 bg-amber-50/80 p-2 text-xs leading-5 text-amber-800">
                  {t('paperAgent.regenerate.pdfResolve')}
                </div>
              ) : null}
              <p className="text-xs leading-5 text-slate-500">{helperCopy}</p>
            </div>

            {!regenId ? (
              <>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    {t('paperAgent.regenerate.noteLabel')}
                  </span>
                  <textarea
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder={t('paperAgent.regenerate.notePlaceholder')}
                    rows={4}
                    className="mt-1 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
                  />
                </label>

                <Button className="w-full gap-2" onClick={() => startMutation.mutate()} disabled={!canSubmit}>
                  {startMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  {startMutation.isPending ? t('paperAgent.regenerate.queueing') : t('paperAgent.regenerate.regenerateSelection')}
                </Button>
              </>
            ) : null}

            {regenId && (isPolling || jobQuery.isLoading || job?.status === 'completed') ? (
              <RegenerateProgressBar progress={job?.progress} status={job?.status} />
            ) : null}

            {isPolling ? (
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2"
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending || job?.status === 'cancelling'}
              >
                {cancelMutation.isPending || job?.status === 'cancelling' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <X className="h-4 w-4" />
                )}
                {job?.status === 'cancelling' ? t('paperAgent.regenerate.cancelling') : t('paperAgent.regenerate.cancelRegenerate')}
              </Button>
            ) : null}

            {completedJob ? (
              <div className="space-y-3">
                <DiffPreview
                  paperId={paperId}
                  beforePath={completedJob.before_path}
                  afterPath={completedJob.after_path}
                  diffSummary={completedJob.diff_summary}
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <Button className="gap-2" onClick={handleAccept}>
                    {t('paperAgent.regenerate.acceptCandidate')}
                  </Button>
                  <Button
                    variant="outline"
                    className="gap-2 border-red-200 text-red-700 hover:border-red-300 hover:text-red-800"
                    onClick={() => rejectMutation.mutate()}
                    disabled={rejectMutation.isPending}
                  >
                    {rejectMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RotateCcw className="h-4 w-4" />
                    )}
                    {t('paperAgent.regenerate.rejectRestore')}
                  </Button>
                </div>
              </div>
            ) : null}

            {failedJob || terminalState ? (
              <div className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <div className="font-semibold">
                      {failedJob
                        ? t('paperAgent.regenerate.failed')
                        : t('paperAgent.regenerate.jobStatus', { status: paperRegenerateStatusLabel(t, terminalState) })}
                    </div>
                    <div className="text-xs leading-5">{failedJob ? jobErrorMessage(failedJob, t) : helperCopy}</div>
                  </div>
                </div>
                <Button variant="outline" size="sm" className="w-full bg-white" onClick={handleRestart}>
                  {t('paperAgent.regenerate.restart')}
                </Button>
              </div>
            ) : null}

            {currentError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700">
                {errorMessage(currentError, t)}
              </div>
            ) : null}
          </>
        ) : (
          <div className="space-y-4 py-3">
            <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                <Sparkles className="h-5 w-5" />
              </div>
              <p className="text-sm font-semibold text-slate-800">{t('paperAgent.regenerate.emptyTitle')}</p>
              <p className="text-xs leading-5 text-slate-500">
                {t('paperAgent.regenerate.emptyDescription')}
              </p>
            </div>
            <div className="grid gap-2 text-xs leading-5 text-slate-500">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  1
                </span>
                <span>{t('paperAgent.regenerate.step1')}</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  2
                </span>
                <span>{t('paperAgent.regenerate.step2')}</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  3
                </span>
                <span>{t('paperAgent.regenerate.step3')}</span>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
