import { useState } from "react";
import { Check, ChevronDown, Loader2, X } from "lucide-react";
import {
  chartSpec,
  defaultConfig,
  type AnalysisConfig,
  type Catalog,
  type ResultSource,
} from "../../../api/resultWorkbench";
import { Button } from "../../ui/button";
import { Select } from "../../ui/select";
import { ModalShell } from "../../ui/modal-shell";
import AnalysisSettings from "./AnalysisSettings";
import { useResultText } from "./text";

type Goal =
  | "overall"
  | "calibrationGoal"
  | "subgroup"
  | "uncertainty"
  | "distributionGoal"
  | "comparisonGoal";
export default function AddAnalysisDialog({
  sources,
  config,
  catalog,
  busy,
  error,
  onChange,
  onStart,
  onClose,
}: {
  sources: ResultSource[];
  config: AnalysisConfig;
  catalog?: Catalog;
  busy: boolean;
  error: string;
  onChange: (value: AnalysisConfig) => void;
  onStart: () => void;
  onClose: () => void;
}) {
  const { text } = useResultText();
  const [advanced, setAdvanced] = useState(true);
  const [goal, setGoal] = useState<Goal>(
    sources.length > 1 || !sources[0]?.prediction_count
      ? "comparisonGoal"
      : config.interval.enabled
        ? "uncertainty"
        : config.group_by
          ? "subgroup"
          : sources[0]?.gt_count || sources[0]?.segmentation_metrics
            ? "overall"
            : "distributionGoal",
  );
  const primary = sources[0];
  const hasSamples = sources.some((source) => source.prediction_count);
  const hasGT = sources.some(
    (source) => source.gt_count || source.segmentation_metrics,
  );
  const classification = primary?.task_type.includes("classification");
  const choices: {
    id: Goal;
    hint:
      | "overallHint"
      | "calibrationHint"
      | "subgroupHint"
      | "uncertaintyHint"
      | "distributionHint"
      | "comparisonHint";
  }[] = [
    ...(hasGT
      ? [{ id: "overall" as const, hint: "overallHint" as const }]
      : []),
    ...(classification && hasGT && primary.probability_count
      ? [{ id: "calibrationGoal" as const, hint: "calibrationHint" as const }]
      : []),
    ...(hasSamples
      ? [
          { id: "subgroup" as const, hint: "subgroupHint" as const },
          {
            id: "distributionGoal" as const,
            hint: "distributionHint" as const,
          },
        ]
      : []),
    ...(hasSamples && hasGT
      ? [{ id: "uncertainty" as const, hint: "uncertaintyHint" as const }]
      : []),
    ...(sources.length > 1 || !hasSamples
      ? [{ id: "comparisonGoal" as const, hint: "comparisonHint" as const }]
      : []),
  ];
  const applyGoal = (next: Goal) => {
    setGoal(next);
    const base = {
      ...defaultConfig(primary),
      source_ids: sources.map((source) => source.source_id),
      facet_id: config.facet_id,
    };
    if (next === "calibrationGoal") {
      base.metrics = ["brier", "log_loss", "average_precision"];
      base.charts = ["calibration", "pr"].map(chartSpec);
    }
    if (next === "subgroup") base.group_by = "gender";
    if (next === "uncertainty") base.interval.enabled = true;
    if (next === "distributionGoal") {
      base.metrics = classification
        ? ["mean_confidence", "entropy"]
        : primary.task_type.includes("survival")
          ? ["mean_risk"]
           : primary.task_type === 'patch_detection' ? ['detection_count'] : ["dice", "miou"];
      base.charts = (
        classification
          ? ["distribution", "confidence"]
          : primary.task_type.includes("survival")
            ? ["risk"]
             : primary.task_type === 'patch_detection' ? [] : ["segmentation"]
      ).map(chartSpec);
    }
    if (next === "comparisonGoal") {
      if (!hasSamples)
        base.metrics = [
          ...new Set(sources.flatMap((source) => Object.keys(source.metrics))),
        ].slice(0, 16);
      base.charts = [
        ...base.charts.filter((chart) => chart.id !== "comparison"),
        chartSpec("comparison"),
      ];
    }
    onChange(base);
  };
  return (
    <ModalShell
      isOpen
      onClose={busy ? undefined : onClose}
      maxWidth="xl"
      className="!max-w-3xl"
      title={text("addAnalysis")}
    >
      <header className="flex items-start justify-between gap-3 border-b border-[color:var(--surface-border)] px-5 py-5 sm:px-7">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            {text("addAnalysis")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {text("addAnalysisHint")}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          disabled={busy}
          aria-label={text("close")}
          onClick={onClose}
        >
          <X size={18} />
        </Button>
      </header>
      <div className="space-y-5 px-5 py-6 sm:px-7">
        <h3 className="text-sm font-medium">{text("analysisGoal")}</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {choices.map((choice) => (
            <button
              key={choice.id}
              aria-pressed={goal === choice.id}
              onClick={() => applyGoal(choice.id)}
              className={`rounded-2xl border p-4 text-left transition-colors ${goal === choice.id ? "border-primary-300 bg-primary-50/50" : "border-[color:var(--surface-border)] hover:bg-[color:var(--surface-muted)]"}`}
            >
              <span className="flex items-center justify-between gap-2 text-sm font-semibold text-slate-800">
                {text(choice.id)}
                {goal === choice.id && <Check size={15} />}
              </span>
              <span className="mt-2 block text-xs leading-6 text-slate-500">
                {text(choice.hint)}
              </span>
            </button>
          ))}
        </div>
        {goal === "subgroup" && (
          <Select
            ariaLabel={text("grouping")}
            value={config.group_by}
            onChange={(value) =>
              onChange({
                ...config,
                group_by: value as AnalysisConfig["group_by"],
              })
            }
            options={(
              ["gender", "age_band", "source", "dataset_id"] as const
            ).map((value) => ({ value, label: text(value) }))}
          />
        )}
        <div className="border-t border-[color:var(--surface-border)] pt-4">
          <Button
            variant="ghost"
            className="w-full justify-between px-0"
            aria-expanded={advanced}
            onClick={() => setAdvanced(!advanced)}
          >
            {text("advanced")}
            <ChevronDown size={16} className={advanced ? "rotate-180" : ""} />
          </Button>
          {advanced && (
            <div className="mt-4">
              <AnalysisSettings
                config={config}
                onChange={onChange}
                sources={sources}
                catalog={catalog}
              />
            </div>
          )}
        </div>
        {error && (
          <p
            role="alert"
            className="rounded-xl bg-red-50 p-3 text-sm text-red-600"
          >
            {error}
          </p>
        )}
      </div>
      <footer className="flex flex-col gap-4 border-t border-[color:var(--surface-border)] bg-[color:var(--surface-muted)] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
        <p className="max-w-md text-xs leading-6 text-slate-500">
          {text("backgroundHint")}
        </p>
        <Button
          disabled={busy || !config.metrics.length}
          onClick={onStart}
          className="shrink-0"
        >
          {busy && <Loader2 size={14} className="mr-2 animate-spin" />}
          {text("startAnalysis")}
        </Button>
      </footer>
    </ModalShell>
  );
}
