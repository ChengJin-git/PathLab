import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ChevronDown,
  Database,
  FileImage,
  FileSpreadsheet,
  Globe2,
  Loader2,
  LockKeyhole,
  Microscope,
} from "lucide-react";
import { Button } from "../ui/button";
import { Select } from "../ui/select";
import { Checkbox } from "../ui/checkbox";
import { DatasetMetadataFields } from "../datasets/DatasetFields";
import { useDatasetText } from "../datasets/text";
import type { DatasetSummary } from "../../api/wsi";
import {
  TASK_TYPES,
  getTaskMetadata,
  type TaskType,
} from "../../constants/training";
import { organSources, organSourceKeyMap } from "../../constants/wsi";
import { useUploadText } from "./uploadText";
import { UploadHeader } from "./UploadHeader";

export interface DatasetConfigStepProps {
  datasetName: string;
  onDatasetNameChange: (value: string) => void;
  dataType: "patch" | "wsi";
  onDataTypeChange: (value: "patch" | "wsi") => void;
  taskTypes: TaskType[];
  onTaskTypesChange: (value: TaskType[]) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
  metadata: Record<string, unknown>;
  onMetadataChange: (value: Record<string, unknown>) => void;
  dataLevel: "file" | "case";
  onDataLevelChange: (value: "file" | "case") => void;
  datasetSourceSelection: string;
  datasetSourceCustom: string;
  onDatasetSourceSelectionChange: (value: string) => void;
  onDatasetSourceCustomChange: (value: string) => void;
  isExistingDataset: boolean;
  existingDatasets: DatasetSummary[];
  showOwners?: boolean;
  onSelectDataset: (id: string) => void;
  loading?: boolean;
  error?: boolean;
  onRetry: () => void;
  isPublic: boolean;
  onIsPublicChange: (value: boolean) => void;
  saving?: boolean;
  onNext: () => void;
  onBack: () => void;
}

