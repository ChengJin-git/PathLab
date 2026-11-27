import { API_BASE } from "../config";
import { apiFetch, apiFetchBlob, downloadBlobFile } from "./client";

export interface MetricValue {
  std?: number | null;
  value: number | null;
  label?: string;
  unit?: string;
  direction?: string;
  ci_lower?: number | null;
  ci_upper?: number | null;
  reason?: string;
  ci_valid_samples?: number;
}
export interface ChartSpec {
  id: string;
  title: string;
  color: string;
  visible: boolean;
  x_min: number | null;
  x_max: number | null;
}
export interface AnalysisConfig {
  source_ids: string[];
  facet_id: string;
  split: string;
  unit: "file" | "case";
  positive_class: string;
  average: "binary" | "macro" | "micro" | "weighted";
  threshold: number;
  detection_iou: number;
  metrics: string[];
  charts: ChartSpec[];
  group_by: "" | "source" | "gender" | "age_band" | "dataset_id";
  filters: {
    source: string;
    gender: string;
    age_min: number | null;
    age_max: number | null;
    confidence_max: number | null;
    errors_only: boolean;
  };
  interval: {
    enabled: boolean;
    level: number;
    samples: number;
    unit: "case" | "sample";
    seed: number;
  };
}
export interface ResultSource {
  task_families?: string[];
  facets?: {
    id: string;
    title: string;
    task_type: string;
    metric_keys: string[];
    chart_keys: string[];
  }[];
  research_title?: string;
  iteration?: number;
  source_id: string;
  title: string;
  kind: string;
  task_type: string;
  revision: string;
  task_id: string | null;
  session_id: string | null;
  prediction_count: number;
  gt_count?: number;
  probability_count?: number;
  classes?: string[];
  splits: string[];
  split_counts?: Record<string, number>;
  unit?: "file" | "case";
  metrics: Record<string, MetricValue>;
  dataset_ids: string[];
  model_id?: string;
  summary?: string;
  analysis_id?: string;
  segmentation_metrics?: boolean;
  segmentation_thresholds?: boolean;
  detection_boxes?: boolean;
  survival?: boolean;
  training_history?: boolean;
}
export interface Definition {
  id: string;
  label: string;
  family: string;
  requires: string;
  unit?: string;
  direction?: string;
}
export interface Catalog {
  version: string;
  metrics: Definition[];
  charts: Definition[];
}
export interface PlotData {
  kind: "line" | "bar" | "matrix";
  title?: string;
  color?: string;
  categories?: string[];
  classes?: string[];
  matrix?: number[][];
  step?: boolean;
  series?: {
    name: string;
    x?: number[];
    y: (number | null)[];
    metric?: number;
  }[];
}
export interface Sample {
  sample_id: string;
  wsi_id: string;
  filename?: string;
  case_id?: string;
  dataset_id?: string;
  label?: string;
  pred?: string;
  confidence?: number;
  source?: string;
  gender?: string;
  age?: number;
}
export interface SourceResult {
  source_id: string;
  title: string;
  revision: string;
  count: number | null;
  gt_count: number | null;
  metrics: Record<string, MetricValue>;
  charts: Record<string, PlotData>;
  groups: {
    group: string;
    count: number;
    metrics: Record<string, number | null>;
  }[];
  samples: Sample[];
  notes: string[];
}
export interface AnalysisRun {
  analysis_id: string;
  title: string;
  status: string;
  progress: number;
  phase: string;
  error: string | null;
  created_at: string;
  finished_at?: string;
  source_ids: string[];
  config?: AnalysisConfig;
  sources?: ResultSource[];
  result?: {
    native_artifact?: { task_id: string; analysis_id: string };
    results: SourceResult[];
    comparisons: {
      left: string;
      right: string;
      same_samples: boolean;
      overlap: number;
      disagreement: number | null;
      note: string;
    }[];
  };
}
export interface Recipe {
  recipe_id: string;
  name: string;
  config: AnalysisConfig;
  version: number;
}
export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
  source_ids: string[];
  action?: string;
  config?: AnalysisConfig;
  analysis_id?: string;
  handoff?: string;
}
export interface AssistantResponse {
  conversation_id: string;
  version: number;
  messages: AssistantMessage[];
  message: string;
  action: string;
  config?: AnalysisConfig;
  run?: AnalysisRun;
  handoff?: string;
}
export interface Page<T> {
  items: T[];
  has_more: boolean;
}
export const resultBase = () => `${API_BASE}/results/workbench`;
export function resultGet<T>(
  path: string,
  params: Record<string, string | number | undefined> = {},
  signal?: AbortSignal,
) {
  const search = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [key, String(value)]),
  );
  return apiFetch<T>(`${resultBase()}${path}${search.size ? `?${search}` : ""}`, {
    signal,
  });
}
export function resultSend<T>(
  path: string,
  body?: unknown,
  method = "POST",
  signal?: AbortSignal,
) {
  return apiFetch<T>(`${resultBase()}${path}`, {
    method,
    signal,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
export async function exportAnalysis(
  id: string,
  format: "json" | "csv" | "inputs" | "original",
) {
  const blob = await apiFetchBlob(
    `${resultBase()}/runs/${id}/export?format=${format}`,
  );
  downloadBlobFile(
    blob,
    `${id}${format === "inputs" ? "_inputs" : ""}.${format === "csv" ? "csv" : "json"}`,
  );
}
export function chartSpec(id: string): ChartSpec {
  return {
    id,
    title: "",
    color: "#2563eb",
    visible: true,
    x_min: null,
    x_max: null,
  };
}
export function defaultConfig(source?: ResultSource): AnalysisConfig {
  const survival = source?.task_type.includes("survival"),
    segmentation = source?.task_type.includes("segmentation"),
    detection = source?.task_type === "patch_detection";
  const metrics = !source?.prediction_count
    ? Object.keys(source?.metrics || {}).slice(0, 8)
    : detection ? source?.gt_count ? ['map', 'map_50', 'detection_precision', 'detection_recall'] : ['detection_count'] : survival
      ? source?.gt_count
        ? ["c_index", "mean_risk"]
        : ["sample_count", "mean_risk"]
      : segmentation
        ? source?.segmentation_metrics
          ? ["dice", (source.classes?.length || 0) > 1 ? "miou" : "iou"]
          : ["sample_count"]
        : source.gt_count
          ? ["accuracy", "auc", "f1", "balanced_accuracy"]
          : source.probability_count
            ? ["mean_confidence", "entropy"]
            : ["sample_count"];
  return {
    source_ids: source ? [source.source_id] : [],
    facet_id: "",
    split: source?.splits.includes("test")
      ? "test"
      : source?.splits[0] || "unassigned",
    unit: source?.unit || "file",
    positive_class: source?.classes?.at(-1) || "",
    average: "macro",
    threshold: 0.5,
    detection_iou: 0.5,
    metrics,
    charts: (detection ? source?.gt_count ? ['detection_pr'] : [] : survival
      ? source?.gt_count
        ? ["km", "risk"]
        : ["risk"]
      : segmentation
        ? source?.segmentation_metrics
          ? ["segmentation"]
          : []
        : source?.gt_count
          ? ["roc", "confusion"]
          : source?.prediction_count
            ? source.probability_count
              ? ["distribution", "confidence"]
              : ["distribution"]
            : ["comparison"]
    ).map(chartSpec),
    group_by: "",
    filters: {
      source: "",
      gender: "",
      age_min: null,
      age_max: null,
      confidence_max: null,
      errors_only: false,
    },
    interval: {
      enabled: false,
      level: 0.95,
      samples: 200,
      unit: "case",
      seed: 42,
    },
  };
}
