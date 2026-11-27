import { Children, useEffect, useState, useRef, type ReactNode } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  Database,
  Wrench,
  BookOpen,
  Folder,
  ChevronDown,
  ChevronRight,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Pin,
  Loader2,
  Clock,
  CircleAlert,
  Files,
  UploadCloud,
} from "lucide-react";
import { useAuth } from "../../contexts/AuthContext";
import { BackgroundTaskPanel } from "../BackgroundTaskPanel";
import { useSidebarText } from "./sidebarText";
import {
  listChatFolders,
  listFiledChats,
  saveChatFolder,
  deleteChatFolder,
  fileChat,
  chatNavigationChanged,
  type ChatFolder,
  type FiledChat,
} from "../../api/chatNavigation";
import {
  createConversation,
  deleteConversation,
  getConversation,
} from "../../api/chat";
import { apiFetch, downloadBlobFile } from "../../api/client";
import { API_BASE } from "../../config";
import HistoryFiles from "./HistoryFiles";
import { stripChatBlocks } from "./chatBlockParsing";
import { SPECIAL_BLOCK_TAGS } from "../../lib/utils/chatBlockRegistry";
import { Select } from '../ui/select';
import { preloadDataPage } from '../../lib/dataPages';
import type { Page } from "../../api/workbench";

const button =
  "flex min-h-10 cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-primary-500 disabled:opacity-50";
