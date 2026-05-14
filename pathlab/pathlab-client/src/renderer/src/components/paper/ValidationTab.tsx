import { AlertCircle, ArrowRight, CheckCircle2, MinusCircle, ShieldCheck, Sparkles } from 'lucide-react'
import { getPaperFileUrl, type GuardIssueSummary, type GuardResultSummary, type PaperRunDetail, type ValidationSummary } from '../../api/papers'
import { Badge } from '../ui/badge'
import { Card, CardContent } from '../ui/card'

interface ValidationTabProps {
  paperId: string
  run: PaperRunDetail
  validationSummary: ValidationSummary | null
}

const EXPECTED_GUARDS = ['metric', 'identifier', 'latex', 'citation', 'claim', 'consistency']

function normalizeGuardName(value: string): string {
  return value.replace(/_guard$/, '').replace(/-/g, '_')
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase()
  if (['passed', 'pass', 'ok', 'success'].includes(normalized)) return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (['failed', 'fail', 'error'].includes(normalized)) return 'border-red-200 bg-red-50 text-red-700'
  if (['warning', 'warnings'].includes(normalized)) return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-slate-200 bg-slate-50 text-slate-500'
}

function statusIcon(status: string) {
  const normalized = status.toLowerCase()
  if (['passed', 'pass', 'ok', 'success'].includes(normalized)) return <CheckCircle2 className="h-4 w-4" />
  if (['failed', 'fail', 'error'].includes(normalized)) return <AlertCircle className="h-4 w-4" />
  return <MinusCircle className="h-4 w-4" />
}

function scoreLabel(value: unknown): string {
  if (typeof value === 'number') return value.toFixed(1)
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    if (typeof record.total === 'number') return record.total.toFixed(1)
    if (typeof record.overall === 'number') return record.overall.toFixed(1)
    return JSON.stringify(record)
  }
  return '-'
}

function guardMap(summary: ValidationSummary | null): Map<string, GuardResultSummary> {
  const map = new Map<string, GuardResultSummary>()
  for (const guard of summary?.m10_guards ?? []) {
    map.set(normalizeGuardName(guard.guard), guard)
  }
  return map
}

function isFailingGuard(guard: GuardResultSummary | undefined): boolean {
  if (!guard) return false
  return guard.status.toLowerCase() === 'fail' || guard.error_count > 0
}

function collectSampleIssues(guards: GuardResultSummary[]): GuardIssueSummary[] {
  return guards.flatMap((guard) => guard.sample_issues ?? []).slice(0, 6)
}

function nextActionText(run: PaperRunDetail, hasBlockingIssues: boolean, hasRefinement: boolean): string {
  if (!hasBlockingIssues) return 'All deterministic checks passed; the pipeline can render and export the PDF.'
  if (run.status === 'running' || run.current_stage === 'refining') {
    return 'Auto-refinement will use these guard reports as feedback and revise the draft before rendering.'
  }
  if (hasRefinement) {
    return 'Review the refinement result below. If issues remain, edit or regenerate the affected section.'
  }
  return 'The system should continue into refinement. If this run is stopped, rerun from Refinement or regenerate the affected section.'
}

