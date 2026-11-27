import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWorkbenchText } from '../components/chat/workbenchText'
import { useTranslation } from 'react-i18next'
import { dataTypeLabel } from '../lib/dataTypeLabel'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Activity,
  ArrowLeft,
  ArrowUp,
  ChevronDown,
  Clock3,
  Download,
  FileText,
  Loader2,
  Pause,
  Play,
  Square,
  Terminal,
} from 'lucide-react'
import {
  downloadAutoResearchSession,
  downloadResearchFile,
  getAutoResearchSession,
  pauseResearch,
  resumeAutoResearchSession,
  sendResearchMessage,
  stopAutoResearchSession
} from '../api/autoresearch'
import { useSessionStream } from '../components/autoresearch/useSessionStream'
import { RunDetails } from '../components/autoresearch/RunDetails'
import { useResearchText } from '../components/autoresearch/researchText'
import type {
  AutoResearchEvent,
  AutoResearchSessionDetail,
  ResearchArtifact,
  ResearchDataset,
  ResearchReportRevision
} from '../types/autoresearch'
import {
  ExperimentComparison,
  JobProgress
} from '../components/autoresearch/ResearchResults'
import ResearchQuestion, {
  type ResearchForm
} from '../components/autoresearch/ResearchQuestion'
import ResearchOutline, { ResearchQueueNotice, type ResearchStep } from '../components/autoresearch/ResearchOutline'
import { researchPlanState, researchStepKey } from '../components/autoresearch/researchPlan'
import ResearchRecoveryPanel from '../components/autoresearch/ResearchRecoveryPanel'
import ResearchRefinementPanel from '../components/autoresearch/ResearchRefinementPanel'
import { researchStatus } from '../components/autoresearch/researchState'
import { notifyAutoResearchSessionCreated } from '../lib/autoresearchSessionEvents'
import ResearchTimeline from '../components/autoresearch/ResearchTimeline'
import ResearchSideQuestion from '../components/autoresearch/ResearchSideQuestion'
import { isTimelineEvent, mergeResearchEvents } from '../components/autoresearch/researchActivity'
import { researchActivity } from '../api/workbench'
import { Button } from '../components/ui/button'
import ResearchFilePreview, { researchFilePath } from '../components/autoresearch/ResearchFilePreview'
import { formatAutoResearchElapsed } from '../lib/autoresearchTime'

const liveStatuses = new Set([
  'queued',
  'preparing',
  'running',
  'waiting',
  'pausing',
  'stopping'
])
const prose =
  'prose prose-sm max-w-none break-words prose-pre:max-h-80 prose-pre:overflow-auto prose-a:text-blue-600'

function Markdown({ children, onOpenFile, workspacePath }: { children: string; onOpenFile?: (path: string) => void; workspacePath?: string }) {
  return (
    <div className={prose}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({href, children}) => {
        const path = researchFilePath(href, workspacePath);
        return path && onOpenFile ? <button type="button" className="text-primary-700 underline underline-offset-2" onClick={() => onOpenFile(path)}>{children}</button>
          : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
      } }}>{children}</ReactMarkdown>
    </div>
  )
}

export default function AutoResearchSessionPage() {
  const { id } = useParams<{ id: string }>()
  return <ResearchSession key={id} id={id} />
}

