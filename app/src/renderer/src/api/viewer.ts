import { API_BASE } from "../config";
import { apiFetch, withAuthTokenQuery } from "./client";
import { getWorkspaceSelection } from "../lib/workspaceSelection";

export type AnnotationLayer = "personal" | "shared";
export interface Geometry {
  type: "rect" | "polygon";
  x: number;
  y: number;
  width: number;
  height: number;
  points?: number[][];
  holes?: number[][][];
}
export interface RegionValue extends Geometry {
  label: string;
  color: string;
  task_type?: "patch_segmentation" | "patch_detection" | "patch_classification";
}
export interface ViewerRegion extends RegionValue {
  id: string;
  revision: number;
  created_by?: string;
  edited_by?: string;
  layer?: AnnotationLayer;
  score?: number;
}
export interface ViewerContext {
  wsi_id: string;
  name: string;
  dataset_id: string | null;
  dataset_name: string | null;
  width: number;
  height: number;
  mpp: number | null;
  data_type: "wsi" | "patch";
  can_personal: boolean;
  can_shared: boolean;
  can_manage: boolean;
  previous: string | null;
  next: string | null;
}
export interface FeatureSet {
  id: string;
  model_id: string;
  preprocessing_id: string;
  text_similarity: boolean;
  image_similarity: boolean;
  reason: string | null;
  revision: string;
}
export interface ViewerCapabilities {
  features: FeatureSet[];
  prompt_models: { id: string; name: string }[];
}
export interface RegionChange {
  id: string;
  revision: number;
  value: RegionValue | null;
}
export interface MutationResult {
  operation_id: string;
  changes: { id: string; revision: number; value: ViewerRegion | null }[];
}
export interface ViewerReply {
  message?: string;
  action?: string;
  status?: string;
  reason?: string;
  regions: ViewerRegion[];
  threshold?: number;
  label?: string;
  selected_ids?: string[];
  measurement?: { count: number; area_px: number; area_um2: number | null };
}
const root = (id: string) =>
  `${API_BASE}/viewer/slides/${encodeURIComponent(id)}`;
const json = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
export const viewerContext = (id: string, signal?: AbortSignal) =>
  apiFetch<ViewerContext>(`${root(id)}/context`, { signal });
export const viewerCapabilities = (id: string, signal?: AbortSignal) =>
  apiFetch<ViewerCapabilities>(`${root(id)}/capabilities`, { signal });
export const viewerRegions = (
  id: string,
  layer: AnnotationLayer,
  bbox?: Geometry,
  after = "",
  signal?: AbortSignal,
  limit = 50,
) => {
  const params = new URLSearchParams({ layer, after, limit: String(limit) });
  if (bbox)
    for (const key of ["x", "y", "width", "height"] as const)
      params.set(key, String(bbox[key]));
  return apiFetch<{
    items: ViewerRegion[];
    total: number;
    next_cursor: string | null;
  }>(`${root(id)}/regions?${params}`, { signal });
};
export const saveViewerRegions = (
  id: string,
  layer: AnnotationLayer,
  changes: RegionChange[],
  operation_id: string,
) =>
  apiFetch<MutationResult>(
    `${root(id)}/regions`,
    json({ layer, changes, operation_id }),
  );
export const resolveViewerRegions = (
  id: string,
  layer: AnnotationLayer,
  ids: string[],
  signal?: AbortSignal,
) =>
  apiFetch<{ items: ViewerRegion[]; revisions: Record<string, number> }>(
    `${root(id)}/regions/selection`,
    { ...json({ layer, ids }), signal },
  );
export const viewerEvents = (id: string, layer: AnnotationLayer) => {
  const workspace = getWorkspaceSelection().workspaceId;
  return withAuthTokenQuery(
    `${root(id)}/events?layer=${layer}${workspace ? "&workspace_id=" + encodeURIComponent(workspace) : ""}`,
  );
};
export const publishViewerReference = (
  id: string,
  layer: AnnotationLayer,
  regions: { id: string; revision: number }[],
) => apiFetch(`${root(id)}/reference-labels`, json({ layer, regions }));
export const assistRegion = (
  id: string,
  body: {
    region: Geometry;
    method: string;
    points?: number[][];
    tolerance?: number;
    model_id?: string;
  },
  signal?: AbortSignal,
) =>
  apiFetch<{ regions: Geometry[] }>(`${root(id)}/assist`, {
    ...json(body),
    signal,
  });
export const changeGeometry = (
  id: string,
  body: {
    operation: string;
    regions: Geometry[];
    points?: number[][];
    radius?: number;
  },
) => apiFetch<{ regions: Geometry[] }>(`${root(id)}/geometry`, json(body));
export const searchViewerFeatures = (
  id: string,
  body: {
    feature_id: string;
    query?: string;
    region?: Geometry;
    negative_regions?: Geometry[];
  },
  signal?: AbortSignal,
) => apiFetch<ViewerReply>(`${root(id)}/search`, { ...json(body), signal });
export const askViewer = (
  id: string,
  body: {
    message: string;
    language: string;
    layer: AnnotationLayer;
    task_id?: string;
    feature_id?: string;
    selected_ids: string[];
    selection?: Geometry;
    history: { role: string; content: string }[];
  },
  signal?: AbortSignal,
) => apiFetch<ViewerReply>(`${root(id)}/assistant`, { ...json(body), signal });
export function regionValue(region: ViewerRegion): RegionValue {
  const { type, x, y, width, height, points, holes, label, color, task_type } =
    region;
  return { type, x, y, width, height, points, holes, label, color, task_type };
}