export function ValidationTab({ paperId, run, validationSummary }: ValidationTabProps) {
  const guards = guardMap(validationSummary)
  const warningPath = validationSummary?.warnings_md_path || 'validation/warnings.md'
  const refinement = validationSummary?.refinement ?? null
  const guardNames = Array.from(new Set([...EXPECTED_GUARDS, ...guards.keys()]))
  const failingGuards = guardNames
    .map((name) => guards.get(name))
    .filter((guard): guard is GuardResultSummary => isFailingGuard(guard))
  const blockingIssueCount = failingGuards.reduce((sum, guard) => sum + guard.error_count, 0)
  const hasBlockingIssues = blockingIssueCount > 0
  const sampleIssues = collectSampleIssues(failingGuards)

  if (!validationSummary) {
    return (
      <Card className="border-dashed border-slate-200 bg-slate-50/70">
        <CardContent className="py-10 text-center">
          <ShieldCheck className="mx-auto h-8 w-8 text-slate-300" />
          <div className="mt-3 font-semibold text-slate-800">Validation not generated yet</div>
          <p className="mt-1 text-sm text-slate-500">The validating stage will populate guard summaries and warnings.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-950">Validation summary</h2>
          <p className="text-sm text-slate-500">M10 guard cards plus M11 refinement score.</p>
        </div>
        <a
          href={getPaperFileUrl(paperId, warningPath)}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-950"
        >
          Open warnings.md
        </a>
      </div>

      <div
        className={[
          'rounded-2xl border p-4 text-sm shadow-sm',
          hasBlockingIssues
            ? 'border-amber-200 bg-amber-50 text-amber-900'
            : 'border-emerald-200 bg-emerald-50 text-emerald-900',
        ].join(' ')}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5">
            {hasBlockingIssues ? <AlertCircle className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">
              {hasBlockingIssues
                ? `Validation found ${blockingIssueCount} blocking issue${blockingIssueCount === 1 ? '' : 's'}`
                : 'Validation passed'}
            </div>
            <div className="mt-1 flex items-start gap-2">
              <ArrowRight className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{nextActionText(run, hasBlockingIssues, Boolean(refinement))}</span>
            </div>
            {sampleIssues.length ? (
              <div className="mt-3 grid gap-2">
                {sampleIssues.map((issue, index) => (
                  <div key={`${issue.code}-${index}`} className="rounded-xl bg-white/70 p-3">
                    <div className="font-semibold">{issue.code}</div>
                    <div className="mt-0.5">{issue.message}</div>
                    <div className="mt-1 text-xs opacity-80">
                      {[issue.path, issue.context].filter(Boolean).join(' · ')}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          {hasBlockingIssues ? (
            <div className="hidden items-center gap-1 rounded-full border border-amber-200 bg-white/70 px-2.5 py-1 text-xs font-semibold sm:flex">
              <Sparkles className="h-3.5 w-3.5" />
              Refinement feedback
            </div>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
        {guardNames.map((name) => {
          const guard = guards.get(name)
          const status = guard?.status ?? 'not_run'
          const guardFailed = isFailingGuard(guard)
          return (
            <div key={name} className={`rounded-2xl border p-4 ${statusTone(status)}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 font-semibold capitalize">
                    {statusIcon(status)}
                    {name.replace(/_/g, ' ')}
                  </div>
                  <div className="mt-1 text-xs opacity-80">{guard?.path ?? 'validation summary'}</div>
                </div>
                <Badge variant={guardFailed ? 'destructive' : status === 'not_run' ? 'outline' : 'secondary'}>{status}</Badge>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.issue_count ?? 0}</div><div>issues</div></div>
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.error_count ?? 0}</div><div>errors</div></div>
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.warning_count ?? 0}</div><div>warns</div></div>
              </div>
              {guard?.sample_issues?.length ? (
                <div className="mt-3 space-y-2">
                  {guard.sample_issues.slice(0, 3).map((issue, index) => (
                    <div key={`${issue.code}-${index}`} className="rounded-xl bg-white/70 p-2 text-xs leading-5">
                      <span className="font-semibold">{issue.code}</span>: {issue.message}
                      {issue.path || issue.context ? (
                        <div className="mt-1 opacity-75">{[issue.path, issue.context].filter(Boolean).join(' · ')}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <Card className="bg-slate-950 text-white">
          <CardContent className="p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Hybrid score</div>
            <div className="mt-2 text-4xl font-black tracking-[-0.08em]">{validationSummary.hybrid_score ?? '-'}</div>
            <p className="mt-3 text-sm text-slate-300">Guard failures force rejection; accepted refinement keeps score monotonic.</p>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-white">
          <CardContent className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Refinement</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{refinement?.final_status ?? 'not run'}</div>
              </div>
              <Badge variant="outline">{refinement?.iteration_count ?? 0} iterations</Badge>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-slate-50 p-3 text-sm"><div className="text-slate-500">Accepted</div><div className="font-semibold text-slate-950">{refinement?.accepted_iterations?.join(', ') || '-'}</div></div>
              <div className="rounded-2xl bg-slate-50 p-3 text-sm"><div className="text-slate-500">Initial</div><div className="font-semibold text-slate-950">{scoreLabel(refinement?.initial_score)}</div></div>
              <div className="rounded-2xl bg-slate-50 p-3 text-sm"><div className="text-slate-500">Final</div><div className="font-semibold text-slate-950">{scoreLabel(refinement?.final_score)}</div></div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
