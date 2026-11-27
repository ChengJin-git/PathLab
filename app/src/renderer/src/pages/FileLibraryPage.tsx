import { useEffect, useRef, useState, lazy, Suspense } from "react";
import { Select } from "../components/ui/select";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  Files,
  Folder,
  Upload,
  Plus,
  Search,
  X,
  Download,
  ArrowUpRight,
  Loader2,
  MoreHorizontal,
  FileText,
  Image,
  FileCode,
  Sheet,
  Check,
  ChevronRight,
  MessageSquare,
  Pencil,
  Trash2,
  ArrowLeft,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useFileLibraryText } from "../components/chat/fileLibraryText";
import * as api from "../api/fileLibrary";
import { Checkbox } from "../components/ui/checkbox";
import { formatFileSize } from "../lib/utils/utils";
import { downloadWorkbenchFile, type ResourceItem } from "../api/workbench";
const Preview = lazy(() => import("../components/chat/FilePreviewContent"));
const button =
  "inline-flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-40";
const field =
  "min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100";
type Edit = {
  kind:
    | "folder"
    | "rename"
    | "delete-file"
    | "delete-folder"
    | "batch-edit"
    | "batch-delete"
    | "text";
  id?: string;
  name?: string;
  file?: api.LibraryFile;
};
function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase();
  const Icon = ["png", "jpg", "jpeg", "webp", "gif"].includes(ext || "")
    ? Image
    : ["csv", "tsv", "xlsx"].includes(ext || "")
      ? Sheet
      : ["py", "js", "json", "sh", "r"].includes(ext || "")
        ? FileCode
        : FileText;
  return <Icon size={20} strokeWidth={1.5} />;
}
function ActionMenu({
  label,
  items,
}: {
  label: string;
  items: { label: string; action: () => void; danger?: boolean }[];
}) {
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button aria-label={label} className={button + " px-2"}>
          <MoreHorizontal size={18} />
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="end"
          sideOffset={6}
          className="z-[95] min-w-44 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/10"
        >
          {items.map((item) => (
            <Menu.Item
              key={item.label}
              onSelect={item.action}
              className={
                "cursor-pointer rounded-lg px-3 py-2.5 text-sm outline-none data-[highlighted]:bg-slate-100 " +
                (item.danger ? "text-red-600" : "text-slate-700")
              }
            >
              {item.label}
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
export default function FileLibraryPage() {
  const { user, isAdmin } = useAuth();
  const t = useFileLibraryText();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [params, setParams] = useSearchParams();
  const selected = params.get("file") || "";
  const [view, setView] = useState(isAdmin ? "all" : "mine");
  const [groupMode, setGroupMode] = useState<"chat" | "files">("chat");
  const [conversation, setConversation] = useState("");
  const [checked, setChecked] = useState<Map<string, api.LibraryFile>>(
    new Map(),
  );
  const [batchNames, setBatchNames] = useState<Record<string, string>>({});
  const [batchFolder, setBatchFolder] = useState("__keep__");
  const [textContent, setTextContent] = useState("");
  const [textRevision, setTextRevision] = useState("");
  const [textLoading, setTextLoading] = useState(false);
  const [owner, setOwner] = useState("");
  const [folder, setFolder] = useState("");
  const [origin, setOrigin] = useState("");
  const [query, setQuery] = useState("");
  const [needle, setNeedle] = useState("");
  const [hits, setHits] = useState<api.FileHit[]>();
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<Edit>();
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState(() => innerWidth < 1100);
  const upload = useRef<HTMLInputElement>(null);
  const replace = useRef<HTMLInputElement>(null);
  const lock = useRef(false);
  const searchController = useRef<AbortController>();
  const textRequest = useRef(0);
  useEffect(() => {
    if (edit?.kind !== "text" || !edit.file) return;
    const version = ++textRequest.current;
    setTextLoading(true);
    setTextContent("");
    setTextRevision("");
    void api
      .readLibraryText(edit.file.id)
      .then((data) => {
        if (version !== textRequest.current) return;
        setTextContent(data.content);
        setTextRevision(data.revision);
      })
      .catch((error) => {
        if (version === textRequest.current) setError(String(error));
      })
      .finally(() => {
        if (version === textRequest.current) setTextLoading(false);
      });
    return () => {
      textRequest.current++;
    };
  }, [edit]);
  useEffect(() => {
    const media = matchMedia("(max-width:1099px)");
    const changed = () => setMobile(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => setNeedle(query.trim()), 200);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    searchController.current?.abort();
    setHits(undefined);
    setSearching(false);
    setChecked(new Map());
  }, [query, folder, view, owner, origin, conversation, groupMode]);
  useEffect(() => () => searchController.current?.abort(), []);
  const folders = useQuery({
    queryKey: ["library-folders", user?.id, view],
    queryFn: ({ signal }) => api.libraryFolders(view, signal),
  });
  const owners = useQuery({
    queryKey: ["library-owners", user?.id],
    queryFn: ({ signal }) => api.libraryOwners(signal),
    enabled: isAdmin && view === "all",
  });
  const list = useInfiniteQuery({
    queryKey: [
      "library-files",
      user?.id,
      view,
      owner,
      folder,
      origin,
      needle,
      conversation,
      groupMode,
    ],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) =>
      api.libraryFiles(
        {
          view,
          owner,
          folder,
          origin,
          q: needle,
          cursor: pageParam,
          conversation,
          limit: "30",
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: groupMode === "files" || !!conversation,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) =>
        page.items.some((item) =>
          ["queued", "processing"].includes(item.index_status),
        ),
      )
        ? 2500
        : false,
  });
  const groups = useInfiniteQuery({
    queryKey: ["library-groups", user?.id, view, owner, folder, origin, needle],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) =>
      api.libraryGroups(
        {
          view,
          owner,
          folder,
          origin,
          q: needle,
          cursor: pageParam,
          limit: "30",
        },
        signal,
      ),
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: groupMode === "chat",
  });
  const groupRows = groups.data?.pages.flatMap((page) => page.items) || [];
  const group = groupRows.find((item) => item.id === conversation);
  const showingGroups = groupMode === "chat" && !conversation;
  const detail = useQuery({
    queryKey: ["library-file", user?.id, selected],
    queryFn: ({ signal }) => api.libraryFile(selected, signal),
    enabled: !!selected,
    refetchInterval: (query) =>
      ["queued", "processing"].includes(query.state.data?.index_status || "")
        ? 1500
        : false,
  });
  const file = detail.data;
  const rows = list.data?.pages.flatMap((page) => page.items) || [];
  const selectedFiles = [...checked.values()];
  const allLoadedSelected =
    rows.length > 0 && rows.slice(0, 100).every((item) => checked.has(item.id));
  const folderItems = folders.data?.items || [];
  const currentFolder = folderItems.find((item) => item.id === folder);
  async function refresh() {
    await Promise.all(
      [
        "library-files",
        "library-file",
        "library-folders",
        "library-groups",
      ].map((key) => cache.invalidateQueries({ queryKey: [key, user?.id] })),
    );
  }
  useEffect(() => {
    const changed = () => {
      void refresh();
    };
    window.addEventListener("chat:deleted", changed);
    return () => window.removeEventListener("chat:deleted", changed);
  }, [cache, user?.id]);
  async function act(fn: () => Promise<unknown>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
      setEdit(undefined);
      setChecked(new Map());
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function openEdit(value: Edit) {
    setEdit(value);
    setName(value.name || "");
    setError("");
    if (value.kind === "batch-edit") {
      setBatchNames(
        Object.fromEntries(
          [...checked.values()].map((file) => [file.id, file.name]),
        ),
      );
      setBatchFolder("__keep__");
    }
  }
  const toggleFile = (item: api.LibraryFile, value: boolean) =>
    setChecked((previous) => {
      const next = new Map(previous);
      if (value) {
        if (next.size >= 100) {
          setError(t("selectionLimit"));
          return previous;
        }
        next.set(item.id, item);
      } else next.delete(item.id);
      return next;
    });
  const fileActions = (item: api.LibraryFile) => [
    {
      label: t("rename"),
      action: () =>
        openEdit({ kind: "rename", id: item.id, name: item.name, file: item }),
    },
    ...(item.editable_text
      ? [
          {
            label: t("editText"),
            action: () => openEdit({ kind: "text", id: item.id, file: item }),
          },
        ]
      : []),
    {
      label: t("remove"),
      action: () => openEdit({ kind: "delete-file", id: item.id, file: item }),
      danger: true,
    },
  ];
  function use(item: ResourceItem, fresh = false) {
    const path = fresh
      ? "/dashboard"
      : sessionStorage.getItem("workbench:chat:" + user?.id) || "/dashboard";
    if (fresh) window.dispatchEvent(new Event("chat:new"));
    navigate(path, {
      state: {
        reference: { kind: item.kind, id: item.id, revision: item.revision },
      },
    });
  }
  async function searchContents() {
    if (!query.trim()) return;
    searchController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    setSearching(true);
    setError("");
    try {
      const response = await api.searchLibrary(
        query,
        { folder, all_users: view === "all", owner },
        controller.signal,
      );
      if (!controller.signal.aborted) setHits(response.items);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }
  const status = (value: string) =>
    t(
      (["ready", "queued", "processing", "failed", "cancelled"].includes(value)
        ? value
        : "unsupported") as "ready",
    );
  const inspector = (
    <>
      {file ? (
        <>
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <span className="text-xs font-medium text-slate-500">
              {t("details")}
            </span>
            <button
              aria-label={t("close")}
              className={button + " min-h-8 px-1.5"}
              onClick={() => setParams({})}
            >
              <X size={17} />
            </button>
          </div>
          <div className="space-y-4 px-5 py-5">
            <div className="flex items-center gap-3">
              <span className="rounded-xl bg-slate-100 p-3 text-slate-500">
                <FileIcon name={file.name} />
              </span>
              <div className="min-w-0">
                <h2 className="break-words text-sm font-semibold text-slate-800">
                  {file.name}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {Math.max(
                    1,
                    Math.ceil((file.size || 0) / 1024),
                  ).toLocaleString()}{" "}
                  KB · {status(file.index_status)}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                className={
                  button + " flex-1 bg-blue-600 text-white hover:bg-blue-700"
                }
                onClick={() => use(file)}
              >
                {t("use")}
                <ArrowUpRight size={15} />
              </button>
              <button
                className={button + " bg-slate-100"}
                aria-label={t("download")}
                disabled={downloading}
                onClick={async () => {
                  if (downloading) return;
                  setDownloading(true);
                  setError("");
                  try {
                    await downloadWorkbenchFile(file, null);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setDownloading(false);
                  }
                }}
              >
                {downloading ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : (
                  <Download size={17} />
                )}
              </button>
              <ActionMenu
                label={t("actions")}
                items={[
                  { label: t("newChat"), action: () => use(file, true) },
                  ...fileActions(file),
                  {
                    label: t("replace"),
                    action: () => replace.current?.click(),
                  },
                ]}
              />
            </div>
            <label className="flex items-center justify-between gap-3 text-xs text-slate-500">
              {t("move")}
              <Select
                ariaLabel={t("move")}
                value={file.folder_id || ""}
                disabled={busy}
                onChange={(value) =>
                  void act(() =>
                    api.editLibraryFile(file, {
                      folder_id: value || null,
                    }),
                  )
                }
                className="w-[70%]"
                triggerClassName="text-xs"
                options={[
                  { value: "", label: t("root") },
                  ...folderItems
                    .filter((item) => item.owner_id === file.owner_id)
                    .map((item) => ({ value: item.id, label: item.name })),
                ]}
              />
            </label>
            {file.conversation_id && (
              <button
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                onClick={() => navigate("/dashboard/" + file.conversation_id)}
              >
                {t("sourceChat")}
                <ChevronRight size={12} />
              </button>
            )}
            {["queued", "processing", "failed", "cancelled"].includes(
              file.index_status,
            ) && (
              <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 p-3 text-xs">
                <span role="status">{status(file.index_status)}</span>
                <button
                  className="text-blue-600"
                  onClick={() =>
                    void act(() =>
                      api.indexLibraryFile(
                        file.id,
                        ["queued", "processing"].includes(file.index_status),
                      ),
                    )
                  }
                >
                  {["queued", "processing"].includes(file.index_status)
                    ? t("cancel")
                    : t("retry")}
                </button>
              </div>
            )}
            {file.index_error && (
              <p className="text-xs leading-5 text-red-600">
                {file.index_error}
              </p>
            )}
            {params.get("revision") &&
              params.get("revision") !== file.revision && (
                <p className="text-xs text-amber-700">{t("changed")}</p>
              )}
          </div>
          <div className="min-h-0 flex-1 overflow-hidden border-t border-slate-100">
            <Suspense fallback={<div className="h-full bg-slate-50" />}>
              <Preview
                file={file}
                workspaceId={null}
                page={Number(params.get("page")) || undefined}
              />
            </Suspense>
          </div>
        </>
      ) : detail.error ? (
        <p role="alert" className="p-5 text-sm text-red-600">
          {String(detail.error)}
        </p>
      ) : (
        <div className="m-5 h-48 animate-pulse rounded-xl bg-slate-50" />
      )}
    </>
  );
  return (
    <section className="mx-auto flex h-[calc(100dvh-7rem)] min-h-[480px] max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm shadow-slate-900/[0.02]">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-5 py-5 sm:px-7">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            {t("title")}
          </h1>
          <p className="mt-1 hidden text-xs text-slate-500 sm:block">
            {t("subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            className={button}
            aria-label={t("newFolder")}
            onClick={() => openEdit({ kind: "folder" })}
          >
            <Folder size={17} />
            <Plus size={12} />
          </button>
          <button
            className={button + " bg-blue-600 text-white hover:bg-blue-700"}
            disabled={busy}
            onClick={() => upload.current?.click()}
          >
            {busy ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Upload size={16} />
            )}
            <span>{t("upload")}</span>
          </button>
        </div>
      </header>
      <input
        ref={upload}
        type="file"
        multiple
        className="hidden"
        aria-label={t("upload")}
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = "";
          void act(async () => {
            for (const file of files) await api.uploadLibraryFile(file);
          });
        }}
      />
      <input
        ref={replace}
        type="file"
        className="hidden"
        aria-label={t("replace")}
        onChange={(event) => {
          const value = event.target.files?.[0];
          event.target.value = "";
          if (value && file) void act(() => api.uploadLibraryFile(value, file));
        }}
      />
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label={t("folders")}
          className="hidden w-44 shrink-0 space-y-1 overflow-y-auto border-r border-slate-100 bg-slate-50/70 p-3 xl:block"
        >
          <button
            className={
              button +
              " w-full justify-start " +
              (!folder ? "bg-white text-blue-600 shadow-sm" : "")
            }
            onClick={() => setFolder("")}
          >
            <Files size={16} />
            {t("all")}
          </button>
          <p className="px-3 pb-1 pt-5 text-[11px] font-medium text-slate-400">
            {t("folders")}
          </p>
          {folderItems.map((item) => (
            <div key={item.id} className="group flex items-center">
              <button
                className={
                  button +
                  " min-w-0 flex-1 justify-start px-2 " +
                  (folder === item.id ? "bg-white text-blue-600" : "")
                }
                onClick={() => setFolder(item.id)}
              >
                <Folder size={15} />
                <span className="truncate">{item.name}</span>
              </button>
              <ActionMenu
                label={item.name + " " + t("actions")}
                items={[
                  {
                    label: t("rename"),
                    action: () =>
                      openEdit({
                        kind: "folder",
                        id: item.id,
                        name: item.name,
                      }),
                  },
                  {
                    label: t("remove"),
                    action: () =>
                      openEdit({ kind: "delete-folder", id: item.id }),
                    danger: true,
                  },
                ]}
              />
            </div>
          ))}
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="shrink-0 space-y-3 border-b border-slate-100 px-4 py-4 sm:px-6">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void searchContents();
              }}
            >
              <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-slate-100/80 px-3 text-slate-400 focus-within:ring-2 focus-within:ring-blue-100">
                <Search size={17} />
                <input
                  className="min-h-10 min-w-0 flex-1 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("search")}
                  aria-label={t("search")}
                />
                {query && (
                  <button
                    type="button"
                    aria-label={t("cancel")}
                    onClick={() => setQuery("")}
                  >
                    <X size={14} />
                  </button>
                )}
              </label>
              <button
                disabled={!query.trim() || searching}
                className={button + " shrink-0 border border-slate-200"}
              >
                {searching ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <span>{t("contentSearch")}</span>
                )}
              </button>
            </form>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
                {[
                  ["", "all"],
                  ["generated", "generated"],
                  ["upload", "uploads"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setOrigin(value)}
                    className={
                      "min-h-8 rounded-md px-3 text-xs transition-colors " +
                      (origin === value
                        ? "bg-white font-medium text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-800")
                    }
                  >
                    {t(label as "all")}
                  </button>
                ))}
              </div>
              <div className="flex min-w-0 gap-2">
                <Select
                  ariaLabel={t("folders")}
                  className="max-w-36 xl:hidden"
                  triggerClassName="text-xs"
                  value={folder}
                  onChange={setFolder}
                  options={[
                    { value: "", label: t("all") },
                    ...folderItems.map((item) => ({
                      value: item.id,
                      label: item.name,
                    })),
                  ]}
                />
                {currentFolder && (
                  <div className="xl:hidden">
                    <ActionMenu
                      label={currentFolder.name + " " + t("actions")}
                      items={[
                        {
                          label: t("rename"),
                          action: () =>
                            openEdit({
                              kind: "folder",
                              id: currentFolder.id,
                              name: currentFolder.name,
                            }),
                        },
                        {
                          label: t("remove"),
                          action: () =>
                            openEdit({
                              kind: "delete-folder",
                              id: currentFolder.id,
                            }),
                          danger: true,
                        },
                      ]}
                    />
                  </div>
                )}
                {isAdmin && (
                  <Select
                    ariaLabel={t("everyone")}
                    value={view}
                    triggerClassName="text-xs"
                    onChange={(value) => {
                      setView(value);
                      setFolder("");
                      setOwner("");
                    }}
                    options={[
                      { value: "mine", label: t("mine") },
                      { value: "all", label: t("everyone") },
                    ]}
                  />
                )}
                {view === "all" && (
                  <Select
                    ariaLabel={t("owner")}
                    value={owner}
                    className="max-w-36"
                    triggerClassName="text-xs"
                    onChange={setOwner}
                    options={[
                      { value: "", label: t("everyone") },
                      ...(owners.data?.items || []).map((item) => ({
                        value: item.id,
                        label: item.name,
                      })),
                    ]}
                  />
                )}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2 sm:px-6">
            {conversation ? (
              <button
                className={button + " min-w-0 justify-start px-0"}
                onClick={() => setConversation("")}
              >
                <ArrowLeft size={15} />
                <span className="truncate">
                  {group?.title ||
                    t(
                      conversation === "__unlinked__"
                        ? "unlinked"
                        : "chatFiles",
                    )}
                </span>
              </button>
            ) : (
              <div className="flex gap-3">
                {(["chat", "files"] as const).map((mode) => (
                  <button
                    key={mode}
                    aria-pressed={groupMode === mode}
                    className={
                      button +
                      " px-0 " +
                      (groupMode === mode ? "text-slate-900" : "text-slate-400")
                    }
                    onClick={() => {
                      setGroupMode(mode);
                      setConversation("");
                    }}
                  >
                    {t(mode === "chat" ? "byChat" : "flat")}
                  </button>
                ))}
              </div>
            )}
            {!showingGroups && !hits && (
              <span className="text-xs text-slate-400">
                {t("loaded")} · {rows.length}
              </span>
            )}
          </div>
          {!!checked.size && !hits && (
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2 sm:px-6">
              <span className="mr-auto text-xs font-medium text-slate-600">
                {checked.size} {t("selection")}
              </span>
              <button
                className={button}
                disabled={busy}
                onClick={() => openEdit({ kind: "batch-edit" })}
              >
                <Pencil size={14} />
                {t("batchEdit")}
              </button>
              <button
                className={button + " text-red-600"}
                disabled={busy}
                onClick={() => openEdit({ kind: "batch-delete" })}
              >
                <Trash2 size={14} />
                {t("batchDelete")}
              </button>
              <button
                className={button}
                aria-label={t("cancel")}
                onClick={() => setChecked(new Map())}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {(error || (showingGroups ? groups.error : list.error)) && (
            <p
              role="alert"
              className="m-4 rounded-lg bg-red-50 p-3 text-sm text-red-600"
            >
              {error || String(showingGroups ? groups.error : list.error)}
            </p>
          )}
          <div className="min-h-0 flex-1 overflow-auto">
            {hits ? (
              <div className="space-y-3 p-5">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{t("searchResults")}</span>
                  <button
                    onClick={() => setHits(undefined)}
                    className="text-blue-600"
                  >
                    {t("back")}
                  </button>
                </div>
                {!hits.length && (
                  <p className="py-10 text-center text-sm text-slate-500">
                    {t("noEvidence")}
                  </p>
                )}
                {hits.map((hit, index) => (
                  <button
                    key={index}
                    onClick={() =>
                      setParams({
                        file: hit.file_id,
                        page: String(hit.page),
                        revision: hit.revision,
                      })
                    }
                    className="block w-full rounded-xl border border-slate-100 p-4 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/30"
                  >
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <FileText size={15} />
                      {hit.name}
                      <span className="ml-auto text-xs font-normal text-slate-400">
                        {hit.page ? `${t("page")} ${hit.page}` : hit.section}
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-500">
                      {hit.text}
                    </p>
                  </button>
                ))}
              </div>
            ) : showingGroups ? (
              <>
                {groupRows.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setConversation(item.id)}
                    className="flex min-h-20 w-full items-center gap-4 border-b border-slate-100 px-5 py-4 text-left transition-colors hover:bg-slate-50"
                  >
                    <span className="text-slate-400">
                      {item.id === "__unlinked__" ? (
                        <Files size={20} strokeWidth={1.5} />
                      ) : (
                        <MessageSquare size={20} strokeWidth={1.5} />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-800">
                        {item.title ||
                          t(
                            item.id === "__unlinked__"
                              ? "unlinked"
                              : "chatFiles",
                          )}
                      </span>
                      <span className="mt-1 block text-xs text-slate-400">
                        {item.file_count} {t("fileCount")} ·{" "}
                        {formatFileSize(item.total_size)}
                      </span>
                    </span>
                    <span className="hidden text-xs text-slate-400 sm:block">
                      {new Date(item.updated_at).toLocaleDateString()}
                    </span>
                    <ChevronRight size={15} className="text-slate-300" />
                  </button>
                ))}
                {groups.isLoading ? (
                  <div role="status" className="p-10">
                    <Loader2
                      className="mx-auto animate-spin text-slate-400"
                      size={20}
                    />
                  </div>
                ) : (
                  !groupRows.length && (
                    <div className="px-8 py-20 text-center">
                      <p className="text-sm text-slate-600">{t("empty")}</p>
                      <p className="mt-2 text-xs text-slate-400">
                        {t("emptyHint")}
                      </p>
                    </div>
                  )
                )}
                {groups.hasNextPage && (
                  <div className="p-4 text-center">
                    <button
                      disabled={groups.isFetchingNextPage}
                      className={button}
                      onClick={() => void groups.fetchNextPage()}
                    >
                      {t("more")}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-slate-100 bg-white px-5 py-2.5 text-[11px] font-medium text-slate-400">
                  <Checkbox
                    aria-label={t("selectPage")}
                    checked={allLoadedSelected}
                    disabled={!rows.length || busy}
                    onCheckedChange={(value) =>
                      setChecked(
                        value
                          ? new Map(
                              rows.slice(0, 100).map((item) => [item.id, item]),
                            )
                          : new Map(),
                      )
                    }
                  />
                  <span className="flex-1">
                    {currentFolder?.name || t("name")}
                  </span>
                  <span className="hidden sm:block">{t("updated")}</span>
                </div>
                {rows.map((item) => (
                  <div
                    key={item.id}
                    className={
                      "flex min-h-[72px] w-full items-center gap-3 border-b border-slate-100/80 px-5 py-3 text-left transition-colors " +
                      (item.id === selected
                        ? "bg-blue-50/70"
                        : "hover:bg-slate-50")
                    }
                  >
                    <Checkbox
                      aria-label={item.name}
                      checked={checked.has(item.id)}
                      disabled={busy}
                      onCheckedChange={(value) => toggleFile(item, !!value)}
                    />
                    <button
                      onClick={() => {
                        setParams({ file: item.id });
                        setError("");
                      }}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <span className="shrink-0 text-slate-400">
                        <FileIcon name={item.name} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-slate-700">
                          {item.name}
                        </span>
                        <span className="mt-1 flex items-center gap-1.5 text-[11px] text-slate-400">
                          {["queued", "processing"].includes(
                            item.index_status,
                          ) ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : item.index_status === "ready" ? (
                            <Check size={11} />
                          ) : null}
                          {status(item.index_status)}
                          <span>·</span>
                          {Math.max(
                            1,
                            Math.ceil((item.size || 0) / 1024),
                          ).toLocaleString()}{" "}
                          KB
                          {view === "all" && (
                            <span className="truncate">
                              · {item.owner_name || item.owner_id}
                            </span>
                          )}
                        </span>
                      </span>
                    </button>
                    <span className="hidden text-xs text-slate-400 sm:block">
                      {new Date(item.updated_at).toLocaleDateString()}
                    </span>
                    <ActionMenu
                      label={item.name + " " + t("actions")}
                      items={fileActions(item)}
                    />
                  </div>
                ))}
                {list.isLoading ? (
                  <div aria-busy="true" className="space-y-5 p-6">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="h-10 rounded-lg bg-slate-50" />
                    ))}
                  </div>
                ) : (
                  !rows.length && (
                    <div className="mx-auto flex max-w-sm flex-col items-center px-8 py-20 text-center">
                      <Files
                        size={34}
                        strokeWidth={1}
                        className="mb-5 text-slate-300"
                      />
                      <h2 className="text-base font-medium text-slate-700">
                        {t("empty")}
                      </h2>
                      <p className="mt-2 text-sm leading-6 text-slate-400">
                        {t("emptyHint")}
                      </p>
                    </div>
                  )
                )}
                {list.hasNextPage && (
                  <div className="p-4 text-center">
                    <button
                      disabled={list.isFetchingNextPage}
                      className={button}
                      onClick={() => void list.fetchNextPage()}
                    >
                      {t("more")}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        {selected && !mobile && (
          <aside
            aria-label={t("details")}
            className="flex w-[38%] min-w-[340px] max-w-[520px] shrink-0 flex-col border-l border-slate-100 bg-white"
          >
            {inspector}
          </aside>
        )}
      </div>
      <Dialog.Root
        open={!!selected && mobile}
        onOpenChange={(open) => {
          if (!open) setParams({});
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[80] bg-slate-900/20" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-2 z-[81] flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-xl sm:inset-6"
          >
            <Dialog.Title className="sr-only">{t("details")}</Dialog.Title>
            {inspector}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <Dialog.Root
        open={!!edit}
        onOpenChange={(open) => {
          if (!open && !busy) setEdit(undefined);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[90] bg-slate-900/20" />
          <Dialog.Content
            aria-describedby={undefined}
            className={
              "fixed left-1/2 top-1/2 z-[91] max-h-[90dvh] overflow-y-auto -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-6 shadow-xl " +
              (edit?.kind === "text" || edit?.kind === "batch-edit"
                ? "w-[min(720px,calc(100vw-32px))]"
                : "w-[min(420px,calc(100vw-32px))]")
            }
          >
            <Dialog.Title className="text-base font-semibold text-slate-800">
              {edit?.kind === "batch-delete"
                ? t("deleteSelectedHint")
                : edit?.kind === "batch-edit"
                  ? t("batchEdit")
                  : edit?.kind === "text"
                    ? t("editText")
                    : edit?.kind === "delete-file"
                      ? t("deleteHint")
                      : edit?.kind === "delete-folder"
                        ? t("groupDelete")
                        : t("name")}
            </Dialog.Title>
            <form
              className="mt-5 space-y-5"
              onSubmit={(event) => {
                event.preventDefault();
                void act(async () => {
                  if (!edit) return;
                  if (edit.kind === "delete-file") {
                    await api.deleteLibraryFile(edit.id!);
                    setParams({});
                  } else if (edit.kind === "delete-folder") {
                    await api.deleteLibraryFolder(edit.id!);
                    setFolder("");
                  } else if (edit.kind === "rename" && edit.file)
                    await api.editLibraryFile(edit.file, { name });
                  else if (edit.kind === "text" && edit.file)
                    await api.saveLibraryText(
                      edit.file.id,
                      textRevision,
                      textContent,
                    );
                  else if (edit.kind === "batch-delete") {
                    await api.batchLibraryFiles(
                      selectedFiles.map((item) => ({
                        id: item.id,
                        revision: item.revision,
                        updated_at: item.updated_at,
                      })),
                      "delete",
                    );
                    if (checked.has(selected)) setParams({});
                  } else if (edit.kind === "batch-edit")
                    await api.batchLibraryFiles(
                      selectedFiles.map((item) => ({
                        id: item.id,
                        revision: item.revision,
                        updated_at: item.updated_at,
                        name: batchNames[item.id],
                      })),
                      "edit",
                      batchFolder === "__keep__"
                        ? undefined
                        : batchFolder || null,
                    );
                  else if (edit.kind === "folder")
                    await api.saveLibraryFolder(name, edit.id);
                });
              }}
            >
              {edit && ["folder", "rename"].includes(edit.kind) && (
                <input
                  required
                  autoFocus
                  maxLength={edit.kind === "rename" ? 240 : 120}
                  aria-label={t("name")}
                  className={field + " w-full"}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              )}
              {edit?.kind === "text" &&
                (textLoading ? (
                  <Loader2 className="mx-auto animate-spin" size={20} />
                ) : (
                  <textarea
                    aria-label={t("content")}
                    value={textContent}
                    onChange={(event) => setTextContent(event.target.value)}
                    maxLength={1024 * 1024}
                    className={
                      field +
                      " min-h-72 w-full py-3 font-mono text-xs leading-6"
                    }
                    disabled={busy || !textRevision}
                  />
                ))}
              {edit?.kind === "batch-edit" && (
                <div className="space-y-4">
                  <p className="text-xs leading-5 text-slate-500">
                    {t("batchHint")}
                  </p>
                  <Select
                    ariaLabel={t("move")}
                    value={batchFolder}
                    onChange={setBatchFolder}
                    options={[
                      { value: "__keep__", label: t("keepFolder") },
                      { value: "", label: t("root") },
                      ...folderItems
                        .filter((item) =>
                          selectedFiles.every(
                            (file) => file.owner_id === item.owner_id,
                          ),
                        )
                        .map((item) => ({ value: item.id, label: item.name })),
                    ]}
                  />
                  <div className="max-h-72 space-y-3 overflow-y-auto">
                    {selectedFiles.map((item) => (
                      <label
                        key={item.id}
                        className="block space-y-1 text-xs text-slate-500"
                      >
                        <span className="block truncate">{item.name}</span>
                        <input
                          aria-label={item.name}
                          required
                          maxLength={240}
                          className={field + " w-full"}
                          value={batchNames[item.id] || ""}
                          onChange={(event) =>
                            setBatchNames((previous) => ({
                              ...previous,
                              [item.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {error && (
                <p role="alert" className="text-sm text-red-600">
                  {error}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className={button}
                  disabled={busy}
                  onClick={() => setEdit(undefined)}
                >
                  {t("cancel")}
                </button>
                <button
                  disabled={
                    busy ||
                    (edit?.kind === "text" && (textLoading || !textRevision))
                  }
                  className={
                    button + " bg-blue-600 text-white hover:bg-blue-700"
                  }
                >
                  {t(
                    edit?.kind.startsWith("delete") ||
                      edit?.kind === "batch-delete"
                      ? "remove"
                      : "save",
                  )}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
