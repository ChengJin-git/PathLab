import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

const FRIENDLY_ERROR_MESSAGES: Record<string, string> = {
  stale_selection: 'The section was edited by another regen. Refresh and try again.',
  stale_reject: 'Section moved on. Reject is no longer safe.',
  selection_not_found: "Couldn't match this selection to the source.",
  ambiguous_selection: 'This selection matches multiple paragraphs. Try selecting a longer span.',
  selection_too_short: 'Select at least ~20 characters.',
}

function extractBackendCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  if (FRIENDLY_ERROR_MESSAGES[error.code]) return error.code

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

function errorMessage(error: unknown): string {
  const code = extractBackendCode(error)
  if (code && FRIENDLY_ERROR_MESSAGES[code]) return FRIENDLY_ERROR_MESSAGES[code]
  return error instanceof Error ? error.message : String(error)
}

function jobErrorMessage(job: RegenerateJobEntry): string {
  const code = job.error_code ?? ''
  if (FRIENDLY_ERROR_MESSAGES[code]) return FRIENDLY_ERROR_MESSAGES[code]
  return job.error_message || 'Regenerate failed. Try again with a more precise selection.'
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
      if (!selection) throw new Error('Select source text before regenerating.')
      const cached = queryClient.getQueryData<PaperSectionListResponse>(['paper-sections', paperId])
      const sections = cached ?? (await getPaperSections(paperId))
      const section = sections.sections?.find((item) => item.section_name === sectionName)
      if (!section) throw new Error(`Section source is not available: ${sectionName}`)

      return postSectionRegenerate(paperId, sectionName, {
        mode: 'selection',
        target_section: sectionName,
        target_paragraph: selection.paragraphIndex,
        selected_text: selection.text,
        source_hash: section.content_hash,
        char_start: selection.charStart,
        char_end: selection.charEnd,
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
      if (!regenId) throw new Error('No regenerate job to cancel.')
      return postRegenerateCancel(paperId, regenId)
    },
    onSuccess: () => {
      void jobQuery.refetch()
    },
  })

  const rejectMutation = useMutation({
    mutationFn: () => {
      if (!regenId) throw new Error('No regenerate job to reject.')
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
    if (!selection) return 'Select any text on the left to regenerate just that span.'
    if (completedJob)
      return 'Review the backend diff. Accept keeps this candidate; reject restores the before snapshot.'
    if (failedJob) return jobErrorMessage(failedJob)
    if (terminalState === 'cancelled') return 'This regenerate job was cancelled and restored to the before snapshot.'
    if (terminalState === 'rejected') return 'This candidate was rejected and the previous section was restored.'
    if (isSubmittingOrPolling)
      return 'The backend is locating the selection, rewriting, guarding, refining, and recompiling.'
    return 'Add a short instruction, then regenerate only the selected span.'
  }, [completedJob, failedJob, isSubmittingOrPolling, selection, terminalState])

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
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Regenerate</div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-4 w-4 text-sky-500" />
              {sectionName}
            </CardTitle>
          </div>
          {selection ? (
            <Button variant="ghost" size="icon" aria-label="Clear selection" onClick={handleClear}>
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
                    from PDF
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-sky-50 text-sky-700">
                    paragraph {selection.paragraphIndex}
                  </Badge>
                )}
                <span className="text-slate-400">{selection.text.length} chars</span>
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
                  PDF selection: the backend will resolve the exact paragraph and character span before regenerating.
                </div>
              ) : null}
              <p className="text-xs leading-5 text-slate-500">{helperCopy}</p>
            </div>

            {!regenId ? (
              <>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Note (optional)
                  </span>
                  <textarea
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="What should change? e.g. shorten, remove an unsupported claim, or clarify the clinical caveat."
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
                  {startMutation.isPending ? 'Queueing...' : 'Regenerate selection'}
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
                {job?.status === 'cancelling' ? 'Cancelling...' : 'Cancel regenerate'}
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
                    Accept candidate
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
                    Reject and restore
                  </Button>
                </div>
              </div>
            ) : null}

            {failedJob || terminalState ? (
              <div className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <div className="font-semibold">{failedJob ? 'Regenerate failed' : `Job ${terminalState}`}</div>
                    <div className="text-xs leading-5">{failedJob ? jobErrorMessage(failedJob) : helperCopy}</div>
                  </div>
                </div>
                <Button variant="outline" size="sm" className="w-full bg-white" onClick={handleRestart}>
                  Restart with this selection
                </Button>
              </div>
            ) : null}

            {currentError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700">
                {errorMessage(currentError)}
              </div>
            ) : null}
          </>
        ) : (
          <div className="space-y-4 py-3">
            <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                <Sparkles className="h-5 w-5" />
              </div>
              <p className="text-sm font-semibold text-slate-800">Pick a span to rewrite</p>
              <p className="text-xs leading-5 text-slate-500">
                Highlight a sentence or paragraph on the left, optionally add a note, and the model rewrites just that
                span.
              </p>
            </div>
            <div className="grid gap-2 text-xs leading-5 text-slate-500">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  1
                </span>
                <span>Select text in the PDF or LaTeX source.</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  2
                </span>
                <span>Add an optional note describing what should change.</span>
              </div>
              <div className="flex items-start gap-2">
                <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                  3
                </span>
                <span>Review the diff, then accept or revert. Other paragraphs stay locked.</span>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