export function DatasetConfigStep(props: DatasetConfigStepProps) {
  const { t } = useTranslation();
  const text = useDatasetText();
  const copy = useUploadText();
  const taskHint = {
    classification: "classificationLabel",
    survival: "survivalLabel",
    segmentation: "segmentationLabel",
    detection: "detectionLabel",
  } as const;
  return (
    <>
      <UploadHeader
        step={1}
        append={props.isExistingDataset}
        onBack={props.onBack}
      />
      {!!props.existingDatasets.length && !props.isExistingDataset && (
        <details
          className="upload-existing"
          open={props.datasetName.trim() ? true : undefined}
        >
          <summary>
            <Database size={15} />
            <span>{copy("appendExisting")}</span>
            <ChevronDown size={14} />
          </summary>
          <div className="upload-existing-list">
            {props.existingDatasets.map((dataset) => (
              <button
                type="button"
                key={dataset.dataset_id}
                onClick={() => props.onSelectDataset(dataset.dataset_id!)}
              >
                <span>{dataset.dataset_name}</span>
                <small>
                  {text(dataset.data_type === 'wsi' ? 'wsi' : 'patch')}
                  {props.showOwners && dataset.username ? ` · ${dataset.username}` : ''}
                  {' · '}
                  {t("uploadPage.fileCount", { count: dataset.file_count })}
                </small>
              </button>
            ))}
          </div>
        </details>
      )}
      <div className="upload-sheet">
        <div className="upload-config-grid">
          <div className="upload-config-form">
            <section className="upload-form-section">
              <div className="upload-section-heading">
                <div>
                  <h2>{copy("basics")}</h2>
                  <p>{copy("basicsHint")}</p>
                </div>
              </div>
              <div className="upload-fields-row">
                <label>
                  <span className="upload-field-label">
                    {t("uploadComponents.datasetConfig.datasetName")}
                  </span>
                  <input
                    value={props.datasetName}
                    onChange={(event) =>
                      props.onDatasetNameChange(event.target.value)
                    }
                    placeholder={t(
                      "uploadComponents.datasetConfig.datasetNamePlaceholder",
                    )}
                    className="upload-input"
                  />
                </label>
                <div>
                  <label htmlFor="upload-source" className="upload-field-label">
                    {t("uploadComponents.datasetConfig.sourceOrganTissue")}{" "}
                    <span className="upload-optional">
                      · {copy("optional")}
                    </span>
                  </label>
                  <Select
                    id="upload-source"
                    value={props.datasetSourceSelection}
                    onChange={props.onDatasetSourceSelectionChange}
                    options={organSources.map((source) => ({
                      value: source,
                      label: t(`organSources.${organSourceKeyMap[source]}`),
                    }))}
                  />
                </div>
              </div>
              {props.datasetSourceSelection === "Other" && (
                <input
                  aria-label={t(
                    "uploadComponents.datasetConfig.otherSourcePlaceholder",
                  )}
                  placeholder={t(
                    "uploadComponents.datasetConfig.otherSourcePlaceholder",
                  )}
                  value={props.datasetSourceCustom}
                  onChange={(event) =>
                    props.onDatasetSourceCustomChange(event.target.value)
                  }
                  className="upload-input mt-3"
                />
              )}
              <fieldset disabled={props.isExistingDataset} className="mt-4">
                <legend className="upload-field-label">
                  {copy("imageType")}
                </legend>
                <div className="upload-type-options">
                  {(["patch", "wsi"] as const).map((kind) => (
                    <button
                      key={kind}
                      type="button"
                      aria-pressed={props.dataType === kind}
                      onClick={() => props.onDataTypeChange(kind)}
                      className="upload-type-option"
                    >
                      {kind === "patch" ? (
                        <FileImage size={24} strokeWidth={1.5} />
                      ) : (
                        <Microscope size={24} strokeWidth={1.5} />
                      )}
                      <span>
                        <strong>{text(kind)}</strong>
                        <small>
                          {copy(kind === "patch" ? "patchHint" : "wsiHint")}
                        </small>
                      </span>
                      <span aria-hidden className="upload-radio-dot" />
                    </button>
                  ))}
                </div>
              </fieldset>
              {props.dataType === "wsi" && (
                <div className="mt-4 max-w-xs">
                  <label htmlFor="upload-level" className="upload-field-label">
                    {t("uploadComponents.datasetConfig.dataLevel")}
                  </label>
                  <Select
                    id="upload-level"
                    value={props.dataLevel}
                    onChange={(value) =>
                      props.onDataLevelChange(value as "case" | "file")
                    }
                    disabled={props.isExistingDataset}
                    options={[
                      {
                        value: "file",
                        label: t("uploadComponents.datasetConfig.fileLevel"),
                      },
                      {
                        value: "case",
                        label: t("uploadComponents.datasetConfig.caseLevel"),
                      },
                    ]}
                  />
                </div>
              )}
            </section>
            <section className="upload-form-section">
              <div className="upload-section-heading">
                <div>
                  <h2>{text("tasks")}</h2>
                  <p>{copy("taskHint")}</p>
                </div>
                <span className="upload-optional">{copy("multipleTasks")}</span>
              </div>
              <div className="upload-task-options">
                {TASK_TYPES.filter(
                  (task) =>
                    getTaskMetadata(task.value).dataType === props.dataType,
                ).map((task) => {
                  const family = getTaskMetadata(task.value).taskFamily;
                  return (
                    <label className="upload-task-option" key={task.value}>
                      <Checkbox
                        aria-label={text(family)}
                        checked={props.taskTypes.includes(task.value)}
                        onCheckedChange={(checked) =>
                          props.onTaskTypesChange(
                            checked
                              ? [...props.taskTypes, task.value]
                              : props.taskTypes.filter(
                                  (value) => value !== task.value,
                                ),
                          )
                        }
                      />
                      <span>
                        <strong>{text(family)}</strong>
                        <small>{copy(taskHint[family])}</small>
                      </span>
                    </label>
                  );
                })}
              </div>
            </section>
            <section className="upload-form-section upload-description-fields">
              <DatasetMetadataFields
                description={props.description}
                metadata={props.metadata}
                onDescription={props.onDescriptionChange}
                onMetadata={props.onMetadataChange}
              />
            </section>
            {!props.isExistingDataset && (
              <section className="upload-form-section upload-visibility">
                {props.isPublic ? (
                  <Globe2 size={18} />
                ) : (
                  <LockKeyhole size={18} />
                )}
                <div>
                  <strong>{copy("visibility")}</strong>
                  <p>{copy(props.isPublic ? "publicHint" : "privateHint")}</p>
                </div>
                <label>
                  <Checkbox
                    checked={props.isPublic}
                    onCheckedChange={props.onIsPublicChange}
                  />
                  {t("uploadComponents.datasetConfig.public")}
                </label>
              </section>
            )}
            {props.error && (
              <p role="alert" className="mt-4 text-sm text-red-600">
                {copy("datasetFailed")}{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={props.onRetry}
                >
                  {t("common.retry")}
                </button>
              </p>
            )}
          </div>
          <aside className="upload-config-aside">
            <p className="upload-aside-label">
              {copy(props.isExistingDataset ? "selectedDataset" : "preview")}
            </p>
            <div className="upload-aside-dataset">
              <Database size={18} />
              <div>
                <strong>{props.datasetName.trim() || copy("unnamed")}</strong>
                <p>
                  {text(props.dataType)} ·{" "}
                  {t(
                    props.dataLevel === "case"
                      ? "uploadComponents.datasetConfig.caseLevel"
                      : "uploadComponents.datasetConfig.fileLevel",
                  )}
                </p>
              </div>
            </div>
            <div className="upload-aside-tasks">
              {props.taskTypes.map((task) => (
                <span key={task}>{text(getTaskMetadata(task).taskFamily)}</span>
              ))}
            </div>
            <div className="upload-preparation">
              <p className="upload-aside-label">{copy("prepareNext")}</p>
              <ul>
                <li>
                  <FileImage size={17} />
                  <div>
                    <strong>{copy("imageFiles")}</strong>
                    <p>{copy("imageFilesHint")}</p>
                  </div>
                </li>
                <li>
                  <FileSpreadsheet size={17} />
                  <div>
                    <strong>{copy("labelFiles")}</strong>
                    <p>{copy("labelsHint")}</p>
                  </div>
                </li>
              </ul>
            </div>
            <p className="upload-aside-note">{copy("laterHint")}</p>
          </aside>
        </div>
        <footer className="upload-config-footer">
          <p>{copy("readyHint")}</p>
          <Button
            className="upload-primary"
            disabled={
              !props.datasetName.trim() ||
              !props.taskTypes.length ||
              props.loading ||
              props.error ||
              props.saving
            }
            onClick={props.onNext}
          >
            {props.saving ? (
              <>
                <Loader2 size={14} className="mr-2 animate-spin" />
                {copy("creating")}
              </>
            ) : (
              <>
                {t("uploadComponents.datasetConfig.nextChooseFiles")}
                <ArrowRight size={15} className="ml-3" />
              </>
            )}
          </Button>
        </footer>
      </div>
    </>
  );
}