function ResearchSession({ id }: { id?: string }) {
  const workbenchText = useWorkbenchText()
  const { t, i18n } = useTranslation()
  const { text, status } = useResearchText()
  const [session, setSession] = useState<AutoResearchSessionDetail>()
  const [error, setError] = useState('')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState('')
  const [sentNotice, setSentNotice] = useState(false)
  const [selectedTab, setTab] = useState('activity')
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  const [retainedActivity, setRetainedActivity] = useState<AutoResearchEvent[]>([])
  const [before, setBefore] = useState<number | null>(null)
  const [preview, setPreview] = useState<string>()
  const [sideQuestion, setSideQuestion] = useState<{sequence?:number;version:number}|null>(null)
  const askAbout = (sequence?:number) => setSideQuestion(previous=>({sequence,version:(previous?.version||0)+1}))
  const activityRef = useRef<HTMLDivElement>(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const follow = useRef(true)
  const stream = useSessionStream(id, !!session && liveStatuses.has(session.status), session?.sequence || 0)
  const refresh = useCallback(async () => {
    if (id) {
      const value = await getAutoResearchSession(id)
      if (!mounted.current) return
      setSession(value)
      notifyAutoResearchSessionCreated(value)
    }
  }, [id])
  useEffect(() => {
    let active = true
    const load = () =>
      id &&
      getAutoResearchSession(id)
        .then((value) => {
          if (active) setSession(value)
        })
        .catch((e) => {
          if (active) {
            setSession(undefined)
            setError(String(e))
          }
        })
    setSession(undefined)
    setSelectedStep(null)
    setTab('activity')
    setError('')
    void load()
    return () => {
      active = false
    }
  }, [id])
  const events = useMemo(() => {
    const map = new Map<number, AutoResearchEvent>()
    for (const event of [...(session?.events || []), ...stream.events])
      if (event.seq) map.set(event.seq, event)
    return [...map.values()].sort((a, b) => (a.seq || 0) - (b.seq || 0))
  }, [session?.events, stream.events])
  useEffect(() => {
    setRetainedActivity(previous => mergeResearchEvents(previous, session?.activity || [], stream.events.filter(isTimelineEvent)))
  }, [session?.activity, stream.events])
  const activity = useMemo(() => mergeResearchEvents(retainedActivity, session?.activity || [], stream.events), [retainedActivity, session?.activity, stream.events])
  useEffect(() => {
    if (follow.current && activityRef.current)
      activityRef.current.scrollTop = activityRef.current.scrollHeight
  }, [activity])
  const state = session?.state || {}
  const linkedReport = state.manuscript_id || state.report_generation_id || state.report_draft_id
  const reportUrl = linkedReport ? `/reports?report=${encodeURIComponent(String(linkedReport))}` : `/reports?source_type=research&source_id=${encodeURIComponent(id || '')}`
  const reportHistory = (state.report_history || []) as ResearchReportRevision[]
  const freshEvents = events.filter(e => (e.seq || 0) > (session?.sequence || 0))
  const planEvent = [...freshEvents].reverse().find((e) => e.kind === 'plan')
  const plan = (planEvent?.steps || state.plan || []) as ResearchStep[]
  const highlightedStep = plan.find(step => researchStepKey(step) === selectedStep)
  const stepIndex = highlightedStep ? plan.indexOf(highlightedStep) : -1
  const hasStepActivity = !!highlightedStep?.id && activity.some(event => event.step_id === highlightedStep.id)
  const visibleActivity = highlightedStep?.id
    ? activity.filter(event => event.step_id === highlightedStep.id)
    : activity
  const datasets = (state.datasets || []) as ResearchDataset[]
  const forms = ([...freshEvents].reverse().find((e) => e.kind === 'forms')?.forms ||
    state.forms ||
    []) as ResearchForm[]
  const artifacts = useMemo(() => {
    const map = new Map<string, ResearchArtifact>()
    for (const a of [
      ...(session?.jobs || []).flatMap((j) => j.result.artifacts || []),
      ...((state.artifacts || []) as ResearchArtifact[])
    ])
      map.set(a.path, a)
    return [...map.values()]
  }, [state.artifacts, session?.jobs])
  const currentStatus = researchStatus(session, events)
  const recoverable = ['blocked', 'failed', 'interrupted', 'paused'].includes(currentStatus)
  const live = liveStatuses.has(currentStatus)
  // The event stream carries live activity; jobs, runs and state are re-read only while the
  // session is live, plus once when it settles.
  const polling = !!session && live
  const wasPolling = useRef(false)
  useEffect(() => {
    const poll = () => {
      if (id) void getAutoResearchSession(id).then((value) => { if (mounted.current) setSession(value) }).catch(() => undefined)
    }
    if (wasPolling.current && !polling) poll()
    wasPolling.current = polling
    if (!polling) return
    const timer = setInterval(poll, 10000)
    return () => clearInterval(timer)
  }, [id, polling])
  const planState = researchPlanState(plan, currentStatus)
  const currentStep = planState.active[0]
  const hasExperiments = !!session?.experiments?.length
  const allowExperiments = session?.task_kind === 'experiment' || hasExperiments
  const hasData = datasets.length > 0 || session?.jobs?.some(job => job.kind === 'download')
  const tabs = [
    ['activity', text.details], ['overview', text.report], ['artifacts', text.artifacts],
    ...(hasData ? [['data', text.data]] : []),
    ...(allowExperiments ? [['runs', text.runs]] : []),
    ...(session?.jobs?.length ? [['logs', text.rawLog]] : []),
  ]
  const tab = tabs.some(([key]) => key === selectedTab) ? selectedTab : 'activity'
  const elapsed = formatAutoResearchElapsed(session?.created_at,
    live ? Date.now() : (session?.updated_at || Date.now() / 1000) * 1000, i18n.language)
  const selectStep = (key: string) => {
    follow.current = false
    setSelectedStep(previous => previous === key ? null : key)
    setTab('activity')
  }

  async function action(name: string, fn: () => Promise<unknown>) {
    setBusy(name)
    setError('')
    try {
      await fn()
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }
  async function send() {
    if (!id || !input.trim()) return
    const value = input
    await action('send', async () => {
       await sendResearchMessage(id, value)
       setInput('')
       setSentNotice(true)
    })
  }
  const showFile = (path: string) => setPreview(path)

  return (
    <div className="flex min-h-[75vh] flex-col gap-4">
      <header className="rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center gap-3 p-4 sm:gap-4 sm:p-5">
        {session?.chat_conversation_id && (
          <Button asChild variant="ghost" size="icon" className="shrink-0">
            <Link
              to={`/dashboard/${encodeURIComponent(session.chat_conversation_id)}`}
              aria-label={workbenchText('returnToChat')}
              title={workbenchText('returnToChat')}
            >
              <ArrowLeft size={18} aria-hidden="true" />
            </Link>
          </Button>
        )}
        <div className="min-w-0 flex-1 basis-64">
          <p className="mb-1 text-xs font-medium text-slate-500">{workbenchText('details')}</p>
          <h1
            className="line-clamp-2 max-w-4xl break-words text-lg font-semibold leading-7 tracking-tight text-slate-950 sm:text-xl"
            title={session?.title || session?.question}
          >
            {session?.title || text.loading}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 ${currentStatus === 'failed' ? 'bg-red-50 text-red-700' : currentStatus === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-primary-50 text-primary-700'}`}
            >
              {live && <Loader2 size={12} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />}
              {status(currentStatus)}
            </span>
            {elapsed && <span className="inline-flex items-center gap-1.5 tabular-nums"><Clock3 size={12} aria-hidden="true" />{text.elapsed} {elapsed}</span>}
            <span>
              {!live ? text.saved : stream.status === 'open' ? text.synced : text.reconnecting}
            </span>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {currentStatus === 'completed' && session?.experiments?.some(run => run.status === 'completed') && <Button asChild variant="outline" size="sm" className="gap-2"><Link to={reportUrl}><FileText size={15} />{t('reports.open')}</Link></Button>}
          <Button type="button" variant="ghost" size="icon" disabled={!!busy || !session} title={text.bundle}
            onClick={() =>
              id &&
              void action('download', () => downloadAutoResearchSession(id))
            }
            aria-label={text.bundle}
          >
            <Download size={17} />
          </Button>
          {live && (
            <Button type="button" variant="outline" size="sm" className="gap-2"
              disabled={!!busy}
              onClick={() =>
                id && void action('pause', () => pauseResearch(id))
              }
            >
              <Pause size={14} />
              {text.pause}
            </Button>
          )}
          {recoverable && (
            <Button type="button" size="sm" className="gap-2"
              disabled={!!busy}
              onClick={() =>
                id && void action('resume', () => resumeAutoResearchSession(id))
              }
            >
              <Play size={14} />
              {text.resume}
            </Button>
          )}
          {(live || ['paused', 'blocked'].includes(currentStatus)) && (
            <Button type="button" variant="ghost" size="sm" className="gap-2 text-red-700 hover:bg-red-50 hover:text-red-800"
              disabled={!!busy}
              onClick={() =>
                id && void action('stop', () => stopAutoResearchSession(id))
              }
            >
              <Square size={13} />
              {text.stop}
            </Button>
          )}
        </div>
      </div>
      {currentStep && <div data-testid="research-current-work" className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-[color:var(--surface-border)] px-5 py-3 text-xs sm:px-6">
        <span className="shrink-0 text-slate-500">{text.currentWork}</span>
        <span className="min-w-0 flex-1 basis-40 truncate text-sm font-medium text-slate-700" title={currentStep.title}>{currentStep.title}</span>
        {planState.active.length > 1 && <span className="shrink-0 text-slate-500">{text.parallelSteps.replace('{count}', String(planState.active.length))}</span>}
      </div>}
      </header>
      {live && (!!state.budget_shutdown || events.some(event => event.kind === 'budget_checkpoint' && Number(event.seq) > (session?.sequence || 0))) && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{t('reports.budgetSaving')}</div>}
      {recoverable && !!state.report_draft_id && <Link to={reportUrl} className="inline-flex items-center gap-2 text-sm font-medium text-blue-700"><FileText size={15} />{t('reports.openDraft')}</Link>}
      {currentStatus === 'queued' && <ResearchQueueNotice queue={session?.queue} />}
      {session?.jobs?.filter(job => job.status === 'queued' && job.payload.device === 'gpu').slice(0, 1).map(job => <JobProgress key={job.job_id} job={job} events={events} />)}
      {recoverable && id && <ResearchRecoveryPanel key={id} sessionId={id} recovery={session?.recovery || (session?.error ? { reason: 'other', detail: session.error } : null)} workspaceId={state.workspace_id as string | undefined} onContinued={refresh} />}
      {currentStatus === 'completed' && ['partial', 'no_result'].includes(session?.outcome || '') && <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">{session?.outcome === 'partial' ? text.partialOutcome : text.noResultOutcome}</div>}
      {error && (
        <div
          role="alert"
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}
      {currentStatus === 'paused' && (
        <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {text.pausedHint}
        </div>
      )}
      <div className="grid min-h-0 flex-1 items-start gap-4 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)] xl:gap-5">
        <ResearchOutline plan={plan} selected={selectedStep} onSelect={selectStep} status={currentStatus} completedRuns={session?.experiments?.filter(run => run.status === 'completed').length || 0} totalRuns={session?.experiments?.length || 0} />
        <div className="min-w-0 space-y-3" data-testid="research-details">
          <div role="tablist" aria-label={workbenchText('details')} className="flex gap-1 overflow-x-auto rounded-full border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] p-1">
            {tabs.map(([key, label]) => <Button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} variant={tab === key ? 'default' : 'ghost'} size="sm" className="flex-1">{label}</Button>)}
          </div>
           {tab === 'activity' && session?.question && <details className="rounded-2xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] px-4 py-3 text-sm"><summary className="cursor-pointer font-medium text-slate-700">{text.goal}</summary><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">{session.current_goal || session.question}</p></details>}
           {highlightedStep && tab === 'activity' && <div className="rounded-2xl border border-primary-100 bg-primary-50/50 px-5 py-3"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-primary-700">{text.stepDetails} {String(stepIndex + 1).padStart(2, '0')}</span><Button type="button" variant="ghost" size="sm" onClick={() => { setSelectedStep(null); follow.current = true }}>{text.allActivity}</Button></div><h2 className="mt-2 text-sm font-semibold text-slate-900">{highlightedStep.title}</h2>{highlightedStep.summary && <p className="mt-2 text-xs leading-6 text-slate-600">{highlightedStep.summary}</p>}{!hasStepActivity && <p className="mt-2 text-xs leading-6 text-slate-500">{text.noStepActivity}</p>}</div>}
        {tab === 'activity' && <section className="flex min-h-[32rem] flex-col overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)]">
          <h2 className="flex items-center gap-2 border-b border-[color:var(--surface-border)] px-5 py-4 text-sm font-semibold">
            <Activity size={16} />
            {text.activity}
            <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={()=>askAbout()}>{workbenchText('sideQuestion')}</Button>
          </h2>
          <div
            ref={activityRef}
            onScroll={(e) => {
              const el = e.currentTarget
              follow.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 80
            }}
            className="max-h-[65vh] min-h-80 flex-1 space-y-4 overflow-y-auto p-5"
          >
            {!visibleActivity.length && !highlightedStep && (
              <div className="flex items-center gap-2 py-8 text-sm text-gray-500">
                <Loader2 size={16} className="animate-spin" />
                {text.noActivity}
              </div>
            )}
            {(before ?? session?.activity_before ?? 0) > 0 && <Button type="button" variant="ghost" size="sm" disabled={!!busy} onClick={() => void action('history', async () => {
              const page = await researchActivity(id!, before ?? session?.activity_before ?? 0)
              follow.current = false
              setRetainedActivity(previous => mergeResearchEvents(page.items, previous))
              setBefore(page.next_before ?? 0)
            })}>{workbenchText('older')}</Button>}
            <ResearchTimeline events={visibleActivity} running={live} onAsk={askAbout} renderProse={value => <Markdown onOpenFile={showFile} workspacePath={session?.workspace_path}>{value}</Markdown>} />
            {id && <ResearchSideQuestion sessionId={id} selection={sideQuestion} onClose={()=>setSideQuestion(null)}/>}
          </div>
          {id && forms.length > 0 && (
            <div className="space-y-3 border-t border-[color:var(--surface-border)] p-3">
              {forms.map((form) => (
                <ResearchQuestion key={form.id} sessionId={id} form={form} />
              ))}
            </div>
          )}
        </section>}
        {tab !== 'activity' && <section className="min-w-0 overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)]">
          <div
            role="tabpanel"
            className="max-h-[75vh] space-y-6 overflow-auto p-5"
          >
            {tab === 'overview' && (
              <>
                <section>
                  <h2 className="mb-3 text-sm font-semibold">{text.report}</h2>
                  {session?.experiments?.some(run => run.status === 'completed') && <Button asChild variant="outline" size="sm" className="mb-4 gap-2"><Link to={reportUrl}><FileText size={15} />{t('reports.open')}</Link></Button>}
                  {state.report ? (
                    <Markdown onOpenFile={showFile} workspacePath={session?.workspace_path}>{String(state.report)}</Markdown>
                  ) : (
                    <p className="text-sm text-gray-500">{text.noReport}</p>
                  )}
                </section>
                {reportHistory.length > 0 && <section className="space-y-3 border-t border-[color:var(--surface-border)] pt-5">
                  <h2 className="text-sm font-semibold">{t('autoResearch.refinement.previousReports')}</h2>
                  {reportHistory.map((revision, index) => <details key={revision.saved_at} className="rounded-2xl border border-[color:var(--surface-border)] p-3">
                    <summary className="cursor-pointer text-xs text-gray-600">{t('autoResearch.refinement.revision', { number: index + 1 })} · {new Date(revision.saved_at * 1000).toLocaleString(i18n.language)}</summary>
                    <div className="mt-3"><Markdown onOpenFile={showFile} workspacePath={session?.workspace_path}>{revision.report}</Markdown></div>
                  </details>)}
                </section>}
              </>
            )}
            {tab === 'logs' && <section><h2 className="mb-4 flex items-center gap-2 text-sm font-semibold"><Terminal size={16} />{text.rawLog}</h2>{!session?.jobs?.length && <p className="text-sm text-gray-500">{text.noLog}</p>}<div className="space-y-2">{session?.jobs?.map(job => <Button key={job.job_id} type="button" variant="outline" onClick={() => void showFile(job.kind === 'download' ? `downloads/${job.job_id}.log` : `runs/${job.job_id}/run.log`)} className="h-auto w-full gap-3 rounded-2xl p-3 text-left text-xs"><Terminal size={15} /><span className="min-w-0 flex-1 truncate">{String(job.payload.name || job.job_id)}</span><span className="text-slate-500">{status(job.status)}</span><ChevronDown size={14} /></Button>)}</div></section>}
            {tab === 'data' && (
              <>
                <div className="space-y-3">
                  {datasets.map((d) => (
                    <article
                      key={d.dataset_id}
                      className="rounded-2xl border border-[color:var(--surface-border)] p-4"
                    >
                      <h3 className="text-sm font-semibold">{d.name}</h3>
                      <p className="mt-2 text-xs text-gray-500">
                        {dataTypeLabel(t, d.data_type)} · {d.file_count} {text.files}
                      </p>
                      <p className="mt-2 break-words text-xs text-gray-600">
                        {d.feature_extractors?.join(' · ')}
                      </p>
                      {d.manifest_path && (
                        <Button type="button" variant="link" size="sm" className="mt-3"
                          onClick={() =>
                            void showFile(
                              `datasets/${d.dataset_id}/manifest.json`
                            )
                          }
                        >
                          {text.preview}
                        </Button>
                      )}
                    </article>
                  ))}
                </div>
                {session?.jobs
                  ?.filter((j) => j.kind === 'download')
                  .map((j) => (
                    <article key={j.job_id} className="rounded-2xl border border-[color:var(--surface-border)] p-4">
                      <h3 className="text-sm font-medium">
                        {text.publicData} · {status(j.status)}
                      </h3>
                      <JobProgress job={j} events={events} />
                      <details className="mt-3 text-xs text-gray-600"><summary className="cursor-pointer">{text.details} / {text.rawLog}</summary><pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 font-mono text-[11px] leading-5">{JSON.stringify(j.result, null, 2)}</pre></details>
                    </article>
                  ))}
              </>
            )}
            {tab === 'runs' && (
              <>
                <ExperimentComparison
                  experiments={session?.experiments || []}
                />
                {!session?.experiments?.length && (
                  <p className="text-sm text-gray-500">{text.noRuns}</p>
                )}
                {session?.experiments?.map((run) => (
                  <article key={run.run_id} className="rounded-2xl border border-[color:var(--surface-border)] p-4">
                     <div className="flex flex-wrap justify-between gap-3">
                      <h3 className="text-sm font-semibold">
                        {run.iteration}. {run.experiment_name}
                      </h3>
                      <span className="text-xs text-gray-500">
                        {status(run.status)}
                      </span>
                    </div>
                    {session.jobs
                      ?.filter((j) => j.job_id === run.run_id)
                      .map((j) => (
                        <JobProgress key={j.job_id} job={j} events={events} />
                      ))}
                    <div className="mt-4 grid grid-cols-2 gap-2">
                      {Object.entries(run.metrics || {})
                        .filter(([, value]) => typeof value === 'number')
                        .slice(0, 8)
                        .map(([key, value]) => (
                          <div key={key} className="rounded-lg bg-gray-50 p-3">
                            <span className="break-all text-xs text-gray-500">
                              {key}
                            </span>
                            <strong className="mt-1 block font-mono text-lg">
                              {value.toFixed(4)}
                            </strong>
                          </div>
                        ))}
                    </div>
                    <RunDetails sessionId={id!} run={run} label={`${text.config} / ${text.metric}`} />
                    <Button type="button" variant="link" size="sm"
                      onClick={() =>
                        void showFile(`runs/${run.run_id}/run.log`)
                      }
                      className="mt-3 gap-1"
                    >
                      <Terminal size={13} />
                      {text.logs}
                    </Button>
                  </article>
                ))}
              </>
            )}
            {tab === 'artifacts' && (
              <>
                {!artifacts.length && (
                  <p className="text-sm text-gray-500">{text.noArtifacts}</p>
                )}
                {artifacts.map((a) => (
                  <article
                    key={a.path}
                    className="flex items-center gap-3 rounded-2xl border border-[color:var(--surface-border)] p-3"
                  >
                    <FileText size={19} className="shrink-0 text-gray-400" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{a.name}</p>
                      <p className="truncate text-xs text-gray-500">{a.path}</p>
                    </div>
                    <Button type="button" variant="ghost" size="icon"
                      onClick={() => void showFile(a.path)}
                      aria-label={`${text.preview} ${a.name}`}
                    >
                      <FileText size={15} />
                    </Button>
                    <Button type="button" variant="ghost" size="icon"
                      onClick={() =>
                        id &&
                        void action('download', () =>
                          downloadResearchFile(id, a.path)
                        )
                      }
                      aria-label={`${text.download} ${a.name}`}
                    >
                      <Download size={15} />
                    </Button>
                  </article>
                ))}
              </>
            )}
          </div>
        </section>}
        {currentStatus === 'completed' && id && <ResearchRefinementPanel
          key={id}
          sessionId={id}
          experiments={session?.experiments || []}
          remainingExperiments={Math.max(0, (session?.max_iterations || 0) - (session?.current_iteration || 0))}
          maxExperiments={session?.max_iterations || 0}
          allowExperiments={allowExperiments}
          onContinued={refresh}
        />}
        {(live || currentStatus === 'paused') && <form onSubmit={e => { e.preventDefault(); void send() }} className="rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] p-4 shadow-[var(--shadow-soft)]">
          <label className="mb-2 block text-xs font-semibold text-gray-700" htmlFor="research-steer">{text.instruction}</label>
          <div className="flex items-end gap-2"><textarea id="research-steer" value={input} onChange={e => { setInput(e.target.value); setSentNotice(false) }} rows={2} maxLength={20000} placeholder={text.steerHint} className="min-w-0 flex-1 resize-none rounded-2xl border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-base)] p-3 text-sm leading-6 outline-none focus:border-primary-300 focus:ring-4 focus:ring-primary-500/10" /><Button type="submit" size="icon" disabled={!input.trim() || !!busy} aria-label={text.send}>{busy === 'send' ? <Loader2 size={18} className="animate-spin" /> : <ArrowUp size={18} />}</Button></div>
          <p role={sentNotice ? 'status' : undefined} className="mt-2 text-xs leading-5 text-gray-500">{sentNotice ? text.instructionQueued : text.steerDelivery}</p>
        </form>}
        </div>
      </div>
      {preview && id && <ResearchFilePreview key={`${id}:${preview}`} sessionId={id} path={preview} workspaceId={state.workspace_id as string | undefined} onClose={() => setPreview(undefined)} />}
    </div>
  )
}
