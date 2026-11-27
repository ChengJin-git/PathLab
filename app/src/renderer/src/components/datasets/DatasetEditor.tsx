import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Upload, X } from "lucide-react";
import {
  fetchDatasetSummary,
  updateDatasetProperties,
  type UpdatedDatasetProperties,
} from "../../api/wsi";
import { importDatasetLabels } from "../../api/datasetCatalog";
import type { TaskType } from "../../constants/training";
import { getTaskMetadata } from "../../constants/training";
import { ModalShell } from "../ui/modal-shell";
import { Button } from "../ui/button";
import { DatasetMetadataFields, DatasetTaskChoices } from "./DatasetFields";
import { useDatasetText } from "./text";
import { parseLabelFiles } from "./labelImport";
import { Checkbox } from "../ui/checkbox";
import { useTranslation } from "react-i18next";
import { UploadAttachment } from "../upload/UploadAttachment";
import { useUploadText } from "../upload/uploadText";
import "../upload/upload.css";

export default function DatasetEditor({
  datasetId,
  initialTab = "details",
  onClose,
  onSaved,
  embedded = false,
  onBusyChange,
}: {
  datasetId: string;
  initialTab?: "details" | "labels";
  onClose: () => void;
  onSaved: (saved: UpdatedDatasetProperties) => void;
  embedded?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const text = useDatasetText();
  const copy = useUploadText();
  const { t } = useTranslation();
  const dataset = useQuery({
    queryKey: ["dataset-editor", datasetId],
    queryFn: () => fetchDatasetSummary(datasetId, "upload"),
    refetchOnWindowFocus: false,
  });
  const [tab, setTab] = useState(initialTab);
  const [name, setName] = useState(""),
    [description, setDescription] = useState("");
  const [metadata, setMetadata] = useState<Record<string, unknown>>({});
  const [tasks, setTasks] = useState<TaskType[]>([]);
  const [source, setSource] = useState(""),
    [isPublic, setIsPublic] = useState(false);
  const [table, setTable] = useState<File | null>(null);
  const [annotations, setAnnotations] = useState<
    Partial<Record<TaskType, File>>
  >({});
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  useEffect(() => {
    if (!dataset.data) return;
    setName(dataset.data.dataset_name);
    setDescription(dataset.data.description || "");
    setMetadata(dataset.data.metadata);
    setTasks(dataset.data.task_types);
    setSource(dataset.data.source_organ || "");
    setIsPublic(!!dataset.data.is_public);
  }, [dataset.data]);
  const save = async () => {
    if (!dataset.data) return;
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    setNotice("");
    try {
      let saved: UpdatedDatasetProperties;
      if (tab === "details") {
        saved = (
          await updateDatasetProperties(datasetId, {
            name,
            description,
            metadata,
            remove_metadata: Object.keys(dataset.data.metadata).filter(
              (key) => !(key in metadata),
            ),
            task_types: tasks,
            source,
            is_public: isPublic,
            revision: dataset.data.revision,
          })
        ).dataset;
      } else {
        const values = await parseLabelFiles(table, annotations);
        const result = await importDatasetLabels(datasetId, {
          revision: dataset.data.revision,
          task_types: tasks,
          ...values,
        });
        saved = result.dataset;
        setNotice(
          `${text("saved")} · ${result.updated_images} ${text("images")}`,
        );
        setTable(null);
        setAnnotations({});
      }
      onSaved(saved);
      if (tab === "details") onClose();
      else await dataset.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  };
  const content = (
    <div className="upload-page upload-label-workspace">
      {!embedded && (
        <header className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-900">
            {text("overview")}
          </h2>
          <button
            aria-label={text("cancel")}
            disabled={busy}
            onClick={onClose}
            className="rounded p-2 text-slate-500 hover:bg-slate-50"
          >
            <X size={18} />
          </button>
        </header>
      )}
      {dataset.isLoading ? (
        <div className="p-12">
          <Loader2 className="mx-auto animate-spin" />
        </div>
      ) : (
        dataset.data && (
          <>
            {!embedded && (
              <div className="flex gap-5 border-b border-slate-100 px-6 text-sm">
                {(["details", "labels"] as const).map((value) => (
                  <button
                    key={value}
                    onClick={() => setTab(value)}
                    className={`border-b-2 py-3 ${tab === value ? "border-slate-900 font-medium text-slate-900" : "border-transparent text-slate-500"}`}
                  >
                    {text(value === "details" ? "edit" : "tasks")}
                  </button>
                ))}
              </div>
            )}
            {tab === "labels" && (
              <div
                className="upload-label-coverage"
                aria-label={copy("labelCoverage")}
              >
                <p className="upload-aside-label">{copy("labelCoverage")}</p>
                {dataset.data.tasks.map((task) => (
                  <div key={task.task_type}>
                    <span>
                      {text(getTaskMetadata(task.task_type).taskFamily)}
                    </span>
                    <p>
                      {task.labelled_count} / {task.sample_count} ·{" "}
                      {text(task.status)}
                    </p>
                  </div>
                ))}
              </div>
            )}
            <fieldset
              disabled={busy}
              className={`upload-label-editor-body space-y-6 ${embedded ? "" : "max-h-[60vh] overflow-y-auto"} px-6 py-5`}
            >
              {tab === "details" && (
                <input
                  aria-label="Dataset name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
                />
              )}
              {tab === "details" && (
                <label className="block space-y-2 text-sm text-slate-600">
                  {t("uploadComponents.datasetConfig.sourceOrganTissue")}
                  <input
                    value={source}
                    onChange={(event) => setSource(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2"
                  />
                </label>
              )}
              <DatasetTaskChoices
                dataType={dataset.data.data_type}
                value={tasks}
                retained={
                  tab === "labels"
                    ? dataset.data.task_types
                    : dataset.data.tasks
                        .filter((task) => task.labelled_count > 0)
                        .map((task) => task.task_type)
                }
                onChange={setTasks}
              />
              {tab === "labels" &&
                tasks.some(
                  (task) => !dataset.data!.task_types.includes(task),
                ) && (
                  <p className="text-xs text-indigo-600">
                    {copy("newTask")} ·{" "}
                    {tasks
                      .filter(
                        (task) => !dataset.data!.task_types.includes(task),
                      )
                      .map((task) => text(getTaskMetadata(task).taskFamily))
                      .join(" / ")}
                  </p>
                )}
              {tab === "details" ? (
                <DatasetMetadataFields
                  description={description}
                  metadata={metadata}
                  onDescription={setDescription}
                  onMetadata={setMetadata}
                />
              ) : (
                <>
                  <div>
                    <UploadAttachment
                      label={text("table")}
                      hint={copy("csvHint")}
                      accept=".csv"
                      file={table}
                      onChange={(event) =>
                        setTable(event.target.files?.[0] || null)
                      }
                      onRemove={() => setTable(null)}
                      disabled={busy}
                    />
                    {tasks
                      .filter((task) =>
                        ["patch_segmentation", "patch_detection"].includes(
                          task,
                        ),
                      )
                      .map((task) => (
                        <UploadAttachment
                          key={task}
                          label={`${text(getTaskMetadata(task).taskFamily)} · ${text("coco")}`}
                          hint={copy("spatialHint")}
                          accept=".json"
                          file={annotations[task]}
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            setAnnotations((previous) => ({
                              ...previous,
                              [task]: file,
                            }));
                          }}
                          onRemove={() =>
                            setAnnotations((previous) => {
                              const next = { ...previous };
                              delete next[task];
                              return next;
                            })
                          }
                          disabled={busy}
                        />
                      ))}
                  </div>
                  <p className="text-xs leading-6 text-slate-500">
                    {text("tableHint")}
                  </p>
                </>
              )}
              {notice && (
                <p role="status" className="text-sm text-emerald-700">
                  {notice}
                </p>
              )}
              {tab === "details" && (
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <Checkbox
                    checked={isPublic}
                    onCheckedChange={(value) => setIsPublic(!!value)}
                  />
                  {t("uploadComponents.datasetConfig.public")}
                </label>
              )}
              {error && (
                <p role="alert" className="text-sm text-red-600">
                  {error}
                </p>
              )}
            </fieldset>
            <footer className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
              <Button variant="ghost" disabled={busy} onClick={onClose}>
                {text("cancel")}
              </Button>
              <Button
                disabled={busy || !tasks.length || !name.trim()}
                onClick={save}
                className="upload-primary"
              >
                {busy ? (
                  <Loader2 size={14} className="mr-2 animate-spin" />
                ) : (
                  tab === "labels" && <Upload size={14} className="mr-2" />
                )}
                {text(tab === "labels" ? "import" : "save")}
              </Button>
            </footer>
          </>
        )
      )}
      {dataset.error && (
        <p role="alert" className="p-6 text-sm text-red-600">
          {String(dataset.error)}
        </p>
      )}
    </div>
  );
  return embedded ? (
    <section className="upload-sheet" aria-label={copy("appendLabels")}>
      {content}
    </section>
  ) : (
    <ModalShell
      isOpen
      onClose={busy ? undefined : onClose}
      maxWidth="xl"
      title={text("overview")}
    >
      {content}
    </ModalShell>
  );
}
