import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Loader2 } from 'lucide-react'
import { continueResearch } from '../../api/autoresearch'
import type { ResearchExperiment } from '../../types/autoresearch'
import { Select } from '../ui/select'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { useResearchText } from './researchText'

interface ResearchRefinementPanelProps {
  sessionId: string
  experiments: ResearchExperiment[]
  remainingExperiments: number
  maxExperiments: number
  allowExperiments: boolean
  onContinued: () => Promise<void>
}

export default function ResearchRefinementPanel({
  sessionId,
  experiments,
  remainingExperiments,
  maxExperiments,
  allowExperiments,
  onContinued
}: ResearchRefinementPanelProps) {
  const { t } = useTranslation()
  const { text } = useResearchText()
  const [baseline, setBaseline] = useState('')
  const [instructions, setInstructions] = useState('')
  const [additionalExperiments, setAdditionalExperiments] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const completedRuns = experiments.filter((run) => run.status === 'completed')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !instructions.trim()) return
    setBusy(true)
    setError('')
    try {
      await continueResearch(sessionId, {
        text: instructions.trim(),
        ...(allowExperiments ? {
          baseline_run_id: baseline || undefined,
          additional_experiments: additionalExperiments,
        } : {})
      })
      await onContinued()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label={allowExperiments ? t('autoResearch.refinement.title') : text.continueTask}
      className="space-y-4 rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] p-5"
    >
      <div>
        <h2 className="text-sm font-semibold text-gray-900">
          {allowExperiments ? t('autoResearch.refinement.title') : text.continueTask}
        </h2>
        <p className="mt-2 text-xs leading-6 text-gray-500">
          {allowExperiments ? t('autoResearch.refinement.description') : text.continueTaskHint}
        </p>
      </div>
      {allowExperiments && <label className="block text-xs font-medium text-gray-700">
        {t('autoResearch.refinement.baseline')}
        <Select
          ariaLabel={t('autoResearch.refinement.baseline')}
          value={baseline}
          onChange={setBaseline}
          disabled={busy}
          className="mt-2"
          options={[{value:'',label:t('autoResearch.refinement.findings')},...completedRuns.map(run=>({value:run.run_id,label:`${run.iteration}. ${run.experiment_name}`}))]}
        />
      </label>}
      <label className="block text-xs font-medium text-gray-700">
        {allowExperiments ? t('autoResearch.refinement.instructions') : text.followupLabel}
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          disabled={busy}
          required
          maxLength={12000}
          rows={3}
          placeholder={allowExperiments ? t('autoResearch.refinement.placeholder') : text.followupPlaceholder}
          className="mt-2 w-full rounded-2xl border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-base)] p-3 text-sm leading-6 outline-none focus:border-primary-300 focus:ring-4 focus:ring-primary-500/10"
        />
      </label>
      <div className="flex flex-wrap items-end justify-between gap-4">
        {allowExperiments && <label className="text-xs font-medium text-gray-700">
          {t('autoResearch.refinement.extraExperiments')}
          <Input
            type="number"
            min={0}
            max={Math.max(0, Math.min(20, 100 - maxExperiments))}
            value={additionalExperiments}
            disabled={busy}
            onChange={(e) => setAdditionalExperiments(Number(e.target.value))}
            className="ml-3 inline-flex w-20"
          />
          <span className="mt-2 block font-normal leading-5 text-gray-500">
            {t('autoResearch.refinement.budget', {
              count: remainingExperiments + additionalExperiments
            })}
          </span>
        </label>}
        <Button type="submit"
          disabled={busy || !instructions.trim()}
          className="ml-auto gap-2"
        >
          {busy ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ArrowRight size={16} />
          )}
          {allowExperiments ? t('autoResearch.refinement.submit') : text.continueTask}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
    </form>
  )
}
