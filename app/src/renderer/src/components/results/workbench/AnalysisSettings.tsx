import { useState, type ReactNode } from "react";
import { ChevronDown, Check } from "lucide-react";
import type {
  AnalysisConfig,
  Catalog,
  Definition,
  ResultSource,
} from "../../../api/resultWorkbench";
import { chartSpec } from "../../../api/resultWorkbench";
import { Button } from "../../ui/button";
import { Checkbox } from "../../ui/checkbox";
import { Input } from "../../ui/input";
import { Select } from "../../ui/select";
import { useResultText } from "./text";

export const inputClass =
  "min-w-0 h-10 rounded-xl border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-4 focus:ring-primary-500/20";
export function capability(definition: Definition, source: ResultSource) {
  const family = source.task_type.includes("survival")
    ? "survival"
    : source.task_type.includes("segmentation")
      ? "segmentation"
      : source.task_type.includes("classification")
        ? "classification"
        : source.task_type === 'patch_detection' ? 'detection' : "custom";
  if (definition.requires === "metrics") return true;
  if (definition.requires === "training_history")
    return !!source.training_history;
  if (definition.family !== "any" && definition.family !== family) return false;
  if (!source.prediction_count) return false;
  if (definition.requires === "gt") return !!source.gt_count;
  if (definition.requires === "gt_probs")
    return !!source.gt_count && !!source.probability_count;
  if (definition.requires === "probs") return !!source.probability_count;
  if (definition.requires === "segmentation_metrics")
    return !!source.segmentation_metrics;
  if (definition.requires === "survival") return !!source.survival;
  return true;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-2">
      <p className="text-xs font-medium text-slate-600">{label}</p>
      {children}
    </div>
  );
}
function AdvancedSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="border-t border-[color:var(--surface-border)] pt-4">
      <Button
        variant="ghost"
        className="h-auto w-full justify-between px-0 py-1 text-sm"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {title}
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </Button>
      {open && <div className="mt-4">{children}</div>}
    </section>
  );
}

