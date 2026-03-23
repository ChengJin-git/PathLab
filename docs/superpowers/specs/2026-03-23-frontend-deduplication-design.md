# Frontend Deduplication & Component Extraction — Design Spec

**Date:** 2026-03-23  
**Status:** Approved (v3 — post spec-review round 2)  
**Scope:** `pathlab/pathlab-client/src/renderer/src`

---

## Background

The PathLab frontend has grown to 130+ TSX files. Through audit, six categories of redundancy were identified:

| Category | Files affected | Est. lines removable |
|---|---|---|
| Modal overlay JSX duplication | 22 specific files | ~440 |
| Manual loading/error state (vs useAsyncAction) | 26 files | ~300 |
| Debounce useEffect copies | 2 files, 5 sites | ~50 |
| Pagination reimplemented per-component | 6 | ~200 |
| `Loader2` spinner inline pattern | 84 sites | ~150 |

> Note: `training/` vs `list/` modal consolidation was evaluated and **removed from scope** — see Section 2.

---

## Goals

- High cohesion: each unit has one clear purpose and well-defined interface
- Low coupling: consumers don't know modal internals; hooks don't know UI
- Zero behaviour change: pure refactor, no new features, no UX differences
- All TypeScript type-safe, no `as any` suppressions

---

## Section 1 — New Primitive Files (pure additions)

### `components/ui/modal-shell.tsx`

Replaces 3 diverged overlay variants repeating across 22 files.

```typescript
interface ModalShellProps {
  isOpen: boolean
  onClose?: () => void      // if provided: backdrop click + Escape close; otherwise neither fires
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '6xl'  // default: 'md'
  className?: string        // applied to the inner content container
  children: React.ReactNode
}
```

**Behavioral contract (must NOT change existing behaviour):**
- Backdrop (outer div) click: calls `onClose` only when prop is provided
- Inner content div: uses `e.stopPropagation()` — content clicks never bubble to backdrop
- No portal — renders inline in the DOM tree (same as all current modals)
- No focus trap, no scroll lock — keep existing browser defaults
- Escape key: `useEffect` + `keydown` listener calls `onClose` only when prop is provided
- `maxWidth` maps: `sm→max-w-sm`, `md→max-w-md`, `lg→max-w-lg`, `xl→max-w-xl`, `6xl→max-w-6xl`

**Canonical styling (Variant B — newest animated style):**

Overlay: `fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200`

Content: `bg-white rounded-xl sm:rounded-2xl shadow-2xl w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto {maxWidth}`

**Migration targets (22 files, exact settings):**

```
components/ChangePasswordModal.tsx              maxWidth="md"   onClose=yes
components/SetEmailModal.tsx                    maxWidth="md"   onClose=yes
components/DisclaimerModal.tsx                  maxWidth="xl"   onClose=no
components/MaintenanceNoticeModal.tsx           maxWidth="lg"   onClose=no
components/RegisterRequestModal.tsx             maxWidth="md"   onClose=no
components/settings/ConfirmDialog.tsx           maxWidth="sm"   onClose=no
components/settings/CreateUserModal.tsx         maxWidth="md"   onClose=yes
components/settings/EditUserModal.tsx           maxWidth="md"   onClose=yes
components/settings/EmailTemplateModal.tsx      maxWidth="lg"   onClose=yes
components/settings/PermissionModal.tsx         maxWidth="md"   onClose=yes
components/settings/DatasetPermissionModal.tsx  maxWidth="lg"   onClose=yes
components/settings/MigrationModal.tsx          maxWidth="md"   onClose=no
components/settings/PermissionCenterModal.tsx   maxWidth="6xl"  onClose=yes
components/list/ExportLabelsModal.tsx           maxWidth="md"   onClose=yes
components/list/FileMetadataModal.tsx           maxWidth="lg"   onClose=yes
components/list/DeleteModals.tsx  (×2 modals)   maxWidth="lg"   onClose=no
components/list/EditModals.tsx    (×3 modals)   maxWidth="md"   onClose=yes (per modal)
components/training/DeleteConfirmModal.tsx      maxWidth="md"   onClose=no
components/training/EditMetadataModal.tsx       maxWidth="md"   onClose=yes
components/training/BatchEditModal.tsx          maxWidth="md"   onClose=yes
components/training/FileMetadataModal.tsx       maxWidth="lg"   onClose=yes
```

