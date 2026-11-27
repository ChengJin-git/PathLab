import { API_BASE } from "../config";
import { apiFetch, withAuthTokenQuery } from "./client";
import type { Geometry } from "./viewer";

export interface AnnotationRegion extends Geometry {
  id: string;
  label: string;
  color: string;
  created_by?: string;
}
export type AnnotationsMap = Record<string, AnnotationRegion[]>;
export type AnnotationSource = "imported_gt" | "user_label";
export interface DatasetGroundTruthResponse {
  dataset_id: string;
  annotations: AnnotationsMap;
  record_count: number;
  source: "ground_truth";
  annotation_source?: AnnotationSource | null;
  width?: number | null;
  height?: number | null;
}
export interface ExtractRegionsRequest {
  annotations?: AnnotationsMap;
  dataset_name: string;
  task_type: string;
  source_dataset_id?: string;
  dataset_scope?: boolean;
  source_organ?: string;
  annotation_mode?: "personal" | "shared";
}
export interface ExtractRegionsResponse {
  task_id: string;
  status: string;
}
export interface ExtractProgressEvent {
  task_id: string;
  progress: number | null;
  done?: boolean;
}
export function getWSILabels(
  wsiId: string,
  taskType?: "patch_segmentation" | "patch_detection",
): Promise<DatasetGroundTruthResponse> {
  return apiFetch(
    `${API_BASE}/annotation/wsi/${encodeURIComponent(wsiId)}/labels${taskType ? `?task_type=${taskType}` : ""}`,
  );
}
export function getLabelThumbnailUrl(wsiId: string, size = 160): string {
  return withAuthTokenQuery(
    `${API_BASE}/annotation/wsi/${encodeURIComponent(wsiId)}/label-thumbnail?size=${size}`,
  );
}
export function extractRegions(
  body: ExtractRegionsRequest,
): Promise<ExtractRegionsResponse> {
  return apiFetch(`${API_BASE}/annotation/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
export function getExtractProgressSSEUrl(taskId: string): string | null {
  const url = `${API_BASE}/annotation/extract/${encodeURIComponent(taskId)}/stream`;
  const authenticated = withAuthTokenQuery(url);
  return authenticated === url ? null : authenticated;
}
export interface AnnotationAuditEntry {
  id: number;
  dataset_id: string;
  dataset_name: string | null;
  user_id: string | null;
  user_display: string | null;
  event_type: string;
  event_metadata: Record<string, unknown>;
  created_at: string;
}
export interface AnnotationAuditResponse {
  entries: AnnotationAuditEntry[];
  count: number;
}
export function listAnnotationAudit(params: {
  dataset_id?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
}): Promise<AnnotationAuditResponse> {
  const query = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([key, value]) => [key, String(value)]),
  );
  return apiFetch(`${API_BASE}/annotation/audit?${query}`);
}
export function exportAnnotationAuditUrl(params: {
  dataset_id?: string;
  event_type?: string;
}): string {
  return `${API_BASE}/annotation/audit/export?${new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][])}`;
}
