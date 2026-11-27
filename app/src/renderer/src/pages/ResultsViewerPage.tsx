import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Loader2,
  MessageSquare,
  Plus,
  Save,
  X,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useDebounce } from "../lib/hooks/useDebounce";
import {
  getWorkspaceSelection,
  WORKSPACE_CHANGED,
} from "../lib/workspaceSelection";
import {
  chartSpec,
  defaultConfig,
  exportAnalysis,
  resultGet,
  resultSend,
  type AnalysisConfig,
  type AnalysisRun,
  type Catalog,
  type Page,
  type Recipe,
  type ResultSource,
} from "../api/resultWorkbench";
import { inputClass } from "../components/results/workbench/AnalysisSettings";
import SourcePicker from "../components/results/workbench/SourcePicker";
import SamplePreview, { type PreviewSample } from '../components/results/workbench/SamplePreview';
import { Button, buttonVariants } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Card } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Checkbox } from "../components/ui/checkbox";
import {
  SegmentedControl,
  EmptyStatePanel,
} from "../components/ui/workspace-primitives";
import { PageHeader } from "../components/PageHeader";
import "../components/results/workbench/results.css";
import {
  useResultText,
  type TextKey,
} from "../components/results/workbench/text";

const ResultPlots = lazy(
  () => import("../components/results/workbench/ResultPlots"),
);
const PublishedAnalysis = lazy(
  () => import("../components/results/workbench/PublishedAnalysis"),
);
const AnalysisAssistant = lazy(
  () => import("../components/results/workbench/AnalysisAssistant"),
);
const AddAnalysisDialog = lazy(
  () => import("../components/results/workbench/AddAnalysisDialog"),
);
const button = buttonVariants({
  variant: "outline",
  size: "sm",
  className: "gap-2",
});
const metricValue = (value: {
  value: number | null;
  unit?: string;
  ci_lower?: number | null;
  ci_upper?: number | null;
  std?: number | null;
}) => {
  const format = (number: number) =>
    value.unit === "ratio"
      ? `${(number * 100).toFixed(2)}%`
      : `${number.toLocaleString(undefined, { maximumFractionDigits: 4 })}${value.unit ? ` ${value.unit}` : ""}`;
  return value.value == null
    ? "—"
    : `${format(value.value)}${value.std != null ? ` ± ${format(value.std)}` : ""}${value.ci_lower != null && value.ci_upper != null ? ` [${format(value.ci_lower)}, ${format(value.ci_upper)}]` : ""}`;
};

