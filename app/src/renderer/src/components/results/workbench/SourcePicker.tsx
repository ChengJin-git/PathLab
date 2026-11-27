import { Check, RefreshCw } from "lucide-react";
import type { ResultSource } from "../../../api/resultWorkbench";
import { Card } from "../../ui/card";
import { Button } from "../../ui/button";
import { Select } from "../../ui/select";
import { SearchField } from "../../ui/workspace-primitives";
import { useResultText, type TextKey } from "./text";

export default function SourcePicker({
  items,
  selected,
  query,
  kind,
  taskFamily,
  comparison,
  offset,
  loading,
  refreshing,
  hasMore,
  onQuery,
  onKind,
  onFamily,
  onCompare,
  onPage,
  onSelect,
  onRefresh,
}: {
  items: ResultSource[];
  selected: ResultSource[];
  query: string;
  kind: string;
  taskFamily: string;
  comparison: boolean;
  offset: number;
  loading: boolean;
  refreshing: boolean;
  hasMore: boolean;
  onQuery: (value: string) => void;
  onKind: (value: string) => void;
  onFamily: (value: string) => void;
  onCompare: () => void;
  onPage: (value: number) => void;
  onSelect: (source: ResultSource) => void;
  onRefresh: () => void;
}) {
  const { text } = useResultText();
  return (
    <Card className="overflow-hidden lg:sticky lg:top-4">
      <div className="space-y-3 border-b border-[color:var(--surface-border)] p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">
              {text("sources")}
            </h2>
            <p className="mt-1 text-[11px] leading-5 text-slate-400">
              {text(comparison ? "compareHint" : "sourceHint")}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            aria-label={text("retry")}
            onClick={onRefresh}
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          </Button>
        </div>
        <SearchField
          value={query}
          onChange={onQuery}
          placeholder={text("search")}
        />
        <Select
          ariaLabel={text("all")}
          value={kind}
          onChange={onKind}
          triggerClassName="h-10 text-xs"
          options={[
            { value: "", label: text("all") },
            ...(
              [
                "training",
                "external",
                "inference",
                "research",
                "experiment",
                "analysis",
              ] as const
            ).map((value) => ({ value, label: text(value) })),
          ]}
        />
        <Select
          ariaLabel={text("allTasks")}
          value={taskFamily}
          onChange={onFamily}
          triggerClassName="h-10 text-xs"
          options={[
            { value: "", label: text("allTasks") },
            ...(
              [
                "classification",
                "survival",
                "segmentation",
                "detection",
                "multitask",
                "custom",
              ] as const
            ).map((value) => ({ value, label: text(value) })),
          ]}
        />
        <Button
          variant={comparison ? "default" : "outline"}
          size="sm"
          className="w-full"
          aria-pressed={comparison}
          onClick={onCompare}
        >
          {text(comparison ? "exitCompare" : "compareMode")}
        </Button>
      </div>
      <div className="max-h-[32vh] space-y-1 overflow-y-auto p-2 lg:max-h-[62vh]">
        {loading ? (
          <div role="status" className="space-y-3 p-3">
            {[0, 1, 2, 3].map((key) => (
              <div
                key={key}
                className="h-20 animate-pulse rounded-xl bg-slate-100"
              />
            ))}
          </div>
        ) : !items.length ? (
          <p className="p-5 text-center text-xs text-slate-400">
            {text("noSources")}
          </p>
        ) : (
          items.map((source) => {
            const active = selected.some(
              (item) => item.source_id === source.source_id,
            );
            return (
              <button
                key={source.source_id}
                aria-pressed={active}
                onClick={() => onSelect(source)}
                className={`group w-full rounded-2xl border px-3 py-3 text-left transition-colors ${active ? "border-primary-200 bg-primary-50/70" : "border-transparent hover:border-[color:var(--surface-border)] hover:bg-white/80"}`}
              >
                <div className="flex items-start gap-3">
                  {comparison && (
                    <span
                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-md border ${active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white"}`}
                    >
                      {active && <Check size={10} strokeWidth={3} />}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="mb-2 flex flex-wrap gap-1.5">
                      {(source.task_families || ["custom"]).map((family) => (
                        <span
                          key={family}
                          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${family === "classification" ? "bg-blue-50 text-blue-700" : family === "survival" ? "bg-amber-50 text-amber-700" : family === "segmentation" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                        >
                          {text(family as TextKey)}
                        </span>
                      ))}
                      {(source.task_families?.length || 0) > 1 && (
                        <span className="text-[10px] text-slate-400">
                          {text("multitask")}
                        </span>
                      )}
                    </span>
                    <span
                      className="line-clamp-3 text-xs font-medium leading-5 text-slate-800"
                      title={source.title}
                    >
                      {source.title}
                    </span>
                    {source.research_title &&
                      source.research_title !== source.title && (
                        <span
                          className="mt-1 block truncate text-[11px] text-slate-400"
                          title={source.research_title}
                        >
                          {source.research_title}
                        </span>
                      )}
                    <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-500">
                      <span>{text(source.kind as TextKey)}</span>
                      {source.iteration != null && (
                        <span>
                          ·{" "}
                          {text("experimentNumber", {
                            number: source.iteration,
                          })}
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block text-[10px] leading-5 text-slate-400">
                      {text(
                        source.prediction_count
                          ? source.gt_count || source.segmentation_metrics
                            ? "labelledPredictions"
                            : "predictionsOnly"
                          : "metricsOnly",
                      )}
                      {source.prediction_count > 0 &&
                        ` · ${source.prediction_count.toLocaleString()}`}
                    </span>
                  </span>
                </div>
              </button>
            );
          })
        )}
      </div>
      <div className="flex items-center justify-between border-t border-[color:var(--surface-border)] px-3 py-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={!offset}
          onClick={() => onPage(offset - 20)}
        >
          {text("previous")}
        </Button>
        <span className="text-[11px] text-slate-400">
          {text("pageNumber", { number: offset / 20 + 1 })}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={!hasMore}
          onClick={() => onPage(offset + 20)}
        >
          {text("next")}
        </Button>
      </div>
    </Card>
  );
}
