import { useTranslation } from "react-i18next";
import { ModalShell } from "../ui/modal-shell";
import { Select } from "../ui/select";

type DatasetFamily =
  "classification" | "survival" | "segmentation" | "detection";
interface MetadataFields {
  label: string;
  caseId: string;
  age: string;
  gender: string;
  eventTime: string;
  eventStatus: string;
}
interface FieldCallbacks {
  label: (value: string) => void;
  caseId: (value: string) => void;
  age: (value: string) => void;
  gender: (value: string) => void;
  eventTime: (value: string) => void;
  eventStatus: (value: string) => void;
}

function MetadataForm({
  title,
  description,
  values,
  onChange,
  datasetType,
  busy,
  onCancel,
  onConfirm,
  identifier,
  batch = false,
}: {
  title: string;
  description: string;
  values: MetadataFields;
  onChange: FieldCallbacks;
  datasetType?: DatasetFamily;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  identifier?: string;
  batch?: boolean;
}) {
  const { t } = useTranslation();
  const fields: [keyof MetadataFields, string, string][] = [
    ...(datasetType === "classification"
      ? [
          ["label", "labelDiseaseClassification", "text"] as [
            keyof MetadataFields,
            string,
            string,
          ],
        ]
      : []),
    ...(datasetType === "survival"
      ? [
          ["eventTime", "eventTime", "number"] as [
            keyof MetadataFields,
            string,
            string,
          ],
        ]
      : []),
    ["caseId", "caseId", "text"],
    ["age", "age", "number"],
  ];
  return (
    <ModalShell
      isOpen
      onClose={busy ? undefined : onCancel}
      maxWidth="md"
      className="p-5 sm:p-6"
    >
      <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
      {batch && (
        <p className="mt-3 text-xs text-slate-500">
          {t("listComponents.editModals.leaveFieldsEmpty")}
        </p>
      )}
      <fieldset disabled={busy} className="mt-5 space-y-4">
        {identifier && (
          <input
            aria-label="Image ID"
            value={identifier}
            disabled
            className="w-full rounded-lg border bg-slate-50 px-3 py-2 text-xs text-slate-500"
          />
        )}
        {fields.map(([key, label, type]) => (
          <label key={key} className="block space-y-1 text-sm text-slate-700">
            {t(`listComponents.editModals.${label}`)}
            <input
              type={type}
              min={type === "number" ? 0 : undefined}
              step={key === "eventTime" ? "any" : undefined}
              value={values[key]}
              onChange={(event) => onChange[key](event.target.value)}
              placeholder={t(
                batch
                  ? "listComponents.editModals.keepExisting"
                  : `listComponents.editModals.${key === "label" ? "labelPlaceholder" : key === "caseId" ? "caseIdPlaceholder" : key === "eventTime" ? "eventTimePlaceholder" : "agePlaceholder"}`,
              )}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
        ))}
        {datasetType === "survival" && (
          <label className="block space-y-1 text-sm text-slate-700">
            {t("listComponents.editModals.eventStatus")}
            <Select
              value={values.eventStatus}
              onChange={onChange.eventStatus}
              options={[
                { value: "1", label: t("listComponents.editModals.event") },
                { value: "0", label: t("listComponents.editModals.censored") },
              ]}
              placeholder={t("listComponents.editModals.selectStatus")}
            />
          </label>
        )}
        <label className="block space-y-1 text-sm text-slate-700">
          {t("listComponents.editModals.gender")}
          <Select
            value={values.gender}
            onChange={onChange.gender}
            options={[
              { value: "Male", label: t("listComponents.editModals.male") },
              { value: "Female", label: t("listComponents.editModals.female") },
              {
                value: "Unspecified",
                label: t("listComponents.editModals.unspecified"),
              },
            ]}
            placeholder={t("listComponents.editModals.selectGender")}
          />
        </label>
        <div className="flex justify-end gap-3 border-t border-slate-100 pt-4">
          <button
            onClick={onCancel}
            className="rounded-lg border px-4 py-2 text-sm"
          >
            {t("listComponents.editModals.cancel")}
          </button>
          <button
            onClick={onConfirm}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white"
          >
            {t(
              busy
                ? "listComponents.editModals.saving"
                : "listComponents.editModals.saveChanges",
            )}
          </button>
        </div>
      </fieldset>
    </ModalShell>
  );
}

