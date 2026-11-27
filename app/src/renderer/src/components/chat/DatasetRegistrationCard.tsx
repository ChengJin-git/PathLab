import { useNavigate } from "react-router-dom";
import { Database, ArrowRight } from "lucide-react";
import { Button } from "../ui/button";
import { useDatasetText } from "../datasets/text";
import { getTaskMetadata, type TaskType } from "../../constants/training";

interface DatasetRegistrationConfig {
  dataset_id?: string;
  dataset_name?: string;
  data_type: "patch" | "wsi";
  task_types: TaskType[];
  aggregation_level?: "file" | "case";
  description?: string;
  source_organ?: string;
  metadata?: Record<string, unknown>;
  is_public?: boolean;
  initial_tab?: "images" | "labels";
}

export function parseDatasetRegistrationConfig(
  content: string,
): DatasetRegistrationConfig | null {
  const match = content.match(
    /\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/,
  );
  if (!match) return null;
  try {
    const value = JSON.parse(match[1]) as DatasetRegistrationConfig;
    if (
      !["patch", "wsi"].includes(value.data_type) ||
      !Array.isArray(value.task_types) ||
      !value.task_types.length
    )
      return null;
    if (
      value.task_types.some(
        (task) => getTaskMetadata(task).dataType !== value.data_type,
      )
    )
      return null;
    return value;
  } catch {
    return null;
  }
}

export function removeDatasetRegistrationBlock(content: string): string {
  return content
    .replace(/\[DATASET_REGISTRATION\][\s\S]*?\[\/DATASET_REGISTRATION\]/g, "")
    .trim();
}

export function DatasetRegistrationCard({
  config,
  disabled,
}: {
  config: DatasetRegistrationConfig;
  disabled?: boolean;
}) {
  const navigate = useNavigate();
  const text = useDatasetText();
  return (
    <section className="my-3 space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Database size={16} />
        {config.dataset_name || text("overview")}
      </h3>
      <p className="text-xs leading-6 text-slate-500">
        {text(config.data_type)} ·{" "}
        {config.task_types
          .map((task) => text(getTaskMetadata(task).taskFamily))
          .join(" / ")}
      </p>
      {config.description && (
        <p className="text-sm leading-6 text-slate-600">{config.description}</p>
      )}
      <Button
        size="sm"
        disabled={disabled}
        onClick={() =>
          navigate("/upload", {
            state: {
              datasetId: config.dataset_id,
              datasetName: config.dataset_name,
              taskTypes: config.task_types,
              dataType: config.data_type,
              dataLevel: config.aggregation_level || "file",
              description: config.description,
              sourceOrgan: config.source_organ,
              metadata: config.metadata,
              isPublic: config.is_public,
              initialTab: config.initial_tab,
              fromAIChat: true,
            },
          })
        }
      >
        {text(config.initial_tab === "labels" ? "labels" : "append")}
        <ArrowRight size={14} className="ml-2" />
      </Button>
    </section>
  );
}
