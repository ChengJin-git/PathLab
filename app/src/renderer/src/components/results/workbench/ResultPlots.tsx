import { useMemo, useRef } from "react";
import type EChartsReact from "echarts-for-react";
import type { EChartsOption } from "echarts";
import ReactECharts from "../../charts/LazyECharts";
import type {
  AnalysisConfig,
  AnalysisRun,
  ChartSpec,
  PlotData,
  SourceResult,
} from "../../../api/resultWorkbench";
import { useResultText } from "./text";
import { Card } from "../../ui/card";
import { Button } from "../../ui/button";

const palette = [
  "#2563eb",
  "#0d9488",
  "#d97706",
  "#9333ea",
  "#dc2626",
  "#475569",
  "#0891b2",
  "#65a30d",
];
function Plot({
  data,
  spec,
  title,
}: {
  data: PlotData;
  spec?: ChartSpec;
  title: string;
}) {
  const ref = useRef<EChartsReact>(null);
  const { text } = useResultText();
  const option = useMemo<EChartsOption>(() => {
    const common: EChartsOption = {
      animation: false,
      color: [spec?.color || data.color || palette[0], ...palette.slice(1)],
      grid: { left: 55, right: 25, top: 50, bottom: 55 },
      tooltip: { trigger: "axis", renderMode: "richText" },
      legend: { type: "scroll", textStyle: { fontSize: 11 } },
    };
    if (data.kind === "matrix") {
      return {
        ...common,
        tooltip: { trigger: "item", renderMode: "richText" },
        grid: { left: 85, right: 30, top: 20, bottom: 70 },
        xAxis: {
          type: "category",
          data: data.classes,
          name: text("predicted"),
        },
        yAxis: { type: "category", data: data.classes, name: text("actual") },
        visualMap: {
          min: 0,
          max: Math.max(1, ...data.matrix!.flat()),
          orient: "horizontal",
          left: "center",
          bottom: 0,
          inRange: { color: ["#eff6ff", "#2563eb"] },
        },
        series: [
          {
            type: "heatmap",
            data: data.matrix!.flatMap((row, y) =>
              row.map((value, x) => [x, y, value]),
            ),
            label: { show: data.classes!.length < 12 },
          },
        ],
      };
    }
    return {
      ...common,
      xAxis: data.categories
        ? {
            type: "category",
            data: data.categories,
            axisLabel: { hideOverlap: true },
          }
        : {
            type: "value",
            min: spec?.x_min ?? undefined,
            max: spec?.x_max ?? undefined,
          },
      yAxis: { type: "value", scale: true },
      series: (data.series || []).map((line) => ({
        name: line.name,
        type: data.kind === "bar" ? "bar" : "line",
        step: data.step ? "end" : undefined,
        showSymbol: false,
        connectNulls: false,
        data: line.x ? line.x.map((x, i) => [x, line.y[i]]) : line.y,
        lineStyle: { width: 2 },
      })),
    };
  }, [data, spec, text]);
  const download = (type: "png" | "svg") => {
    if (!ref.current) return;
    const link = document.createElement("a");
    link.href = ref.current
      .getEchartsInstance()
      .getDataURL({ type, pixelRatio: 3, backgroundColor: "#fff" });
    link.download = `${title}.${type}`;
    link.click();
  };
  return (
    <Card className="min-w-0 p-5">
      <header className="mb-3 flex items-start justify-between gap-3">
        <h3 className="text-sm font-medium text-slate-900">
          {spec?.title || title}
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0"
          onClick={() => download("png")}
        >
          PNG ↓
        </Button>
      </header>
      <ReactECharts
        ref={ref}
        option={option}
        notMerge
        style={{ height: 300 }}
      />
    </Card>
  );
}

export default function ResultPlots({
  run,
  config,
  compact = false,
}: {
  run: AnalysisRun;
  config: AnalysisConfig;
  compact?: boolean;
}) {
  const { chart, metric } = useResultText();
  const results = run.result?.results || [];
  const plots: {
    key: string;
    title: string;
    data: PlotData;
    spec?: ChartSpec;
  }[] = [];
  const ids = [
    ...new Set(results.flatMap((result) => Object.keys(result.charts))),
  ];
  for (const id of ids) {
    const spec = config.charts.find((chart) => chart.id === id);
    if (spec && !spec.visible) continue;
    const available = results.filter((result) => result.charts[id]);
    if (
      available.length > 1 &&
      available.every((result) => result.charts[id].kind === "line") &&
      ["roc", "pr", "calibration", "threshold", "km"].includes(id)
    ) {
      plots.push({
        key: id,
        title: chart(id),
        spec,
        data: {
          ...available[0].charts[id],
          series: available.flatMap((result) =>
            (result.charts[id].series || []).map((line) => ({
              ...line,
              name: `${result.title} · ${line.name}`,
            })),
          ),
        },
      });
    } else
      for (const result of available)
        plots.push({
          key: `${result.source_id}:${id}`,
          title:
            results.length === 1 ? chart(id) : `${result.title} · ${chart(id)}`,
          data: result.charts[id],
          spec,
        });
  }
  if (
    results.length > 1 &&
    config.charts.some((c) => c.id === "comparison" && c.visible)
  ) {
    for (const key of config.metrics) {
      plots.push({
        key: `compare:${key}`,
        title: metric(key),
        data: {
          kind: "bar",
          categories: results.map((r) => r.title),
          series: [
            { name: key, y: results.map((r) => r.metrics[key]?.value ?? null) },
          ],
        },
      });
    }
  }
  if (config.charts.some(item => item.id === 'disagreement' && item.visible) && run.result?.comparisons.length) {
    const pairs = run.result.comparisons.filter(pair => pair.disagreement !== null)
    if (pairs.length) plots.push({ key: 'disagreement', title: chart('disagreement'), data: {
      kind: 'bar', categories: pairs.map(pair => `${results.find(item => item.source_id === pair.left)?.title} / ${results.find(item => item.source_id === pair.right)?.title}`),
      series: [{ name: chart('disagreement'), y: pairs.map(pair => pair.disagreement) }],
    } })
  }
  return (
    <div
      className={`grid min-w-0 gap-4 ${compact ? "grid-cols-1" : "xl:grid-cols-2"}`}
    >
      {plots.map(({ key, ...plot }) => (
        <Plot key={key} {...plot} />
      ))}
    </div>
  );
}

export function metricText(value: SourceResult["metrics"][string] | undefined) {
  if (value?.value == null) return "—";
  const format = (number: number) =>
    value.unit === "ratio"
      ? `${(number * 100).toFixed(2)}%`
      : `${number.toLocaleString(undefined, { maximumFractionDigits: 4 })}${value.unit ? ` ${value.unit}` : ""}`;
  return `${format(value.value)}${value.ci_lower != null && value.ci_upper != null ? ` [${format(value.ci_lower)}, ${format(value.ci_upper)}]` : ""}`;
}
