import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { AlertCircle, ArrowLeft, Check, Loader2, Search, X } from 'lucide-react'
import { ApiError } from '../../api/client'
import {
  postCitation,
  type AddCitationMode,
  type AddCitationPreview,
  type AddCitationRequest,
  type ManualCitationFields,
} from '../../api/papers'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { ModalShell } from '../ui/modal-shell'

interface AddCitationModalProps {
  paperId: string
  isOpen: boolean
  onClose: () => void
  onDuplicate?: (key: string) => void
  onAdded?: (key: string) => void
}

const EMPTY_MANUAL: ManualCitationFields = {
  title: '',
  authors: [],
  year: null,
  venue: null,
  doi: null,
  arxiv_id: null,
  url: null,
  entry_type: null,
  booktitle: null,
  journal: null,
}

type PreviewState = AddCitationPreview | null

export function AddCitationModal({ paperId, isOpen, onClose, onDuplicate, onAdded }: AddCitationModalProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [pasteText, setPasteText] = useState('')
  const [required, setRequired] = useState(false)
  const [manual, setManual] = useState<ManualCitationFields>(EMPTY_MANUAL)
  const [manualTouched, setManualTouched] = useState(false)
  const [forcedManual, setForcedManual] = useState(false)
  const [preview, setPreview] = useState<PreviewState>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [duplicateKey, setDuplicateKey] = useState<string | null>(null)
  const detectedMode = useMemo(() => (forcedManual ? 'manual' : detectMode(pasteText)), [forcedManual, pasteText])

  useEffect(() => {
    if (!isOpen) {
      setPasteText('')
      setRequired(false)
      setManual(EMPTY_MANUAL)
      setManualTouched(false)
      setForcedManual(false)
      setPreview(null)
      setBanner(null)
      setDuplicateKey(null)
    }
  }, [isOpen])

  useEffect(() => {
    if (detectedMode === 'manual' && !manualTouched) {
      setManual((current) => ({ ...current, title: pasteText.trim() }))
    }
  }, [detectedMode, manualTouched, pasteText])

  const previewMutation = useMutation({
    mutationFn: () => postCitation(paperId, buildRequest(detectedMode, pasteText, manual, required, true)),
    onSuccess: (result) => {
      if ('proposed_key' in result) {
        setPreview(result)
        setBanner(null)
        setDuplicateKey(result.duplicate_of ?? null)
      }
    },
    onError: (error) => handleError(error, pasteText, setManual, setForcedManual, setBanner, setDuplicateKey, t),
  })

  const confirmMutation = useMutation({
    mutationFn: () => postCitation(paperId, buildRequest(detectedMode, pasteText, manual, required, false)),
    onSuccess: async (result) => {
      if ('key' in result) {
        await qc.invalidateQueries({ queryKey: ['paper-citations', paperId] })
        await qc.invalidateQueries({ queryKey: ['paper-run', paperId] })
        onAdded?.(result.key)
        onClose()
      }
    },
    onError: (error) => handleError(error, pasteText, setManual, setForcedManual, setBanner, setDuplicateKey, t),
  })

  const canPreview = detectedMode === 'manual' ? Boolean(manual.title.trim()) : Boolean(pasteText.trim())
  const busy = previewMutation.isPending || confirmMutation.isPending

  return (
    <ModalShell isOpen={isOpen} onClose={busy ? undefined : onClose} maxWidth="xl" title={t('paperAgent.addCitation.title')}>
      <div className="relative overflow-hidden bg-slate-950 text-white">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.22),transparent_36%),radial-gradient(circle_at_bottom_right,rgba(251,191,36,0.18),transparent_32%)]" />
        <div className="relative flex items-start justify-between gap-4 p-5">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-200">{t('paperAgent.addCitation.kicker')}</div>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{t('paperAgent.addCitation.title')}</h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">
              {t('paperAgent.addCitation.description')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-full border border-white/10 bg-white/10 p-2 text-white/80 transition hover:bg-white/20 disabled:opacity-50"
            aria-label={t('paperAgent.addCitation.closeAria')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {banner ? (
          <div className="flex items-start justify-between gap-3 rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <div className="flex items-start gap-2">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{banner}</span>
            </div>
            {duplicateKey ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 shrink-0"
                onClick={() => {
                  onDuplicate?.(duplicateKey)
                  onClose()
                }}
              >
                {t('paperAgent.addCitation.goExisting')}
              </Button>
            ) : null}
          </div>
        ) : null}

        {!preview ? (
          <>
            <label className="block">
              <span className="text-sm font-semibold text-slate-900">{t('paperAgent.addCitation.pasteLabel')}</span>
              <textarea
                value={pasteText}
                onChange={(event) => {
                  setPasteText(event.target.value)
                  setForcedManual(false)
                  setPreview(null)
                  setBanner(null)
                  setDuplicateKey(null)
                }}
                rows={5}
                placeholder="10.1038/s41591-021-01343-4"
                className="mt-2 min-h-[130px] w-full resize-y rounded-2xl border border-slate-200 bg-slate-50 p-3 font-mono text-sm text-slate-900 outline-none transition focus:border-teal-400 focus:bg-white focus:ring-4 focus:ring-teal-100"
              />
            </label>

            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={detectedMode === 'manual' ? 'outline' : 'secondary'}>
                {modeLabel(detectedMode, t)}
              </Badge>
              <label className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={required}
                  onChange={(event) => setRequired(event.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                />
                {t('paperAgent.addCitation.required')}
              </label>
            </div>

            {detectedMode === 'manual' ? (
              <ManualFields
                value={manual}
                t={t}
                onChange={(next) => {
                  setManualTouched(true)
                  setManual(next)
                }}
              />
            ) : null}

            <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                {t('paperAgent.common.cancel')}
              </Button>
              <Button
                type="button"
                className="gap-2"
                onClick={() => previewMutation.mutate()}
                disabled={!canPreview || busy}
              >
                {previewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {t('paperAgent.common.preview')}
              </Button>
            </div>
          </>
        ) : (
          <>
            <PreviewPane preview={preview} />
            <div className="flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-4">
              <Button
                type="button"
                variant="outline"
                className="gap-2"
                onClick={() => {
                  setPreview(null)
                  setBanner(null)
                }}
                disabled={busy}
              >
                <ArrowLeft className="h-4 w-4" />
                {t('paperAgent.common.back')}
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                  {t('paperAgent.common.cancel')}
                </Button>
                <Button type="button" className="gap-2" onClick={() => confirmMutation.mutate()} disabled={busy}>
                  {confirmMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  {t('paperAgent.common.confirmAdd')}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  )
}

function ManualFields({
  value,
  onChange,
  t,
}: {
  value: ManualCitationFields
  onChange: (value: ManualCitationFields) => void
  t: TFunction
}) {
  const authorsText = (value.authors ?? []).join(', ')
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4">
      <div className="mb-3 text-sm font-semibold text-amber-950">{t('paperAgent.addCitation.manualEntry')}</div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('paperAgent.addCitation.titleLabel')} className="sm:col-span-2">
          <input
            value={value.title}
            onChange={(event) => onChange({ ...value, title: event.target.value })}
            className={inputClassName}
            placeholder={t('paperAgent.addCitation.titlePlaceholder')}
          />
        </Field>
        <Field label={t('paperAgent.citations.meta.authors')}>
          <input
            value={authorsText}
            onChange={(event) =>
              onChange({
                ...value,
                authors: event.target.value.split(',').map((item) => item.trim()).filter(Boolean),
              })
            }
            className={inputClassName}
            placeholder={t('paperAgent.addCitation.authorsPlaceholder')}
          />
        </Field>
        <Field label={t('paperAgent.citations.meta.year')}>
          <input
            value={value.year ?? ''}
            onChange={(event) => onChange({ ...value, year: event.target.value ? Number(event.target.value) : null })}
            className={inputClassName}
            inputMode="numeric"
            placeholder="2024"
          />
        </Field>
        <Field label={t('paperAgent.citations.meta.venue')}>
          <input
            value={value.venue ?? ''}
            onChange={(event) => onChange({ ...value, venue: event.target.value || null })}
            className={inputClassName}
            placeholder={t('paperAgent.addCitation.venuePlaceholder')}
          />
        </Field>
        <Field label={t('paperAgent.addCitation.entryType')}>
          <select
            value={value.entry_type ?? ''}
            onChange={(event) =>
              onChange({ ...value, entry_type: (event.target.value || null) as ManualCitationFields['entry_type'] })
            }
            className={inputClassName}
          >
            <option value="">{t('paperAgent.addCitation.infer')}</option>
            <option value="article">{t('paperAgent.citations.types.article')}</option>
            <option value="inproceedings">{t('paperAgent.citations.types.inproceedings')}</option>
            <option value="misc">{t('paperAgent.citations.types.misc')}</option>
          </select>
        </Field>
        <Field label={t('paperAgent.citations.meta.doi')}>
          <input
            value={value.doi ?? ''}
            onChange={(event) => onChange({ ...value, doi: event.target.value || null })}
            className={inputClassName}
            placeholder="10.xxxx/..."
          />
        </Field>
        <Field label="arXiv ID">
          <input
            value={value.arxiv_id ?? ''}
            onChange={(event) => onChange({ ...value, arxiv_id: event.target.value || null })}
            className={inputClassName}
            placeholder="2401.01234"
          />
        </Field>
        <Field label={t('paperAgent.addCitation.journalLabel')}>
          <input
            value={value.journal ?? ''}
            onChange={(event) => onChange({ ...value, journal: event.target.value || null })}
            className={inputClassName}
            placeholder={t('paperAgent.addCitation.journalPlaceholder')}
          />
        </Field>
        <Field label={t('paperAgent.addCitation.booktitleLabel')}>
          <input
            value={value.booktitle ?? ''}
            onChange={(event) => onChange({ ...value, booktitle: event.target.value || null })}
            className={inputClassName}
            placeholder={t('paperAgent.addCitation.booktitlePlaceholder')}
          />
        </Field>
        <Field label="URL" className="sm:col-span-2">
          <input
            value={value.url ?? ''}
            onChange={(event) => onChange({ ...value, url: event.target.value || null })}
            className={inputClassName}
            placeholder="https://..."
          />
        </Field>
      </div>
    </div>
  )
}

function PreviewPane({ preview }: { preview: AddCitationPreview }) {
  const { t } = useTranslation()
  const ref = preview.ref
  return (
    <div className="rounded-3xl border border-teal-200 bg-gradient-to-br from-teal-50 to-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-700">{t('paperAgent.addCitation.previewTitle')}</div>
          <h3 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-slate-950">{ref.title}</h3>
        </div>
        <Badge variant="secondary">{preview.proposed_key}</Badge>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <Meta label={t('paperAgent.citations.meta.authors')} value={(ref.authors ?? []).join(', ')} />
        <Meta label={t('paperAgent.citations.meta.venue')} value={ref.venue ?? ref.journal ?? ref.booktitle ?? undefined} />
        <Meta label={t('paperAgent.citations.meta.year')} value={ref.year ? String(ref.year) : undefined} />
        <Meta label={t('paperAgent.citations.meta.doi')} value={ref.doi ?? undefined} />
        <Meta label={t('paperAgent.citations.meta.type')} value={ref.entry_type ? `@${ref.entry_type}` : undefined} />
        <Meta label={t('paperAgent.citations.meta.source')} value={ref.source} />
      </dl>
    </div>
  )
}

function Field({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <label className={className}>
      <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</span>
      {children}
    </label>
  )
}

function Meta({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-slate-900">{value || '—'}</dd>
    </div>
  )
}

const inputClassName =
  'h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-teal-400 focus:ring-4 focus:ring-teal-100'

function detectMode(value: string): AddCitationMode {
  const text = value.trim()
  if (/^10\.\d{4,9}\//i.test(text) || /doi\.org\/10\.\d{4,9}\//i.test(text)) return 'doi'
  if (/arxiv\.org/i.test(text) || /^\d{4}\.\d{4,5}(v\d+)?$/i.test(text)) return 'arxiv'
  if (/^@(article|inproceedings|misc|inbook|incollection|proceedings)\s*\{/i.test(text)) return 'bibtex'
  return 'manual'
}

function modeLabel(mode: AddCitationMode, t: TFunction): string {
  return t(`paperAgent.addCitation.modes.${mode}`)
}

function buildRequest(
  mode: AddCitationMode,
  pasteText: string,
  manual: ManualCitationFields,
  required: boolean,
  dryRun: boolean,
): AddCitationRequest {
  const trimmed = pasteText.trim()
  const base = { mode, required, dry_run: dryRun }
  if (mode === 'doi') return { ...base, doi: extractDoi(trimmed) ?? trimmed }
  if (mode === 'arxiv') return { ...base, arxiv_id_or_url: trimmed }
  if (mode === 'bibtex') return { ...base, bibtex_raw: trimmed }
  return { ...base, manual }
}

function extractDoi(value: string): string | null {
  const stripped = value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '')
  const match = stripped.match(/10\.\d{4,9}\/\S+/i)
  return match?.[0]?.replace(/[.,;]$/, '') ?? null
}

function handleError(
  error: unknown,
  pasteText: string,
  setManual: (value: ManualCitationFields) => void,
  setForcedManual: (value: boolean) => void,
  setBanner: (value: string | null) => void,
  setDuplicateKey: (value: string | null) => void,
  t: TFunction,
) {
  const apiError = error instanceof ApiError ? error : null
  const detail = parseDetails(apiError?.details)
  const code = detail?.code || apiError?.code
  if (code === 'duplicate') {
    const key = typeof detail?.duplicate_of === 'string' ? detail.duplicate_of : null
    setDuplicateKey(key)
    setBanner(key ? t('paperAgent.addCitation.errors.duplicateKnown', { key }) : t('paperAgent.addCitation.errors.duplicate'))
    return
  }
  if (code === 'fetch_failed') {
    setManual({ ...EMPTY_MANUAL, title: pasteText.trim() })
    setForcedManual(true)
    setBanner(t('paperAgent.addCitation.errors.fetchFailed'))
    return
  }
  if (code === 'phi_detected') {
    setBanner(t('paperAgent.addCitation.errors.phiDetected'))
    return
  }
  setBanner(apiError?.message || (error instanceof Error ? error.message : String(error)))
}

function parseDetails(details: string | undefined): Record<string, unknown> | null {
  if (!details) return null
  try {
    const parsed = JSON.parse(details)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}
