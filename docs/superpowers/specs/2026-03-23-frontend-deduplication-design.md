# Frontend Deduplication & Component Extraction — Design Spec

**Date:** 2026-03-23  
**Status:** Approved  
**Scope:** `pathlab/pathlab-client/src/renderer/src`

---

## Background

The PathLab frontend has grown to 130+ TSX files. Through audit, six categories of redundancy were identified totalling an estimated **1,800+ duplicated/redundant lines**:

| Category | Files affected | Estimated lines removable |
|---|---|---|
| Modal overlay JSX duplication | 20+ | ~400 |
| `training/` vs `list/` component copies | 8 | ~600 |
| `Loader2` spinner inline pattern | 26 files, 84 sites | ~150 |
| Manual loading/error state (vs useAsyncAction) | 26 | ~300 |
| Debounce useEffect copies | 5 | ~50 |
| Pagination reimplemented per-component | 6 | ~200 |

---

## Goals

- High cohesion: each unit has one clear purpose and well-defined interface
- Low coupling: consumers don't know modal internals; hooks don't know UI
- Zero behaviour change: pure refactor, no new features
- All TypeScript type-safe, no `as any` suppressions

---

## Section 1 — New Primitive Files (pure additions)

### `components/ui/modal-shell.tsx`

Replaces the 3 diverged modal overlay variants that repeat across 20+ files.

```typescript
interface ModalShellProps {
  isOpen: boolean
  onClose?: () => void        // if provided, backdrop click closes
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '6xl'  // default 'md'
  className?: string
  children: React.ReactNode
}
```

Canonical styling (Variant B — newest animated style):
```
fixed inset-0 z-50 flex items-center justify-center
bg-black/50 backdrop-blur-sm p-2 sm:p-4
animate-in fade-in duration-200
```
Container:
```
bg-white rounded-xl sm:rounded-2xl shadow-2xl w-full overflow-hidden
scale-100 animate-in zoom-in-95 duration-200 max-h-[90vh]
```
`maxWidth` maps: `sm→max-w-sm`, `md→max-w-md`, `lg→max-w-lg`, `xl→max-w-xl`, `6xl→max-w-6xl`.

All 20 existing modals migrate to wrap their content in `<ModalShell>` and delete their local overlay divs.

---

### `lib/useDebounce.ts`

```typescript
function useDebounce<T>(value: T, delay: number): T
```

Replaces 5 repeated `useState + useEffect + setTimeout + clearTimeout` patterns:
- `PermissionCenterModal` (3 instances: `userSearchQuery`, `datasetSearchQuery`, `grantUserSearchQuery`)
- `DatasetConfigStep` (2 instances)

---

### `lib/useConfirmDialog.ts`

```typescript
function useConfirmDialog(): {
  dialogState: ConfirmDialogState
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}
```

`ConfirmDialogState` and `ShowConfirmDialog` types are already defined in `components/settings/ConfirmDialog.tsx` — import from there.

Replaces manual `useState<ConfirmDialogState>` + handler duplication in 10+ parent components (`UsersTab`, `SettingsPage`, `PermissionCenterModal`, `DatasetPermissionModal`, `ListPage`, `TaskListPage`, etc.).

---

### `components/ui/pagination-footer.tsx`

Extract and publicly export the existing `PaginationFooter` component from inside `PermissionCenterModal.tsx`. Interface stays identical — only move it out.

```typescript
interface PaginationFooterProps {
  page: number
  pageSize: number
  total: number
  disabled?: boolean
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}
```

Consumers: `PermissionCenterModal`, `UsersTab`, `ModelsTab`, `FeedbackTab`, `AnnotationAuditCard`, `ListPage`.

---

## Section 2 — Merge & Delete (training/ × list/ duplication)

### Files to delete (4)

| File | Replace with |
|---|---|
| `components/training/DeleteConfirmModal.tsx` | Updated `list/DeleteModals.tsx` |
| `components/training/EditMetadataModal.tsx` | `list/EditModals.tsx` `EditMetadataModal` |
| `components/training/BatchEditModal.tsx` | `list/EditModals.tsx` `BatchEditModal` |
| `components/training/FileMetadataModal.tsx` | `list/FileMetadataModal.tsx` |

### Upgrade `list/DeleteModals.tsx`

The `training/` version uses a single component with `mode: 'single' | 'batch'` prop. The `list/` version has two separate exports (`DeleteConfirmModal`, `BatchDeleteModal`). 

Resolution: keep both named exports in `list/DeleteModals.tsx` (no API change for `ListPage`), and add an optional convenience re-export:

```typescript
// New convenience wrapper used by NewTaskPage (replaces training version)
export function UnifiedDeleteModal(props: DeleteConfirmModalProps | BatchDeleteModalProps) {
  if ('wsiToDelete' in props) return <DeleteConfirmModal {...props} />
  return <BatchDeleteModal {...props} />
}
```

