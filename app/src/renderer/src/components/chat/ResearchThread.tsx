import { Select } from '../ui/select';
import {
  lazy,
  memo,
  Suspense,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChevronRight, CircleHelp, Check, Loader2, Maximize2, MessageCircleQuestion, PanelRight, Pause, Play, Square, X } from "lucide-react";
import { Button } from "../ui/button";
import { SegmentedControl } from "../ui/workspace-primitives";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getAutoResearchSession,
  pauseResearch,
  resumeAutoResearchSession,
  stopAutoResearchSession,
} from "../../api/autoresearch";
import { researchActivity } from "../../api/workbench";
import { useSessionStream } from "../autoresearch/useSessionStream";
import {
  researchStatus,
} from "../autoresearch/researchState";
const ExperimentComparison = lazy(() =>
  import("../autoresearch/ResearchResults").then((module) => ({
    default: module.ExperimentComparison,
  })),
);
const JobProgress = lazy(() =>
  import("../autoresearch/ResearchResults").then((module) => ({
    default: module.JobProgress,
  })),
);
const AnalysisResultView = lazy(
  () => import("../autoresearch/AnalysisResultView"),
);
import ResearchOutline, {
  ResearchQueueNotice,
  type ResearchStep,
} from "../autoresearch/ResearchOutline";
import ResearchQuestion, {
  type ResearchForm,
} from "../autoresearch/ResearchQuestion";
import ResearchRecoveryPanel from "../autoresearch/ResearchRecoveryPanel";
import ResearchRefinementPanel from "../autoresearch/ResearchRefinementPanel";
import ResearchJobNotice from "../autoresearch/ResearchJobNotice";
import { useResearchText } from "../autoresearch/researchText";
import type {
  AutoResearchEvent,
  AutoResearchSessionSummary,
} from "../../types/autoresearch";
import { useWorkbenchText } from "./workbenchText";
import { useConversationFiles } from "./ConversationFiles";
import ResearchTimeline from '../autoresearch/ResearchTimeline';
import ResearchSideQuestion from '../autoresearch/ResearchSideQuestion';
import { isTimelineEvent, mergeResearchEvents } from '../autoresearch/researchActivity';

