import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useViewerAnnotations } from "@renderer/components/wsiViewer/useViewerAnnotations";
import * as api from "@renderer/api/viewer";
vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "owner" } }),
}));
vi.mock("@renderer/components/wsiViewer/viewerText", () => ({
  useViewerText: () => ({ t: (key: string) => key }),
}));
vi.mock("@renderer/api/viewer", async (original) => ({
  ...(await original<typeof api>()),
  viewerRegions: vi.fn(),
  saveViewerRegions: vi.fn(),
  resolveViewerRegions: vi.fn(),
}));
let rows: Map<string, api.ViewerRegion>,
  revisions: Map<string, number>,
  operations: Map<string, api.MutationResult>;
const region = (id: string): api.ViewerRegion => ({
  id,
  revision: 1,
  type: "rect",
  x: 10,
  y: 10,
  width: 20,
  height: 20,
  label: "A",
  color: "#6366f1",
});
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  rows = new Map();
  revisions = new Map();
  operations = new Map();
  vi.mocked(api.viewerRegions).mockImplementation(
    async (_id, _layer, _bounds, after = "", _signal, limit = 50) => {
      const all = [...rows.values()].sort((a, b) => a.id.localeCompare(b.id)),
        items = all.filter((r) => r.id > after);
      return {
        items: items.slice(0, limit),
        total: all.length,
        next_cursor: items.length > limit ? items[limit - 1].id : null,
      };
    },
  );
  vi.mocked(api.resolveViewerRegions).mockImplementation(
    async (_id, _layer, ids) => ({
      items: ids.flatMap((id) => (rows.has(id) ? [rows.get(id)!] : [])),
      revisions: Object.fromEntries(
        ids.map((id) => [id, revisions.get(id) || 0]),
      ),
    }),
  );
  vi.mocked(api.saveViewerRegions).mockImplementation(
    async (_id, _layer, changes, operation) => {
      if (operations.has(operation)) return operations.get(operation)!;
      if (changes.some((c) => (revisions.get(c.id) || 0) !== c.revision))
        throw { status: 409 };
      const result = {
        operation_id: operation,
        changes: changes.map((c) => {
          const revision = c.revision + 1;
          revisions.set(c.id, revision);
          const value = c.value ? { ...c.value, id: c.id, revision } : null;
          if (value) rows.set(c.id, value);
          else rows.delete(c.id);
          return { id: c.id, revision, value };
        }),
      };
      operations.set(operation, result);
      return result;
    },
  );
});
it("paginates without accumulating the list and backs up after deleting the last row", async () => {
  for (let i = 0; i < 51; i++) {
    const r = region(`r${String(i).padStart(3, "0")}`);
    rows.set(r.id, r);
    revisions.set(r.id, 1);
  }
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal"),
  );
  await waitFor(() => expect(result.current.listRegions).toHaveLength(50));
  act(() => result.current.nextPage!());
  await waitFor(() => expect(result.current.page).toBe(2));
  expect(result.current.listRegions.map((r) => r.id)).toEqual(["r050"]);
  await act(() => result.current.remove(["r050"]));
  await waitFor(() => expect(result.current.page).toBe(1));
  expect(result.current.total).toBe(50);
});
it("allows multiple sequential undos and redos on the same object", async () => {
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal"),
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.create([api.regionValue(region("new"))]));
  await waitFor(() => expect(result.current.regions).toHaveLength(1));
  await act(() => result.current.relabel("B"));
  await act(() => result.current.undo());
  expect([...rows.values()][0].label).toBe("A");
  await act(() => result.current.undo());
  expect(rows.size).toBe(0);
  await act(() => result.current.redo());
  await act(() => result.current.redo());
  expect([...rows.values()][0].label).toBe("B");
});
it("retains an operation after response loss and retries without duplicating it", async () => {
  const save = vi.mocked(api.saveViewerRegions).getMockImplementation()!;
  vi.mocked(api.saveViewerRegions).mockImplementationOnce(async (...args) => {
    await save(...args);
    throw Error("offline");
  });
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal"),
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.create([api.regionValue(region("new"))]));
  expect(result.current.pendingEdit).toBe(true);
  expect(rows.size).toBe(1);
  await act(async () => {
    await result.current.retry();
  });
  expect(result.current.pendingEdit).toBe(false);
  expect(rows.size).toBe(1);
  await act(() => result.current.undo());
  expect(rows.size).toBe(0);
});
it("does not undo a remote edit after refreshing the same selected object", async () => {
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal"),
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.create([api.regionValue(region("new"))]));
  const id = [...rows.keys()][0];
  rows.set(id, { ...rows.get(id)!, revision: 2, label: "Remote" });
  revisions.set(id, 2);
  await act(() => result.current.reload());
  await act(() => result.current.undo());
  expect(result.current.error).toBe("conflict");
  expect(rows.get(id)?.label).toBe("Remote");
});
it("loads dense viewport annotations in bounded pages independently of the list", async () => {
  for (let i = 0; i < 650; i++) {
    const r = region(`r${String(i).padStart(4, "0")}`);
    rows.set(r.id, r);
  }
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal", {
      type: "rect",
      x: 0,
      y: 0,
      width: 100,
      height: 100,
    }),
  );
  await waitFor(() => expect(result.current.regions).toHaveLength(650));
  expect(result.current.listRegions).toHaveLength(50);
  expect(api.viewerRegions).toHaveBeenCalledWith(
    "slide",
    "personal",
    expect.any(Object),
    "r0499",
    expect.any(AbortSignal),
    500,
  );
});
it("undoes interleaved objects while preserving unrelated remote history", async () => {
  const { result } = renderHook(() =>
    useViewerAnnotations("slide", "personal"),
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.create([api.regionValue(region("a"))]));
  const a = [...rows.keys()][0];
  await act(() => result.current.create([api.regionValue(region("b"))]));
  await act(() => result.current.update({ ...rows.get(a)!, label: "A2" }));
  await act(() => result.current.undo());
  await act(() => result.current.undo());
  await act(() => result.current.undo());
  expect(rows.size).toBe(0);
  await act(() => result.current.redo());
  await act(() => result.current.redo());
  await act(() => result.current.redo());
  expect(rows.get(a)?.label).toBe("A2");
});