function OptionsMenu({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Dropdown.Root modal={false}>
      <Dropdown.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className="shrink-0 rounded-md p-2 text-gray-500 hover:bg-gray-100"
        >
          <MoreHorizontal size={16} />
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="end"
          sideOffset={4}
          className="z-[75] min-w-44 rounded-lg border border-gray-200 bg-white p-1 shadow-lg"
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          {Children.map(children, (child) => (
            <Dropdown.Item asChild>{child}</Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
type Edit = {
  kind:
    | "new-folder"
    | "rename-folder"
    | "delete-folder"
    | "rename-chat"
    | "move"
    | "delete-chat";
  id?: string;
  name?: string;
};
export default function WorkbenchSidebar() {
  const { user, isAdmin } = useAuth();
  const t = useSidebarText();
  const navigate = useNavigate();
  const location = useLocation();
  const cache = useQueryClient();
  const sidebarRef = useRef<HTMLElement>(null);
  const actionLock = useRef(false);
  const [open, setOpen] = useState(
    () =>
      innerWidth >= 1024 &&
      localStorage.getItem("workbench-sidebar-open") !== "false",
  );
  const [query, setQuery] = useState("");
  const [needle, setNeedle] = useState("");
  const [expanded, setExpanded] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(
        localStorage.getItem("chat-folders:" + user?.id) || "[]",
      );
      return Array.isArray(stored)
        ? stored.filter((value) => typeof value === "string").slice(0, 100)
        : [];
    } catch {
      return [];
    }
  });
  const [edit, setEdit] = useState<Edit>();
  const [name, setName] = useState("");
  const [destination, setDestination] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deletedChats, setDeletedChats] = useState<Set<string>>(new Set());
  const deletingChats = useRef(new Set<string>());
  const folders = useInfiniteQuery({
    queryKey: ["chat-folders", user?.id],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) => listChatFolders(pageParam, signal),
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: !!user?.id,
  });
  const allFolders = folders.data?.pages.flatMap((page) => page.items) || [];
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["chat-folders", user?.id] });
    void cache.invalidateQueries({ queryKey: ["filed-chats", user?.id] });
  };
  useEffect(() => {
    window.addEventListener("chat-navigation:changed", refresh);
    return () => window.removeEventListener("chat-navigation:changed", refresh);
  }, [cache, user?.id]);
  useEffect(() => {
    const handle = () => setOpen((v) => !v);
    window.addEventListener("toggle-ai-sidebar", handle);
    return () => window.removeEventListener("toggle-ai-sidebar", handle);
  }, []);
  useEffect(() => {
    localStorage.setItem("workbench-sidebar-open", String(open));
  }, [open]);
  useEffect(() => {
    localStorage.setItem("chat-folders:" + user?.id, JSON.stringify(expanded));
  }, [expanded, user?.id]);
  useEffect(() => {
    const timer = setTimeout(() => setNeedle(query.trim()), 220);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (innerWidth < 1024) setOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    let wasMobile = innerWidth < 1024;
    const resized = () => {
      const mobile = innerWidth < 1024;
      if (mobile && !wasMobile) setOpen(false);
      wasMobile = mobile;
    };
    window.addEventListener("resize", resized);
    return () => window.removeEventListener("resize", resized);
  }, []);
  useEffect(() => {
    const main = document.querySelector<HTMLElement>("[data-shell-main]");
    const sync = () => {
      if (main) main.inert = open && innerWidth < 1024;
    };
    sync();
    if (open && innerWidth < 1024)
      sidebarRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    window.addEventListener("resize", sync);
    return () => {
      window.removeEventListener("resize", sync);
      if (main) main.inert = false;
    };
  }, [open]);
  useEffect(() => {
    const esc = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !edit && innerWidth < 1024) setOpen(false);
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [edit]);
  function go(path: string) {
    navigate(path);
    if (innerWidth < 1024) setOpen(false);
  }
  function dialog(value: Edit) {
    setName(value.name || "");
    setDestination("");
    setError("");
    setEdit(value);
  }
  async function action(fn: () => Promise<unknown>) {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
      chatNavigationChanged();
      setEdit(undefined);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }
  async function removeConversation(identity: string) {
    if (deletingChats.current.has(identity)) return;
    deletingChats.current.add(identity);
    setDeletedChats((previous) => new Set([...previous, identity]));
    setEdit(undefined);
    setError("");
    window.dispatchEvent(new CustomEvent("chat:deleted", { detail: identity }));
    if (location.pathname === "/dashboard/" + identity) fresh();
    try {
      await deleteConversation(identity);
      await cache.cancelQueries({ queryKey: ["filed-chats", user?.id] });
      cache.setQueriesData<InfiniteData<Page<FiledChat>>>(
        { queryKey: ["filed-chats", user?.id] },
        (data) => data && ({
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            items: page.items.filter((chat) => chat.conversation_id !== identity),
          })),
        }),
      );
      chatNavigationChanged();
    } catch {
      // Restore only this row; another concurrent deletion must stay removed.
      setDeletedChats((previous) => {
        const next = new Set(previous);
        next.delete(identity);
        return next;
      });
      setError(t("deleteFailed"));
      void cache.invalidateQueries({ queryKey: ["filed-chats", user?.id] });
    } finally {
      deletingChats.current.delete(identity);
    }
  }
  function fresh() {
    window.dispatchEvent(new Event("chat:new"));
    go("/dashboard");
  }
  async function newInFolder(folder: ChatFolder) {
    await action(async () => {
      const chat = await createConversation(t("newChat"), {
        folderId: folder.id,
      });
      setExpanded((v) => (v.includes(folder.id) ? v : [...v, folder.id]));
      go("/dashboard/" + chat.conversation_id);
    });
  }
  function drop(event: React.DragEvent, folder_id: string | null) {
    const id = event.dataTransfer.getData("application/pathlab-chat");
    if (!id) return;
    event.preventDefault();
    void action(() => fileChat(id, { folder_id }));
  }
  return (
    <>
      {open && (
        <button
          className="fixed inset-0 top-[4.25rem] z-40 bg-black/20 lg:hidden"
          aria-label={t("close")}
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        ref={sidebarRef}
        id="workbench-sidebar"
        aria-label={t("chats")}
        className={`${open ? "flex" : "hidden lg:flex"} fixed bottom-0 left-0 top-[4.25rem] z-40 flex-col border-r border-gray-200 bg-slate-50 lg:relative lg:inset-auto lg:z-20 lg:shrink-0 ${open ? "w-[280px]" : "w-14"}`}
      >
        <div className="flex shrink-0 items-center gap-1 px-3 py-3">
          {open && (
            <button
              onClick={fresh}
              className={
                button +
                " min-w-0 flex-1 border border-gray-200 bg-white font-medium"
              }
            >
              <Plus size={17} />
              {t("newChat")}
            </button>
          )}
          <button
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100"
            aria-label={t(open ? "close" : "open")}
            aria-expanded={open}
            aria-controls="workbench-sidebar"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
        </div>
        {open && (
          <>
            <div className="shrink-0 space-y-3 px-3 pb-3">
              <label className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3">
                <Search size={15} className="shrink-0 text-gray-400" />
                <input
                  aria-label={t("search")}
                  placeholder={t("search")}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="min-w-0 w-full bg-transparent py-2.5 text-sm outline-none"
                />
              </label>
            </div>
            <nav className="shrink-0 px-3 pb-3" aria-label="Workbench">
              {[
                { path: "/upload", key: "upload" as const, icon: UploadCloud },
                { path: "/datasets", key: "data" as const, icon: Database },
                { path: "/files", key: "files" as const, icon: Files },
                { path: "/tools", key: "tools" as const, icon: Wrench },
                {
                  path: "/abilities",
                  key: "abilities" as const,
                  icon: BookOpen,
                },
              ].map((item) => (
                <button
                  key={item.path}
                  onPointerEnter={() => preloadDataPage(item.path)}
                  onFocus={() => preloadDataPage(item.path)}
                  onClick={() => go(item.path)}
                  aria-current={
                    location.pathname === item.path ? "page" : undefined
                  }
                  className={
                    button +
                    " w-full " +
                    (location.pathname === item.path
                      ? "bg-primary-50 text-primary-700"
                      : "")
                  }
                >
                  <item.icon size={17} />
                  {t(item.key)}
                </button>
              ))}
            </nav>
            <div className="flex shrink-0 items-center justify-between border-t border-gray-200 px-4 pt-3">
              <h2 className="text-xs font-medium text-slate-500">
                {t("chats")}
              </h2>
              <OptionsMenu label={t("menu")}>
                <button
                  className={button + " w-full"}
                  onClick={() => {
                    dialog({ kind: "new-folder" });
                  }}
                >
                  {t("newFolder")}
                </button>
              </OptionsMenu>
            </div>
            {(error && !edit) || folders.error ? (
              <p role="alert" className="px-4 py-2 text-xs text-red-600">
                {error || String(folders.error)}
              </p>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
              {!needle && (
                <div className="mb-3">
                  {allFolders.map((folder) => (
                    <section
                      key={folder.id}
                      aria-label={folder.name}
                      onDragOver={(e) => {
                        if (
                          e.dataTransfer.types.includes(
                            "application/pathlab-chat",
                          )
                        )
                          e.preventDefault();
                      }}
                      onDrop={(e) => drop(e, folder.id)}
                      className="rounded-lg focus-within:bg-white"
                    >
                      <div className="flex items-center">
                        <button
                          className={button + " min-w-0 flex-1 px-2"}
                          aria-expanded={expanded.includes(folder.id)}
                          onClick={() =>
                            setExpanded((v) =>
                              v.includes(folder.id)
                                ? v.filter((id) => id !== folder.id)
                                : [...v, folder.id],
                            )
                          }
                        >
                          {expanded.includes(folder.id) ? (
                            <ChevronDown size={13} />
                          ) : (
                            <ChevronRight size={13} />
                          )}
                          <Folder
                            size={16}
                            className="shrink-0 text-gray-500"
                          />
                          <span className="truncate" title={folder.name}>
                            {folder.name}
                          </span>
                        </button>
                        <OptionsMenu
                          label={`${t("folderMenu")}: ${folder.name}`}
                        >
                          <button
                            className={button + " w-full"}
                            onClick={() => void newInFolder(folder)}
                          >
                            {t("newChat")}
                          </button>
                          <button
                            className={button + " w-full"}
                            onClick={() =>
                              dialog({
                                kind: "rename-folder",
                                id: folder.id,
                                name: folder.name,
                              })
                            }
                          >
                            {t("rename")}
                          </button>
                          <button
                            className={button + " w-full"}
                            onClick={() =>
                              dialog({
                                kind: "delete-folder",
                                id: folder.id,
                                name: folder.name,
                              })
                            }
                          >
                            {t("removeFolder")}
                          </button>
                        </OptionsMenu>
                      </div>
                      {expanded.includes(folder.id) && (
                        <ChatRows
                          hiddenIds={deletedChats}
                          folder={folder.id}
                          needle=""
                          onEdit={dialog}
                          onPin={(chat) =>
                            void action(() =>
                              fileChat(chat.conversation_id, {
                                pinned: !chat.pinned,
                              }),
                            )
                          }
                          go={go}
                        />
                      )}
                    </section>
                  ))}
                  {folders.hasNextPage && (
                    <button
                      className={button}
                      disabled={folders.isFetchingNextPage}
                      onClick={() => void folders.fetchNextPage()}
                    >
                      {t("more")}
                    </button>
                  )}
                </div>
              )}
              <div
                onDragOver={(e) => {
                  if (e.dataTransfer.types.includes("application/pathlab-chat"))
                    e.preventDefault();
                }}
                onDrop={(e) => drop(e, null)}
              >
                {!needle && allFolders.length > 0 && (
                  <div className="px-2 py-2 text-xs text-gray-500">
                    {t("unfiled")}
                  </div>
                )}
                <ChatRows
                  hiddenIds={deletedChats}
                  key={needle}
                  folder=""
                  needle={needle}
                  onEdit={dialog}
                  onPin={(chat) =>
                    void action(() =>
                      fileChat(chat.conversation_id, { pinned: !chat.pinned }),
                    )
                  }
                  go={go}
                />
              </div>
            </div>
          </>
        )}
        <footer
          className={
            open
              ? "shrink-0 border-t border-gray-200 p-2"
              : "mt-auto border-t p-1"
          }
        >
          <BackgroundTaskPanel sidebar compact={!open} />
          {isAdmin && (
            <button
              className={button + " w-full"}
              aria-label={t("system")}
              onClick={() => {
                go("/settings");
              }}
            >
              <Settings size={17} />
              {open && t("system")}
            </button>
          )}
        </footer>
      </aside>
      <Dialog.Root
        open={!!edit}
        onOpenChange={(value) => {
          if (!value && !busy) setEdit(undefined);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[80] bg-black/25" />
          <Dialog.Content
            aria-describedby="chat-filing-description"
            className="fixed left-1/2 top-1/2 z-[81] w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-white p-5 shadow-xl"
          >
            <Dialog.Title className="text-base font-semibold">
              {edit?.kind === "new-folder"
                ? t("newFolder")
                : edit?.kind === "delete-folder"
                  ? t("removeFolder")
                  : edit?.kind === "move"
                    ? t("move")
                    : edit?.kind === "delete-chat"
                      ? t("delete")
                      : t("rename")}
            </Dialog.Title>
            <Dialog.Description
              id="chat-filing-description"
              className="mt-2 text-sm text-gray-500"
            >
              {edit?.kind === "delete-folder"
                ? t("folderHint")
                : edit?.kind === "delete-chat"
                  ? t("deleteHint")
                  : edit?.name || t("folderName")}
            </Dialog.Description>
            <form
              className="mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (edit?.kind === "delete-chat") {
                  void removeConversation(edit.id!);
                  return;
                }
                void action(async () => {
                  if (!edit) return;
                  if (edit.kind === "new-folder") {
                    const row = await saveChatFolder(name);
                    setExpanded((v) => [...v, row.id]);
                  } else if (edit.kind === "rename-folder")
                    await saveChatFolder(name, edit.id);
                  else if (edit.kind === "delete-folder")
                    await deleteChatFolder(edit.id!);
                  else if (edit.kind === "rename-chat")
                    await fileChat(edit.id!, { title: name });
                  else if (edit.kind === "move")
                    await fileChat(edit.id!, {
                      folder_id: destination || null,
                    });
                });
              }}
            >
              {edit?.kind === "move" ? (
                <>
                  <Select
                    ariaLabel={t("move")}
                    value={destination}
                    onChange={setDestination}
                    options={[{value:'', label:t('outside')}, ...allFolders.map(folder => ({value:folder.id, label:folder.name}))]}
                  />
                  {folders.hasNextPage && (
                    <button
                      type="button"
                      className={button}
                      onClick={() => void folders.fetchNextPage()}
                    >
                      {t("more")}
                    </button>
                  )}
                </>
              ) : (
                edit &&
                !edit.kind.startsWith("delete") && (
                  <input
                    required
                    maxLength={edit.kind === "rename-chat" ? 500 : 120}
                    aria-label={t("folderName")}
                    className="w-full rounded-lg border p-3 text-sm"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                )
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
                  type="submit"
                  disabled={busy}
                  className={
                    button + " bg-primary-600 text-white hover:bg-primary-700"
                  }
                >
                  {busy ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : edit?.kind.startsWith("delete") ? (
                    t(edit.kind === "delete-folder" ? "removeFolder" : "delete")
                  ) : (
                    t("save")
                  )}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function ChatRows({
  folder,
  needle,
  onEdit,
  onPin,
  go,
  hiddenIds,
}: {
  folder: string;
  needle: string;
  onEdit: (edit: Edit) => void;
  onPin: (chat: FiledChat) => void;
  go: (path: string) => void;
  hiddenIds: Set<string>;
}) {
  const { user } = useAuth();
  const t = useSidebarText();
  const location = useLocation();
  const navigate = useNavigate();
  const [files, setFiles] = useState<string>();
  const [error, setError] = useState("");
  const query = useInfiniteQuery({
    queryKey: ["filed-chats", user?.id, folder, needle],
    initialPageParam: "",
    queryFn: ({ pageParam, signal }) =>
      listFiledChats(folder, needle, pageParam, signal),
    getNextPageParam: (last) => last.next_cursor || undefined,
    enabled: !!user?.id,
    staleTime: 3000,
  });
  const rows = (query.data?.pages.flatMap((page) => page.items) || []).filter(
    (chat) => !hiddenIds.has(chat.conversation_id),
  );
  const ids = rows.slice(-100).map((row) => row.conversation_id);
  const status = useQuery({
    queryKey: ["sidebar-chat-status", user?.id, ids.join(",")],
    queryFn: ({ signal }) =>
      apiFetch<{
        states: Record<string, string>;
        file_conversations: string[];
      }>(`${API_BASE}/workbench/research-statuses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_ids: ids }),
        signal,
      }),
    enabled: !!ids.length,
    refetchInterval: 8000,
    refetchIntervalInBackground: false,
  });
  async function exportChat(chat: FiledChat) {
    try {
      const detail = await getConversation(chat.conversation_id);
      const body = detail.messages
        .map(
          (message) =>
            `## ${message.role}\n\n${stripChatBlocks(message.content, [...SPECIAL_BLOCK_TAGS])}`,
        )
        .join("\n\n");
      downloadBlobFile(
        new Blob([`# ${chat.title}\n\n${body}`], { type: "text/markdown" }),
        (chat.title || "chat").replace(/[\\/:*?"<>|]/g, "_").slice(0, 80) +
          ".md",
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function group(row: FiledChat) {
    if (row.pinned) return t("pinned");
    const now = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const date = new Date(row.updated_at).toDateString();
    return date === now.toDateString()
      ? t("today")
      : date === yesterday.toDateString()
        ? t("yesterday")
        : t("earlier");
  }
  return (
    <div className={folder ? "pl-4" : ""}>
      {query.isLoading && (
        <p role="status" className="px-2 py-3 text-xs text-gray-500">
          {t("loading")}
        </p>
      )}
      {(query.error || error) && (
        <p role="alert" className="px-2 py-3 text-xs text-red-600">
          {error || String(query.error)}
        </p>
      )}
      {!query.isLoading && !rows.length && (
        <p className="px-2 py-3 text-xs text-gray-400">
          {t(needle ? "noResults" : "empty")}
        </p>
      )}
      {rows.map((chat, index) => {
        const state = status.data?.states[chat.conversation_id];
        return (
          <div key={chat.conversation_id}>
            {!folder &&
              !needle &&
              (index === 0 || group(chat) !== group(rows[index - 1])) && (
                <h3 className="px-2 pb-1 pt-3 text-xs text-gray-500">
                  {group(chat)}
                </h3>
              )}
            <div
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  "application/pathlab-chat",
                  chat.conversation_id,
                );
                e.dataTransfer.effectAllowed = "move";
              }}
              className={
                "group rounded-lg " +
                (location.pathname === "/dashboard/" + chat.conversation_id
                  ? "bg-primary-50"
                  : "hover:bg-white")
              }
            >
              <div className="flex items-center">
                <button
                  onClick={() => go("/dashboard/" + chat.conversation_id)}
                  className="flex min-h-10 min-w-0 flex-1 items-center gap-2 px-2 text-left text-sm"
                  title={chat.title}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{chat.title}</span>
                    {needle && chat.folder_name && (
                      <span className="block truncate text-xs text-gray-500">
                        {chat.folder_name}
                      </span>
                    )}
                  </span>
                  {chat.pinned && (
                    <Pin size={12} className="shrink-0 text-gray-400" />
                  )}
                  {state && (
                    <span
                      aria-label={t(
                        state === "queued"
                          ? "queued"
                          : state === "blocked"
                            ? "blocked"
                            : state === "paused"
                              ? "paused"
                              : state === "failed"
                                ? "failed"
                                : "running",
                      )}
                    >
                      {state === "failed" ? (
                        <CircleAlert size={13} className="text-red-600" />
                      ) : ["queued", "blocked", "paused"].includes(state) ? (
                        <Clock size={13} />
                      ) : (
                        <Loader2 size={13} className="animate-spin" />
                      )}
                    </span>
                  )}
                </button>
                <OptionsMenu label={`${t("menu")}: ${chat.title}`}>
                  <button
                    className={button + " w-full"}
                    onClick={() =>
                      onEdit({
                        kind: "rename-chat",
                        id: chat.conversation_id,
                        name: chat.title,
                      })
                    }
                  >
                    {t("rename")}
                  </button>
                  <button
                    className={button + " w-full"}
                    onClick={() =>
                      onEdit({
                        kind: "move",
                        id: chat.conversation_id,
                        name: chat.title,
                      })
                    }
                  >
                    {t("move")}
                  </button>
                  <button
                    className={button + " w-full"}
                    onClick={() => onPin(chat)}
                  >
                    {t(chat.pinned ? "unpin" : "pin")}
                  </button>
                  <button
                    className={button + " w-full"}
                    onClick={() => void exportChat(chat)}
                  >
                    {t("export")}
                  </button>
                  <button
                    className={button + " w-full"}
                    onClick={() =>
                      onEdit({
                        kind: "delete-chat",
                        id: chat.conversation_id,
                        name: chat.title,
                      })
                    }
                  >
                    {t("delete")}
                  </button>
                </OptionsMenu>
              </div>
              {user &&
                status.data?.file_conversations.includes(
                  chat.conversation_id,
                ) && (
                  <HistoryFiles
                    conversationId={chat.conversation_id}
                    userId={user.id}
                    expanded={files === chat.conversation_id}
                    onToggle={() =>
                      setFiles((value) =>
                        value === chat.conversation_id
                          ? undefined
                          : chat.conversation_id,
                      )
                    }
                    onOpen={(file) => {
                      navigate("/dashboard/" + chat.conversation_id, {
                        state: {
                          sidebarFile: {
                            conversationId: chat.conversation_id,
                            file,
                            key: performance.now(),
                          },
                        },
                      });
                    }}
                  />
                )}
            </div>
          </div>
        );
      })}
      {query.hasNextPage && (
        <button
          className={button + " w-full justify-center"}
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t("more")}
        </button>
      )}
    </div>
  );
}
