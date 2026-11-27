import { useEffect, useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import { downloadWorkbenchFile, type ResourceItem } from "../../api/workbench";
import { useConversationFiles } from "./ConversationFiles";
import { useWorkbenchText } from "./workbenchText";
import { getWorkspaceSelection } from "../../lib/workspaceSelection";

export function parseDeliveredFiles(content: string): ResourceItem[] {
  const match = /\[FILE_DELIVERY\]([\s\S]*?)\[\/FILE_DELIVERY\]/.exec(content);
  if (!match) return [];
  try {
    const result = JSON.parse(match[1]);
    return Array.isArray(result.files)
      ? result.files
          .filter(
            (file: ResourceItem) =>
              file.kind === "file" && file.id && file.name,
          )
          .slice(0, 4)
      : [];
  } catch {
    return [];
  }
}
export default function FileDeliveryCard({ files }: { files: ResourceItem[] }) {
  const viewer = useConversationFiles();
  const text = useWorkbenchText();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    viewer?.changed();
  }, [files.map((file) => file.id).join(":")]);
  return (
    <div className="my-3 space-y-2">
      {files.map((file) => (
        <div
          key={file.id}
          className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-3"
        >
          <FileText size={20} className="shrink-0 text-gray-400" />
          <button
            type="button"
            onClick={() => viewer?.openFile(file)}
            className="min-w-0 flex-1 text-left"
          >
            <span className="block truncate text-sm font-medium text-gray-800">
              {file.name}
            </span>
            <span className="mt-0.5 block text-xs text-gray-400">
              {text("fileSaved")} · {text("preview")}
            </span>
          </button>
          <button
            disabled={!!busy}
            aria-label={`${text("download")} ${file.name}`}
            onClick={async () => {
              setBusy(file.id);
              setError("");
              try {
                await downloadWorkbenchFile(
                  file,
                  getWorkspaceSelection().workspaceId,
                );
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy("");
              }
            }}
            className="rounded p-2 text-gray-500 hover:bg-gray-100"
          >
            {busy === file.id ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Download size={15} />
            )}
          </button>
        </div>
      ))}
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
