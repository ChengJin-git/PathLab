import { AlertCircle, CheckCircle2, MinusCircle, ShieldCheck } from 'lucide-react'
import { getPaperFileUrl, type GuardResultSummary, type ValidationSummary } from '../../api/papers'
import { Badge } from '../ui/badge'
import { Card, CardContent } from '../ui/card'

interface ValidationTabProps {
  paperId: string
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

export function ValidationTab({ paperId, validationSummary }: ValidationTabProps) {
  const guards = guardMap(validationSummary)
  const warningPath = validationSummary?.warnings_md_path || 'validation/warnings.md'
  const refinement = validationSummary?.refinement ?? null
  const guardNames = Array.from(new Set([...EXPECTED_GUARDS, ...guards.keys()]))

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

      <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
        {guardNames.map((name) => {
          const guard = guards.get(name)
          const status = guard?.status ?? 'not_run'
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
                <Badge variant={status === 'failed' ? 'destructive' : status === 'not_run' ? 'outline' : 'secondary'}>{status}</Badge>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.issue_count ?? 0}</div><div>issues</div></div>
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.error_count ?? 0}</div><div>errors</div></div>
                <div className="rounded-xl bg-white/60 px-2 py-2"><div className="font-semibold">{guard?.warning_count ?? 0}</div><div>warns</div></div>
              </div>
              {guard?.sample_issues?.length ? (
                <div className="mt-3 space-y-2">
                  {guard.sample_issues.slice(0, 2).map((issue, index) => (
                    <div key={`${issue.code}-${index}`} className="rounded-xl bg-white/70 p-2 text-xs leading-5">
                      <span className="font-semibold">{issue.code}</span>: {issue.message}
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