export default function ResultsViewerPage() {
  const { user } = useAuth();
  const {
    text,
    metric,
    chart: chartLabel,
    split,
    note: noteText,
  } = useResultText();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [workspace, setWorkspace] = useState(getWorkspaceSelection);
  useEffect(() => {
    const update = () => setWorkspace(getWorkspaceSelection());
    window.addEventListener(WORKSPACE_CHANGED, update);
    return () => window.removeEventListener(WORKSPACE_CHANGED, update);
  }, []);
  const scopeKey = `${user?.id}:${workspace.workspaceId || "all"}`;
  const [query, setQuery] = useState("");
  const search = useDebounce(query, 250);
  const [kind, setKind] = useState("");
  const [taskFamily, setTaskFamily] = useState("");
  const [comparison, setComparison] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ResultSource[]>([]);
  const [config, setConfig] = useState<AnalysisConfig>(defaultConfig());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [mobileSourcesOpen, setMobileSourcesOpen] = useState(false);
  const [tab, setTab] = useState<"overview" | "samples" | "history">(
    "overview",
  );
  const [runId, setRunId] = useState(params.get("analysis") || "");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [recipeOffset, setRecipeOffset] = useState(0);
  const [recipesOpen, setRecipesOpen] = useState(false);
  const [recipeName, setRecipeName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [samplePage, setSamplePage] = useState(0);
  const sourceQuery = useQuery({
    queryKey: ["result-sources", scopeKey, search, kind, taskFamily, offset],
    queryFn: ({ signal }) =>
      resultGet<Page<ResultSource>>(
        "/sources",
        { query: search, kind, task_family: taskFamily, offset },
        signal,
      ),
    staleTime: 30_000,
  });
  const catalog = useQuery({
    queryKey: ["result-catalog"],
    queryFn: ({ signal }) => resultGet<Catalog>("/catalog", {}, signal),
    staleTime: Infinity,
  });
  const target = params.get("source");
  const targetSource = useQuery({
    queryKey: ["result-source", scopeKey, target],
    queryFn: ({ signal }) =>
      resultGet<ResultSource>("/source", { source_id: target! }, signal),
    enabled: !!target,
  });
  const runQuery = useQuery({
    queryKey: ["result-run", scopeKey, runId],
    queryFn: ({ signal }) =>
      resultGet<AnalysisRun>(`/runs/${runId}`, {}, signal),
    enabled: !!runId,
    refetchInterval: (query) =>
      ["queued", "running", "cancelling"].includes(
        query.state.data?.status || "",
      )
        ? 1500
        : false,
  });
  const run = runQuery.data;
  const restoredRun = useRef("");
  const activeRuns = useQuery({
    queryKey: ["result-active", scopeKey],
    queryFn: ({ signal }) =>
      resultGet<Page<AnalysisRun>>(
        "/runs",
        { status: "active", limit: 8 },
        signal,
      ),
    refetchInterval: (query) => (query.state.data?.items.length ? 3000 : 15000),
  });
  const history = useQuery({
    queryKey: [
      "result-history",
      scopeKey,
      selected[0]?.source_id,
      historyOffset,
    ],
    queryFn: ({ signal }) =>
      resultGet<Page<AnalysisRun>>(
        "/runs",
        { source_id: selected[0]?.source_id, offset: historyOffset },
        signal,
      ),
    enabled: tab === "history",
  });
  const latest = useQuery({
    queryKey: ["result-latest", scopeKey, selected[0]?.source_id],
    queryFn: ({ signal }) =>
      resultGet<Page<AnalysisRun>>(
        "/runs",
        { source_id: selected[0]?.source_id, limit: 1 },
        signal,
      ),
    enabled: selected.length === 1 && !runId && selected[0].kind !== "analysis",
  });
  const recipes = useQuery({
    queryKey: ["result-recipes", scopeKey, recipeOffset],
    queryFn: ({ signal }) =>
      resultGet<Page<Recipe>>("/recipes", { offset: recipeOffset }, signal),
    enabled: recipesOpen,
  });
  const sampleQuery = useQuery({
    queryKey: ["result-samples", scopeKey, runId, samplePage],
    queryFn: ({ signal }) =>
      resultGet<Page<Record<string, unknown>>>(
        `/runs/${runId}/samples`,
        { offset: samplePage * 50 },
        signal,
      ),
    enabled: tab === "samples" && run?.status === "completed",
  });
  const readonly = workspace.executionMode === "read_only";
  useEffect(() => {
    setSelected([]);
    setConfig(defaultConfig());
    setRunId(params.get("analysis") || "");
    setError("");
  }, [scopeKey]);
  useEffect(() => {
    if (targetSource.data) {
      setSelected([targetSource.data]);
      setConfig(defaultConfig(targetSource.data));
      setHistoryOffset(0);
    }
  }, [targetSource.data]);
  useEffect(() => {
    if (run?.status === "completed")
      void qc.invalidateQueries({ queryKey: ["result-history", scopeKey] });
  }, [run?.status, scopeKey, qc]);
  useEffect(() => {
    if (run?.config && restoredRun.current !== run.analysis_id) {
      restoredRun.current = run.analysis_id;
      if (selected.length === 0) setSelected(run.sources || []);
      setConfig(run.config);
    }
  }, [run, selected.length]);
  useEffect(() => {
    const item = latest.data?.items[0];
    if (item && !runId && selected.length === 1) setRunId(item.analysis_id);
  }, [latest.data, runId, selected.length]);
  const selectSource = (source: ResultSource) => {
    if (
      comparison &&
      selected.length &&
      !selected.some((item) => item.source_id === source.source_id)
    ) {
      const taskTypes = (value: ResultSource) =>
        [...(value.task_families || ["custom"])].sort().join(",");
      if (taskTypes(source) !== taskTypes(selected[0])) {
        setError(text("incompatibleTasks"));
        return;
      }
    }
    setError("");
    setRunId("");
    setMobileSourcesOpen(false);
    setHistoryOffset(0);
    setSamplePage(0);
    setParams(
      (previous) => {
        previous.delete("analysis");
        previous.delete("source");
        return previous;
      },
      { replace: true },
    );
    if (!comparison) {
      setSelected([source]);
      setConfig(defaultConfig(source));
      setTab("overview");
      return;
    }
    if (selected.some((item) => item.source_id === source.source_id)) {
      const next = selected.filter(
        (item) => item.source_id !== source.source_id,
      );
      setSelected(next);
      setConfig((value) => ({
        ...value,
        source_ids: next.map((item) => item.source_id),
      }));
      return;
    }
    if (selected.length === 8) {
      setError(text("selectionLimit"));
      return;
    }
    const next = [...selected, source];
    setSelected(next);
    setConfig((value) =>
      selected.length
        ? {
            ...value,
            source_ids: next.map((item) => item.source_id),
            charts: value.charts.some((c) => c.id === "comparison")
              ? value.charts
              : [...value.charts, chartSpec("comparison")],
          }
        : defaultConfig(source),
    );
  };
  const openRun = (id: string) => {
    restoredRun.current = "";
    setSelected([]);
    setRunId(id);
    setTab("overview");
    setSamplePage(0);
    setParams(
      (previous) => {
        previous.set("analysis", id);
        return previous;
      },
      { replace: true },
    );
  };
  const execute = async () => {
    setBusy(true);
    setError("");
    try {
      const value = await resultSend<AnalysisRun>("/runs", { config });
      qc.setQueryData(["result-run", scopeKey, value.analysis_id], value);
      openRun(value.analysis_id);
      setSettingsOpen(false);
      void qc.invalidateQueries({ queryKey: ["result-active", scopeKey] });
      void qc.invalidateQueries({ queryKey: ['workbench-background'] });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const handoff = (goal = "") => {
    navigate("/dashboard", {
      state: {
        toolDraft: `${goal || text("assistantHint")}\n\n${text("analysisContext")}:\n${JSON.stringify({ config, analysis_id: runId || undefined, sources: selected.map((s) => ({ source_id: s.source_id, title: s.title, revision: s.revision })) }, null, 2)}`,
        references: selected
          .map((source) =>
            source.task_id
              ? { kind: "task", id: source.task_id }
              : { kind: "research", id: source.session_id },
          )
          .filter((ref) => ref.id),
      },
    });
  };
  const saveRecipe = async () => {
    if (!recipeName.trim()) return;
    try {
      await resultSend("/recipes", { name: recipeName.trim(), config });
      setRecipeName("");
      setNotice(text("saved"));
      void qc.invalidateQueries({ queryKey: ["result-recipes"] });
    } catch (e) {
      setError(String(e));
    }
  };
  const shownError =
    error ||
    (sourceQuery.error ? String(sourceQuery.error) : "") ||
    (runQuery.error ? String(runQuery.error) : "") ||
    (targetSource.error ? String(targetSource.error) : "");
  const activeFacet = selected[0]?.facets?.find(
    (facet) => facet.id === config.facet_id,
  );
  const analysisSources = selected.map((source) => {
    const facet = source.facets?.find((item) => item.id === config.facet_id);
    return facet
      ? {
          ...source,
          task_type: facet.task_type,
          metrics: Object.fromEntries(
            Object.entries(source.metrics).filter(([key]) =>
              facet.metric_keys.includes(key),
            ),
          ),
          prediction_count:
            facet.task_type === source.task_type ? source.prediction_count : 0,
        }
      : source;
  });
  const facetKeys = activeFacet ? new Set(activeFacet.metric_keys) : null;
  const outputs = (run?.result?.results || []).map((result) => ({
    ...result,
    metrics: facetKeys
      ? Object.fromEntries(
          Object.entries(result.metrics).filter(([key]) => facetKeys.has(key)),
        )
      : result.metrics,
  }));
  const metadataOnly =
    selected.length > 0 && selected.every((source) => !source.prediction_count);
  const comparisonKeys = [
    ...new Set(outputs.flatMap((result) => Object.keys(result.metrics))),
  ];
  const initialKeys = [
    ...new Set(
      selected.flatMap((source) =>
        Object.keys(source.metrics || {}).filter(
          (key) => !facetKeys || facetKeys.has(key),
        ),
      ),
    ),
  ].slice(0, 20);
  const calculationFingerprint = (value: AnalysisConfig) =>
    JSON.stringify({ ...value, charts: value.charts.map((c) => c.id) });
  const dirty =
    run?.config &&
    calculationFingerprint(run.config) !== calculationFingerprint(config);
  const fallback = (
    <div role="status" className="p-6 text-sm text-slate-500">
      {text("loading")}
    </div>
  );
  return (
    <div className="results-workbench mx-auto w-full max-w-[1800px] px-3 pb-8 sm:px-6">
      <PageHeader
        title={text("title")}
        description={text("subtitle")}
        className="mb-6"
      >
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => setRecipesOpen(!recipesOpen)}
        >
          <Save size={14} />
          {text("recipes")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          aria-pressed={assistantOpen}
          onClick={() => setAssistantOpen(!assistantOpen)}
        >
          <MessageSquare size={14} />
          {text("assistant")}
        </Button>
      </PageHeader>
      {!!activeRuns.data?.items.length && (
        <Card className="mb-5 flex flex-wrap items-center gap-3 px-5 py-3">
          <Loader2 size={15} className="animate-spin text-primary-600" />
          <span className="text-xs text-slate-500">
            {text("activeAnalyses")}
          </span>
          {activeRuns.data.items.map((item) => (
            <Button
              key={item.analysis_id}
              variant="ghost"
              size="sm"
              onClick={() => openRun(item.analysis_id)}
              className="max-w-64"
            >
              <span className="truncate">{item.title}</span>
              <span className="ml-2 text-primary-600">
                {text(item.status as TextKey)} · {item.progress}%
              </span>
            </Button>
          ))}
        </Card>
      )}
      {run && ['queued', 'running', 'cancelling'].includes(run.status) && <Card className="mb-5 p-5" role="status" aria-live="polite">
        <div className="flex items-center justify-between text-sm">
          <span>{text(run.phase as TextKey)}</span><span>{run.progress}%</span>
        </div>
        <progress className="my-3 h-2 w-full" max={100} value={run.progress} />
        <p className="text-sm leading-6 text-slate-600">{text('longRunning')}</p>
      </Card>}
      {shownError && (
        <div
          role="alert"
          className="mb-4 flex items-start justify-between gap-3 rounded-lg bg-red-50 p-3 text-sm text-red-700"
        >
          <span>{shownError}</span>
          <button
            onClick={() => {
              setError("");
              void sourceQuery.refetch();
              if (runId) void runQuery.refetch();
            }}
          >
            {text("retry")}
          </button>
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="mb-3 flex justify-between rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-700"
        >
          {notice}
          <button onClick={() => setNotice("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {recipesOpen && (
        <Card className="mb-5 p-5">
          <div className="flex flex-wrap gap-2">
            <Input
              aria-label={text("recipeName")}
              placeholder={text("recipeName")}
              value={recipeName}
              onChange={(e) => setRecipeName(e.target.value)}
              className="max-w-xs"
            />
            <button
              disabled={!recipeName.trim() || readonly}
              className={button}
              onClick={() => void saveRecipe()}
            >
              {text("save")}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {recipes.data?.items.map((recipe) => (
              <div
                key={recipe.recipe_id}
                className="flex items-center gap-1 rounded-lg border px-2 py-1"
              >
                <button
                  className="px-2 py-1 text-xs"
                  onClick={() => {
                    setConfig({
                      ...recipe.config,
                      source_ids: config.source_ids,
                    });
                    setSettingsOpen(true);
                  }}
                >
                  {recipe.name}
                </button>
                <button
                  title={text("update")}
                  disabled={readonly}
                  className="p-1 text-slate-400"
                  onClick={async () => {
                    try {
                      await resultSend(
                        `/recipes/${recipe.recipe_id}`,
                        { name: recipe.name, config, version: recipe.version },
                        "PUT",
                      );
                      void recipes.refetch();
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  <Save size={12} />
                </button>
                <button
                  title={text("delete")}
                  disabled={readonly}
                  className="p-1 text-slate-400"
                  onClick={async () => {
                    try {
                      await resultSend(
                        `/recipes/${recipe.recipe_id}`,
                        undefined,
                        "DELETE",
                      );
                      void recipes.refetch();
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
          {recipes.error && (
            <p className="mt-2 text-xs text-red-600">{String(recipes.error)}</p>
          )}
          <div className="mt-2 flex gap-4 text-xs">
            <button
              disabled={!recipeOffset}
              onClick={() => setRecipeOffset((v) => v - 20)}
            >
              {text("previous")}
            </button>
            <button
              disabled={!recipes.data?.has_more}
              onClick={() => setRecipeOffset((v) => v + 20)}
            >
              {text("next")}
            </button>
          </div>
        </Card>
      )}
      <div
        className={`grid min-w-0 items-start gap-5 ${assistantOpen ? "xl:grid-cols-[260px_minmax(0,1fr)_320px]" : "lg:grid-cols-[290px_minmax(0,1fr)]"}`}
      >
        <aside className="min-w-0">
          <Button
            variant="outline"
            className="mb-3 w-full justify-between lg:hidden"
            onClick={() => setMobileSourcesOpen(!mobileSourcesOpen)}
            aria-expanded={mobileSourcesOpen}
          >
            {text("sources")}
            <span className="max-w-40 truncate text-xs text-slate-400">
              {selected[0]?.title || text("empty")}
            </span>
          </Button>
          <div
            className={
              mobileSourcesOpen || !selected.length
                ? "block"
                : "hidden lg:block"
            }
          >
            <SourcePicker
              items={sourceQuery.data?.items || []}
              selected={selected}
              query={query}
              kind={kind}
              taskFamily={taskFamily}
              comparison={comparison}
              offset={offset}
              loading={sourceQuery.isLoading}
              refreshing={sourceQuery.isFetching}
              hasMore={!!sourceQuery.data?.has_more}
              onQuery={(value) => {
                setQuery(value);
                setOffset(0);
              }}
              onKind={(value) => {
                setKind(value);
                setOffset(0);
              }}
              onFamily={(value) => {
                setTaskFamily(value);
                setOffset(0);
              }}
              onCompare={() => {
                setComparison(!comparison);
                if (comparison && selected.length > 1) {
                  setSelected([selected[0]]);
                  setConfig(defaultConfig(selected[0]));
                  setRunId("");
                }
              }}
              onPage={setOffset}
              onSelect={selectSource}
              onRefresh={() => void sourceQuery.refetch()}
            />
          </div>
        </aside>
        <main className="min-w-0 space-y-4">
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 flex-1 flex-wrap gap-2">
                {selected.length ? (
                  selected.map((source) => (
                    <span
                      key={source.source_id}
                      className="inline-flex max-w-full items-center gap-2 rounded-md bg-slate-100 px-2.5 py-1.5 text-xs text-slate-700"
                    >
                      <span
                        className="max-w-[300px] truncate"
                        title={source.title}
                      >
                        {source.title}
                      </span>
                      <button
                        aria-label={`${text("delete")} ${source.title}`}
                        onClick={() => {
                          const remaining = selected.filter(
                            (item) => item.source_id !== source.source_id,
                          );
                          setSelected(remaining);
                          setConfig((value) => ({
                            ...value,
                            source_ids: remaining.map((item) => item.source_id),
                          }));
                          setRunId("");
                          setParams({}, { replace: true });
                        }}
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))
                ) : (
                  <span className="py-1 text-sm text-slate-400">
                    {text("empty")}
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={
                    !selected.length ||
                    readonly ||
                    selected.every(
                      (source) =>
                        !source.prediction_count &&
                        !Object.keys(source.metrics || {}).length,
                    )
                  }
                  onClick={() => {
                    setError("");
                    setSettingsOpen(true);
                  }}
                  className="gap-2"
                >
                  <Plus size={14} />
                  {text("addAnalysis")}
                </Button>
              </div>
            </div>
            {selected.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                {(selected[0].task_families || ["custom"]).map((family) => (
                  <span key={family} className="font-medium text-slate-700">
                    {text(family as TextKey)}
                  </span>
                ))}
                {!metadataOnly && (
                  <>
                    <span>{split(config.split)}</span>
                    <span>{text(config.unit)}</span>
                  </>
                )}
                <span>
                  {selected.length} {text("selected")}
                </span>
                {metadataOnly && <span>{text("noPredictions")}</span>}
              </div>
            )}
            {!!selected[0]?.facets?.length && (
              <div className="mt-4">
                <Select
                  ariaLabel={text("taskFacet")}
                  value={config.facet_id}
                  onChange={(value) =>
                    setConfig((c) => ({ ...c, facet_id: value }))
                  }
                  options={[
                    { value: "", label: text("allFacets") },
                    ...selected[0].facets.map((facet) => ({
                      value: facet.id,
                      label: facet.title,
                    })),
                  ]}
                />
              </div>
            )}
          </Card>
          <nav className="flex flex-wrap items-center justify-between gap-3 py-1">
            <SegmentedControl
              value={tab}
              onChange={setTab}
              options={(["overview", "samples", "history"] as const).map(
                (value) => ({ value, label: text(value) }),
              )}
            />
            {run?.status === "completed" && (
              <Select
                ariaLabel={text("export")}
                className="w-40"
                triggerClassName="h-10 text-xs"
                value=""
                placeholder={text("export")}
                options={[
                  "json",
                  "csv",
                  ...(run.result?.native_artifact ? ["original"] : ["inputs"]),
                ].map((value) => ({
                  value,
                  label:
                    value === "inputs"
                      ? text("exportInputs")
                      : value === "original"
                        ? text("exportOriginal")
                        : value.toUpperCase(),
                }))}
                onChange={(value) =>
                  void exportAnalysis(
                    run.analysis_id,
                    value as "json" | "csv" | "inputs" | "original",
                  ).catch((e) => setError(String(e)))
                }
              />
            )}
          </nav>
          {tab === "history" ? (
            <section className="space-y-2">
              {history.isLoading ? (
                fallback
              ) : !history.data?.items.length ? (
                <p className="p-8 text-center text-sm text-slate-400">
                  {text("noHistory")}
                </p>
              ) : (
                history.data.items.map((item) => (
                  <div
                    key={item.analysis_id}
                    className="flex items-center justify-between gap-3 rounded-lg border bg-white p-3"
                  >
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => openRun(item.analysis_id)}
                    >
                      <p className="truncate text-sm font-medium">
                        {item.title}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {new Date(item.created_at).toLocaleString()} ·{" "}
                        {text(item.status as TextKey)}
                      </p>
                    </button>
                    <button
                      disabled={
                        ["queued", "running", "cancelling"].includes(
                          item.status,
                        ) || readonly
                      }
                      className="text-xs text-slate-400 hover:text-red-600"
                      onClick={async () => {
                        try {
                          await resultSend(
                            `/runs/${item.analysis_id}`,
                            undefined,
                            "DELETE",
                          );
                          void history.refetch();
                          if (runId === item.analysis_id) setRunId("");
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      {text("delete")}
                    </button>
                  </div>
                ))
              )}
              <div className="flex justify-end gap-4 text-xs">
                <button
                  disabled={!historyOffset}
                  onClick={() => setHistoryOffset((v) => v - 20)}
                >
                  {text("previous")}
                </button>
                <button
                  disabled={!history.data?.has_more}
                  onClick={() => setHistoryOffset((v) => v + 20)}
                >
                  {text("next")}
                </button>
              </div>
            </section>
          ) : tab === "samples" ? (
            <section className="overflow-hidden rounded-xl border bg-white">
              <div className="grid gap-4 p-4 md:grid-cols-2">
                {sampleQuery.data?.items.map((item, index) => (
                  <SamplePreview key={index} sample={item as unknown as PreviewSample} analysisId={runId} threshold={run?.config?.threshold ?? 0.5} />
                ))}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50">
                    <tr>
                      {[
                        "source",
                        "samples",
                        "actual",
                        "predicted",
                        "confidence",
                      ].map((key) => (
                        <th key={key} className="p-3">
                          {text(key as TextKey)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sampleQuery.data?.items.map((item, i) => (
                      <tr key={i} className="border-t">
                        <td className="max-w-32 truncate p-3">
                          {String(item.source_title || "")}
                        </td>
                        <td className="max-w-48 truncate p-3">
                          <button
                            className="text-blue-600 hover:underline"
                            onClick={() =>
                              navigate(
                                `/wsi/${encodeURIComponent(String(item.wsi_id))}`,
                              )
                            }
                          >
                            {String(item.filename || item.wsi_id || "")}
                          </button>
                        </td>
                        <td className="p-3">{String(item.label ?? "—")}</td>
                        <td className="p-3">{String(item.pred ?? "—")}</td>
                        <td className="p-3 font-mono">
                          {typeof item.confidence === "number"
                            ? `${(item.confidence * 100).toFixed(1)}%`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!sampleQuery.data?.items.length && (
                  <p className="p-8 text-center text-sm text-slate-400">
                    {sampleQuery.isFetching
                      ? text("loading")
                      : text("noSamples")}
                  </p>
                )}
              </div>
              {sampleQuery.error && (
                <p role="alert" className="p-3 text-xs text-red-600">
                  {String(sampleQuery.error)}
                </p>
              )}
              <div className="flex justify-end gap-4 p-3 text-xs">
                <button
                  disabled={!samplePage}
                  onClick={() => setSamplePage((v) => v - 1)}
                >
                  {text("previous")}
                </button>
                <button
                  disabled={!sampleQuery.data?.has_more}
                  onClick={() => setSamplePage((v) => v + 1)}
                >
                  {text("next")}
                </button>
              </div>
            </section>
          ) : (
            <div className="space-y-4">
              {!selected.length && !run ? (
                <EmptyStatePanel
                  title={text("empty")}
                  description={text("viewHint")}
                  icon={<BarChart3 size={28} />}
                  className="min-h-[420px]"
                />
              ) : (
                <>
                  {run && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-white px-4 py-3">
                      <div>
                        <span
                          className={`text-xs font-medium ${run.status === "failed" ? "text-red-600" : "text-slate-600"}`}
                        >
                          {text(run.status as TextKey)}
                        </span>
                        <span className="ml-3 text-xs text-slate-400">
                          {new Date(run.created_at).toLocaleString()}
                        </span>
                        {run.error && (
                          <p role="alert" className="mt-2 text-sm text-red-600">
                            {run.error}
                          </p>
                        )}
                      </div>
                      {["running", "queued"].includes(run.status) ? (
                        <button
                          className={button}
                          onClick={async () => {
                            try {
                              await resultSend(`/runs/${runId}/cancel`);
                              void runQuery.refetch();
                            } catch (e) {
                              setError(String(e));
                            }
                          }}
                        >
                          {text("cancel")}
                        </button>
                      ) : (
                        <button
                          className={button}
                          onClick={() => {
                            if (run.config) {
                              setConfig(run.config);
                              setSelected(run.sources || []);
                              setSettingsOpen(true);
                            }
                          }}
                        >
                          {text("rerun")}
                        </button>
                      )}
                    </div>
                  )}
                  {dirty && (
                    <p className="text-xs text-amber-700">
                      {text("pendingChanges")}
                    </p>
                  )}
                  {!run && selected.length > 0 && initialKeys.length > 0 && (
                    <div className="overflow-x-auto rounded-xl border bg-white">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-50">
                          <tr>
                            <th className="p-3">{text("recorded")}</th>
                            {selected.map((source) => (
                              <th
                                className="max-w-52 p-3"
                                key={source.source_id}
                              >
                                {source.title}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {initialKeys.map((key) => (
                            <tr key={key} className="border-t">
                              <th className="p-3 font-normal">{metric(key)}</th>
                              {selected.map((source) => (
                                <td
                                  className="whitespace-nowrap p-3 font-mono"
                                  key={source.source_id}
                                >
                                  {source.metrics[key]
                                    ? metricValue(source.metrics[key])
                                    : "—"}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {outputs.length > 0 && (
                    <>
                      <div className="overflow-x-auto rounded-xl border bg-white">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-slate-50">
                            <tr>
                              <th className="p-3">{text("metrics")}</th>
                              {outputs.map((result) => (
                                <th
                                  key={result.source_id}
                                  className="min-w-40 p-3"
                                >
                                  <span className="block max-w-64">
                                    {result.title}
                                  </span>
                                  <span className="mt-1 block font-normal text-slate-400">
                                    {result.count ?? "—"} {text("count")}
                                  </span>
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {comparisonKeys.map((key) => (
                              <tr key={key} className="border-t">
                                <th className="p-3 font-normal text-slate-600">
                                  {metric(
                                    key,
                                    outputs.find((r) => r.metrics[key])
                                      ?.metrics[key]?.label,
                                  )}
                                </th>
                                {outputs.map((result) => (
                                  <td
                                    title={
                                      result.metrics[key]?.reason
                                        ? text("missingData")
                                        : ""
                                    }
                                    className="whitespace-nowrap p-3 font-mono text-slate-900"
                                    key={result.source_id}
                                  >
                                    {result.metrics[key]
                                      ? metricValue(result.metrics[key])
                                      : "—"}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {run?.result?.comparisons.map((item, i) => (
                        <p
                          key={i}
                          className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600"
                        >
                          {
                            outputs.find((r) => r.source_id === item.left)
                              ?.title
                          }{" "}
                          /{" "}
                          {
                            outputs.find((r) => r.source_id === item.right)
                              ?.title
                          }
                          :{" "}
                          {item.same_samples
                            ? text("sameCohort")
                            : text("cohortDifference")}{" "}
                          · {text("overlap")}: {item.overlap}
                          {item.disagreement != null &&
                            ` · ${text("disagreement")}: ${(item.disagreement * 100).toFixed(2)}%`}
                        </p>
                      ))}
                      <details>
                        <summary className="cursor-pointer text-xs text-slate-500">
                          {text("preview")}
                        </summary>
                        <div className="mt-3 space-y-2">
                          {config.charts.map((chart, i) => (
                            <div
                              key={chart.id}
                              className="flex flex-wrap items-center gap-2"
                            >
                              <div className="flex w-40 items-center gap-2 text-xs">
                                <Checkbox
                                  aria-label={chartLabel(chart.id)}
                                  checked={chart.visible}
                                  onCheckedChange={(checked) =>
                                    setConfig((c) => ({
                                      ...c,
                                      charts: c.charts.map((item, index) =>
                                        index === i
                                          ? {
                                              ...item,
                                              visible: checked,
                                            }
                                          : item,
                                      ),
                                    }))
                                  }
                                />
                                {chartLabel(chart.id)}
                              </div>
                              <Input
                                aria-label={text("chartTitle")}
                                placeholder={text("chartTitle")}
                                value={chart.title}
                                className={`${inputClass} max-w-52`}
                                onChange={(e) =>
                                  setConfig((c) => ({
                                    ...c,
                                    charts: c.charts.map((item, index) =>
                                      index === i
                                        ? { ...item, title: e.target.value }
                                        : item,
                                    ),
                                  }))
                                }
                              />
                              <input
                                type="color"
                                aria-label={text("color")}
                                value={chart.color}
                                onChange={(e) =>
                                  setConfig((c) => ({
                                    ...c,
                                    charts: c.charts.map((item, index) =>
                                      index === i
                                        ? { ...item, color: e.target.value }
                                        : item,
                                    ),
                                  }))
                                }
                              />
                              {(["x_min", "x_max"] as const).map((key) => (
                                <Input
                                  key={key}
                                  type="number"
                                  aria-label={text(
                                    key === "x_min" ? "minimum" : "maximum",
                                  )}
                                  placeholder={text(
                                    key === "x_min" ? "minimum" : "maximum",
                                  )}
                                  className={`${inputClass} max-w-24`}
                                  value={chart[key] ?? ""}
                                  onChange={(e) =>
                                    setConfig((c) => ({
                                      ...c,
                                      charts: c.charts.map((item, index) =>
                                        index === i
                                          ? {
                                              ...item,
                                              [key]:
                                                e.target.value === ""
                                                  ? null
                                                  : Number(e.target.value),
                                            }
                                          : item,
                                      ),
                                    }))
                                  }
                                />
                              ))}
                            </div>
                          ))}
                        </div>
                      </details>
                      {run && (
                        <Suspense fallback={fallback}>
                          <ResultPlots
                            run={run}
                            config={config}
                            compact={assistantOpen}
                          />
                        </Suspense>
                      )}
                      {outputs.map((result) => (
                        <div key={result.source_id} className="space-y-3">
                          {result.groups.length > 0 && (
                            <div className="overflow-x-auto rounded-lg border bg-white">
                              <table className="w-full text-left text-xs">
                                <thead className="bg-slate-50">
                                  <tr>
                                    <th className="p-3">
                                      {result.title} · {text("grouping")}
                                    </th>
                                    <th className="p-3">N</th>
                                    {[
                                      ...new Set(
                                        result.groups.flatMap((group) =>
                                          Object.keys(group.metrics),
                                        ),
                                      ),
                                    ].map((key) => (
                                      <th className="p-3" key={key}>
                                        {metric(key)}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {result.groups.map((group) => (
                                    <tr key={group.group} className="border-t">
                                      <th className="p-3 font-normal">
                                        {group.group}
                                      </th>
                                      <td className="p-3">{group.count}</td>
                                      {[
                                        ...new Set(
                                          result.groups.flatMap((item) =>
                                            Object.keys(item.metrics),
                                          ),
                                        ),
                                      ].map((key) => (
                                        <td className="p-3 font-mono" key={key}>
                                          {metricValue({
                                            ...result.metrics[key],
                                            value: group.metrics[key] ?? null,
                                            ci_lower: null,
                                            ci_upper: null,
                                          })}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                          {result.notes.map((note, i) => (
                            <p
                              key={i}
                              className="text-xs leading-5 text-slate-500"
                            >
                              {noteText(note)}
                            </p>
                          ))}
                        </div>
                      ))}
                    </>
                  )}
                  {!run && selected.length > 0 && (
                    <p className="px-1 text-sm text-slate-500">
                      {text("noRun")}
                    </p>
                  )}
                  {selected
                    .filter((source) => source.kind === "analysis")
                    .map((source) => (
                      <section
                        key={source.source_id}
                        className="rounded-xl border bg-white p-4"
                      >
                        <h2 className="mb-4 text-sm font-medium">
                          {source.title}
                        </h2>
                        <Suspense fallback={fallback}>
                          <PublishedAnalysis
                            facetId={config.facet_id}
                            source={source}
                            scopeKey={scopeKey}
                          />
                        </Suspense>
                      </section>
                    ))}
                  {selected.length > 0 && (
                    <Button
                      variant="link"
                      size="sm"
                      className="gap-2"
                      title={text("handoffHint")}
                      onClick={() => handoff()}
                    >
                      {text("handoff")}
                      <ArrowRight size={13} />
                    </Button>
                  )}
                </>
              )}
            </div>
          )}
        </main>
        {assistantOpen && (
          <Suspense fallback={fallback}>
            <AnalysisAssistant
              key={scopeKey}
              scopeKey={scopeKey}
              config={config}
              run={run}
              onConfig={setConfig}
              onRun={(value) => {
                qc.setQueryData(
                  ["result-run", scopeKey, value.analysis_id],
                  value,
                );
                openRun(value.analysis_id);
              }}
              onClose={() => setAssistantOpen(false)}
              onHandoff={handoff}
            />
          </Suspense>
        )}
      </div>
      {settingsOpen && (
        <Suspense fallback={fallback}>
          <AddAnalysisDialog
            sources={analysisSources}
            config={config}
            catalog={catalog.data}
            busy={busy}
            error={error}
            onChange={setConfig}
            onStart={() => void execute()}
            onClose={() => setSettingsOpen(false)}
          />
        </Suspense>
      )}
    </div>
  );
}
