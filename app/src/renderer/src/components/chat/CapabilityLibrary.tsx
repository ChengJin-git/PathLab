import { useEffect, useRef, useState } from "react";
import { Select } from '../ui/select';
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Globe2,
  Loader2,
  LockKeyhole,
  Plug,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
import { useAuth } from "../../contexts/AuthContext";
import { commandLanguage } from "../../locales/commands";
import {
  connectCapability,
  importCapability,
  installCapability,
  listCapabilities,
  readCapability,
  removeCapability,
  saveCapability,
  syncCapability,
  type CapabilityDraft,
  type CapabilityEntry,
  type CapabilityKind,
} from "../../api/capabilities";
import type { WorkbenchCommand } from "../../api/workbench";
import { useCapabilityText } from "./capabilityText";
import SkillPackageEditor from "./SkillPackageEditor";
import CapabilityLogo from './CapabilityLogo'
import { Button } from '../ui/button'
import { Input } from '../ui/input'

const inputClass =
  "w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 disabled:bg-gray-50";
const buttonClass =
  "inline-flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-50 focus-visible:ring-2 focus-visible:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-50";

export default function CapabilityLibrary({
  kind,
  onClose,
  onUse,
  inline = false,
}: {
  kind: CapabilityKind;
  onClose: () => void;
  onUse: (command: WorkbenchCommand) => void;
  inline?: boolean;
}) {
  const { user, isAdmin } = useAuth();
  const { i18n } = useTranslation();
  const text = useCapabilityText();
  const language = commandLanguage(i18n.language);
  const client = useQueryClient();
  const [activeKind, setKind] = useState(kind);
  const [view, setView] = useState("installed");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [cursor, setCursor] = useState("");
  const [previous, setPrevious] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const upload = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(query);
      setCursor("");
      setPrevious([]);
    }, 180);
    return () => clearTimeout(timer);
  }, [query]);
  const page = useQuery({
    queryKey: [
      "capability-library",
      user?.id,
      user?.role,
      activeKind,
      view,
      debounced,
      cursor,
      language,
    ],
    queryFn: ({ signal }) =>
      listCapabilities(
        { kind: activeKind, view, q: debounced, cursor, language },
        signal,
      ),
    enabled: !selected && !creating,
    staleTime: 3000,
  });
  function refresh() {
    void client.invalidateQueries({ queryKey: ["capability-library"] });
    window.dispatchEvent(new Event("capabilities:changed"));
  }
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function reset(nextKind = activeKind, nextView = view) {
    setKind(nextKind);
    setView(nextView);
    setCursor("");
    setPrevious([]);
    setSelected(null);
    setCreating(false);
    setError("");
    if (nextKind !== activeKind) {
      setQuery("");
      setDebounced("");
    }
  }
  const content = (
    <>
      <header className="flex shrink-0 items-start justify-between gap-4 border-b border-gray-100 px-4 py-4 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">
            {text("abilities")}
          </h1>
          <p
            id="capability-library-description"
            className="mt-1 text-xs leading-5 text-gray-500"
          >
            {text("subtitle")}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label={text("close")}
          className="cursor-pointer rounded-lg p-2 text-gray-500 hover:bg-gray-100"
        >
          <X size={19} />
        </button>
      </header>
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <nav
          aria-label={text("subtitle")}
          className="flex shrink-0 gap-1 border-b border-gray-100 bg-gray-50/60 p-2 sm:w-40 sm:flex-col sm:border-b-0 sm:border-r sm:p-3"
        >
          {(["skill", "connector"] as const).map((value) => (
            <button
              key={value}
              onClick={() => reset(value)}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm ${activeKind === value ? "bg-white font-medium text-primary-700 shadow-sm" : "text-gray-600 hover:bg-white"}`}
            >
              {value === "skill" ? <BookOpen size={16} /> : <Plug size={16} />}
              <span>{text(value === "skill" ? "skills" : "connectors")}</span>
            </button>
          ))}
        </nav>
        <main className="min-h-0 min-w-0 flex-1 overflow-auto p-4 sm:p-6">
          {selected || creating ? (
            <CapabilityEditor
              key={selected || "new-" + activeKind}
              id={selected}
              kind={activeKind}
              language={language}
              onBack={() => reset()}
              onSaved={(entry) => {
                refresh();
                setCreating(false);
                setSelected(entry.id);
              }}
              onUse={(entry) => {
                onUse({
                  id: entry.id,
                  name: entry.name,
                  description: entry.description,
                  mode: "skill",
                  library_skill_id: entry.id,
                });
                onClose();
              }}
              onChanged={refresh}
            />
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <div
                  className="flex min-w-0 flex-1 flex-wrap gap-1"
                  role="tablist"
                  aria-label={text("skills")}
                >
                  {[
                    "installed",
                    "discover",
                    "mine",
                    ...(isAdmin ? ["all"] : []),
                  ].map((value) => (
                    <button
                      role="tab"
                      aria-selected={view === value}
                      key={value}
                      onClick={() => reset(activeKind, value)}
                      className={`min-h-10 cursor-pointer rounded-lg px-3 text-sm ${view === value ? "bg-gray-100 font-medium text-gray-900" : "text-gray-500 hover:bg-gray-50"}`}
                    >
                      {text(
                        value === "installed" && activeKind === "connector"
                          ? "connectedApps"
                          : (value as "installed"),
                      )}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => setCreating(true)}
                  className={buttonClass}
                >
                  <Plus size={15} />
                  {text("add")}
                </button>
                {activeKind === "skill" && (
                  <button
                    disabled={busy}
                    onClick={() => upload.current?.click()}
                    className={buttonClass}
                  >
                    <Upload size={15} />
                    {text("upload")}
                  </button>
                )}
              </div>
              <input
                ref={upload}
                type="file"
                accept=".md,.markdown,.zip,.skill"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file)
                    void action(async () => {
                      const entry = await importCapability(file, "private");
                      setSelected(entry.id);
                    });
                }}
              />
              <label className="mb-5 flex items-center gap-2 rounded-lg border border-gray-200 px-3 focus-within:border-primary-500">
                <Search size={16} className="text-gray-400" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={text("search")}
                  aria-label={text("search")}
                  className="min-h-11 min-w-0 flex-1 bg-transparent text-sm outline-none"
                />
              </label>
              {activeKind === "skill" && (
                <p className="mb-4 text-xs leading-5 text-gray-500">
                  {text("preloadHint")}
                </p>
              )}
              {(error || page.error) && (
                <p role="alert" className="mb-4 text-sm text-red-600">
                  {error || String(page.error)}
                </p>
              )}
              {page.isFetching && (
                <p
                  role="status"
                  className="mb-3 flex items-center gap-2 text-xs text-gray-500"
                >
                  <Loader2 size={14} className="animate-spin" />
                  {text("loading")}
                </p>
              )}
              <div className="grid gap-3 md:grid-cols-2">
                {page.data?.items.map((entry) => (
                  <article
                    key={entry.id}
                    className="flex min-w-0 flex-col rounded-xl border border-gray-200 p-4"
                  >
                    <div className="flex items-start gap-3">
                      <CapabilityLogo entry={entry} />
                      <button
                        className="min-w-0 flex-1 cursor-pointer text-left"
                        onClick={() => setSelected(entry.id)}
                      >
                        <h3 className="break-words text-sm font-semibold text-gray-900">
                          {entry.name}
                        </h3>
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">
                          {entry.description}
                        </p>
                      </button>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                      {entry.builtin ? (
                        <span>{text("builtin")}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1">
                          {entry.visibility === "public" ? (
                            <Globe2 size={12} />
                          ) : (
                            <LockKeyhole size={12} />
                          )}
                          {text(entry.visibility)}
                        </span>
                      )}
                      {entry.kind === "connector" && (
                        <span
                          className={entry.connected ? "text-emerald-700" : ""}
                        >
                          {text(entry.connected ? "connected" : "disconnected")}
                        </span>
                      )}
                    </div>
                    {isAdmin && view === "all" && entry.owner_id && (
                      <p
                        className="mt-2 truncate text-[11px] text-gray-500"
                        title={entry.owner_id}
                      >
                        {text("owner")}: {entry.owner_id}
                      </p>
                    )}
                    <footer className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
                      <button
                        onClick={() => setSelected(entry.id)}
                        className="min-h-9 cursor-pointer text-xs text-gray-600 underline underline-offset-4"
                      >
                        {text("detail")}
                      </button>
                      {entry.installed ? (
                        <button
                          role="switch"
                          aria-checked={entry.enabled}
                          aria-label={`${entry.enabled ? text("disable") : text("enable")} ${entry.name}`}
                          disabled={busy}
                          onClick={() =>
                            void action(() =>
                              installCapability(entry.id, !entry.enabled),
                            )
                          }
                          className="flex min-h-10 cursor-pointer items-center gap-2 text-xs text-gray-600 disabled:opacity-40"
                        >
                          <span>
                            {text(entry.enabled ? "enabled" : "disabled")}
                          </span>
                          <span
                            className={`inline-flex h-5 w-9 items-center rounded-full p-0.5 transition-colors ${entry.enabled ? "bg-primary-600" : "bg-gray-200"}`}
                          >
                            <span
                              className={`h-4 w-4 rounded-full bg-white transition-transform ${entry.enabled ? "translate-x-4" : ""}`}
                            />
                          </span>
                        </button>
                      ) : (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void action(() => installCapability(entry.id, true))
                          }
                          className={buttonClass}
                        >
                          <Plus size={14} />
                          {text("install")}
                        </button>
                      )}
                    </footer>
                  </article>
                ))}
              </div>
              {!page.isLoading && !page.data?.items.length && (
                <p className="py-14 text-center text-sm text-gray-500">
                  {text("empty")}
                </p>
              )}
              <footer className="mt-5 flex justify-end gap-2">
                <button
                  className={buttonClass}
                  disabled={!previous.length || page.isFetching}
                  onClick={() => {
                    setCursor(previous.at(-1) || "");
                    setPrevious(previous.slice(0, -1));
                  }}
                >
                  <ChevronLeft size={15} />
                  {text("previous")}
                </button>
                <button
                  className={buttonClass}
                  disabled={!page.data?.next_cursor || page.isFetching}
                  onClick={() => {
                    setPrevious([...previous, cursor]);
                    setCursor(page.data!.next_cursor!);
                  }}
                >
                  {text("next")}
                  <ChevronRight size={15} />
                </button>
              </footer>
            </>
          )}
        </main>
      </div>
    </>
  );
  if (inline)
    return (
      <section className="flex min-h-[calc(100dvh-110px)] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white">
        {content}
      </section>
    );
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-black/25" />
        <Dialog.Content
          aria-describedby="capability-library-description"
          className="fixed inset-2 z-[81] flex min-h-0 flex-col overflow-hidden rounded-2xl border bg-white shadow-xl sm:inset-6 lg:inset-x-[max(24px,calc((100vw-1080px)/2))]"
        >
          <Dialog.Title className="sr-only">{text("abilities")}</Dialog.Title>
          {content}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CapabilityEditor({
  id,
  kind,
  language,
  onBack,
  onSaved,
  onUse,
  onChanged,
}: {
  id: string | null;
  kind: CapabilityKind;
  language: string;
  onBack: () => void;
  onSaved: (entry: CapabilityEntry) => void;
  onUse: (entry: CapabilityEntry) => void;
  onChanged: () => void;
}) {
  const { user } = useAuth();
  const text = useCapabilityText();
  const [draft, setDraft] = useState<CapabilityDraft>({
    kind,
    name: "",
    description: "",
    visibility: "private",
    content: "",
    url: "",
  });
  const [editing, setEditing] = useState(!id);
  const [fileEditing, setFileEditing] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [github, setGithub] = useState('');
  const query = useQuery({
    queryKey: ["capability-entry", user?.id, user?.role, id, language],
    queryFn: ({ signal }) => readCapability(id!, language, signal),
    enabled: !!id,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (query.data) {
      const entry = query.data;
      setGithub(entry.github_source?.url || '');
      setDraft({
        kind: entry.kind,
        name: entry.name,
        description: entry.description,
        visibility: entry.visibility,
        content: entry.content || "",
        url: entry.config?.url || "",
        revision: entry.revision,
        source_url: entry.github_source?.url || '',
      });
    }
  }, [query.data]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      onChanged();
      if (id) await query.refetch();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const entry = query.data;
  const mutable = editing && (!id || entry?.editable);
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <button
        onClick={onBack}
        disabled={fileEditing}
        className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-sm text-gray-500"
      >
        <ArrowLeft size={16} />
        {text("back")}
      </button>
      {query.isLoading && id ? (
        <p role="status">{text("loading")}</p>
      ) : (
        <>
          {(error || query.error) && (
            <p
              role="alert"
              className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
            >
              {error || String(query.error)}
            </p>
          )}
          {entry && <section className="space-y-3 rounded-2xl border border-slate-200 p-4"><div className="flex items-center gap-3"><CapabilityLogo entry={entry} /><div className="min-w-0"><h2 className="text-sm font-semibold">{entry.name}</h2><p className="mt-1 text-xs text-slate-500">{text('syncHint')}</p></div></div>
            <label className="block text-xs font-medium text-slate-600">{text('github')}<Input className="mt-2" value={github} placeholder="https://github.com/owner/repository" disabled={!entry.can_sync || busy || editing || fileEditing} onChange={event => setGithub(event.target.value)} /></label>
            {entry.github_source?.commit && <p className="break-all text-xs text-slate-500">{entry.github_source.path} · {entry.github_source.commit.slice(0, 12)}{entry.github_source.synced_at && <> · {text('synced')}: {new Date(entry.github_source.synced_at).toLocaleString()}</>}</p>}
            {entry.can_sync ? <Button type="button" variant="outline" size="sm" disabled={!github || busy || editing || fileEditing} onClick={() => void action(async () => { await syncCapability(entry.id, entry.revision, github === entry.github_source?.url ? undefined : github) })}>{busy && <Loader2 size={14} className="mr-2 animate-spin" />}{text('sync')}</Button> : entry.github_source && <p className="text-xs text-slate-500">{text('syncOwner')}</p>}
            <p className="text-xs text-slate-500">{text('artwork')}: {entry.logo ? <a href={entry.logo.source} target="_blank" rel="noreferrer" className="underline">{entry.logo.license}</a> : <a href="https://github.com/lucide-icons/lucide/blob/main/LICENSE" target="_blank" rel="noreferrer" className="underline">{text('fallbackArtwork')}</a>}</p>
          </section>}
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!mutable || busy) return;
              void action(async () => {
                const saved = await saveCapability(draft, id || undefined);
                setEditing(false);
                onSaved(saved);
              });
            }}
          >
            <label className="block text-xs font-medium text-gray-600">
              {text("name")}
              <input
                required
                maxLength={120}
                disabled={!mutable || busy}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className={inputClass + " mt-2"}
              />
            </label>
            <label className="block text-xs font-medium text-gray-600">
              {text("description")}
              <textarea
                maxLength={1200}
                rows={2}
                disabled={!mutable || busy}
                value={draft.description}
                onChange={(e) =>
                  setDraft({ ...draft, description: e.target.value })
                }
                className={inputClass + " mt-2"}
              />
            </label>
            {!entry?.builtin && (
              <label className="block text-xs font-medium text-gray-600">
                {text("visibility")}
                <Select
                  ariaLabel={text('visibility')}
                  disabled={!mutable || busy}
                  value={draft.visibility}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      visibility: value as "private" | "public",
                    })
                  }
                  className="mt-2"
                  options={[{value:'private',label:text('private')},{value:'public',label:text('public')}]}
                />
                <span className="mt-2 block text-xs font-normal leading-5 text-gray-500">
                  {text(
                    draft.visibility === "public"
                      ? "publicHint"
                      : "privateHint",
                  )}
                </span>
              </label>
            )}
            {!entry?.builtin && <label className="block text-xs font-medium text-gray-600">{text('github')}<Input className="mt-2" disabled={!mutable || busy} value={draft.source_url || ''} placeholder="https://github.com/owner/repository" onChange={event => setDraft({ ...draft, source_url: event.target.value })} /><span className="mt-2 block font-normal text-gray-500">{text('sourceHint')}</span></label>}
            {kind === "skill" ? (
              <label className="block text-xs font-medium text-gray-600">
                {text("content")}
                <textarea
                  required
                  rows={12}
                  maxLength={128000}
                  disabled={!mutable || busy}
                  placeholder={text("skillPlaceholder")}
                  value={draft.content}
                  onChange={(e) =>
                    setDraft({ ...draft, content: e.target.value })
                  }
                  className={inputClass + " mt-2 font-mono text-xs leading-6"}
                />
              </label>
            ) : (
              !entry?.builtin && (
                <label className="block text-xs font-medium text-gray-600">
                  {text("endpoint")}
                  <input
                    type="url"
                    required
                    disabled={!mutable || busy}
                    placeholder="https://example.com/mcp"
                    value={draft.url}
                    onChange={(e) =>
                      setDraft({ ...draft, url: e.target.value })
                    }
                    className={inputClass + " mt-2"}
                  />
                  <span className="mt-2 block font-normal leading-5 text-gray-500">
                    {text("endpointHint")}
                  </span>
                </label>
              )
            )}
            {kind === "skill" && !id && (
              <p className="text-xs text-gray-500">
                {text("filesAfterCreate")}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {mutable ? (
                <>
                  <button
                    type="submit"
                    disabled={busy}
                    className={
                      buttonClass + " bg-gray-900 text-white hover:bg-gray-800"
                    }
                  >
                    {busy ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <Check size={15} />
                    )}{" "}
                    {text("save")}
                  </button>
                  {id && (
                    <button
                      type="button"
                      onClick={() => {
                        if (entry)
                          setDraft({
                            kind: entry.kind,
                            name: entry.name,
                            description: entry.description,
                            visibility: entry.visibility,
                            content: entry.content || "",
                            url: entry.config?.url || "",
                             revision: entry.revision,
                             source_url: entry.github_source?.url || '',
                          });
                        setEditing(false);
                      }}
                      className={buttonClass}
                    >
                      {text("cancel")}
                    </button>
                  )}
                </>
              ) : (
                <>
                  {entry?.editable && (
                    <button
                      type="button"
                      disabled={fileEditing}
                      onClick={(event) => {
                        event.preventDefault();
                        setEditing(true);
                      }}
                      className={buttonClass}
                    >
                      {text("edit")}
                    </button>
                  )}
                  {entry &&
                    kind === "skill" &&
                    entry.installed &&
                    entry.enabled && (
                      <button
                        type="button"
                        onClick={() => onUse(entry)}
                        disabled={fileEditing}
                        className={
                          buttonClass + " border-primary-200 text-primary-700"
                        }
                      >
                        {text("use")}
                      </button>
                    )}
                  {entry && !entry.installed && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await installCapability(entry.id, true);
                        })
                      }
                      className={buttonClass}
                    >
                      {text("install")}
                    </button>
                  )}
                </>
              )}
            </div>
          </form>
          {entry && kind === "skill" && !entry.builtin && !editing && (
            <SkillPackageEditor
              entry={entry}
              onEditing={setFileEditing}
              onChanged={async () => {
                onChanged();
                return (await query.refetch()).data;
              }}
            />
          )}
          {entry &&
            kind === "connector" &&
            !entry.builtin &&
            entry.installed &&
            !editing && (
              <section className="space-y-3 rounded-xl border border-gray-200 p-4">
                <p className="text-sm font-medium">
                  {text(entry.connected ? "connected" : "disconnected")}
                </p>
                <label className="block text-xs font-medium text-gray-600">
                  {text("token")}
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    disabled={busy}
                    className={inputClass + " mt-2"}
                    placeholder={entry.has_credential ? "••••••••" : ""}
                  />
                  <span className="mt-1 block font-normal leading-5 text-gray-500">
                    {text("tokenHint")}
                  </span>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    disabled={busy}
                    className={buttonClass}
                    onClick={() =>
                      void action(async () => {
                        await installCapability(
                          entry.id,
                          true,
                          token || undefined,
                        );
                        await connectCapability(entry.id);
                        setToken("");
                      })
                    }
                  >
                    {busy ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Plug size={14} />
                    )}{" "}
                    {text("connect")}
                  </button>
                  {entry.has_credential && (
                    <button
                      disabled={busy}
                      className={buttonClass}
                      onClick={() =>
                        void action(async () => {
                          await installCapability(entry.id, entry.enabled, "");
                          setToken("");
                        })
                      }
                    >
                      {text("tokenClear")}
                    </button>
                  )}
                </div>
                {!!entry.tools?.length && (
                  <details>
                    <summary className="cursor-pointer py-2 text-xs text-gray-600">
                      {text("tools")} · {entry.tools.length}
                    </summary>
                    <ul className="max-h-48 space-y-2 overflow-auto text-xs text-gray-500">
                      {entry.tools.map((tool) => (
                        <li key={tool.name}>
                          <strong className="text-gray-700">{tool.name}</strong>
                          <p>{tool.description}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            )}
          {entry && !entry.builtin && !editing && !fileEditing && (
            <div className="border-t border-gray-100 pt-4">
              {entry.editable ? (
                <>
                  {confirm ? (
                    <div className="space-y-3">
                      <p className="text-sm text-gray-600">{text("confirm")}</p>
                      <div className="flex gap-2">
                        <button
                          disabled={busy}
                          className={buttonClass + " text-red-600"}
                          onClick={() =>
                            void action(async () => {
                              await removeCapability(entry.id);
                              onBack();
                            })
                          }
                        >
                          {text("remove")}
                        </button>
                        <button
                          className={buttonClass}
                          onClick={() => setConfirm(false)}
                        >
                          {text("cancel")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      className="min-h-10 cursor-pointer text-xs text-red-600"
                      onClick={() => setConfirm(true)}
                    >
                      {text("remove")}
                    </button>
                  )}
                </>
              ) : (
                entry.installed && (
                  <button
                    disabled={busy}
                    className={buttonClass}
                    onClick={() =>
                      void action(async () => {
                        await removeCapability(entry.id, true);
                        onBack();
                      })
                    }
                  >
                    {text("uninstall")}
                  </button>
                )
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
