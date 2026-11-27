import { Select } from '../ui/select';
import {
  createContext,
  lazy,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "../ui/button";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  X,
} from "lucide-react";
import {
  conversationFiles,
  downloadWorkbenchFile,
  indexResearchFiles,
  referenceResearchPath,
  type ResourceItem,
  type FilePreview,
} from "../../api/workbench";
import type { AutoResearchSessionSummary } from "../../types/autoresearch";
import { useWorkbenchText } from "./workbenchText";

const FilePreviewContent = lazy(() => import("./FilePreviewContent"));
type FileTarget = ResourceItem | { sessionId: string; path: string };
export interface FileOpenRequest {
  conversationId: string;
  file?: ResourceItem;
  key: number;
}
interface FileWorkspace {
  open: boolean;
  openFiles: (sessionId?: string) => void;
  openFile: (target: FileTarget) => void;
  close: () => void;
  changed: () => void;
}
const FilesContext = createContext<FileWorkspace | null>(null);
const PanelContext = createContext<ReactNode>(null);
export const useConversationFiles = () => useContext(FilesContext);
export function ConversationFilesPanel() {
  return useContext(PanelContext);
}

export function ConversationFilesProvider({
  children,
  conversationId,
  workspaceId,
  userId,
  sessions,
  onReference,
  openRequest,
}: {
  children: ReactNode;
  conversationId: string | null;
  workspaceId: string | null;
  userId?: string;
  sessions: AutoResearchSessionSummary[];
  onReference: (item: ResourceItem) => void;
  openRequest?: FileOpenRequest;
}) {
  // A new scope gets a fresh viewer and cancels all in-flight previews.
  return (
    <FileWorkspace
      key={`${userId}:${workspaceId}:${conversationId}`}
      {...{
        children,
        conversationId,
        workspaceId,
        userId,
        sessions,
        onReference,
        openRequest,
      }}
    />
  );
}

