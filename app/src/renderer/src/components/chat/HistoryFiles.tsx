import { useEffect, useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  FolderOpen,
  Loader2,
} from "lucide-react";
import {
  conversationFiles,
  downloadConversationFile,
  type ResourceItem,
} from "../../api/workbench";
import { useWorkbenchText } from "./workbenchText";

export default function HistoryFiles({
  conversationId,
  userId,
  expanded,
  onToggle,
  onOpen,
}: {
  conversationId: string;
  userId: string;
  expanded: boolean;
  onToggle: () => void;
  onOpen: (file?: ResourceItem) => void;
}) {
  const text = useWorkbenchText();
  const client = useQueryClient();
  const panelId = useId();
  const [cursors, setCursors] = useState([""]);
  const [pageIndex, setPageIndex] = useState(0);
  const [query, setQuery] = useState("");
  const [needle, setNeedle] = useState("");
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState("");
  useEffect(() => {
    if (query === needle) return;
    const timer = setTimeout(() => {
      setNeedle(query);
      setCursors([""]);
      setPageIndex(0);
    }, 180);
    return () => clearTimeout(timer);
  }, [query, needle]);
  const page = useQuery({
    queryKey: [
      "history-files",
      userId,
      conversationId,
      needle,
      cursors[pageIndex],
    ],
    queryFn: ({ signal }) =>
      conversationFiles(
        conversationId,
        { view: "all", q: needle, cursor: cursors[pageIndex] },
        signal,
      ),
    enabled: expanded,
    staleTime: 3000,
    gcTime: 30000,
    retry: 1,
  });
  useEffect(() => {
    if (!expanded)
      void client.cancelQueries({
        queryKey: ["history-files", userId, conversationId],
      });
  }, [expanded, userId, conversationId, client]);
  async function download(file: ResourceItem) {
    setDownloading(file.id);
    setError("");
    try {
      await downloadConversationFile(conversationId, file);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading("");
    }
  }
  return (
    <div className="border-t border-gray-100 px-2 pb-1">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={onToggle}
        className="flex w-full items-center gap-1.5 rounded px-1 py-2 text-left text-[11px] text-gray-500 hover:text-gray-800"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <FolderOpen size={12} />
        <span>{text("file")}</span>
        {expanded && page.isFetching && (
          <Loader2 size={11} className="ml-auto animate-spin" />
        )}
      </button>
      {expanded && (
        <section
          id={panelId}
          aria-label={text("historyFiles")}
          className="space-y-1 pb-1"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label={text("fileSearch")}
            placeholder={text("fileSearch")}
            className="mb-1 w-full rounded-md border border-gray-200 bg-white/80 px-2 py-1.5 text-xs outline-none focus:border-gray-400"
          />
          {(error || page.error) && (
            <p role="alert" className="px-1 py-2 text-xs text-red-600">
              {error || String(page.error)}
            </p>
          )}
          {page.isLoading && (
            <p className="px-1 py-2 text-xs text-gray-400">{text("loading")}</p>
          )}
          {!page.isLoading && !page.data?.items.length && (
            <p className="px-1 py-2 text-xs text-gray-400">
              {text("fileListEmpty")}
            </p>
          )}
          <ul className="max-h-56 overflow-y-auto">
            {page.data?.items.map((file) => (
              <li
                key={file.id}
                className="group/file flex items-center gap-1 rounded hover:bg-white/80"
              >
                <button
                  type="button"
                  onClick={() => onOpen(file)}
                  title={file.path || file.name}
                  className="flex min-w-0 flex-1 items-center gap-1.5 px-1 py-1.5 text-left text-xs text-gray-600"
                >
                  <FileText size={12} className="shrink-0 text-gray-400" />
                  <span className="truncate">{file.name}</span>
                </button>
                <button
                  type="button"
                  aria-label={`${text("download")} ${file.name}`}
                  title={text("download")}
                  disabled={!!downloading}
                  onClick={() => void download(file)}
                  className="shrink-0 rounded p-1 text-gray-400 hover:text-gray-700 disabled:opacity-40"
                >
                  {downloading === file.id ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Download size={12} />
                  )}
                </button>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-1 border-t border-gray-100 pt-1">
            <button
              type="button"
              onClick={() => onOpen()}
              className="px-1 py-1 text-[11px] text-gray-500 hover:text-gray-800"
            >
              {text("openFileManager")}
            </button>
            <div className="flex items-center gap-1 text-[11px] text-gray-400">
              <button
                type="button"
                aria-label={text("previous")}
                disabled={pageIndex === 0 || page.isFetching}
                onClick={() => setPageIndex((value) => value - 1)}
                className="rounded p-1 hover:bg-white disabled:opacity-30"
              >
                <ChevronLeft size={13} />
              </button>
              <span aria-live="polite">{pageIndex + 1}</span>
              <button
                type="button"
                aria-label={text("more")}
                disabled={!page.data?.next_cursor || page.isFetching}
                onClick={() => {
                  setCursors((values) => [
                    ...values.slice(0, pageIndex + 1),
                    page.data!.next_cursor!,
                  ]);
                  setPageIndex((value) => value + 1);
                }}
                className="rounded p-1 hover:bg-white disabled:opacity-30"
              >
                <ChevronRight size={13} />
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
