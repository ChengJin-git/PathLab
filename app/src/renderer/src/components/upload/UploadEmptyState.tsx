import { FileUp, FolderOpen, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui/button";
import { useUploadText } from "./uploadText";

export function UploadEmptyState({
  dataType,
  dragging,
  busy,
  onDragging,
  onDrop,
  onFiles,
  onFolder,
}: {
  dataType: "patch" | "wsi";
  dragging: boolean;
  busy: boolean;
  onDragging: (value: boolean) => void;
  onDrop: (data: globalThis.DataTransfer) => Promise<void>;
  onFiles: () => void;
  onFolder: () => void;
}) {
  const { t } = useTranslation();
  const copy = useUploadText();
  return (
    <div
      className="upload-dropzone"
      data-dragging={dragging}
      onDragOver={(event) => {
        event.preventDefault();
        if (!busy) onDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node))
          onDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDragging(false);
        if (!busy) void onDrop(event.dataTransfer);
      }}
    >
      <div className="upload-drop-icon">
        <FileUp size={25} strokeWidth={1.4} />
      </div>
      <h3>{t("uploadPage.dropFilesHere")}</h3>
      <p>{copy("dropHint")}</p>
      <div className="upload-pickers">
        <Button className="upload-primary" disabled={busy} onClick={onFiles}>
          <Plus size={14} className="mr-2" />
          {copy("chooseFiles")}
        </Button>
        <Button variant="outline" disabled={busy} onClick={onFolder}>
          <FolderOpen size={14} className="mr-2" />
          {copy("chooseFolder")}
        </Button>
      </div>
      <div className="upload-formats">
        {copy("formats")} ·{" "}
        {dataType === "patch"
          ? "PNG · JPG · TIFF · BMP"
          : "SVS · NDPI · MRXS · TIFF · …"}
      </div>
    </div>
  );
}
