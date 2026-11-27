import { useEffect, useRef, useState } from "react";
import { Checkbox } from '../ui/checkbox'
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileCode2,
  Download,
  Plus,
  Upload,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import { useAuth } from "../../contexts/AuthContext";
import {
  listSkillFiles,
  readSkillFile,
  saveSkillFile,
  uploadSkillFile,
  replaceSkillPackage,
  deleteSkillFile,
  downloadSkillFile,
  type CapabilityEntry,
} from "../../api/capabilities";
import { useCapabilityText } from "./capabilityText";

const button =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50";
const input =
  "w-full min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-primary-500";
type Mode = "list" | "read" | "edit" | "new" | "upload" | "replace" | "package";

export default function SkillPackageEditor({
  entry,
  onChanged,
  onEditing,
}: {
  entry: CapabilityEntry;
  onChanged: () => Promise<CapabilityEntry | undefined>;
  onEditing: (active: boolean) => void;
}) {
  const { user } = useAuth();
  const t = useCapabilityText();
  const cache = useQueryClient();
  const [mode, setMode] = useState<Mode>("list");
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  const [executable, setExecutable] = useState(false);
  const [revision, setRevision] = useState(entry.revision);
  const [selectedFile, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [after, setAfter] = useState("");
  const [previous, setPrevious] = useState<string[]>([]);
  const lock = useRef(false);
  const changing = ["edit", "new", "upload", "replace", "package"].includes(
    mode,
  );
  useEffect(() => {
    onEditing(changing || busy);
    return () => onEditing(false);
  }, [changing, busy, onEditing]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setAfter("");
      setPrevious([]);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const list = useQuery({
    queryKey: [
      "skill-files",
      user?.id,
      user?.role,
      entry.id,
      entry.revision,
      query,
      after,
    ],
    queryFn: ({ signal }) =>
      listSkillFiles(
        entry.id,
        { q: query, after, revision: String(entry.revision) },
        signal,
      ),
    refetchOnWindowFocus: false,
  });
  const file = useQuery({
    queryKey: [
      "skill-file",
      user?.id,
      user?.role,
      entry.id,
      path,
      entry.revision,
    ],
    queryFn: ({ signal }) => readSkillFile(entry.id, path, signal),
    enabled: mode === "read",
    refetchOnWindowFocus: false,
  });
  function open(next: Mode, name = "") {
    setMode(next);
    setPath(name);
    setFile(null);
    setError("");
    setSaved(false);
    setContent("");
    setExecutable(false);
    setRevision(list.data?.revision ?? entry.revision);
  }
  async function action(
    fn: () => Promise<unknown>,
    next: Mode = "list",
    refresh = true,
  ) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await fn();
      setMode(next);
      if (!refresh) return;
      setAfter("");
      setPrevious([]);
      const updated = await onChanged();
      await cache.invalidateQueries({
        queryKey: [
          "skill-files",
          user?.id,
          user?.role,
          entry.id,
          updated?.revision ?? entry.revision,
        ],
      });
      await cache.invalidateQueries({
        queryKey: [
          "skill-file",
          user?.id,
          user?.role,
          entry.id,
          path,
          updated?.revision ?? entry.revision,
        ],
      });
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="min-w-0 space-y-4 rounded-xl border border-gray-200 p-3 sm:p-4"
      aria-label={t("files")}
    >
      <div>
        <h3 className="text-sm font-semibold text-gray-900">{t("files")}</h3>
        <p className="mt-1 text-xs leading-5 text-gray-500">{t("filesHint")}</p>
      </div>
      {(error || list.error || (mode === "read" && file.error)) && (
        <p role="alert" className="break-words text-sm text-red-600">
          {error || String(list.error || file.error)}
        </p>
      )}
      {saved && (
        <p role="status" className="text-xs text-emerald-700">
          {t("created")}
        </p>
      )}
      {mode === "list" ? (
        <>
          {entry.editable && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={button}
                disabled={busy}
                onClick={() => open("new")}
              >
                <Plus size={14} />
                {t("newFile")}
              </button>
              <button
                type="button"
                className={button}
                disabled={busy}
                onClick={() => open("upload")}
              >
                <Upload size={14} />
                {t("uploadFile")}
              </button>
              <button
                type="button"
                className={button}
                disabled={busy}
                onClick={() => open("package")}
              >
                {t("replacePackage")}
              </button>
            </div>
          )}
          <input
            className={input}
            aria-label={t("filesSearch")}
            placeholder={t("filesSearch")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {list.isLoading ? (
            <p role="status" className="text-xs">
              {t("loading")}
            </p>
          ) : (
            <ul className="max-h-72 overflow-y-auto divide-y divide-gray-100">
              {list.data?.items.map((item) => (
                <li key={item.path}>
                  <button
                    type="button"
                    className="flex min-h-11 w-full items-center gap-2 py-2 text-left text-xs hover:bg-gray-50"
                    onClick={() => open("read", item.path)}
                    disabled={busy}
                  >
                    <FileCode2 size={15} className="shrink-0 text-gray-400" />
                    <span className="min-w-0 flex-1 break-all font-mono">
                      {item.path}
                      {item.path === list.data.entrypoint && (
                        <span className="ml-2 font-sans text-gray-500">
                          {t("entrypoint")}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 text-gray-400">
                      {Math.max(1, Math.ceil(item.size / 1024))} KiB
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={button}
              disabled={busy}
              onClick={() => void action(async () => {})}
            >
              {t("refreshFiles")}
            </button>
            <button
              type="button"
              className={button}
              disabled={!previous.length || list.isFetching}
              onClick={() => {
                setAfter(previous.at(-1)!);
                setPrevious(previous.slice(0, -1));
              }}
            >
              {t("previous")}
            </button>
            <button
              type="button"
              className={button}
              disabled={!list.data?.next_cursor || list.isFetching}
              onClick={() => {
                setPrevious([...previous, after]);
                setAfter(list.data!.next_cursor!);
              }}
            >
              {t("next")}
            </button>
          </div>
        </>
      ) : (
        <>
          <button
            type="button"
            disabled={busy}
            className={button}
            onClick={() => open("list")}
          >
            <ArrowLeft size={14} />
            {changing ? t("cancel") : t("files")}
          </button>
          {mode === "read" ? (
            <>
              <p className="break-all font-mono text-xs text-gray-600">
                {path}
              </p>
              {file.isFetching ? (
                <p role="status">{t("loading")}</p>
              ) : (
                file.data && (
                  <>
                    {file.data.text !== null ? (
                      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 font-mono text-xs leading-5">
                        {file.data.text}
                      </pre>
                    ) : (
                      <p className="text-xs leading-5 text-gray-500">
                        {t("binaryHint")}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className={button}
                        disabled={busy}
                        onClick={() =>
                          void action(
                            () => downloadSkillFile(entry.id, path),
                            "read",
                            false,
                          )
                        }
                      >
                        <Download size={14} />
                        {t("download")}
                      </button>
                      {entry.editable && (
                        <>
                          {file.data.text !== null && (
                            <button
                              type="button"
                              className={button}
                              disabled={busy}
                              onClick={() => {
                                setContent(file.data!.text!);
                                setExecutable(file.data!.executable);
                                setRevision(file.data!.revision);
                                setMode("edit");
                                setSaved(false);
                              }}
                            >
                              {t("edit")}
                            </button>
                          )}
                          <button
                            type="button"
                            className={button}
                            disabled={busy}
                            onClick={() => {
                              setRevision(file.data!.revision);
                              setExecutable(file.data!.executable);
                              setMode("replace");
                              setFile(null);
                              setSaved(false);
                            }}
                          >
                            {t("replaceFile")}
                          </button>
                          {path !== list.data?.entrypoint && (
                            <button
                              type="button"
                              className={button + " text-red-600"}
                              disabled={busy}
                              onClick={() =>
                                void action(() =>
                                  deleteSkillFile(
                                    entry.id,
                                    path,
                                    file.data!.revision,
                                  ),
                                )
                              }
                            >
                              {t("deleteFile")}
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </>
                )
              )}
            </>
          ) : (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void action(() =>
                  mode === "package"
                    ? replaceSkillPackage(entry.id, selectedFile!, revision)
                    : ["upload", "replace"].includes(mode)
                      ? uploadSkillFile(
                          entry.id,
                          selectedFile!,
                          path,
                          revision,
                          mode === "replace",
                          executable,
                        )
                      : saveSkillFile(entry.id, {
                          revision,
                          path,
                          content,
                          executable,
                          overwrite: mode === "edit",
                        }),
                );
              }}
            >
              {mode === "package" ? (
                <p className="text-xs leading-5 text-gray-500">
                  {t("packageHint")}
                </p>
              ) : (
                <label className="block text-xs text-gray-600">
                  {t("filePath")}
                  <input
                    className={input + " mt-2 font-mono"}
                    required
                    maxLength={512}
                    disabled={busy || ["edit", "replace"].includes(mode)}
                    placeholder="scripts/analyze.py"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                  />
                </label>
              )}
              {["upload", "replace", "package"].includes(mode) ? (
                <input
                  key={mode}
                  aria-label={
                    mode === "package" ? t("replacePackage") : t("uploadFile")
                  }
                  className="block w-full min-w-0 text-xs"
                  type="file"
                  accept={mode === "package" ? ".zip,.skill" : undefined}
                  required
                  disabled={busy}
                  onChange={(e) => {
                    const value = e.target.files?.[0];
                    if (!value) return;
                    if (value.size > 16 * 1024 * 1024) {
                      setError(t("fileSizeError"));
                      e.target.value = "";
                      setFile(null);
                      return;
                    }
                    setError("");
                    setFile(value);
                    if (mode === "upload" && !path) setPath(value.name);
                  }}
                />
              ) : (
                <label className="block text-xs text-gray-600">
                  {t("fileContent")}
                  <textarea
                    className={
                      input + " mt-2 min-h-64 font-mono text-xs leading-5"
                    }
                    aria-label={t("fileContent")}
                    spellCheck={false}
                    value={content}
                    disabled={busy}
                    onChange={(e) => setContent(e.target.value)}
                  />
                </label>
              )}
              {mode !== "package" && (
                <label className="flex min-h-10 items-center gap-2 text-xs text-gray-600">
                  <Checkbox
                    checked={executable}
                    disabled={busy}
                    onChange={(e) => setExecutable(e.target.checked)}
                  />
                  {t("executable")}
                </label>
              )}
              <button
                type="submit"
                className={button + " bg-gray-900 text-white hover:bg-gray-800"}
                disabled={
                  busy ||
                  (["upload", "replace", "package"].includes(mode) &&
                    !selectedFile)
                }
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                {t("saveFile")}
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