---

### `lib/useDebounce.ts`

```typescript
function useDebounce<T>(value: T, delay: number): T
```

**Exact replacement targets (5 useEffect blocks, 2 files):**
- `components/settings/PermissionCenterModal.tsx`: 3 effects for `userSearchQuery`, `datasetSearchQuery`, `grantUserSearchQuery`  
  Each uses `window.setTimeout(..., SEARCH_DEBOUNCE_MS)`
- `components/upload/DatasetConfigStep.tsx`: 2 debounce effects

Each `useState + useEffect + setTimeout/clearTimeout` block becomes:
```typescript
const debouncedQuery = useDebounce(query, 300)
```
The derived `setDebouncedXSearchQuery` state variables are **deleted** from these files.

---

### `lib/useConfirmDialog.ts`

```typescript
import type { ConfirmDialogState, ShowConfirmDialog } from '../components/settings/ConfirmDialog'

const CLOSED: ConfirmDialogState = { isOpen: false, title: '', message: '', onConfirm: () => {} }

function useConfirmDialog(): {
  dialogState: ConfirmDialogState
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}
```

**Integration requirement — MANDATORY:** Every adopting component MUST render `<ConfirmDialog>` in its output:
```tsx
const { dialogState, showConfirmDialog, closeConfirmDialog } = useConfirmDialog()
return (
  <>
    {/* existing component JSX */}
    <ConfirmDialog dialog={dialogState} onClose={closeConfirmDialog} />
  </>
)
```

**Target files (11):**
```
pages/ListPage.tsx
pages/TaskListPage.tsx
pages/TaskDetailPage.tsx
pages/NewTaskPage.tsx
components/settings/UsersTab.tsx
components/settings/StorageTab.tsx
components/settings/ModelsTab.tsx
components/settings/AnnotationAuditCard.tsx
components/settings/DatasetPermissionModal.tsx
components/settings/PermissionModal.tsx
components/settings/PermissionCenterModal.tsx  ← parent (SettingsPage) uses hook; modal's prop interface unchanged
```

---

### `components/ui/pagination-footer.tsx`

Extracted from inside `PermissionCenterModal.tsx`. Owns its own i18n via `useTranslation()` internally — no `t` prop required by callers.

```typescript
interface PaginationFooterProps {
  page: number
  pageSize: number
  total: number
  disabled?: boolean
  pageSizeOptions?: string[]   // default: ['4', '6', '9', '18']
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}
```

**Target files (6):**
```
components/settings/PermissionCenterModal.tsx  — internal → public import (remove t prop)
components/settings/UsersTab.tsx               — replace own pagination JSX
components/settings/ModelsTab.tsx              — replace own pagination JSX
components/settings/FeedbackTab.tsx            — replace own pagination JSX
components/settings/AnnotationAuditCard.tsx    — replace own pagination JSX
pages/ListPage.tsx                             — replace own pagination JSX
```

---

## Section 2 — training/ vs list/ Modals: Out of Scope

**Decision:** Full consolidation of `training/` and `list/` modal components is **removed from this refactor**.

**Reason:** The training and list versions have fundamentally different prop contracts (uncontrolled callbacks in training vs controlled value/setter pairs in list, plus different UX — training modals lack delete-mode selection and storage info UI). Merging them would require behavior changes, violating the "zero behaviour change" constraint.

**What we do instead:** Both sets of training modals are included in the **ModalShell migration** (Section 1), so they stop duplicating the overlay boilerplate. Deeper consolidation of training/list logic is deferred to a separate refactor once the component APIs are aligned.

---

## Section 3 — State Layer Unification

### 3a. `useAsyncAction` — targeted adoption

**Scope (strictly):** Only migrate event-handler–triggered imperative calls with this exact pattern:
```typescript
setState(true)
try { await apiCall() }
catch (err) { setError(...) }
finally { setState(false) }
```

**EXCLUDED:**
- `react-query` / `useQuery` managed fetches (already handled)
- `useEffect`-driven data loading with cleanup/cancellation
- Background task polling (SSE, intervals)

