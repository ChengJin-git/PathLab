import { API_BASE } from "../config";
import { apiFetch } from "./client";
import { invalidateWSIListCache, type UpdatedDatasetProperties } from "./wsi";
import type { TaskType } from "../constants/training";

export interface DatasetDraft {
  name: string;
  description: string;
  data_type: "patch" | "wsi";
  aggregation_level: "file" | "case";
  task_types: TaskType[];
  source_organ: string;
  metadata: Record<string, unknown>;
  is_public: boolean;
}
export interface DatasetLabelImport {
  properties?: import("./wsi").DatasetPropertiesUpdate;
  revision: number;
  task_types: TaskType[];
  rows: Record<string, unknown>[];
  annotations: Partial<Record<TaskType, Record<string, unknown>>>;
}
export async function createDataset(
  draft: DatasetDraft,
): Promise<UpdatedDatasetProperties> {
  const value = await apiFetch<UpdatedDatasetProperties>(
    `${API_BASE}/wsi/datasets`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    },
  );
  invalidateWSIListCache();
  return value;
}
export async function importDatasetLabels(
  id: string,
  body: DatasetLabelImport,
): Promise<{ dataset: UpdatedDatasetProperties; updated_images: number }> {
  const value = await apiFetch<{
    dataset: UpdatedDatasetProperties;
    updated_images: number;
  }>(`${API_BASE}/wsi/datasets/${encodeURIComponent(id)}/labels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  invalidateWSIListCache();
  return value;
}