export default function AnalysisSettings({
  config,
  onChange,
  sources,
  catalog,
}: {
  config: AnalysisConfig;
  onChange: (value: AnalysisConfig) => void;
  sources: ResultSource[];
  catalog?: Catalog;
}) {
  const { text, metric, chart, split } = useResultText();
  const update = (patch: Partial<AnalysisConfig>) =>
    onChange({ ...config, ...patch });
  const primary = sources[0];
  const predictionSources = sources.filter((s) => s.prediction_count);
  const splits = predictionSources.length
    ? predictionSources[0].splits.filter((value) =>
        predictionSources.every((source) => source.splits.includes(value)),
      )
    : [config.split];
  const family = primary?.task_type.includes("survival")
    ? "survival"
    : primary?.task_type.includes("segmentation")
      ? "segmentation"
      : primary?.task_type.includes("classification")
        ? "classification"
         : primary?.task_type === 'patch_detection' ? 'detection' : "custom";
  const customMetrics = [
    ...new Set(sources.flatMap((source) => Object.keys(source.metrics || {}))),
  ].filter(
    (key) =>
      !catalog?.metrics.some((item) => item.id === key) &&
      (!config.facet_id ||
        sources.some((source) =>
          source.facets
            ?.find((facet) => facet.id === config.facet_id)
            ?.metric_keys.includes(key),
        )),
  );
  const metrics = (catalog?.metrics || []).filter(
    (item) =>
      (item.family === "any" ||
        item.family === family ||
        sources.some((source) => item.id in source.metrics)) &&
      sources.some(
        (source) => capability(item, source) || item.id in source.metrics,
      ),
  );
  const charts = (catalog?.charts || []).filter(
    (item) =>
      (item.family === "any" || item.family === family) &&
      sources.some((source) => capability(item, source)),
  );
  const toggleMetric = (id: string) =>
    update({
      metrics: config.metrics.includes(id)
        ? config.metrics.filter((key) => key !== id)
        : [...config.metrics, id],
    });
  return (
    <div className="space-y-6">
      {predictionSources.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={text("split")}>
            <Select
              ariaLabel={text("split")}
              value={config.split}
              onChange={(value) => update({ split: value })}
              options={[...new Set([...splits, config.split])].map((value) => ({
                value,
                label: split(value),
              }))}
            />
          </Field>
          <Field label={text("unit")}>
            <Select
              ariaLabel={text("unit")}
              value={config.unit}
              onChange={(value) =>
                update({ unit: value as AnalysisConfig["unit"] })
              }
              options={[
                { value: "file", label: text("file") },
                {
                  value: "case",
                  label: text("case"),
                   disabled: family === "segmentation" || family === "detection",
                },
              ]}
            />
          </Field>
          {(family === 'detection' || family === 'segmentation') && <>
            <Field label={text('threshold')}>
              <Input aria-label={text('threshold')} type="number" min={0} max={1} step={0.01}
                disabled={family === 'segmentation' && !primary?.segmentation_thresholds}
                value={config.threshold} onChange={event => update({ threshold: Number(event.target.value) })} />
            </Field>
            {family === 'detection' && <Field label={text('detectionIou')}>
              <Input aria-label={text('detectionIou')} type="number" min={0.1} max={0.95} step={0.05}
                value={config.detection_iou} onChange={event => update({ detection_iou: Number(event.target.value) })} />
            </Field>}
            <p className="sm:col-span-2 text-xs leading-6 text-slate-500">{text(family === 'detection' ? 'detectionHint' : primary?.segmentation_thresholds ? 'thresholdHint' : 'thresholdUnavailable')}</p>
          </>}
          {family === "classification" && !!primary?.prediction_count && (
            <>
              <Field label={text("positive")}>
                <Select
                  ariaLabel={text("positive")}
                  value={config.positive_class}
                  onChange={(value) => update({ positive_class: value })}
                  options={(primary.classes || []).map((value) => ({
                    value,
                    label: value,
                  }))}
                />
              </Field>
              <Field label={text("average")}>
                <Select
                  ariaLabel={text("average")}
                  value={config.average}
                  onChange={(value) =>
                    update({ average: value as AnalysisConfig["average"] })
                  }
                  options={(
                    [
                      "macro",
                      "micro",
                      "weighted",
                      ...(primary.classes?.length === 2 ? ["binary"] : []),
                    ] as const
                  ).map((value) => ({
                    value,
                    label: text(
                      value as "macro" | "micro" | "weighted" | "binary",
                    ),
                  }))}
                />
              </Field>
              {primary.classes?.length === 2 && (
                <div className="sm:col-span-2 rounded-2xl bg-[color:var(--surface-muted)] p-4">
                  <label
                    className="flex items-center justify-between text-xs font-medium text-slate-600"
                    htmlFor="result-threshold"
                  >
                    {text("threshold")}
                    <span className="rounded-md bg-white px-2 py-1 font-mono text-slate-900">
                      {config.threshold.toFixed(2)}
                    </span>
                  </label>
                  <input
                    id="result-threshold"
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={config.threshold}
                    onChange={(event) =>
                      update({ threshold: Number(event.target.value) })
                    }
                    className="mt-3 w-full accent-slate-900"
                  />
                </div>
              )}
            </>
          )}
        </div>
      )}
      <section>
        <h3 className="text-sm font-semibold text-slate-900">
          {text("metrics")}
        </h3>
        <p className="mb-3 mt-1 text-xs leading-5 text-slate-500">
          {text("metricHelp")}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {[
            ...metrics.map((item) => ({
              id: item.id,
              label: metric(item.id, item.label),
              available: sources.some(
                (source) =>
                  capability(item, source) || item.id in source.metrics,
              ),
            })),
            ...customMetrics.map((id) => ({ id, label: id, available: true })),
          ].map((item) => (
            <div
              key={item.id}
              className={`flex min-w-0 items-center gap-3 rounded-xl px-3 py-2.5 ${config.metrics.includes(item.id) ? "bg-[color:var(--surface-muted)]" : ""}`}
            >
              <Checkbox
                aria-label={item.label}
                checked={config.metrics.includes(item.id)}
                disabled={!item.available && !config.metrics.includes(item.id)}
                onCheckedChange={() => toggleMetric(item.id)}
              />
              <button
                className={`min-w-0 flex-1 text-left text-xs leading-5 ${item.available ? "text-slate-700" : "text-slate-400"}`}
                disabled={!item.available}
                onClick={() => toggleMetric(item.id)}
                title={!item.available ? text("unavailable") : item.label}
              >
                {item.label}
              </button>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-slate-900">
          {text("charts")}
        </h3>
        <p className="mb-3 mt-1 text-xs leading-5 text-slate-500">
          {text("chartHelp")}
        </p>
        <div className="flex flex-wrap gap-2">
          {charts.map((item) => {
            const active = config.charts.some((value) => value.id === item.id);
            return (
              <Button
                size="sm"
                variant={active ? "default" : "outline"}
                key={item.id}
                disabled={
                  !active && !sources.some((source) => capability(item, source))
                }
                aria-pressed={active}
                onClick={() =>
                  update({
                    charts: active
                      ? config.charts.filter((value) => value.id !== item.id)
                      : [...config.charts, chartSpec(item.id)],
                  })
                }
              >
                {active && <Check size={12} className="mr-1.5" />}
                {chart(item.id)}
              </Button>
            );
          })}
        </div>
      </section>
      {predictionSources.length > 0 && (
        <AdvancedSection title={`${text("filters")} · ${text("grouping")}`}>
          <div className="grid gap-4 sm:grid-cols-2">
            {(["source", "gender"] as const).map((key) => (
              <Field key={key} label={text(key)}>
                <Input
                  aria-label={text(key)}
                  value={config.filters[key]}
                  onChange={(event) =>
                    update({
                      filters: { ...config.filters, [key]: event.target.value },
                    })
                  }
                />
              </Field>
            ))}
            {(["age_min", "age_max", "confidence_max"] as const).map((key) => (
              <Field
                key={key}
                label={
                  key === "confidence_max"
                    ? text("confidence")
                    : `${text("age")} · ${text(key === "age_min" ? "minimum" : "maximum")}`
                }
              >
                <Input
                  aria-label={key}
                  disabled={key === 'confidence_max' && family !== 'classification'}
                  type="number"
                  min="0"
                  max={key === "confidence_max" ? 1 : 150}
                  step={key === "confidence_max" ? 0.05 : 1}
                  value={config.filters[key] ?? ""}
                  onChange={(event) =>
                    update({
                      filters: {
                        ...config.filters,
                        [key]:
                          event.target.value === ""
                            ? null
                            : Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
            ))}
            <Field label={text("grouping")}>
              <Select
                ariaLabel={text("grouping")}
                value={config.group_by}
                onChange={(value) =>
                  update({ group_by: value as AnalysisConfig["group_by"] })
                }
                options={[
                  { value: "", label: text("none") },
                  ...(
                    ["source", "gender", "age_band", "dataset_id"] as const
                  ).map((value) => ({ value, label: text(value) })),
                ]}
              />
            </Field>
            <div className="flex items-center gap-3 sm:col-span-2">
              <Checkbox
                aria-label={text("errorsOnly")}
                disabled={family !== 'classification'}
                checked={config.filters.errors_only}
                onCheckedChange={(value) =>
                  update({ filters: { ...config.filters, errors_only: value } })
                }
              />
              <span className="text-xs text-slate-600">
                {text("errorsOnly")}
              </span>
            </div>
          </div>
        </AdvancedSection>
      )}
      {predictionSources.length > 0 && (
        <AdvancedSection title={text("interval")}>
          <div className="mb-4 flex items-center gap-3">
            <Checkbox
              aria-label={text("interval")}
              checked={config.interval.enabled}
              onCheckedChange={(value) =>
                update({ interval: { ...config.interval, enabled: value } })
              }
            />
            <span className="text-xs text-slate-600">
              {text("interval")} · {text("percentile")}
            </span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {(["level", "samples", "seed"] as const).map((key) => (
              <Field
                key={key}
                label={text(key === "samples" ? "repeats" : key)}
              >
                <Input
                  type="number"
                  aria-label={key}
                  min={key === "level" ? 0.8 : key === "samples" ? 50 : 0}
                  max={
                    key === "level"
                      ? 0.99
                      : key === "samples"
                        ? 2000
                        : 2147483647
                  }
                  step={key === "level" ? 0.01 : key === "samples" ? 50 : 1}
                  value={config.interval[key]}
                  onChange={(event) =>
                    update({
                      interval: {
                        ...config.interval,
                        [key]: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
            ))}
            <Field label={text("resampleUnit")}>
              <Select
                ariaLabel={text("resampleUnit")}
                value={config.interval.unit}
                onChange={(value) =>
                  update({
                    interval: {
                      ...config.interval,
                      unit: value as "case" | "sample",
                    },
                  })
                }
                options={[
                  { value: "case", label: text("case") },
                  { value: "sample", label: text("sample") },
                ]}
              />
            </Field>
          </div>
        </AdvancedSection>
      )}
    </div>
  );
}
