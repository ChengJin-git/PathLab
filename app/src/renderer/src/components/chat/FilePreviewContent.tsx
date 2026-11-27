import { useEffect, useMemo, useState } from "react";
import { Select } from '../ui/select';
import { File, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import DOMPurify from "dompurify";
import {
  previewWorkbenchFile,
  readWorkbenchMedia,
  type FilePreview,
  type ResourceItem,
} from "../../api/workbench";
import { useWorkbenchText } from "./workbenchText";
import DocumentPreview from './DocumentPreview';

export function safePreviewHtml(content: string): string {
  const clean = DOMPurify.sanitize(content, {
    WHOLE_DOCUMENT: true,
    FORBID_TAGS: [
      "script",
      "iframe",
      "object",
      "embed",
      "form",
      "base",
      "meta",
      "link",
    ],
    FORBID_ATTR: ["srcset", "action", "formaction"],
  });
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'"><style>body{font:14px/1.7 system-ui,sans-serif;margin:24px;color:#1e293b;overflow-wrap:anywhere}img{max-width:100%;height:auto}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px}</style></head><body>${clean}</body></html>`;
}

export default function FilePreviewContent({
  file,
  workspaceId,
  reload = 0,
  page,
  initialPreview,
}: {
  file: ResourceItem;
  workspaceId?: string | null;
  reload?: number;
  page?: number;
  initialPreview?: FilePreview;
}) {
  const text = useWorkbenchText();
  const [preview, setPreview] = useState<FilePreview | undefined>(initialPreview);
  const [media, setMedia] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(!initialPreview);
  const [sheet, setSheet] = useState("");
  const [raw, setRaw] = useState(false);
  useEffect(() => {
    setSheet("");
    setRaw(false);
  }, [file.id]);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    const supplied = !sheet && reload === 0 && initialPreview?.file_id === file.id ? initialPreview : undefined;
    setBusy(!supplied || ["image", "audio", "video"].includes(supplied.kind));
    setError("");
    setPreview(supplied);
    setMedia("");
    async function load() {
      try {
        const data = supplied || await previewWorkbenchFile(
          file.id,
          workspaceId,
          controller.signal,
          sheet,
        );
        if (controller.signal.aborted) return;
        if (["image", "audio", "video"].includes(data.kind)) {
          const blob = await readWorkbenchMedia(
            file.id,
            workspaceId,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          objectUrl = URL.createObjectURL(blob);
          setMedia(objectUrl);
        }
        setPreview(data);
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    void load();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file.id, file.revision, workspaceId, sheet, reload, initialPreview]);
  const html = useMemo(
    () =>
      preview?.kind === "html" ? safePreviewHtml(preview.content || "") : "",
    [preview],
  );
  if (busy)
    return (
      <div
        role="status"
        className="flex h-full items-center justify-center gap-2 text-sm text-gray-400"
      >
        <Loader2 size={16} className="animate-spin" />
        {text("loading")}
      </div>
    );
  if (error)
    return (
      <p role="alert" className="p-5 text-sm text-red-600">
        {error}
      </p>
    );
  if (!preview) return null;
  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-preview-kind={preview.kind}
    >
      {(preview.kind === "markdown" ||
        preview.kind === "html" ||
        !!preview.sheets?.length) && (
        <div className="flex shrink-0 items-center gap-1 border-b border-gray-100 px-4 py-2 text-xs">
          {!!preview.sheets?.length ? (
            <Select ariaLabel={text('sheet')} value={preview.sheet || ''} onChange={setSheet}
              className="max-w-full" triggerClassName="text-xs"
              options={preview.sheets.map(name=>({value:name,label:name}))} />
          ) : (
            <>
              <button
                onClick={() => setRaw(false)}
                aria-pressed={!raw}
                className={`rounded px-2 py-1 ${!raw ? "bg-gray-100 text-gray-900" : "text-gray-500"}`}
              >
                {text("preview")}
              </button>
              <button
                onClick={() => setRaw(true)}
                aria-pressed={raw}
                className={`rounded px-2 py-1 ${raw ? "bg-gray-100 text-gray-900" : "text-gray-500"}`}
              >
                {text("source")}
              </button>
            </>
          )}
        </div>
      )}
      {preview.truncated && (
        <p className="shrink-0 border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {text("previewTruncated")}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto bg-white">
        {preview.kind === "image" && (
          <div className="flex min-h-full items-center justify-center bg-gray-50 p-5">
            <img
              src={media}
              alt={preview.name}
              className="max-h-full max-w-full object-contain"
            />
          </div>
        )}
        {['pdf', 'slides', 'document'].includes(preview.kind) && <DocumentPreview key={`${file.id}:${preview.revision}`} preview={preview} workspaceId={workspaceId} initialPage={page} />}
        {preview.kind === 'audio' && <div className="flex h-full items-center justify-center p-5"><audio controls preload="metadata" src={media} aria-label={preview.name} className="w-full max-w-xl" /></div>}
        {preview.kind === 'video' && <div className="flex h-full items-center justify-center bg-slate-950"><video controls playsInline preload="metadata" src={media} aria-label={preview.name} className="max-h-full max-w-full" /></div>}
        {preview.kind === "html" && !raw && (
          <iframe
            title={preview.name}
            sandbox=""
            srcDoc={html}
            className="h-full min-h-[360px] w-full border-0"
          />
        )}
        {preview.kind === "markdown" && !raw && (
          <article className="article-prose max-w-none break-words p-5">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                img: ({ alt }) => (
                  <span className="text-gray-400">[{alt || "image"}]</span>
                ),
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                ),
              }}
            >
              {preview.content || ""}
            </ReactMarkdown>
          </article>
        )}
        {(raw || ["text", "code"].includes(preview.kind)) && (
          <pre className="m-0 min-h-full whitespace-pre-wrap break-words p-5 font-mono text-xs leading-6 text-gray-700">
            <code>{preview.content}</code>
          </pre>
        )}
        {preview.kind === "table" && (
          <table className="w-full border-collapse text-left text-xs">
            <tbody>
              {preview.rows?.map((row, i) => (
                <tr
                  key={i}
                  className={
                    i === 0
                      ? "sticky top-0 bg-gray-100 font-semibold text-gray-800"
                      : "even:bg-gray-50"
                  }
                >
                  <th className="w-10 border-b border-r border-gray-200 px-2 py-2 text-right font-normal text-gray-400">
                    {i + 1}
                  </th>
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="max-w-sm whitespace-pre-wrap break-words border-b border-r border-gray-200 px-3 py-2"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {preview.kind === "unsupported" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-sm text-gray-500">
            <File size={28} className="text-gray-300" />
            <p>{text(preview.reason || "unsupportedPreview")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
