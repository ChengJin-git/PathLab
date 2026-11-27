import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetchBlob, downloadBlobFile } from "../../../api/client";
import {
  resultBase,
  resultGet,
  type MetricValue,
  type ResultSource,
} from "../../../api/resultWorkbench";
import {
  ConfusionMatrixChart,
  RocCurveChart,
  KMCurveChart,
  LossCurveChart,
  type ConfusionMatrixData,
  type RocCurveData,
  type KMCurveData,
  type LossCurveData,
} from "../../charts/AnalysisCharts";
import { metricText } from "./ResultPlots";
import { useResultText } from "./text";

interface Published {
  tasks?: {
    id: string;
    title: string;
    task_type: string;
    metric_keys: string[];
    chart_keys: string[];
    figure_paths?: string[];
    table_indices?: number[];
  }[];
  title: string;
  summary: string;
  metrics: Record<string, MetricValue | number>;
  code_path: string;
  chart_data: {
    confusion_matrix?: ConfusionMatrixData;
    roc_curve?: RocCurveData;
    km_curve?: KMCurveData;
    loss_curve?: LossCurveData;
  };
  figures: { path: string; title: string; caption: string }[];
  tables: {
    title: string;
    columns: string[];
    rows: (string | number | null)[][];
  }[];
}
function Figure({
  sourceId,
  figure,
}: {
  sourceId: string;
  figure: Published["figures"][number];
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const endpoint = `${resultBase()}/source/figure?${new URLSearchParams({ source_id: sourceId, path: figure.path })}`;
  useEffect(() => {
    const controller = new AbortController();
    let object = "";
    apiFetchBlob(endpoint, { signal: controller.signal })
      .then((blob) => {
        if (!controller.signal.aborted) {
          object = URL.createObjectURL(blob);
          setUrl(object);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(String(e));
      });
    return () => {
      controller.abort();
      if (object) URL.revokeObjectURL(object);
    };
  }, [endpoint]);
  return (
    <figure className="rounded-lg border p-3">
      <figcaption className="mb-2 text-sm font-medium">
        {figure.title}
      </figcaption>
      {url &&
        (/\.pdf$/i.test(figure.path) ? (
          <a href={url} target="_blank" rel="noreferrer">
            PDF ↗
          </a>
        ) : (
          <img
            className="max-h-96 w-full object-contain"
            src={url}
            alt={figure.title}
            loading="lazy"
          />
        ))}
      <p className="mt-2 text-xs text-slate-500">{figure.caption}</p>
      {error && <p role="alert">{error}</p>}
    </figure>
  );
}
export default function PublishedAnalysis({
  source,
  scopeKey,
  facetId,
}: {
  source: ResultSource;
  scopeKey: string;
  facetId?: string;
}) {
  const { text, chart, metric } = useResultText();
  const query = useQuery({
    queryKey: ["result-published", scopeKey, source.source_id, source.revision],
    queryFn: ({ signal }) =>
      resultGet<Published>(
        "/source/artifact",
        { source_id: source.source_id },
        signal,
      ),
  });
  if (query.isLoading) return <p role="status">{text("loading")}</p>;
  if (query.error)
    return (
      <p role="alert" className="text-sm text-red-600">
        {String(query.error)}
      </p>
    );
  if (!query.data) return null;
  const facet = query.data.tasks?.find((task) => task.id === facetId);
  const data = facet
    ? {
        ...query.data,
        metrics: Object.fromEntries(
          Object.entries(query.data.metrics).filter(([key]) =>
            facet.metric_keys.includes(key),
          ),
        ),
        chart_data: Object.fromEntries(
          Object.entries(query.data.chart_data).filter(([key]) =>
            facet.chart_keys.includes(key),
          ),
        ) as Published["chart_data"],
      }
    : query.data;
  return (
    <div className="space-y-5">
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
        {data.summary}
      </p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {Object.entries(data.metrics).map(([key, item]) => (
          <div key={key} className="rounded-lg border p-3">
            <p className="break-all text-xs text-slate-500">
              {metric(key, typeof item === "object" ? item.label : undefined)}
            </p>
            <p className="mt-1 font-mono text-sm">
              {metricText(typeof item === "number" ? { value: item } : item)}
            </p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {data.chart_data.confusion_matrix && (
          <ConfusionMatrixChart
            data={data.chart_data.confusion_matrix}
            title={chart("confusion")}
            compact
          />
        )}
        {data.chart_data.roc_curve && (
          <RocCurveChart
            data={data.chart_data.roc_curve}
            title={chart("roc")}
            compact
          />
        )}
        {data.chart_data.km_curve && (
          <KMCurveChart
            data={data.chart_data.km_curve}
            title={chart("km")}
            compact
          />
        )}
        {data.chart_data.loss_curve && (
          <LossCurveChart
            data={data.chart_data.loss_curve}
            title={chart("loss")}
            compact
          />
        )}
        {data.figures
          .filter(
            (figure) =>
              !facet ||
              !facet.figure_paths?.length ||
              facet.figure_paths.includes(figure.path),
          )
          .map((figure) => (
            <Figure
              key={figure.path}
              figure={figure}
              sourceId={source.source_id}
            />
          ))}
      </div>
      {data.tables.map(
        (table, i) =>
          (!facet ||
            !facet.table_indices?.length ||
            facet.table_indices.includes(i)) && (
            <section key={i}>
              <h3 className="mb-2 text-sm font-medium">{table.title}</h3>
              <div className="max-h-96 overflow-auto rounded-lg border">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr>
                      {table.columns.map((c, j) => (
                        <th key={j} className="sticky top-0 bg-slate-50 p-2">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, k) => (
                      <tr key={k}>
                        {row.map((cell, l) => (
                          <td key={l} className="border-t p-2">
                            {cell ?? "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ),
      )}
      <button
        className="text-xs text-blue-600"
        onClick={async () => {
          const blob = await apiFetchBlob(
            `${resultBase()}/source/figure?${new URLSearchParams({ source_id: source.source_id, path: data.code_path })}`,
          );
          downloadBlobFile(
            blob,
            data.code_path.split("/").at(-1) || "analysis.py",
          );
        }}
      >
        {text("openCode")} ↓
      </button>
    </div>
  );
}
