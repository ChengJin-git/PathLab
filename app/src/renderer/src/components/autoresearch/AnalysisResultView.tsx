import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { API_BASE } from "../../config";
import { apiFetch } from "../../api/client";
import { readResearchImage } from "../../api/autoresearch";
import {
  ConfusionMatrixChart,
  RocCurveChart,
  KMCurveChart,
  LossCurveChart,
  type ConfusionMatrixData,
  type RocCurveData,
  type KMCurveData,
  type LossCurveData,
} from "../charts/AnalysisCharts";
import MetricValues, { type MeasuredMetric } from "../charts/MetricValues";
import { useConversationFiles } from "../chat/ConversationFiles";
import { useWorkbenchText } from "../chat/workbenchText";

interface Result {
  title: string;
  summary: string;
  code_path: string;
  source_files: string[];
  metrics: Record<string, MeasuredMetric>;
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

function AnalysisFigure({
  sessionId,
  figure,
}: {
  sessionId: string;
  figure: Result["figures"][number];
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const files = useConversationFiles();
  const raster = /\.(png|jpe?g|webp)$/i.test(figure.path);
  useEffect(() => {
    if (!raster) return;
    const controller = new AbortController();
    let object = "";
    setUrl("");
    setError("");
    readResearchImage(sessionId, figure.path, controller.signal)
      .then((blob) => {
        if (!controller.signal.aborted) {
          object = URL.createObjectURL(blob);
          setUrl(object);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => {
      controller.abort();
      if (object) URL.revokeObjectURL(object);
    };
  }, [sessionId, figure.path, raster]);
  return (
    <figure className="overflow-hidden rounded-lg border border-gray-200">
      <button
        onClick={() => files?.openFile({ sessionId, path: figure.path })}
        className="block w-full p-3 text-left text-sm text-gray-700"
      >
        <span className="font-medium">
          {figure.title || figure.path.split("/").at(-1)}
        </span>
        {url && (
          <img
            src={url}
            alt={figure.title}
            className="mt-3 max-h-96 w-full object-contain"
          />
        )}
      </button>
      {figure.caption && (
        <figcaption className="px-3 pb-3 text-xs leading-5 text-gray-500">
          {figure.caption}
        </figcaption>
      )}
      {error && <p className="px-3 pb-3 text-xs text-red-600">{error}</p>}
    </figure>
  );
}

export default function AnalysisResultView({
  sessionId,
  analysisId,
  userId,
  version,
}: {
  sessionId: string;
  analysisId: string;
  userId: string;
  version?: string;
}) {
  const text = useWorkbenchText();
  const files = useConversationFiles();
  const query = useQuery({
    queryKey: ["analysis-result", userId, sessionId, analysisId, version],
    queryFn: ({ signal }) =>
      apiFetch<Result>(
        `${API_BASE}/research/sessions/${encodeURIComponent(sessionId)}/analysis/${encodeURIComponent(analysisId)}`,
        { signal },
      ),
    staleTime: 10000,
  });
  if (query.isLoading)
    return <p className="py-3 text-xs text-gray-400">{text("loading")}</p>;
  if (query.error)
    return (
      <p role="alert" className="py-3 text-xs text-red-600">
        {String(query.error)}
      </p>
    );
  const data = query.data;
  if (!data) return null;
  return (
    <section className="space-y-4" aria-label={data.title}>
      <div>
        <h3 className="text-sm font-semibold text-gray-900">{data.title}</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600">
          {data.summary}
        </p>
      </div>
      <MetricValues metrics={data.metrics} preserveUnits />
      {data.chart_data.confusion_matrix && (
        <ConfusionMatrixChart
          data={data.chart_data.confusion_matrix}
          title=""
          compact
        />
      )}
      {data.chart_data.roc_curve && (
        <RocCurveChart data={data.chart_data.roc_curve} title="" compact />
      )}
      {data.chart_data.km_curve && (
        <KMCurveChart data={data.chart_data.km_curve} title="" compact />
      )}
      {data.chart_data.loss_curve && (
        <LossCurveChart data={data.chart_data.loss_curve} title="" compact />
      )}
      {data.figures.map((figure) => (
        <AnalysisFigure
          key={figure.path}
          sessionId={sessionId}
          figure={figure}
        />
      ))}
      {data.tables.map((table, index) => (
        <section key={index}>
          <h4 className="mb-2 text-xs font-medium text-gray-600">
            {table.title}
          </h4>
          <div className="max-h-96 overflow-auto rounded-lg border">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-gray-50">
                <tr>
                  {table.columns.map((column, i) => (
                    <th key={i} className="whitespace-nowrap border-b p-2">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className="border-b p-2">
                        {cell ?? "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <button
        onClick={() => files?.openFile({ sessionId, path: data.code_path })}
        className="text-xs text-gray-500 underline underline-offset-2"
      >
        {text("analysisCode")}
      </button>
    </section>
  );
}