const live = new Set([
  "queued",
  "preparing",
  "running",
  "waiting",
  "pausing",
  "stopping",
]);
function Prose({
  children,
  sessionId,
  workspacePath,
}: {
  children: string;
  sessionId: string;
  workspacePath?: string;
}) {
  const files = useConversationFiles();
  return (
    <div className="prose prose-sm max-w-none break-words prose-pre:max-h-60 prose-pre:overflow-auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const local = href && !/^(?:[a-z]+:|\/\/|#)/i.test(href);
            let path = href || "";
            try {
              path = decodeURIComponent(path);
            } catch {
              /* Keep literal relative paths. */
            }
            if (workspacePath && path.startsWith(workspacePath + "/"))
              path = path.slice(workspacePath.length + 1);
            return local ? (
              <button
                className="text-blue-600 underline underline-offset-2"
                onClick={() => files?.openFile({ sessionId, path })}
              >
                {children}
              </button>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export const ResearchThread = memo(function ResearchThread({
  id,
  workspaceId,
  userId,
  onStatus,
  toolbarRoot,
  panelRoot,
}: {
  id: string;
  workspaceId?: string | null;
  userId: string;
  onStatus: (session: AutoResearchSessionSummary) => void;
  toolbarRoot: HTMLDivElement | null;
  panelRoot: HTMLDivElement | null;
}) {
  const text = useWorkbenchText();
  const files = useConversationFiles();
  const { text: researchText, status: statusLabel } = useResearchText();
  const [panel, setPanel] = useState(false);
  const panelId = useId();
  const detailsButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [tab, setTab] = useState("plan");
  const [selectedAnalysis, setSelectedAnalysis] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [older, setOlder] = useState<AutoResearchEvent[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [sideQuestion, setSideQuestion] = useState<{sequence?:number;version:number}|null>(null);
  const askAbout = (sequence?:number) => setSideQuestion(previous=>({sequence,version:(previous?.version||0)+1}));
  useEffect(()=>{
    const open=(event:Event)=>{if((event as CustomEvent<{sessionId:string}>).detail.sessionId===id)setSideQuestion(previous=>({version:(previous?.version||0)+1}));};
    window.addEventListener('workbench:research-question',open);
    return()=>window.removeEventListener('workbench:research-question',open);
  },[id]);
  useEffect(() => {
    if (files?.open) setPanel(false);
  }, [files?.open]);
  useEffect(() => {
    if (!panel) return;
    closeButton.current?.focus({ preventScroll: true });
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        setPanel(false);
        detailsButton.current?.focus({ preventScroll: true });
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [panel]);
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  const query = useQuery({
    queryKey: ["workbench-research", userId, id],
    queryFn: ({ signal }) => getAutoResearchSession(id, true, signal),
    staleTime: 5000,
    refetchInterval: (query) =>
      live.has(query.state.data?.status || "") ? 12000 : false,
    refetchIntervalInBackground: false,
  });
  const session = query.data;
  const stream = useSessionStream(
    id,
    !!session && live.has(session.status),
    session?.sequence || 0,
  );
  const status = researchStatus(session, stream.events);
  useEffect(() => {
    if (session) statusCallback.current({ ...session, status });
  }, [session, status]);
  useEffect(() => {
    if (session && status !== session.status) void query.refetch();
  }, [status]);
  const events = useMemo(
    () => mergeResearchEvents(older, session?.activity || [], stream.events),
    [older, session?.activity, stream.events],
  );
  useEffect(() => {
    setOlder(previous => mergeResearchEvents(previous, session?.activity || [], stream.events.filter(isTimelineEvent)));
  }, [session?.activity, stream.events]);
  const plan = (session?.state?.plan || []) as ResearchStep[];
  const planEvent = [...stream.events]
    .reverse()
    .find((e) => e.kind === "plan" && (e.seq || 0) > (session?.sequence || 0));
  const forms = (session?.state?.forms || []) as ResearchForm[];
  const analysisResults = (session?.state?.analysis_results || []) as {
    id: string;
    title: string;
    path: string;
    revision: string;
  }[];
  const activeAnalysis =
    analysisResults.find((result) => result.id === selectedAnalysis) ||
    analysisResults.at(-1);
  const artifacts = useMemo(() => {
    const unique = new Map<
      string,
      { path: string; name: string; kind?: string }
    >();
    const candidates = [
      ...((session?.state?.artifacts || []) as {
        path: string;
        name: string;
        kind?: string;
      }[]),
      ...(session?.jobs || []).flatMap((job) => job.result.artifacts || []),
    ];
    for (const item of candidates)
      if (item.kind !== "directory") unique.set(item.path, item);
    return [...unique.values()].slice(-12);
  }, [session?.state?.artifacts, session?.jobs]);
  useEffect(() => {
    files?.changed();
  }, [
    stream.events
      .filter((event) => ["artifacts", "file_index"].includes(event.kind))
      .at(-1)?.seq,
  ]);
  async function action(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError("");
    try {
      await fn();
      await query.refetch();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function loadOlder() {
    await action("older", async () => {
      const oldest = before ?? session?.activity_before ?? 0;
      const page = await researchActivity(
        id,
        Number.isFinite(oldest) ? oldest : 0,
      );
      setOlder(previous => mergeResearchEvents(page.items, previous));
      setBefore(page.next_before ?? 0);
    });
  }
  const reportId =
    session?.state?.manuscript_id || session?.state?.report_draft_id;
  return (
    <section
      className="space-y-4 border-t border-[color:var(--surface-border)] pt-5"
      aria-label={text("research")}
    >
      {toolbarRoot && createPortal(
        <>
          <div className="flex min-w-0 flex-1 basis-full items-center gap-2 sm:basis-0">
            {live.has(status) && <Loader2 size={14} className="shrink-0 animate-spin text-primary-600" aria-hidden="true" />}
            <span className="truncate text-xs font-medium text-slate-700" title={session?.title || text("research")}>{session?.title || text("research")}</span>
            <span className="shrink-0 text-xs text-slate-500 sm:hidden xl:inline">{statusLabel(status)}</span>
          </div>
          <Button type="button" variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={()=>askAbout()}><MessageCircleQuestion size={15}/>{text('sideQuestion')}</Button>
          <Button ref={detailsButton} type="button" variant={panel ? "secondary" : "ghost"} size="sm" className="shrink-0 gap-1.5" aria-expanded={panel} aria-controls={panel ? panelId : undefined} onClick={() => { files?.close(); setPanel(value => !value); }}>
            <PanelRight size={15} aria-hidden="true" />{text("details")}
          </Button>
          <Button asChild variant="outline" size="sm" className="shrink-0 gap-1.5">
            <Link to={`/autoresearch/sessions/${id}`}><Maximize2 size={14} aria-hidden="true" />{text("expandDetails")}</Link>
          </Button>
        </>, toolbarRoot,
      )}
      <header className="flex items-center gap-3 text-sm">
        {live.has(status) && (
          <Loader2 size={15} className="shrink-0 animate-spin text-gray-500" />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-gray-900">
            {session?.title || text("loading")}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span>{statusLabel(status)}</span>
            <span className="rounded-full bg-[color:var(--surface-muted)] px-2 py-0.5">
              {session?.task_kind === "analysis" ? text("analysisOnly")
                : session?.task_kind === "document" ? text("documentOnly")
                : `${session?.current_iteration || 0}/${session?.max_iterations || "—"}`}
            </span>
          </div>
        </div>
      </header>
      {status === 'queued' && <ResearchQueueNotice queue={session?.queue} />}
      {analysisResults.length > 0 && (
        <Button variant="outline" size="sm"
          onClick={() => {
            files?.close();
            setPanel(true);
            setTab("results");
          }}
        >
          {text("viewAnalysis")} ({analysisResults.length})
        </Button>
      )}
      {(error || query.error) && (
        <p role="alert" className="text-sm text-red-600">
          {error || String(query.error)}
        </p>
      )}
      <div className="flex gap-3">
        <Button variant="ghost" size="sm"
          type="button"
          onClick={() => void loadOlder()}
          disabled={!!busy || (before ?? session?.activity_before ?? 0) === 0}
        >
          {text("older")}
        </Button>
      </div>
      <ResearchTimeline events={events} running={live.has(status)} onAsk={askAbout} renderProse={value => <Prose sessionId={id} workspacePath={session?.workspace_path}>{value}</Prose>} />
      <ResearchSideQuestion sessionId={id} selection={sideQuestion} onClose={()=>setSideQuestion(null)}/>
      {artifacts.length > 0 && (
        <div
          aria-label={text("artifactFiles")}
          className="flex flex-wrap gap-2"
        >
          {artifacts.map((file) => (
            <Button variant="outline" size="sm"
              key={file.path}
              title={file.path}
              onClick={() =>
                files?.openFile({ sessionId: id, path: file.path })
              }
              className="max-w-64"
            >
              <span className="truncate">{file.name}</span>
            </Button>
          ))}
        </div>
      )}
      {forms.map((form) => (
        <ResearchQuestion key={form.id} sessionId={id} form={form} />
      ))}
      {status === 'blocked' && (
        <section aria-label={text('assistanceTitle')} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-start gap-3 p-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-700"><CircleHelp size={19} aria-hidden="true" /></div>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-slate-900">{text('assistanceTitle')}</h3>
              <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{session?.recovery?.summary || text('assistanceHint')}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/60 px-4 py-2">
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-600"><Check size={13} aria-hidden="true" />{text('assistanceSaved')}</span>
            <Button type="button" variant="ghost" size="sm" onClick={() => { files?.close(); setTab('plan'); setPanel(true); }} className="gap-1 text-primary-700">{text('assistanceOpen')}<ChevronRight size={14} aria-hidden="true" /></Button>
          </div>
        </section>
      )}
      {panel &&
        panelRoot &&
        createPortal(
          <aside
            id={panelId}
            className="fixed inset-x-2 bottom-2 top-[4.75rem] z-40 flex flex-col overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-elevated)] shadow-[var(--shadow-elevated)] backdrop-blur-xl lg:static lg:m-3 lg:ml-0 lg:h-[calc(100%-1.5rem)] lg:w-[380px] xl:w-[440px]"
            aria-label={text("details")}
          >
            <header className="flex shrink-0 items-center gap-3 px-5 pb-3 pt-4">
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-slate-900">{text("details")}</h2>
                <p className="mt-1 truncate text-xs text-slate-500" title={session?.title}>{session?.title}</p>
              </div>
              <Button asChild variant="ghost" size="icon" title={text("expandDetails")}>
                <Link to={`/autoresearch/sessions/${id}`} aria-label={text("expandDetails")}><Maximize2 size={16} aria-hidden="true" /></Link>
              </Button>
              <Button ref={closeButton} type="button" variant="ghost" size="icon"
                onClick={() => { setPanel(false); detailsButton.current?.focus({ preventScroll: true }); }}
                aria-label={text("close")}
              >
                <X size={17} aria-hidden="true" />
              </Button>
            </header>
            <div className="shrink-0 px-5 pb-3">
              <SegmentedControl value={tab} onChange={setTab} aria-label={text("details")} options={[{ value: "plan", label: text("plan") }, { value: "results", label: text("results") }]} className="w-fit" />
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-y border-[color:var(--surface-border)] bg-[color:var(--surface-base)] px-5 py-3">
              <span className="mr-auto text-xs font-medium text-slate-500">{statusLabel(status)}</span>
              {live.has(status) && (
                <Button type="button" variant="outline" size="sm" className="gap-1.5"
                  disabled={!!busy}
                  onClick={() => void action("pause", () => pauseResearch(id))}
                >
                  <Pause size={12} />
                  {text("pause")}
                </Button>
              )}
              {["paused", "failed", "blocked", "interrupted"].includes(
                status,
              ) && (
                <Button type="button" variant="default" size="sm" className="gap-1.5"
                  disabled={!!busy}
                  onClick={() =>
                    void action("resume", () => resumeAutoResearchSession(id))
                  }
                >
                  <Play size={12} />
                  {text("resume")}
                </Button>
              )}
              {(live.has(status) || ["paused", "blocked"].includes(status)) && (
                <Button type="button" variant="ghost" size="sm" className="gap-1.5 text-red-700 hover:bg-red-50 hover:text-red-800"
                  disabled={!!busy}
                  onClick={() =>
                    void action("stop", () => stopAutoResearchSession(id))
                  }
                >
                  <Square size={12} />
                  {text("stop")}
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
              {tab === "plan" && (
                <>
                  <ResearchOutline
                    plan={(planEvent?.steps as ResearchStep[]) || plan}
                    selected={selectedStep}
                    onSelect={key => setSelectedStep(previous => previous === key ? null : key)}
                    status={status}
                    completedRuns={session?.experiments?.filter(run => run.status === 'completed').length || 0}
                    totalRuns={session?.experiments?.length || 0}
                  />
                  {["paused", "failed", "blocked", "interrupted"].includes(
                    status,
                  ) && (
                    <ResearchRecoveryPanel
                      sessionId={id}
                      recovery={session?.recovery}
                      workspaceId={workspaceId || undefined}
                      onContinued={async () => {
                        await query.refetch();
                      }}
                    />
                  )}
                </>
              )}
              {tab === "results" && (
                <Suspense
                  fallback={
                    <p className="text-xs text-gray-400">{text("loading")}</p>
                  }
                >
                  <ExperimentComparison
                    experiments={session?.experiments || []}
                  />
                  {analysisResults.length > 1 && (
                    <Select ariaLabel={text('viewAnalysis')} value={activeAnalysis?.id || ''}
                      onChange={setSelectedAnalysis} options={analysisResults.map(result => ({value:result.id,label:result.title}))} />
                  )}
                  {activeAnalysis && (
                    <AnalysisResultView
                      key={`${activeAnalysis.id}:${activeAnalysis.revision}`}
                      sessionId={id}
                      analysisId={activeAnalysis.id}
                      userId={userId}
                      version={activeAnalysis.revision}
                    />
                  )}
                  {(session?.jobs || []).map((job) => (
                    <section
                      key={job.job_id}
                      className="rounded-2xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] p-4 text-xs"
                    >
                      <div className="flex flex-wrap justify-between gap-2">
                        <p>{String(job.payload.name || job.job_id)}</p>
                        <span className="text-slate-500">{statusLabel(job.status)}</span>
                      </div>
                      <JobProgress job={job} events={events} />
                      <ResearchJobNotice
                        job={job}
                        event={{ kind: "job" }}
                        onLogs={(path) =>
                          files?.openFile({ sessionId: id, path })
                        }
                      />
                    </section>
                  ))}
                  {!!reportId && (
                    <Link
                      to={`/reports?report=${encodeURIComponent(String(reportId))}`}
                      className="block text-sm text-blue-600"
                    >
                      {researchText.report}
                    </Link>
                  )}
                  {!!session?.state?.report && (
                    <Prose
                      sessionId={id}
                      workspacePath={session.workspace_path}
                    >
                      {String(session.state.report)}
                    </Prose>
                  )}
                  {status === "completed" &&
                    (session?.task_kind === "analysis" ||
                      session?.task_kind === "document") && (
                      <p className="text-xs leading-6 text-gray-500">
                        {text("continueInChat")}
                      </p>
                    )}
                  {status === "completed" &&
                    session?.task_kind !== "analysis" &&
                    session?.task_kind !== "document" && (
                      <ResearchRefinementPanel
                        sessionId={id}
                        experiments={session?.experiments || []}
                        remainingExperiments={Math.max(
                          0,
                          (session?.max_iterations || 0) -
                            (session?.current_iteration || 0),
                        )}
                        maxExperiments={session?.max_iterations || 0}
                        allowExperiments={session?.task_kind === 'experiment' || !!session?.experiments?.length}
                        onContinued={async () => {
                          await query.refetch();
                        }}
                      />
                    )}
                </Suspense>
              )}
            </div>
          </aside>,
          panelRoot,
        )}
    </section>
  );
});
