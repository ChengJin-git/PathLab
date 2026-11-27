import {
  useRef,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import { Check, FileJson, FileSpreadsheet, Upload, X } from "lucide-react";
import { useUploadText } from "./uploadText";
import { useTranslation } from "react-i18next";

export function UploadAttachment({
  label,
  hint,
  accept,
  file,
  onChange,
  onRemove,
  onDrop,
  disabled,
  action,
}: {
  label: string;
  hint: string;
  accept: string;
  file: File | null | undefined;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemove: () => void;
  onDrop?: (event: DragEvent<HTMLDivElement>) => void;
  disabled?: boolean;
  action?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const copy = useUploadText();
  const { t } = useTranslation();
  const Icon = accept === ".json" ? FileJson : FileSpreadsheet;
  return (
    <div
      className="upload-attachment"
      data-ready={!!file}
      onDragOver={
        onDrop
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
            }
          : undefined
      }
      onDrop={disabled ? undefined : onDrop}
    >
      <span className="upload-attachment-icon">
        <Icon size={20} strokeWidth={1.6} />
      </span>
      <div className="upload-attachment-info">
        <span className="upload-attachment-label">
          {label}
          {file && <Check size={13} className="text-emerald-600" />}
        </span>
        <p title={file?.name}>{file ? file.name : hint}</p>
      </div>
      <div className="upload-attachment-actions">
        {action}
        <input
          ref={input}
          aria-label={label}
          type="file"
          accept={accept}
          disabled={disabled}
          tabIndex={-1}
          className="sr-only"
          onChange={(event) => {
            onChange(event);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={disabled}
          className="upload-file-button"
        >
          <Upload size={13} />
          {copy(file ? "replaceAttachment" : "chooseAttachment")}
        </button>
        {file && (
          <button
            type="button"
            aria-label={`${t("uploadPage.removeFile")} ${label}`}
            disabled={disabled}
            onClick={onRemove}
            className="upload-remove"
          >
            <X size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