function FileWorkspace({
  children,
  conversationId,
  workspaceId,
  userId,
  sessions,
  onReference,
  openRequest,
}: {
  children: ReactNode;
  conversationId: string | null;
  workspaceId: string | null;
  userId?: string;
  sessions: AutoResearchSessionSummary[];
  onReference: (item: ResourceItem) => void;
  openRequest?: FileOpenRequest;
}) {
  const text = useWorkbenchText();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [showList, setShowList] = useState(true);
  const [source, setSource] = useState("__all__");
  const [parent, setParent] = useState("");
  const [query, setQuery] = useState("");
  const [exactPath, setExactPath] = useState("");
  const [debounced, setDebounced] = useState("");
  const [cursor, setCursor] = useState("");
  const [previousCursors, setPreviousCursors] = useState<string[]>([]);
  const [tabs, setTabs] = useState<ResourceItem[]>([]);
  const [activeId, setActiveId] = useState("");
  const [initialPreview, setInitialPreview] = useState<FilePreview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [width, setWidth] = useState(640);
  const [surface] = useState(() => {
    const element = document.createElement("div");
    element.className = "h-full min-h-0 min-w-0 overflow-hidden";
    return element;
  });
  const attachSurface = useCallback(
    (element: HTMLDivElement | null) => {
      if (element) element.appendChild(surface);
    },
    [surface],
  );
  const generation = useRef(0);
  const mounted = useRef(true);
  const indexed = useRef(new Map<string, number>());
  const previousFocus = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const active = tabs.find((item) => item.id === activeId);
  const scopeKey = ["conversation-files", userId, workspaceId, conversationId];
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
    };
  }, []);
  useEffect(() => {
    if (query === debounced) return;
    const timer = setTimeout(() => {
      setDebounced(query);
      setCursor("");
      setPreviousCursors([]);
    }, 180);
    return () => clearTimeout(timer);
  }, [query, debounced]);
  const page = useQuery({
    queryKey: [...scopeKey, source, parent, debounced, cursor],
    queryFn: ({ signal }) =>
      conversationFiles(
        conversationId!,
        {
          session_id: source === "__all__" ? "" : source,
          view: source === "__all__" ? "all" : "uploads",
          parent,
          q: debounced,
          cursor,
        },
        signal,
      ),
    enabled: open && !!conversationId,
    staleTime: 2000,
    refetchInterval: (state) => (state.state.data?.indexing ? 1500 : false),
    retry: 1,
  });
  const changed = useCallback(() => {
    void client.invalidateQueries({
      queryKey: ["conversation-files", userId, workspaceId, conversationId],
    });
    void client.invalidateQueries({
      queryKey: ["history-files", userId, conversationId],
    });
    void client.invalidateQueries({
      queryKey: ["chat-research-status", userId],
    });
  }, [client, userId, workspaceId, conversationId]);
  const close = useCallback(() => {
    generation.current++;
    setBusy(false);
    setOpen(false);
    setFullscreen(false);
    previousFocus.current?.focus();
  }, []);
  const reveal = useCallback(() => {
    if (!open) previousFocus.current = document.activeElement as HTMLElement;
    setOpen(true);
  }, [open]);
  const navigate = useCallback((id: string, path = "") => {
    setSource(id);
    setParent(path);
    setCursor("");
    setPreviousCursors([]);
    setQuery("");
    setDebounced("");
  }, []);
  const openFiles = useCallback(
    (sessionId?: string) => {
      generation.current++;
      setBusy(false);
      reveal();
      setShowList(true);
      navigate(sessionId ?? "__all__");
      changed();
    },
    [reveal, navigate, changed],
  );
  const openFile = useCallback(
    (target: FileTarget) => {
      reveal();
      const version = ++generation.current;
      setError("");
      setInitialPreview(undefined);
      const accept = (item: ResourceItem & {preview?: FilePreview}) => {
        if (!mounted.current || version !== generation.current) return;
        setTabs((current) =>
          [...current.filter((tab) => tab.id !== item.id), item].slice(-8),
        );
        setActiveId(item.id);
        setInitialPreview(item.preview);
        const nextSource = item.session_id || "";
        const nextParent = item.path?.split("/").slice(0, -1).join("/") || "";
        if (
          source !== "__all__" &&
          (nextSource !== source || nextParent !== parent)
        )
          navigate(nextSource, nextParent);
        if (window.innerWidth < 1100) setShowList(false);
        setBusy(false);
      };
      if ("sessionId" in target) {
        setBusy(true);
        void referenceResearchPath(target.sessionId, target.path, undefined, true)
          .then(accept)
          .catch((e) => {
            if (mounted.current && version === generation.current) {
              setBusy(false);
              setError(e.message);
            }
          });
      } else accept(target);
    },
    [reveal, navigate, source, parent],
  );
  const handledRequest = useRef<number>();
  useEffect(() => {
    if (
      !openRequest ||
      openRequest.conversationId !== conversationId ||
      handledRequest.current === openRequest.key
    )
      return;
    handledRequest.current = openRequest.key;
    if (openRequest.file) openFile(openRequest.file);
    else openFiles();
  }, [openRequest, conversationId, openFile, openFiles]);
  async function indexFiles(force = false) {
    if (!source || source === "__all__") {
      changed();
      return;
    }
    const key = `${source}:${parent}`;
    if (!force && Date.now() - (indexed.current.get(key) || 0) < 30000) return;
    indexed.current.set(key, Date.now());
    try {
      await indexResearchFiles(source, parent);
      if (mounted.current) changed();
    } catch (e) {
      indexed.current.delete(key);
      if (mounted.current) setError((e as Error).message);
    }
  }
  useEffect(() => {
    if (open && source && source !== "__all__") void indexFiles();
  }, [open, source, parent]);
  useEffect(() => {
    if (!open || fullscreen) return;
    closeButton.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, fullscreen, close]);
  const context = useMemo(
    () => ({ open, openFiles, openFile, close, changed }),
    [open, openFiles, openFile, close, changed],
  );
  async function download() {
    if (!active) return;
    try {
      await downloadWorkbenchFile(active, workspaceId);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const clampWidth = (value: number) =>
    Math.max(440, Math.min(value, window.innerWidth - 380));
  const panel = (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-white">
      <header className="flex shrink-0 items-center gap-2 border-b border-gray-200 px-3 py-2.5">
        <button
          aria-label={text(showList ? "hideFiles" : "showFiles")}
          onClick={() => setShowList((value) => !value)}
          className="rounded p-1.5 text-gray-500 hover:bg-gray-100"
        >
          {showList ? (
            <PanelLeftClose size={16} />
          ) : (
            <PanelLeftOpen size={16} />
          )}
        </button>
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800">
          {text("conversationFiles")}
        </h2>
        {active && (
          <>
            <button
              title={text("reference")}
              aria-label={text("reference")}
              onClick={() => onReference(active)}
              className="rounded p-1.5 text-xs text-gray-500 hover:bg-gray-100"
            >
              @
            </button>
            <button
              title={text("reloadFile")}
              aria-label={text("reloadFile")}
              onClick={() => setReload((value) => value + 1)}
              className="rounded p-1.5 text-gray-500 hover:bg-gray-100"
            >
              <RefreshCw size={15} />
            </button>
            <button
              title={text("download")}
              aria-label={text("download")}
              onClick={() => void download()}
              className="rounded p-1.5 text-gray-500 hover:bg-gray-100"
            >
              <Download size={15} />
            </button>
          </>
        )}
        <button
          title={text(fullscreen ? "exitFullscreen" : "fullscreen")}
          aria-label={text(fullscreen ? "exitFullscreen" : "fullscreen")}
          onClick={() => setFullscreen((value) => !value)}
          className="rounded p-1.5 text-gray-500 hover:bg-gray-100"
        >
          {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
        <button
          ref={closeButton}
          title={text("closePreview")}
          aria-label={text("closePreview")}
          onClick={close}
          className="rounded p-1.5 text-gray-500 hover:bg-gray-100"
        >
          <X size={16} />
        </button>
      </header>
      <div className="flex min-h-0 flex-1">
        {showList && (
          <nav
            aria-label={text("showFiles")}
            className={`flex min-h-0 shrink-0 flex-col border-r border-gray-200 bg-gray-50/50 ${active ? "w-48" : "w-56 max-w-[55vw]"}`}
          >
            <div className="space-y-2 border-b border-gray-200 p-3">
              <Select
                ariaLabel={text("rootFolder")}
                value={source}
                onChange={value => navigate(value)}
                triggerClassName="text-xs"
                options={[{value:'__all__',label:text('allFiles')},{value:'',label:text('uploadedFiles')},
                  ...sessions.map(session=>({value:session.session_id,label:session.title || session.question}))]}
              />
              <div className="flex min-w-0 items-center gap-1 text-xs text-gray-500">
                <button
                  disabled={!parent}
                  aria-label={text("parentFolder")}
                  onClick={() =>
                    navigate(source, parent.split("/").slice(0, -1).join("/"))
                  }
                  className="rounded p-1 hover:bg-gray-100 disabled:opacity-30"
                >
                  <ArrowLeft size={14} />
                </button>
                <button
                  onClick={() => navigate(source)}
                  className="truncate text-left"
                  title={parent || text("rootFolder")}
                >
                  {parent || text("rootFolder")}
                </button>
                <button
                  aria-label={text("refresh")}
                  title={text("refresh")}
                  onClick={() => void indexFiles(true)}
                  className="ml-auto rounded p-1 hover:bg-gray-100"
                >
                  {page.data?.indexing ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <RefreshCw size={13} />
                  )}
                </button>
              </div>
              <input
                aria-label={text("fileSearch")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={text("fileSearch")}
                className="w-full rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs outline-none focus:border-gray-400"
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
              {page.isLoading && (
                <p className="p-3 text-xs text-gray-400">{text("loading")}</p>
              )}
              {page.error && (
                <p role="alert" className="p-3 text-xs text-red-600">
                  {String(page.error)}
                </p>
              )}
              {!page.isLoading && !page.data?.items.length && (
                <p className="p-3 text-xs leading-5 text-gray-400">
                  {page.data?.indexing
                    ? text("indexing")
                    : text("fileListEmpty")}
                </p>
              )}
              {page.data?.partial && (
                <p className="p-2 text-xs text-amber-700">{text("partial")}</p>
              )}
              {source && source !== "__all__" && (
                <details className="mb-1 px-2 py-1 text-xs text-gray-400">
                  <summary className="cursor-pointer">{text("path")}</summary>
                  <div className="mt-2 flex gap-1">
                    <input
                      value={exactPath}
                      onChange={(e) => setExactPath(e.target.value)}
                      aria-label={text("path")}
                      className="min-w-0 flex-1 rounded border bg-white px-2 py-1 text-gray-700"
                    />
                    <button
                      disabled={!exactPath.trim()}
                      aria-label={text("preview")}
                      onClick={() => {
                        openFile({ sessionId: source, path: exactPath.trim() });
                        setExactPath("");
                      }}
                      className="rounded border px-1.5"
                    >
                      <ChevronRight size={13} />
                    </button>
                  </div>
                </details>
              )}
              {page.data?.items.map((file) => (
                <button
                  key={file.id}
                  onClick={() =>
                    file.entry_kind === "directory"
                      ? navigate(source, file.path || "")
                      : openFile(file)
                  }
                  title={file.path || file.name}
                  aria-current={activeId === file.id ? "true" : undefined}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs ${activeId === file.id ? "bg-gray-200/70 text-gray-950" : "text-gray-600 hover:bg-gray-100"}`}
                >
                  {file.entry_kind === "directory" ? (
                    <Folder size={14} className="shrink-0 text-gray-400" />
                  ) : (
                    <FileText size={14} className="shrink-0 text-gray-400" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{file.name}</span>
                  {file.entry_kind === "directory" && (
                    <ChevronRight size={12} />
                  )}
                </button>
              ))}
            </div>
            {(page.data?.next_cursor || previousCursors.length > 0) && (
              <div className="flex items-center justify-between border-t px-2 py-1 text-xs text-gray-500">
                <button
                  disabled={!previousCursors.length || page.isFetching}
                  onClick={() => {
                    setCursor(previousCursors.at(-1)!);
                    setPreviousCursors((values) => values.slice(0, -1));
                  }}
                  className="rounded px-2 py-1 hover:bg-gray-100 disabled:opacity-30"
                >
                  {text("previous")}
                </button>
                <span>{previousCursors.length + 1}</span>
                <button
                  disabled={!page.data?.next_cursor || page.isFetching}
                  onClick={() => {
                    setPreviousCursors((values) => [...values, cursor]);
                    setCursor(page.data!.next_cursor!);
                  }}
                  className="rounded px-2 py-1 hover:bg-gray-100 disabled:opacity-30"
                >
                  {text("more")}
                </button>
              </div>
            )}
          </nav>
        )}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {tabs.length > 0 && (
            <div
              role="tablist"
              aria-label={text("preview")}
              className="flex shrink-0 overflow-x-auto border-b border-gray-200 bg-gray-50/50"
            >
              {tabs.map((file) => (
                <div
                  key={file.id}
                  className={`flex max-w-60 shrink-0 items-center border-r border-gray-200 ${activeId === file.id ? "bg-white" : ""}`}
                >
                  <button
                    role="tab"
                    aria-selected={activeId === file.id}
                    onClick={() => { setInitialPreview(undefined); setActiveId(file.id); }}
                    title={file.path || file.name}
                    className={`truncate px-3 py-2.5 text-xs ${activeId === file.id ? "font-medium text-gray-900" : "text-gray-500"}`}
                  >
                    {file.name}
                  </button>
                  <button
                    aria-label={`${text("closeTab")} ${file.name}`}
                    className="mr-1 rounded p-1 text-gray-400 hover:bg-gray-100"
                    onClick={() => {
                      setTabs((current) =>
                        current.filter((tab) => tab.id !== file.id),
                      );
                      if (activeId === file.id)
                        setActiveId(
                          tabs.filter((tab) => tab.id !== file.id).at(-1)?.id ||
                            "",
                        );
                    }}
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
          {active?.path && (
            <p
              className="shrink-0 truncate border-b border-gray-100 px-4 py-1.5 text-[11px] text-gray-400"
              title={active.path}
            >
              {active.path}
            </p>
          )}
          {error && (
            <p role="alert" className="shrink-0 p-3 text-xs text-red-600">
              {error}
            </p>
          )}
          <div className="min-h-0 flex-1">
            {busy ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 size={18} className="animate-spin text-gray-400" />
              </div>
            ) : active ? (
              <Suspense
                fallback={
                  <p className="p-5 text-xs text-gray-400">{text("loading")}</p>
                }
              >
                <FilePreviewContent
                  key={active.id}
                  file={active}
                  initialPreview={initialPreview?.file_id === active.id ? initialPreview : undefined}
                  workspaceId={workspaceId}
                  reload={reload}
                />
              </Suspense>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center">
                <FolderOpen size={28} className="text-gray-300" />
                <p className="text-sm text-gray-500">{text("selectFile")}</p>
                <p className="text-xs text-gray-400">{text("previewHint")}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
  const renderedPanel = open ? (
    fullscreen ? (
      <Dialog.Root
        open
        onOpenChange={(value) => {
          if (!value) setFullscreen(false);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[80] bg-black/20" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-0 z-[81] outline-none"
            onCloseAutoFocus={(event) => event.preventDefault()}
          >
            <Dialog.Title className="sr-only">
              {text("conversationFiles")}
            </Dialog.Title>
            <div ref={attachSurface} className="h-full" />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    ) : (
      <aside
        aria-label={text("conversationFiles")}
        style={{ "--file-panel-width": `${width}px` } as React.CSSProperties}
        className="fixed inset-x-0 bottom-0 top-[4.25rem] z-40 min-w-0 border-l border-gray-200 bg-white lg:relative lg:inset-auto lg:h-full lg:w-[min(var(--file-panel-width),64vw)] lg:shrink-0"
      >
        <div
          role="separator"
          aria-label={text("resizePreview")}
          aria-orientation="vertical"
          aria-valuemin={440}
          aria-valuemax={1200}
          aria-valuenow={width}
          tabIndex={0}
          className="absolute -left-1 top-0 hidden h-full w-2 cursor-col-resize outline-none focus-visible:bg-blue-100 lg:block"
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              setWidth((value) =>
                clampWidth(value + (event.key === "ArrowLeft" ? 32 : -32)),
              );
            }
          }}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              setWidth(clampWidth(window.innerWidth - event.clientX));
          }}
          onPointerUp={(event) =>
            event.currentTarget.releasePointerCapture(event.pointerId)
          }
        />
        <div ref={attachSurface} className="h-full" />
      </aside>
    )
  ) : null;
  return (
    <FilesContext.Provider value={context}>
      <PanelContext.Provider value={renderedPanel}>
        {children}
        {open && createPortal(panel, surface)}
      </PanelContext.Provider>
    </FilesContext.Provider>
  );
}

export function ConversationFilesButton({
  disabled = false,
}: {
  disabled?: boolean;
}) {
  const files = useConversationFiles();
  const text = useWorkbenchText();
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={disabled}
      aria-label={text("conversationFiles")}
      title={text("conversationFiles")}
      onClick={() => files?.openFiles()}
      className="shrink-0 gap-1.5"
    >
      <FolderOpen size={15} />
      <span className="hidden sm:inline">{text("conversationFiles")}</span>
    </Button>
  );
}

export function FileReferenceButton({
  file,
  className = "",
}: {
  file: ResourceItem;
  className?: string;
}) {
  const files = useConversationFiles();
  return file.kind === "file" ? (
    <button
      type="button"
      title={file.name}
      onClick={() => files?.openFile(file)}
      className={`truncate text-left hover:underline ${className}`}
    >
      @{file.name}
    </button>
  ) : (
    <span className={`truncate ${className}`}>@{file.name}</span>
  );
}
