import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FilePenLine, Loader2 } from "lucide-react";
import {
  fetchDatasetSummary,
  type DatasetPropertiesUpdate,
} from "../../api/wsi";
import { importDatasetLabels } from "../../api/datasetCatalog";
import DatasetEditor from "../datasets/DatasetEditor";
import { useDatasetText } from "../datasets/text";
import { Button } from "../ui/button";

export interface DatasetEditConfig {
  dataset_id: string;
  summary: string;
  properties?: DatasetPropertiesUpdate;
  rows?: Record<string, unknown>[];
  annotations?: Record<string, Record<string, unknown>>;
}
export function parseDatasetEdit(content: string): DatasetEditConfig | null {
  const match = content.match(/\[DATASET_EDIT\]([\s\S]*?)\[\/DATASET_EDIT\]/);
  if (!match) return null;
  try {
    const value = JSON.parse(match[1]);
    return typeof value.dataset_id === "string" &&
      value.dataset_id &&
      typeof value.summary === "string"
      ? value
      : null;
  } catch {
    return null;
  }
}
export default function DatasetEditCard({
  config,
  disabled,
}: {
  config: DatasetEditConfig;
  disabled?: boolean;
}) {
  const text = useDatasetText();
  const query = useQuery({
    queryKey: ["dataset-edit", config.dataset_id],
    queryFn: () => fetchDatasetSummary(config.dataset_id, "upload"),
  });
  const [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false),
    [error, setError] = useState(""),
    [editor, setEditor] = useState(false);
  const apply = async () => {
    if (!query.data) return;
    setBusy(true);
    setError("");
    try {
      await importDatasetLabels(config.dataset_id, {
        revision: query.data.revision,
        properties: config.properties
          ? {
              ...config.properties,
              ...(config.properties.metadata
                ? {
                    metadata: {
                      ...query.data.metadata,
                      ...config.properties.metadata,
                    },
                  }
                : {}),
            }
          : undefined,
        task_types: config.properties?.task_types || query.data.task_types,
        rows: config.rows || [],
        annotations: config.annotations || {},
      });
      setSaved(true);
      await query.refetch();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="my-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <FilePenLine size={16} />
        {query.data?.dataset_name || text("overview")}
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{config.summary}</p>
      {query.error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {String(query.error)}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          disabled={disabled || busy || saved || !query.data}
          onClick={apply}
        >
          {busy && <Loader2 size={14} className="mr-2 animate-spin" />}
          {text(saved ? "saved" : "save")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={disabled || busy || !query.data}
          onClick={() => setEditor(true)}
        >
          {text("tasks")}
        </Button>
      </div>
      {editor && (
        <DatasetEditor
          datasetId={config.dataset_id}
          initialTab="labels"
          onClose={() => setEditor(false)}
          onSaved={() => {
            void query.refetch();
          }}
        />
      )}
    </div>
  );
}
