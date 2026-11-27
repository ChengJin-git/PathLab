import { Plus, X } from "lucide-react";
import { useState } from "react";
import {
  TASK_TYPES,
  getTaskMetadata,
  type TaskType,
} from "../../constants/training";
import { Checkbox } from "../ui/checkbox";
import { useDatasetText } from "./text";

export function DatasetTaskChoices({
  dataType,
  value,
  onChange,
  disabled = false,
  retained = [],
}: {
  dataType: "wsi" | "patch";
  value: TaskType[];
  onChange: (tasks: TaskType[]) => void;
  disabled?: boolean;
  retained?: TaskType[];
}) {
  const text = useDatasetText();
  return (
    <fieldset disabled={disabled} className="space-y-3">
      <legend className="text-sm font-semibold text-slate-900">
        {text("tasks")}
      </legend>
      <p className="text-xs leading-5 text-slate-500">{text("taskHint")}</p>
      <div className="flex flex-wrap gap-2">
        {TASK_TYPES.filter(
          (item) => getTaskMetadata(item.value).dataType === dataType,
        ).map((item) => (
          <label
            key={item.value}
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${value.includes(item.value) ? "border-slate-400 bg-slate-50 text-slate-900" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}
          >
            <Checkbox
              checked={value.includes(item.value)}
              disabled={retained.includes(item.value)}
              onCheckedChange={(checked) =>
                onChange(
                  checked
                    ? [...value, item.value]
                    : value.filter((task) => task !== item.value),
                )
              }
            />
            {text(getTaskMetadata(item.value).taskFamily)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function DatasetMetadataFields({
  description,
  metadata,
  onDescription,
  onMetadata,
}: {
  description: string;
  metadata: Record<string, unknown>;
  onDescription: (value: string) => void;
  onMetadata: (value: Record<string, unknown>) => void;
}) {
  const text = useDatasetText();
  const known = [
    "institution",
    "stain",
    "license",
    "source_url",
    "time_unit",
    "label_definition",
  ] as const;
  const [newField, setNewField] = useState("");
  return (
    <div className="space-y-4">
      <label className="block space-y-2 text-sm font-medium text-slate-700">
        {text("description")}
        <textarea
          rows={3}
          value={description}
          onChange={(event) => onDescription(event.target.value)}
          placeholder={text("descriptionHint")}
          className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-primary-500/20"
        />
      </label>
      <details className="border-t border-slate-100 pt-3">
        <summary className="cursor-pointer text-sm font-medium text-slate-600">
          {text("details")}
        </summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {known.map((key) => (
            <label key={key} className="space-y-1 text-xs text-slate-600">
              {text(key)}
              <input
                value={String(metadata[key] ?? "")}
                onChange={(event) =>
                  onMetadata({ ...metadata, [key]: event.target.value })
                }
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          ))}
          {Object.entries(metadata)
            .filter(([key]) => !known.includes(key as (typeof known)[number]))
            .map(([key, value]) => (
              <div key={key} className="flex items-end gap-2">
                <label className="min-w-0 flex-1 space-y-1 text-xs text-slate-600">
                  {key}
                  <input
                    value={String(value)}
                    onChange={(event) =>
                      onMetadata({ ...metadata, [key]: event.target.value })
                    }
                    className="w-full rounded-lg border px-3 py-2 text-sm"
                  />
                </label>
                <button
                  type="button"
                  aria-label={`${text("cancel")} ${key}`}
                  onClick={() => {
                    const next = { ...metadata };
                    delete next[key];
                    onMetadata(next);
                  }}
                  className="p-2 text-slate-400"
                >
                  <X size={15} />
                </button>
              </div>
            ))}
        </div>
        <div className="mt-4 flex gap-2">
          <input
            aria-label={text("field")}
            placeholder={text("field")}
            value={newField}
            onChange={(event) => setNewField(event.target.value)}
            maxLength={100}
            className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={!newField.trim() || newField.trim() in metadata}
            className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 text-xs text-slate-600 disabled:opacity-40"
            onClick={() => {
              onMetadata({ ...metadata, [newField.trim()]: "" });
              setNewField("");
            }}
          >
            <Plus size={14} />
            {text("addField")}
          </button>
        </div>
      </details>
    </div>
  );
}