export interface EditMetadataModalProps {
  editingWSI: {
    wsi_id: string;
    label?: string;
    case_id: string;
    age?: number;
    gender?: string;
    event_time?: number;
    event_status?: number;
  };
  editLabel: string;
  editCaseId: string;
  editAge: string;
  editGender: string;
  editEventTime: string;
  editEventStatus: string;
  datasetType?: DatasetFamily;
  visualType?: "slides" | "images";
  onEditLabelChange: (value: string) => void;
  onEditCaseIdChange: (value: string) => void;
  onEditAgeChange: (value: string) => void;
  onEditGenderChange: (value: string) => void;
  onEditEventTimeChange: (value: string) => void;
  onEditEventStatusChange: (value: string) => void;
  updating: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}
export function EditMetadataModal(props: EditMetadataModalProps) {
  const { t } = useTranslation();
  return (
    <MetadataForm
      title={t("listComponents.editModals.editMetadata")}
      description={t(
        props.visualType === "images"
          ? "listComponents.editModals.updateImageInfo"
          : "listComponents.editModals.updateSlideInfo",
      )}
      identifier={props.editingWSI.wsi_id}
      datasetType={props.datasetType}
      busy={props.updating}
      onCancel={props.onCancel}
      onConfirm={props.onConfirm}
      values={{
        label: props.editLabel,
        caseId: props.editCaseId,
        age: props.editAge,
        gender: props.editGender,
        eventTime: props.editEventTime,
        eventStatus: props.editEventStatus,
      }}
      onChange={{
        label: props.onEditLabelChange,
        caseId: props.onEditCaseIdChange,
        age: props.onEditAgeChange,
        gender: props.onEditGenderChange,
        eventTime: props.onEditEventTimeChange,
        eventStatus: props.onEditEventStatusChange,
      }}
    />
  );
}

export interface BatchEditModalProps {
  selectedCount: number;
  batchEditLabel: string;
  batchEditCaseId: string;
  batchEditAge: string;
  batchEditGender: string;
  batchEditEventTime: string;
  batchEditEventStatus: string;
  datasetType?: DatasetFamily;
  visualType?: "slides" | "images";
  onBatchEditLabelChange: (value: string) => void;
  onBatchEditCaseIdChange: (value: string) => void;
  onBatchEditAgeChange: (value: string) => void;
  onBatchEditGenderChange: (value: string) => void;
  onBatchEditEventTimeChange: (value: string) => void;
  onBatchEditEventStatusChange: (value: string) => void;
  batchUpdating: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}
export function BatchEditModal(props: BatchEditModalProps) {
  const { t } = useTranslation();
  return (
    <MetadataForm
      title={t("listComponents.editModals.batchEditMetadata")}
      description={t(
        props.visualType === "images"
          ? "listComponents.editModals.updateImages"
          : "listComponents.editModals.updateSlides",
        { count: props.selectedCount },
      )}
      batch
      datasetType={props.datasetType}
      busy={props.batchUpdating}
      onCancel={props.onCancel}
      onConfirm={props.onConfirm}
      values={{
        label: props.batchEditLabel,
        caseId: props.batchEditCaseId,
        age: props.batchEditAge,
        gender: props.batchEditGender,
        eventTime: props.batchEditEventTime,
        eventStatus: props.batchEditEventStatus,
      }}
      onChange={{
        label: props.onBatchEditLabelChange,
        caseId: props.onBatchEditCaseIdChange,
        age: props.onBatchEditAgeChange,
        gender: props.onBatchEditGenderChange,
        eventTime: props.onBatchEditEventTimeChange,
        eventStatus: props.onBatchEditEventStatusChange,
      }}
    />
  );
}