`NewTaskPage` and the training wizard switch from `training/DeleteConfirmModal` to this unified import.

### Props delta for other merged modals

`training/EditMetadataModal` uses `taskType: 'classification' | 'survival' | 'segmentation'` while `list/` uses `datasetType`. They are semantically identical — the `list/` version already has `datasetType` and handles all three. `NewTaskPage` updates its import path; no prop name changes needed.

---

## Section 3 — State Layer Unification

### 3a. `useAsyncAction` — universal adoption

**Current state:** `useAsyncAction` is used correctly in `ListPage` (7 call sites) but ignored in 26 other files that duplicate the `setLoading(true) / try/catch/finally / setLoading(false)` pattern.

**Migration pattern:**
```typescript
// Before
const [loading, setLoading] = useState(false)
const [error, setError] = useState<string | null>(null)
const doSomething = async () => {
  setLoading(true); setError(null)
  try { await apiCall() }
  catch (err) { setError(err instanceof Error ? err.message : 'Error') }
  finally { setLoading(false) }
}

// After
const [, setError] = useState<string | null>(null)
const [isPending, run] = useAsyncAction({
  onError: (err) => setError(err instanceof Error ? err.message : 'Error')
})
const doSomething = () => run(() => apiCall())
```

Files to migrate (by priority):

**Pages (6):**
- `StorageManagementPage` — `detectOrphaned`, `handleCleanup`
- `TaskDetailPage` — `loadTaskDetail`, `handleRerun`
- `TaskListPage` — `handleDeleteTask`
- `ResultsViewerPage` — `runAnalysis`, `startExternalValidation`
- `NewTaskPage` — multiple handlers
- `AIChatPage` — multiple handlers

**Settings (8):**
- `UsersTab`, `ModelsTab`, `FeedbackTab`, `TasksTab`, `GeneralTab`, `StorageTab`, `AnnotationAuditCard`, `PermissionCenterModal`

**Other components (12):**
- `WSIViewer`, `ShareAnnotationDialog`, chat card components (`AnalysisConfigCard`, `TaskConfigCard`, `DatasetRegistrationCard`, `TaskHistoryCard`, `ChartCard`, `MetricCard`, `ImageRecommendationCard`, `QuickAnalysisViewer`)

### 3b. `useDebounce` rollout

Replace all 5 debounce `useEffect` blocks (see Section 1). Each becomes one line:
```typescript
const debouncedQuery = useDebounce(query, 300)
```

### 3c. `useConfirmDialog` rollout

All parent components that currently hold `useState<ConfirmDialogState>` + inline `showConfirmDialog` / `closeConfirmDialog` functions replace those ~15 lines with:
```typescript
const { dialogState, showConfirmDialog, closeConfirmDialog } = useConfirmDialog()
```
Then pass `showConfirmDialog` / `closeConfirmDialog` to child components that need them (e.g., `PermissionCenterModal`).

---

## Execution Order

This ordering minimises merge conflicts and ensures each step is independently verifiable:

1. **Add primitives** — create 4 new files (ModalShell, useDebounce, useConfirmDialog, PaginationFooter). No existing files touched.
2. **Delete training/ duplicates** — upgrade `list/` files, update imports in `NewTaskPage`. Delete 4 files.
3. **Migrate ModalShell** — update 18 modal files to use `<ModalShell>`. One file at a time, each verifiable with `lsp_diagnostics`.
4. **Roll out useDebounce** — 5 files, low risk.
5. **Roll out useConfirmDialog** — 10+ parent components.
6. **Roll out useAsyncAction** — 26 files, highest volume. Pages first (fewer cascading imports), then settings components, then chat components.
7. **Roll out PaginationFooter** — 6 components replace their pagination JSX.

---

## Success Criteria

- [ ] `components/training/DeleteConfirmModal.tsx`, `EditMetadataModal.tsx`, `BatchEditModal.tsx`, `FileMetadataModal.tsx` deleted
- [ ] `ModalShell` used in all 18+ modals; no orphan `fixed inset-0 z-50 flex items-center justify-center bg-black/50` strings remain in modal files
- [ ] `useDebounce` has 0 remaining inline `setTimeout` debounce patterns  
- [ ] `useAsyncAction` used for all async operations; `setIsLoading`/`setLoading` pattern eliminated from pages and settings tabs
- [ ] `PaginationFooter` used in all 6 pagination sites
- [ ] `lsp_diagnostics` clean on all modified files
- [ ] No `as any`, `@ts-ignore`, or `@ts-expect-error` introduced
- [ ] No functional behaviour change (same props accepted, same UI rendered)

---

## Out of Scope

- New UI features or visual design changes
- `useDataSelection.ts`, `useTaskWizard.ts`, domain-specific hooks (already well-scoped)
- API layer (`api/` directory) — already modularised
- Test files