**Standard migration pattern:**
```typescript
const [error, setError] = useState<string | null>(null)
const [isPending, run] = useAsyncAction({
  onError: (err) => setError(err instanceof Error ? err.message : 'Unknown error')
})
const handler = () => {
  setError(null)
  return run(() => apiCall())
}
// When return value is needed:
const result = await run(() => apiCall())
if (result !== undefined) { /* use result */ }
```

**Target files (26 — handlers only):**

Pages (6):
```
pages/StorageManagementPage.tsx    detectOrphaned, handleCleanup, startingEmptyDatasetCleanup
pages/TaskDetailPage.tsx           handleRerun, handleCancel
pages/TaskListPage.tsx             handleDeleteTask
pages/ResultsViewerPage.tsx        runAnalysis, startExternalValidation
pages/NewTaskPage.tsx              handleSubmitTask and other async handlers
pages/AIChatPage.tsx               async message/action handlers
```

Settings (8):
```
components/settings/UsersTab.tsx
components/settings/ModelsTab.tsx
components/settings/FeedbackTab.tsx
components/settings/TasksTab.tsx
components/settings/GeneralTab.tsx
components/settings/StorageTab.tsx
components/settings/AnnotationAuditCard.tsx
components/settings/PermissionCenterModal.tsx
```

Other components (12):
```
components/WSIViewer.tsx
components/wsiViewer/ShareAnnotationDialog.tsx
components/chat/AnalysisConfigCard.tsx
components/chat/TaskConfigCard.tsx
components/chat/DatasetRegistrationCard.tsx
components/chat/TaskHistoryCard.tsx
components/chat/ChartCard.tsx
components/chat/MetricCard.tsx
components/chat/ImageRecommendationCard.tsx
components/chat/QuickAnalysisViewer.tsx
components/settings/DatasetPermissionModal.tsx
components/settings/PermissionModal.tsx
```

---

## Execution Order

1. **Add primitives** — create 4 new files, no existing files touched
2. **Migrate ModalShell** — 22 modal files, one at a time, `lsp_diagnostics` after each
3. **Roll out `useDebounce`** — 2 files (PermissionCenterModal, DatasetConfigStep)
4. **Roll out `useConfirmDialog`** — 11 parent components
5. **Roll out `useAsyncAction`** — 26 files — pages first, then settings, then chat
6. **Roll out `PaginationFooter`** — 6 components

---

## Success Criteria (grep-verifiable)

**ModalShell migration (22 files):**
- For each of the 22 listed files: grep `fixed inset-0` inside that file → 0 matches

**useDebounce rollout (2 files):**
- `components/settings/PermissionCenterModal.tsx`: grep `setDebouncedUserSearchQuery\|setDebouncedDatasetSearchQuery\|setDebouncedGrantUserSearchQuery` → 0 matches; grep `import.*useDebounce` → 1 match
- `components/upload/DatasetConfigStep.tsx`: grep `window\.setTimeout\|window\.clearTimeout\|setTimeout\|clearTimeout` → 0 matches; grep `import.*useDebounce` → 1 match

**useConfirmDialog rollout (11 files):**
- Each of the 11 listed files: grep `useState<ConfirmDialogState>` → 0 matches
- Each file: grep `import.*useConfirmDialog` → 1 match

**useAsyncAction rollout (26 files):**
- Each of the 26 listed files: grep `setLoading(true)\|setIsPending(true)\|setIsLoading(true)\|setSubmitting(true)` (exact string, not regex) → 0 matches per file
- Each file: grep `import.*useAsyncAction` → 1 match

**PaginationFooter rollout (6 files):**
- Each of the 6 listed files: grep `import.*PaginationFooter` → 1 match

**Global:**
- `lsp_diagnostics` clean on every modified file
- No `as any`, `@ts-ignore`, `@ts-expect-error` introduced

---

## Out of Scope

- `training/` vs `list/` deeper modal consolidation (see Section 2)
- New UI features, visual design changes, UX changes
- Domain-specific hooks (`useDataSelection`, `useTaskWizard`, etc.)
- API layer (`api/`) — already modularised
- Test files
- Pre-existing LSP errors unrelated to modified files
