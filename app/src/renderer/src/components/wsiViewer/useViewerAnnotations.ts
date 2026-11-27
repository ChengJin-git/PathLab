import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import * as api from "../../api/viewer";
import { useViewerText } from "./viewerText";

type Edit = {
  before: api.ViewerRegion[];
  after: api.ViewerRegion[];
  ids: string[];
  versions: Record<string, number>;
  restoreVersions?: Record<string, number>;
};
type Pending = {
  changes: api.RegionChange[];
  operation: string;
  edit: Edit;
  mode: "edit" | "undo" | "redo";
};
const PAGE_SIZE = 50;
const VISIBLE_LIMIT = 2000;
function journal(key: string, value: Pending | null) {
  try {
    if (value) sessionStorage.setItem(key, JSON.stringify(value));
    else sessionStorage.removeItem(key);
  } catch {
    /* Editing still works when browser storage is unavailable. */
  }
}

export function useViewerAnnotations(
  id: string,
  layer: api.AnnotationLayer,
  bounds?: api.Geometry,
) {
  const { user } = useAuth();
  const { t } = useViewerText();
  const key = `${user?.id}:${id}:${layer}`;
  const journalKey = `viewer-draft:${key}`;
  const scope = useRef(key);
  scope.current = key;
  const mounted = useRef(true);
  const [regions, setRegions] = useState<api.ViewerRegion[]>([]);
  const current = useRef(regions);
  current.current = regions;
  const [selected, setSelection] = useState<string[]>([]);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [listIds, setListIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingEdit, setPendingEdit] = useState(false);
  const [error, setError] = useState("");
  const [viewportLimited, setViewportLimited] = useState(false);
  const [history, setHistory] = useState<Edit[]>([]);
  const [future, setFuture] = useState<Edit[]>([]);
  const revisions = useRef(new Map<string, number>());
  const pending = useRef<Pending | null>(null);
  const lock = useRef(false);
  const readVersion = useRef(0);
  const controller = useRef<AbortController>();
  const cursors = useRef([""]);
  const activePage = useRef(1);
  const valid = () => mounted.current && scope.current === key;
  const setSelected = (ids: string[] | ((previous: string[]) => string[])) => {
    const next = typeof ids === "function" ? ids(selectedRef.current) : ids;
    selectedRef.current = next.slice(0, 100);
    setSelection(selectedRef.current);
  };
  const load = useCallback(
    async (target = activePage.current) => {
      if (lock.current) return;
      const version = ++readVersion.current;
      controller.current?.abort();
      const request = new AbortController();
      controller.current = request;
      setLoading(true);
      try {
        const visible = async () => {
          const items: api.ViewerRegion[] = [];
          let after = "",
            limited = false;
          if (bounds)
            do {
              const result = await api.viewerRegions(
                id,
                layer,
                bounds,
                after,
                request.signal,
                500,
              );
              items.push(...result.items);
              after = result.next_cursor || "";
              limited = !!after && items.length >= VISIBLE_LIMIT;
            } while (after && !limited);
          return { items, limited };
        };
        const [result, viewport, selection] = await Promise.all([
          api.viewerRegions(
            id,
            layer,
            undefined,
            cursors.current[target - 1] || "",
            request.signal,
            PAGE_SIZE,
          ),
          visible(),
          selectedRef.current.length
            ? api.resolveViewerRegions(
                id,
                layer,
                selectedRef.current,
                request.signal,
              )
            : null,
        ]);
        if (!valid() || version !== readVersion.current || lock.current) return;
        // A deleted final row can remove a whole page; return to the preceding cursor.
        if (!result.items.length && target > 1) {
          activePage.current = target - 1;
          await load(target - 1);
          return;
        }
        const items = [
          ...new Map(
            [
              ...result.items,
              ...viewport.items,
              ...(selection?.items || []),
            ].map((r) => [r.id, r]),
          ).values(),
        ];
        items.forEach((r) => revisions.current.set(r.id, r.revision));
        Object.entries(selection?.revisions || {}).forEach(([id, revision]) =>
          revisions.current.set(id, revision),
        );
        if (selection)
          setSelected((ids) =>
            ids.filter((id) => selection.items.some((r) => r.id === id)),
          );
        current.current = items;
        setRegions(items);
        setListIds(result.items.map((r) => r.id));
        setTotal(result.total);
        setCursor(result.next_cursor);
        activePage.current = target;
        setPage(target);
        setViewportLimited(viewport.limited);
      } catch {
        if (valid() && !request.signal.aborted) setError(t("failed"));
      } finally {
        if (valid() && version === readVersion.current) setLoading(false);
      }
    },
    [key, bounds?.x, bounds?.y, bounds?.width, bounds?.height],
  );
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    readVersion.current++;
    controller.current?.abort();
    current.current = [];
    setRegions([]);
    setSelected([]);
    setHistory([]);
    setFuture([]);
    revisions.current.clear();
    cursors.current = [""];
    activePage.current = 1;
    setPage(1);
    setTotal(0);
    setListIds([]);
    setCursor(null);
    lock.current = false;
    setSaving(false);
    pending.current = null;
    try {
      pending.current = JSON.parse(
        sessionStorage.getItem(journalKey) || "null",
      );
    } catch {}
    setPendingEdit(!!pending.current);
    setError(pending.current ? t("unsavedDraft") : "");
  }, [key]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (pending.current || lock.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);
  useEffect(() => {
    if (layer !== "shared") return;
    const events = new EventSource(api.viewerEvents(id, layer));
    events.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "changed") void loadRef.current();
      if (data.type === "access_revoked") {
        setError(t("readonly"));
        setRegions([]);
        setSelected([]);
        events.close();
      }
    };
    return () => events.close();
  }, [key]);

  const send = async (item: Pending) => {
    if (lock.current) return false;
    lock.current = true;
    setSaving(true);
    setError("");
    controller.current?.abort();
    readVersion.current++;
    try {
      const result = await api.saveViewerRegions(
        id,
        layer,
        item.changes,
        item.operation,
      );
      journal(journalKey, null);
      if (!valid()) return false;
      result.changes.forEach((c) => revisions.current.set(c.id, c.revision));
      const map = new Map(current.current.map((r) => [r.id, r]));
      result.changes.forEach((c) =>
        c.value ? map.set(c.id, c.value) : map.delete(c.id),
      );
      current.current = [...map.values()];
      setRegions(current.current);
      if (item.mode !== "edit")
        setSelected(result.changes.flatMap((c) => (c.value ? [c.id] : [])));
      const versions = Object.fromEntries(
        result.changes.map((c) => [c.id, c.revision]),
      );
      const edit = { ...item.edit, versions };
      const refreshChain = (edits: Edit[], expected: Record<string, number>) =>
        edits.map((e) => ({
          ...e,
          versions: {
            ...e.versions,
            ...Object.fromEntries(
              e.ids
                .filter(
                  (id) => id in versions && e.versions[id] === expected[id],
                )
                .map((id) => [id, versions[id]]),
            ),
          },
        }));
      if (item.mode === "undo") {
        setHistory((h) =>
          refreshChain(
            h.slice(0, -1),
            Object.fromEntries(edit.before.map((r) => [r.id, r.revision])),
          ),
        );
        setFuture((f) => [
          ...f,
          { ...edit, restoreVersions: item.edit.versions },
        ]);
      } else if (item.mode === "redo") {
        setFuture((f) =>
          refreshChain(f.slice(0, -1), item.edit.restoreVersions || {}),
        );
        setHistory((h) => [...h, edit]);
      } else {
        setHistory((h) => [...h.slice(-49), edit]);
        setFuture([]);
      }
      pending.current = null;
      setPendingEdit(false);
      return true;
    } catch (error) {
      if (valid())
        setError(
          (error as { status?: number }).status === 409
            ? t("conflict")
            : t("failed"),
        );
      return false;
    } finally {
      if (valid()) {
        lock.current = false;
        setSaving(false);
        void loadRef.current();
      }
    }
  };
  const apply = async (
    next: api.ViewerRegion[],
    ids: string[],
    mode: Pending["mode"] = "edit",
    source?: Edit,
  ) => {
    if (lock.current || pending.current || !ids.length) return false;
    if (ids.length > 100) {
      setError(t("selectionLimit"));
      return false;
    }
    const before = current.current.filter((r) => ids.includes(r.id));
    const after = next.filter((r) => ids.includes(r.id));
    const item: Pending = {
      changes: ids.map((id) => ({
        id,
        revision: revisions.current.get(id) || 0,
        value: after.some((r) => r.id === id)
          ? api.regionValue(after.find((r) => r.id === id)!)
          : null,
      })),
      operation: crypto.randomUUID(),
      mode,
      edit: source
        ? {
            ...source,
            ...(mode === "redo"
              ? {
                  before: source.before.map((r) => ({
                    ...r,
                    revision: revisions.current.get(r.id) || r.revision,
                  })),
                }
              : {}),
          }
        : { before, after, ids, versions: {} },
    };
    pending.current = item;
    setPendingEdit(true);
    journal(journalKey, item);
    return send(item);
  };
  const create = async (values: api.RegionValue[]) => {
    const added = values.map((value) => ({
      ...value,
      id: crypto.randomUUID(),
      revision: 0,
    }));
    const ok = await apply(
      [...current.current, ...added],
      added.map((r) => r.id),
    );
    if (ok) setSelected(added.map((r) => r.id));
    return ok;
  };
  const remove = async (ids = selected) => {
    if (
      await apply(
        current.current.filter((r) => !ids.includes(r.id)),
        ids,
      )
    )
      setSelected((previous) => previous.filter((id) => !ids.includes(id)));
  };
  const travel = async (mode: "undo" | "redo") => {
    const edit = (mode === "undo" ? history : future).at(-1);
    if (!edit) return;
    if (
      edit.ids.some((id) => revisions.current.get(id) !== edit.versions[id])
    ) {
      setError(t("conflict"));
      return;
    }
    await apply(
      [
        ...current.current.filter((r) => !edit.ids.includes(r.id)),
        ...(mode === "undo" ? edit.before : edit.after),
      ],
      edit.ids,
      mode,
      edit,
    );
  };
  const discard = () => {
    if (lock.current) return;
    pending.current = null;
    setPendingEdit(false);
    journal(journalKey, null);
    setError("");
    void load();
  };
  return {
    regions,
    listRegions: listIds
      .map((id) => regions.find((r) => r.id === id))
      .filter((r): r is api.ViewerRegion => !!r),
    page,
    total,
    loading,
    saving,
    error,
    pendingEdit,
    viewportLimited,
    selected,
    setSelected,
    previousPage: page > 1 ? () => void load(page - 1) : undefined,
    nextPage: cursor
      ? () => {
          cursors.current[page] = cursor;
          void load(page + 1);
        }
      : undefined,
    create,
    remove,
    apply,
    discard,
    preserve: async () => {
      if (lock.current) return;
      const values =
        pending.current?.changes.flatMap((c) => (c.value ? [c.value] : [])) ||
        [];
      discard();
      if (values.length) await create(values);
    },
    update: (value: api.ViewerRegion) =>
      apply(
        current.current.map((r) => (r.id === value.id ? value : r)),
        [value.id],
      ),
    relabel: (label: string, color?: string) =>
      apply(
        current.current.map((r) =>
          selected.includes(r.id)
            ? { ...r, label, color: color || r.color }
            : r,
        ),
        selected,
      ),
    undo: () => travel("undo"),
    redo: () => travel("redo"),
    canUndo: !!history.length && !pendingEdit,
    canRedo: !!future.length && !pendingEdit,
    retry: () =>
      pending.current ? send(pending.current) : (setError(""), load()),
    reload: load,
  };
}
